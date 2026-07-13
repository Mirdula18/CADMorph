"""Performance gate (T044, SC-006): a 10,000-entity single-sheet comparison
completes end to end in under 120 s, with the per-stage breakdown read from
metrics.json (R9) so a regression names its stage.

Measured baseline (2026-07-06, Windows dev machine, CPU): 13.6 s wall —
extraction 6.1 s, classify 2.5 s, match 1.5 s, validation 1.4 s, report
1.2 s, register 0.5 s, summarize 0.07 s, diff 0.01 s. The 120 s budget is
SC-006's ceiling, not the expectation. Fixture generation (~200 s of PyMuPDF
draw calls) dominates this test's runtime and is outside the timed window.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from cadmorph.pipeline import JobStore, run_job

BUDGET_S = 120.0
ENTITY_TARGET = 10_000
PIPELINE_STAGES = (
    "validation", "extraction", "classify", "register",
    "match", "diff", "summarize", "report",
)


@pytest.fixture(scope="module")
def dense_pair(tmp_path_factory) -> Path:
    """SC-006's complexity bound: dense preset at 10,000 entities, with the
    US1 mutation set so match/diff/summarize/report all do real work."""
    from synthgen import make_pair

    out = tmp_path_factory.mktemp("perf") / "pair-dense"
    make_pair("dense", ["dim-change", "add", "remove", "move"], out, entities=ENTITY_TARGET)
    return out


def test_10k_entity_comparison_under_120s_with_stage_breakdown(dense_pair, tmp_path):
    store = JobStore(tmp_path / "data")
    job = store.create(
        (dense_pair / "v1.pdf").read_bytes(), "v1.pdf",
        (dense_pair / "v2.pdf").read_bytes(), "v2.pdf",
    )
    start = time.perf_counter()
    run_job(store, job.comparison_id)
    wall_s = time.perf_counter() - start

    job = store.load(job.comparison_id)
    assert job is not None and job.state == "done", (job.state, job.reason, job.message)

    metrics = json.loads(
        (store.job_dir(job.comparison_id) / "metrics.json").read_text(encoding="utf-8")
    )
    timings_ms = metrics["stage_timings_ms"]
    breakdown = ", ".join(
        f"{stage}={timings_ms[stage] / 1000:.2f}s"
        for stage in PIPELINE_STAGES if stage in timings_ms
    )
    print(f"\nSC-006: wall={wall_s:.2f}s budget={BUDGET_S:.0f}s ({breakdown})")

    # The sheet really is at the SC-006 complexity bound (10k entities/side);
    # without this the gate could silently pass on a trivial fixture.
    extraction = metrics["signals"]["extraction"]
    assert extraction["entities_old"] >= ENTITY_TARGET
    assert extraction["entities_new"] >= ENTITY_TARGET

    hottest = sorted(((ms, stage) for stage, ms in timings_ms.items()), reverse=True)
    assert wall_s < BUDGET_S, (
        f"SC-006 violated: {wall_s:.1f}s >= {BUDGET_S:.0f}s; hottest stages: "
        + ", ".join(f"{stage}={ms / 1000:.1f}s" for ms, stage in hottest[:3])
    )

    # Both directions of the R9 timing claim: every pipeline stage reports a
    # positive timing, and the stages' sum stays within the wall clock that
    # contains them (a timing the wall can't account for would be fabricated).
    missing = set(PIPELINE_STAGES) - set(timings_ms)
    assert not missing, f"stages missing from metrics.json: {sorted(missing)}"
    assert all(timings_ms[stage] > 0 for stage in PIPELINE_STAGES)
    assert sum(timings_ms.values()) / 1000.0 <= wall_s
    # job.json mirrors metrics.json on completion (the status endpoint's source)
    assert job.stage_timings_ms == timings_ms
