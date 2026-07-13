"""Markup traceability contract (T035, SC-004): report deltas and markup
annotations join 1:1 on delta_id, color-coded by change type; plus the
artifact endpoints' contract behavior (sheet.png transform header,
report.pdf content, no-changes banner)."""

from __future__ import annotations

from pathlib import Path

import fitz
import pytest
from fastapi.testclient import TestClient

from cadmorph.api.app import create_app
from cadmorph.report.markup import COLORS


@pytest.fixture(scope="module")
def pair01(tmp_path_factory) -> Path:
    from synthgen import make_pair

    pair_dir = tmp_path_factory.mktemp("markup") / "pair01"
    make_pair("floorplan", ["dim-change", "add", "remove", "move"], pair_dir, seed=7)
    return pair_dir


@pytest.fixture(scope="module")
def client(tmp_path_factory) -> TestClient:
    return TestClient(create_app(data_dir=tmp_path_factory.mktemp("data")))


def _run(client: TestClient, v_old: Path, v_new: Path) -> str:
    with open(v_old, "rb") as f_old, open(v_new, "rb") as f_new:
        response = client.post(
            "/api/v1/comparisons",
            files={
                "file_old": (v_old.name, f_old, "application/pdf"),
                "file_new": (v_new.name, f_new, "application/pdf"),
            },
        )
    assert response.status_code == 202, response.text
    cid = response.json()["comparison_id"]
    status = client.get(f"/api/v1/comparisons/{cid}").json()
    assert status["state"] == "done", status
    return cid


@pytest.fixture(scope="module")
def finished(client, pair01) -> tuple[str, dict]:
    cid = _run(client, pair01 / "v1.pdf", pair01 / "v2.pdf")
    report = client.get(f"/api/v1/comparisons/{cid}/report").json()
    return cid, report


def _annotations(pdf_bytes: bytes) -> list[dict]:
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    out = []
    for page in doc:
        for annot in page.annots() or []:
            out.append(
                {
                    "delta_id": annot.info["content"],
                    "change_type": annot.info["title"],
                    "stroke": tuple(round(c, 2) for c in annot.colors["stroke"]),
                }
            )
    doc.close()
    return out


def test_markup_annotations_join_deltas_1to1(client, finished):
    cid, report = finished
    response = client.get(f"/api/v1/comparisons/{cid}/markup.pdf")
    assert response.status_code == 200
    annotations = _annotations(response.content)
    # 1:1 both directions on delta_id (SC-004 / FR-011)
    assert sorted(a["delta_id"] for a in annotations) == sorted(
        d["delta_id"] for d in report["deltas"]
    )
    by_id = {d["delta_id"]: d for d in report["deltas"]}
    for annotation in annotations:
        delta = by_id[annotation["delta_id"]]
        assert annotation["change_type"] == delta["change_type"]
        expected = tuple(round(c, 2) for c in COLORS[delta["change_type"]])
        assert annotation["stroke"] == expected  # color-coded by change type


def test_no_changes_markup_is_banner_with_zero_annotations(client, pair01):
    cid = _run(client, pair01 / "v1.pdf", pair01 / "v1.pdf")
    response = client.get(f"/api/v1/comparisons/{cid}/markup.pdf")
    assert response.status_code == 200
    doc = fitz.open(stream=response.content, filetype="pdf")
    assert doc.page_count == 2  # banner page + original sheet (FR-012)
    assert "No changes detected" in doc[0].get_text()
    assert not _annotations(response.content)
    doc.close()


def test_sheet_png_serves_transform_header(client, finished):
    cid, _ = finished
    for revision in ("new", "old"):
        response = client.get(f"/api/v1/comparisons/{cid}/sheet.png?revision={revision}")
        assert response.status_code == 200
        assert response.headers["content-type"] == "image/png"
        assert response.content[:8] == b"\x89PNG\r\n\x1a\n"
        header = dict(kv.split("=") for kv in response.headers["X-Sheet-Transform"].split(";"))
        assert float(header["scale"]) == 2.0
        assert float(header["dx"]) == 0.0 and float(header["dy"]) == 0.0
    assert client.get(f"/api/v1/comparisons/{cid}/sheet.png?revision=bogus").status_code == 400


def test_report_pdf_contains_grouped_summary_lines(client, finished):
    cid, report = finished
    response = client.get(f"/api/v1/comparisons/{cid}/report.pdf")
    assert response.status_code == 200
    doc = fitz.open(stream=response.content, filetype="pdf")
    text = "".join(page.get_text() for page in doc)
    doc.close()
    assert "CADMorph Change Detection Report" in text
    assert report["revisions"]["old"]["source_filename"] in text
    for delta in report["deltas"]:
        assert delta["delta_id"] in text  # every entry present, labeled (SC-005)


def test_revision_sheet_dims_are_pdf_points_not_pixels(client, finished, pair01):
    """The SVG overlay's viewBox uses revision sheet dims; they must be the
    source PDF page rect in points (anchor_bbox's coordinate space), never
    the rendered PNG's pixel size."""
    cid, report = finished
    doc = fitz.open(pair01 / "v2.pdf")
    rect = doc[0].rect
    doc.close()
    revision = report["revisions"]["new"]
    assert revision["sheet_width"] == pytest.approx(rect.width)
    assert revision["sheet_height"] == pytest.approx(rect.height)
    # ...and explicitly NOT the rendered pixmap's pixel dimensions
    response = client.get(f"/api/v1/comparisons/{cid}/sheet.png")
    header = dict(kv.split("=") for kv in response.headers["X-Sheet-Transform"].split(";"))
    assert float(header["width"]) == rect.width * 2.0  # zoom 2.0 pixels
    assert revision["sheet_width"] != float(header["width"])
