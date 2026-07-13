"""Structured report.pdf (T034 extension): page structure, exact cover
metrics, confidence placement asserted NEGATIVELY as well as positively,
CH-id traceability, and byte-identity across two full runs (FR-013)."""

from __future__ import annotations

import json
import re

import fitz
import pytest

from cadmorph.deltas.models import ChangeReport, EntityDelta, EntityState
from cadmorph.models import DrawingRevision, EntityMatch, LabeledValue
from cadmorph.pipeline import JobStore, run_job
from cadmorph.report.document import summary_table_rows
from cadmorph.report.severity import affected_area_pct, severity

PERCENT = re.compile(r"\d+(?:\.\d+)?\s*%")


@pytest.fixture(scope="module")
def runs(tmp_path_factory):
    """Two independent full pipeline runs on the canonical mutation pair."""
    from synthgen import make_pair

    root = tmp_path_factory.mktemp("reportpdf")
    pair = root / "pair"
    make_pair("floorplan", ["dim-change", "add", "remove", "move"], pair, seed=7)
    store = JobStore(root / "data")
    cids = []
    for _ in range(2):
        job = store.create(
            (pair / "v1.pdf").read_bytes(), "v1.pdf",
            (pair / "v2.pdf").read_bytes(), "v2.pdf",
        )
        run_job(store, job.comparison_id)
        finished = store.load(job.comparison_id)
        assert finished is not None and finished.state == "done", finished
        cids.append(job.comparison_id)
    return store, cids


@pytest.fixture(scope="module")
def artifacts(runs):
    store, cids = runs
    directory = store.job_dir(cids[0])
    report = json.loads((directory / "report.json").read_text(encoding="utf-8"))
    metrics = json.loads((directory / "metrics.json").read_text(encoding="utf-8"))
    pdf = (directory / "report.pdf").read_bytes()
    return report, metrics, pdf


def test_page_structure_matches_specified_sequence(artifacts):
    _, _, pdf = artifacts
    doc = fitz.open(stream=pdf, filetype="pdf")
    assert doc.page_count >= 5
    expected_headings = (
        "AI-Powered Drawing Change Detection Report",
        "Revision A (Baseline)",
        "Revision B (Revised)",
        "Color-Coded Change Overlay",
        "Structured Change Summary",
    )
    expected_images = (0, 1, 1, 1, 0)
    for i, (heading, n_images) in enumerate(zip(expected_headings, expected_images, strict=True)):
        page = doc[i]
        first_line = next(ln for ln in page.get_text().splitlines() if ln.strip())
        assert first_line.startswith(heading), (i + 1, first_line)
        assert len(page.get_images()) == n_images, (i + 1, heading)
    # header/footer: absent on the cover, present with total count after it
    total = doc.page_count
    assert "Page 1 of" not in doc[0].get_text()
    for i in range(1, total):
        text = doc[i].get_text()
        assert f"Page {i + 1} of {total}" in text
        assert "CADMorph Change Detection Report" in text
        assert "Confidential" in text
    doc.close()


def test_cover_metrics_equal_report_exactly(artifacts):
    """Dashboard numbers must EQUAL recomputation from report.json's deltas
    (same arithmetic), not merely look plausible."""
    report, metrics, pdf = artifacts
    doc = fitz.open(stream=pdf, filetype="pdf")
    cover = doc[0].get_text()
    doc.close()

    deltas = report["deltas"]
    counts = {"added": 0, "removed": 0, "modified": 0}
    for d in deltas:
        counts[d["change_type"]] += 1
    rev = report["revisions"]["new"]
    pct = affected_area_pct(
        [tuple(d["anchor_bbox"]) for d in deltas], rev["sheet_width"], rev["sheet_height"]
    )
    inlier = metrics["signals"]["register"]["inlier_ratio"]

    def cover_value(label: str) -> str:
        match = re.search(re.escape(label) + r"\n([^\n]+)", cover)
        assert match, f"dashboard label {label!r} not found on cover"
        return match.group(1).strip()

    assert cover_value("Source Format") == "Vector PDF"
    assert cover_value("Sheet Size") == (
        f"{rev['sheet_width']:g} pt × {rev['sheet_height']:g} pt"
    )
    assert cover_value("Total Changes") == str(len(deltas))
    assert cover_value("Affected Area") == f"{pct:.2f}%"
    assert cover_value("Added") == str(counts["added"])
    assert cover_value("Removed") == str(counts["removed"])
    assert cover_value("Modified") == str(counts["modified"])
    assert cover_value("Registration Confidence") == f"{inlier * 100:.1f}%"
    assert cover_value("Severity") == severity(pct, len(deltas))
    assert cover_value("Pipeline Version") == report["pipeline_version"]
    # executive summary reuses the same numbers (template-only, FR-016)
    assert f"{len(deltas)} change(s) were detected" in cover
    assert f"Approximately {pct:.2f}% of the sheet area was affected." in cover


def test_ch_map_and_delta_ids_1to1(artifacts):
    report, _, pdf = artifacts
    doc = fitz.open(stream=pdf, filetype="pdf")
    norm = " ".join("".join(p.get_text() for p in doc).split())
    doc.close()
    for i, delta in enumerate(report["deltas"]):
        assert f"CH-{i + 1:03d} = {delta['delta_id']}" in norm
    # no phantom rows: the next CH id must not exist anywhere
    assert f"CH-{len(report['deltas']) + 1:03d}" not in norm


def test_report_pdf_byte_identical_across_full_runs(runs):
    """FR-013 with the new structured content: two complete pipeline runs
    over identical uploads emit identical report.pdf bytes."""
    store, (cid_a, cid_b) = runs
    a = (store.job_dir(cid_a) / "report.pdf").read_bytes()
    b = (store.job_dir(cid_b) / "report.pdf").read_bytes()
    assert a == b


# ---- confidence placement: negative assertions on constructed rows ----


def _rev(rid: str) -> DrawingRevision:
    return DrawingRevision(
        revision_id=rid, source_filename=f"{rid}.pdf", format="pdf",
        sheet_width=842.0, sheet_height=595.0, sheet_diagonal=1031.0,
        content_hash="x",
    )


def _state(eid: str, kind: str = "linework", text: str | None = None,
           dim: str | None = None, semantic: LabeledValue | None = None,
           pos: tuple[float, float] = (100.0, 100.0)) -> EntityState:
    return EntityState(
        entity_id=eid, kind=kind, bbox=(90, 90, 110, 110), position=pos,
        geometry_signature="sig", text_payload=text, dimension_value=dim,
        semantic_label=semantic,
    )


def _constructed_report() -> ChangeReport:
    wall = LabeledValue(value="wall", provenance="inference", confidence=0.92)
    door = LabeledValue(value="door", provenance="inference", confidence=0.80)
    deltas = [
        # learned match + semantic label -> the ONLY row where BOTH
        # confidence cells are allowed
        EntityDelta(
            delta_id="d-learned01", change_type="modified",
            modification_kinds=["dimension_value", "text"],
            before=_state("e1", "dimension", text="D14 = 450 cm", dim="450 cm"),
            after=_state("e1n", "dimension", text="D14 = 40 cm", dim="40 cm",
                         semantic=wall),
            match=EntityMatch(
                old_entity_id="e1", new_entity_id="e1n", tier="learned",
                similarity=LabeledValue(value=0.87, provenance="inference",
                                        confidence=0.87),
            ),
            anchor_bbox=(90, 90, 110, 110),
        ),
        # attribute-tier match (deterministic), no semantic label
        EntityDelta(
            delta_id="d-attrib02", change_type="modified",
            modification_kinds=["moved"],
            before=_state("e2", pos=(100.0, 100.0)),
            after=_state("e2n", pos=(120.0, 100.0)),
            match=EntityMatch(old_entity_id="e2", new_entity_id="e2n",
                              tier="attribute", similarity=None),
            anchor_bbox=(90, 90, 110, 110),
        ),
        # added: no match at all
        EntityDelta(
            delta_id="d-added003", change_type="added",
            before=None, after=_state("e3", "text", text="NOTE: NEW"),
            match=None, anchor_bbox=(700, 120, 750, 170),
        ),
        # removed WITH a semantic label: Entity % allowed, Confidence must
        # STILL be the em dash (no match exists to be confident about)
        EntityDelta(
            delta_id="d-removed4", change_type="removed",
            before=_state("e4", semantic=door), after=None,
            match=None, anchor_bbox=(300, 300, 320, 320),
        ),
    ]
    return ChangeReport(
        comparison_id="c1", revisions={"old": _rev("old"), "new": _rev("new")},
        outcome="changes_found", deltas=deltas, pipeline_version="test-0",
    )


COLUMNS = ("ID", "Change Type", "Entity", "Location",
           "Old Value", "New Value", "Delta", "Confidence")


def test_confidence_absent_everywhere_not_explicitly_allowed():
    report = _constructed_report()
    rows = summary_table_rows(report)
    assert len(rows) == 4

    for row, delta in zip(rows, report.deltas, strict=True):
        cells = dict(zip(COLUMNS, row, strict=True))
        # NEGATIVE: these six cells must never contain a percentage, on any
        # row — a % here means a confidence (or invented number) leaked into
        # a deterministic column
        for column in ("ID", "Change Type", "Location", "Old Value",
                       "New Value", "Delta"):
            assert not PERCENT.search(cells[column]), (
                f"{delta.delta_id}: confidence-like value leaked into "
                f"{column}: {cells[column]!r}"
            )
        # NEGATIVE: Entity carries a % ONLY when a semantic_label exists
        state = delta.after if delta.after is not None else delta.before
        assert state is not None
        if state.semantic_label is None:
            assert not PERCENT.search(cells["Entity"]), (
                f"{delta.delta_id}: Entity shows a confidence with no "
                f"semantic_label: {cells['Entity']!r}"
            )
        # NEGATIVE: Confidence is an em dash unless the match is learned
        if not (delta.match is not None and delta.match.tier == "learned"):
            assert cells["Confidence"] == "—", (
                f"{delta.delta_id}: non-learned row shows a match "
                f"confidence: {cells['Confidence']!r}"
            )

    # POSITIVE anchors (so the negative checks can't pass vacuously)
    learned, attrib, added, removed = rows
    assert learned[COLUMNS.index("Entity")] == "wall (92%)"
    assert learned[COLUMNS.index("Confidence")] == "87%"
    assert learned[COLUMNS.index("Delta")] == "-410 cm"      # real arithmetic
    assert attrib[COLUMNS.index("Confidence")] == "—"
    assert attrib[COLUMNS.index("Delta")] == "20.0 pt"       # moved distance
    assert added[COLUMNS.index("Confidence")] == "—"
    assert removed[COLUMNS.index("Entity")] == "door (80%)"  # semantic OK...
    assert removed[COLUMNS.index("Confidence")] == "—"       # ...match conf NOT
