"""Alignment ground-truth gates (T043, FR-003/FR-004, quickstart Scenario 3).

pair02 (offset+scale export, no mutations) -> no_changes once aligned;
pair03 (unrelated sheets) -> declined end-to-end with alignment_failed;
an offset export of a mutated pair produces the same semantic report as the
un-offset export; float-dust near-identity transforms take the numeric
matching path with identical results.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from cadmorph.api.app import create_app
from cadmorph.deltas.compute import compute_deltas
from cadmorph.extraction.provider import get_provider
from cadmorph.graph.build import build_graph
from cadmorph.match.cascade import match_entities
from cadmorph.match.model import load_encoder
from cadmorph.models import SimilarityTransform
from cadmorph.register.anchors import build_anchor_pairs
from cadmorph.register.ransac import estimate_transform
from scoring import score

MUTATIONS = ["dim-change", "add", "remove", "move"]


@pytest.fixture(scope="module")
def data_dir(tmp_path_factory) -> Path:
    return tmp_path_factory.mktemp("data")


@pytest.fixture(scope="module")
def client(data_dir) -> TestClient:
    return TestClient(create_app(data_dir=data_dir))


@pytest.fixture(scope="module")
def encoder():
    return load_encoder()


def _upload(client, v_old: Path, v_new: Path) -> str:
    with open(v_old, "rb") as f_old, open(v_new, "rb") as f_new:
        response = client.post(
            "/api/v1/comparisons",
            files={
                "file_old": (v_old.name, f_old, "application/pdf"),
                "file_new": (v_new.name, f_new, "application/pdf"),
            },
        )
    assert response.status_code == 202, response.text
    return response.json()["comparison_id"]


def test_pair02_offset_scale_reports_no_changes(client, data_dir, tmp_path):
    """The headline claim: an offset+scaled export of the SAME sheet is not
    a change (FR-003)."""
    from synthgen import make_pair

    pair_dir = tmp_path / "pair02"
    make_pair(
        "floorplan", [], pair_dir, seed=7, export_offset=(34.0, 21.0), export_scale=1.02
    )
    cid = _upload(client, pair_dir / "v1.pdf", pair_dir / "v2.pdf")
    status = client.get(f"/api/v1/comparisons/{cid}").json()
    assert status["state"] == "done", status
    assert status["outcome"] == "no_changes"
    report = client.get(f"/api/v1/comparisons/{cid}/report").json()
    assert report["deltas"] == [] and report["summary_lines"] == []
    metrics = json.loads((data_dir / cid / "metrics.json").read_text(encoding="utf-8"))
    register = metrics["signals"]["register"]
    assert register["status"] == "aligned"
    assert register["inlier_ratio"] >= 0.6
    assert register["rms_residual_rel"] <= 0.005


def test_pair03_unrelated_sheets_declined_end_to_end(client, tmp_path):
    """Zero shared anchors (< MIN_ANCHORS) must surface as a declined job
    state via the API — never a silent pass-through or a crash (FR-004)."""
    from synthgen import make_pair

    pair_dir = tmp_path / "pair03"
    make_pair("unrelated", [], pair_dir, seed=7)
    cid = _upload(client, pair_dir / "v1.pdf", pair_dir / "v2.pdf")
    status = client.get(f"/api/v1/comparisons/{cid}").json()
    assert status["state"] == "declined", status
    assert status["reason"] == "alignment_failed"
    assert "do not appear to be revisions of the same sheet" in status["message"]
    assert client.get(f"/api/v1/comparisons/{cid}/report").status_code == 409


def _detect_semantic(pair_dir: Path, encoder):
    provider = get_provider("pdf")
    old = build_graph(provider.extract(pair_dir / "v1.pdf", "old"))
    new = build_graph(provider.extract(pair_dir / "v2.pdf", "new"))
    reg = estimate_transform(build_anchor_pairs(old, new), new.revision.sheet_diagonal)
    assert reg.status == "aligned"
    outcome = match_entities(old, new, encoder, transform=reg.transform)
    deltas = compute_deltas(old, new, outcome, transform=reg.transform)
    projection = sorted(
        (
            d.change_type,
            tuple(d.modification_kinds),
            (d.before.text_payload, d.before.label, d.before.dimension_value)
            if d.before
            else None,
            (d.after.text_payload, d.after.label, d.after.dimension_value)
            if d.after
            else None,
        )
        for d in deltas
    )
    return deltas, projection


def test_offset_pair_report_equals_unoffset_pair_report(tmp_path, encoder):
    from synthgen import make_pair

    plain_dir, offset_dir = tmp_path / "plain", tmp_path / "offset"
    make_pair("floorplan", MUTATIONS, plain_dir, seed=7)
    make_pair("floorplan", MUTATIONS, offset_dir, seed=7, export_offset=(12.0, -8.0))
    _, plain = _detect_semantic(plain_dir, encoder)
    _, offset = _detect_semantic(offset_dir, encoder)
    assert plain == offset


def test_offset_mutated_pair_scores_against_answer_key(tmp_path, encoder):
    """With export-frame answer keys, the documented scoring rule holds on
    offset exports too: precision/recall 1.0."""
    from synthgen import make_pair

    pair_dir = tmp_path / "pair"
    make_pair("floorplan", MUTATIONS, pair_dir, seed=7, export_offset=(12.0, -8.0))
    deltas, _ = _detect_semantic(pair_dir, encoder)
    key = json.loads((pair_dir / "answer-key.json").read_text(encoding="utf-8"))
    result = score([d.model_dump(mode="json") for d in deltas], key["expected_changes"])
    assert result.recall == 1.0, result.unmatched_expected
    assert result.precision == 1.0, result.extra_deltas


def test_removed_anchor_rendered_in_display_frame(client, tmp_path):
    """Regression: a removed entity's highlight is drawn on the V(n) sheet,
    so under a REAL offset+scale registration its anchor_bbox must be the
    V(n-1) bbox mapped through the fitted transform — while the stored
    `before` state stays verbatim V(n-1) coordinates (FR-009)."""
    import fitz

    from synthgen import make_pair

    pair_dir = tmp_path / "pair"
    make_pair(
        "floorplan", ["remove"], pair_dir, seed=7,
        export_offset=(34.0, 21.0), export_scale=1.02,
    )
    cid = _upload(client, pair_dir / "v1.pdf", pair_dir / "v2.pdf")
    status = client.get(f"/api/v1/comparisons/{cid}").json()
    assert status["state"] == "done", status
    report = client.get(f"/api/v1/comparisons/{cid}/report").json()
    (removed,) = [d for d in report["deltas"] if d["change_type"] == "removed"]

    # before stays verbatim V(n-1); anchor is that bbox mapped by ~(1.02, +34, +21)
    bx = removed["before"]["bbox"]
    expected = [bx[0] * 1.02 + 34.0, bx[1] * 1.02 + 21.0,
                bx[2] * 1.02 + 34.0, bx[3] * 1.02 + 21.0]
    for got, want in zip(removed["anchor_bbox"], expected, strict=True):
        assert abs(got - want) < 0.1, (
            f"anchor_bbox {removed['anchor_bbox']} not at display location {expected}"
        )
    assert removed["anchor_bbox"] != bx  # genuinely transformed, not copied

    # and the markup annotation on the V(n) page sits at the same location
    markup = client.get(f"/api/v1/comparisons/{cid}/markup.pdf")
    doc = fitz.open(stream=markup.content, filetype="pdf")
    annots = {
        a.info["content"]: a.rect for page in doc for a in (page.annots() or [])
    }
    doc.close()
    rect = annots[removed["delta_id"]]
    # PyMuPDF expands the stored /Rect symmetrically for the border stroke,
    # so compare centers (invariant under symmetric expansion), not corners.
    assert abs((rect.x0 + rect.x1) / 2 - (expected[0] + expected[2]) / 2) < 1.0
    assert abs((rect.y0 + rect.y1) / 2 - (expected[1] + expected[3]) / 2) < 1.0


def test_float_dust_transform_takes_numeric_path_same_result(tmp_path, encoder):
    """Regression for the near-identity case: scale=0.9999999999999998 must
    route to the numeric tier-1 path and reproduce the exact-hash result."""
    from synthgen import make_pair

    pair_dir = tmp_path / "pair"
    make_pair("floorplan", MUTATIONS, pair_dir, seed=7)
    provider = get_provider("pdf")
    old = build_graph(provider.extract(pair_dir / "v1.pdf", "old"))
    new = build_graph(provider.extract(pair_dir / "v2.pdf", "new"))
    identity = SimilarityTransform(tx=0.0, ty=0.0, scale=1.0, rotation=0.0)
    dust = SimilarityTransform(
        tx=5.7e-14, ty=-5.7e-14, scale=0.9999999999999998, rotation=0.0
    )

    def run(transform):
        outcome = match_entities(old, new, encoder, transform=transform)
        deltas = compute_deltas(old, new, outcome, transform=transform)
        return [(d.change_type, tuple(d.modification_kinds), d.delta_id) for d in deltas]

    assert run(dust) == run(identity)
