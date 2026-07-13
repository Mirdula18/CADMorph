"""job.log artifact (R9, T047): every comparison writes a JSON-lines log,
every line correlated to its comparison_id, covering all pipeline stages,
never embedding drawing content (FR-016)."""

from __future__ import annotations

import json
from pathlib import Path

from cadmorph.pipeline import JobStore, run_job

STAGES = (
    "validation", "extraction", "classify", "register",
    "match", "diff", "summarize", "report",
)


def _run(store: JobStore, pair: Path) -> str:
    job = store.create(
        (pair / "v1.pdf").read_bytes(), "v1.pdf",
        (pair / "v2.pdf").read_bytes(), "v2.pdf",
    )
    run_job(store, job.comparison_id)
    finished = store.load(job.comparison_id)
    assert finished is not None and finished.state == "done", finished
    return job.comparison_id


def test_job_log_written_correlated_and_content_free(gt_pair, tmp_path):
    store = JobStore(tmp_path / "data")
    cid_a = _run(store, gt_pair)
    cid_b = _run(store, gt_pair)  # second job: cross-contamination probe

    log_path = store.job_dir(cid_a) / "job.log"
    assert log_path.exists()
    text = log_path.read_text(encoding="utf-8")
    lines = [json.loads(line) for line in text.splitlines() if line]
    assert lines

    # correlation in both directions: every line is THIS job's, and the
    # other job's id never leaked in
    assert all(line["comparison_id"] == cid_a for line in lines)
    assert cid_b not in text
    assert (store.job_dir(cid_b) / "job.log").exists()

    # all 8 pipeline stages start and end in the log
    events = {(line["stage"], line["event"]) for line in lines}
    for stage in STAGES:
        assert (stage, "stage_start") in events, stage
        assert (stage, "stage_end") in events, stage

    # R9/FR-016: log payloads carry entity IDs and counts only — never
    # drawing content (these strings all exist in the floorplan fixture)
    for payload in ("KITCHEN", "LIVING ROOM", "SHEET A-101", "450 cm"):
        assert payload not in text
