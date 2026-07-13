"""End-to-end ground-truth gate on pair01 (T029, quickstart Scenario 1).

Runs the full API path (upload -> pipeline -> /report) on the canonical
dim-change/add/remove/move pair and scores the deltas against the answer
key with the documented rule (scoring.py). Asserts SC-001/SC-002 operating
points, FR-014 direction, FR-012 identical-files -> no_changes, and FR-013
byte-identical repeat runs.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from cadmorph.api.app import create_app
from cadmorph.deltas.models import canonical_json
from scoring import score


@pytest.fixture(scope="module")
def pair01(tmp_path_factory) -> Path:
    from synthgen import make_pair

    pair_dir = tmp_path_factory.mktemp("e2e") / "pair01"
    make_pair("floorplan", ["dim-change", "add", "remove", "move"], pair_dir, seed=7)
    return pair_dir


@pytest.fixture(scope="module")
def client(tmp_path_factory) -> TestClient:
    app = create_app(data_dir=tmp_path_factory.mktemp("data"))
    return TestClient(app)


def _run_comparison(client: TestClient, v_old: Path, v_new: Path) -> tuple[str, dict]:
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
    assert status["state"] == "done", f"pipeline did not finish: {status}"
    report = client.get(f"/api/v1/comparisons/{cid}/report")
    assert report.status_code == 200
    return cid, report.json()


@pytest.fixture(scope="module")
def first_run(client, pair01) -> tuple[str, dict]:
    return _run_comparison(client, pair01 / "v1.pdf", pair01 / "v2.pdf")


@pytest.fixture(scope="module")
def report(first_run) -> dict:
    return first_run[1]


def test_pair01_meets_sc001_sc002(report, pair01):
    key = json.loads((pair01 / "answer-key.json").read_text(encoding="utf-8"))
    result = score(report["deltas"], key["expected_changes"])
    # 4 expected changes: SC-001 (>=95% detection) means zero misses here,
    # SC-002 (<=2% false positives) means zero extra deltas.
    assert result.recall == 1.0, f"missed changes: {result.unmatched_expected}"
    assert result.precision == 1.0, f"false positives: {result.extra_deltas}"
    # SC-001 dimension clause (>=99%): every dimension-kind change detected
    dims = [e for e in key["expected_changes"] if e["kind"] == "dimension"]
    assert score(report["deltas"], dims).recall == 1.0
    assert report["outcome"] == "changes_found"


def test_every_delta_has_exactly_one_summary_line(report):
    delta_ids = [d["delta_id"] for d in report["deltas"]]
    line_ids = [line["delta_id"] for line in report["summary_lines"]]
    assert delta_ids == line_ids  # 1:1, same canonical order (Principle III)


def test_direction_identified_fr014(report):
    assert report["revisions"]["old"]["source_filename"] == "v1.pdf"
    assert report["revisions"]["new"]["source_filename"] == "v2.pdf"
    assert report["revisions"]["old"]["revision_id"] == "old"
    assert report["revisions"]["new"]["revision_id"] == "new"


def test_identical_files_yield_no_changes_fr012(client, pair01):
    _, report = _run_comparison(client, pair01 / "v1.pdf", pair01 / "v1.pdf")
    assert report["outcome"] == "no_changes"
    assert report["deltas"] == []
    assert report["summary_lines"] == []


def test_repeat_run_byte_identical_fr013(client, pair01, first_run):
    """Two runs over byte-identical uploads -> byte-identical reports AND
    byte-identical derived artifacts (markup.pdf, report.pdf), modulo the
    per-job comparison_id (contracts/api.md canonicalization)."""
    first_cid, first = first_run
    second_cid, second = _run_comparison(client, pair01 / "v1.pdf", pair01 / "v2.pdf")
    first_c = dict(first)
    second_c = dict(second)
    first_c.pop("comparison_id")
    second_c.pop("comparison_id")
    assert canonical_json(first_c) == canonical_json(second_c)
    for artifact in ("markup.pdf", "report.pdf"):
        a = client.get(f"/api/v1/comparisons/{first_cid}/{artifact}")
        b = client.get(f"/api/v1/comparisons/{second_cid}/{artifact}")
        assert a.status_code == b.status_code == 200
        assert a.content == b.content, f"{artifact} differs between identical runs (FR-013)"
