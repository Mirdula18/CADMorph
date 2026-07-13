# Quickstart & Validation Guide: PDF Drawing Change Detection

**Feature**: [spec.md](./spec.md) | **Plan**: [plan.md](./plan.md) |
**Contracts**: [contracts/](./contracts/)

Runnable scenarios that prove the feature works end to end. Implementation
detail lives in tasks.md; this file is the validation script.

## Prerequisites

- Python 3.11+, Node 20+ (frontend build)
- `pip install -e backend[dev,ml]`, `pip install -e tools/synthgen`, and
  `npm install --prefix frontend` (the `ml` extra is required — the API app
  imports the classifier/matcher at startup; synthgen generates the
  scenario fixtures below)
- Pinned model weights present under `backend/models/` (hash-checked at load;
  see R11) — produced by the training tasks, or the released artifacts
- No network access needed beyond localhost (verifies FR-016 posture)

## Start the app

```bash
uvicorn cadmorph.api.app:app --port 8000          # backend
npm run dev --prefix frontend                      # frontend (proxies /api)
```

## Scenario 1 — Ground-truth comparison (US1, SC-001..004)

```bash
python -m synthgen make-pair --preset floorplan --mutations dim-change,add,remove,move --out data/gt/pair01
```

1. Open the web app, upload `pair01/v1.pdf` as V(n-1) and `pair01/v2.pdf` as V(n).
2. Expect: change list where every entry in `pair01/answer-key.json` appears
   with the correct change type and exact before/after values; no extra entries.
3. Automated equivalent: `pytest backend/tests/groundtruth -k pair01`
   (compares `/api/v1/comparisons/{id}/report` deltas to the answer key,
   reporting precision/recall).

## Scenario 2 — Marked-up drawing (US2, FR-010/011)

1. From Scenario 1's results page, check each list entry highlights its
   region when selected, and the change-type filter hides/shows both list
   entries and highlights together (FR-017).
2. Download `markup.pdf`; expect one color-coded annotation per delta,
   labeled with its delta_id.
3. Automated: contract invariant test joins report deltas ↔ markup
   annotations on delta_id (contracts/api.md).

## Scenario 3 — Alignment (US3, FR-003/004)

```bash
python -m synthgen make-pair --preset floorplan --mutations none --export-offset 34,0 --export-scale 1.02 --out data/gt/pair02
python -m synthgen make-pair --preset unrelated --out data/gt/pair03
```

(`--export-offset` is `dx,dy` in PDF points; 34 pt ≈ 12 mm.)

- `pair02` (offset/scale only): expect outcome `no_changes` — zero deltas.
- `pair03` (unrelated sheets): expect outcome `declined`,
  reason `alignment_failed`, message says inputs don't appear to be the same sheet.

## Scenario 4 — Input rejection (FR-002, edge cases)

Upload a scanned/raster-only PDF and a corrupt file. Expect synchronous or
status-level rejection with `raster_or_empty` / `unreadable`, naming the
offending file. No comparison output is produced.

## Scenario 5 — Determinism gate (FR-013, SC-007)

```bash
pytest backend/tests/determinism
```

Runs the same pair twice through the pipeline; asserts byte-identical
canonical delta JSON and identical summary lines.

## Scenario 6 — Grounding gate (FR-009, Constitution II)

```bash
pytest backend/tests/unit/test_summarizer_grounding.py
```

Asserts: every summary value string appears verbatim in its delta's
before/after state; the summarizer package imports no extraction, PyMuPDF,
or image modules (import-linter rule); deltas with null values render
"value unavailable".

## Scenario 7 — Performance check (SC-006)

```bash
pytest backend/tests/integration/test_perf.py
```

The test generates its own 10,000-entity pair (with mutations) and asserts
the end-to-end comparison completes in < 120 s; `metrics.json` stage timings
identify any regressing stage (R9). To eyeball the same pair in the web UI:
`python -m synthgen make-pair --preset dense --entities 10000 --out data/gt/pair-dense`.

## Expected artifacts per run

`data/{comparison_id}/`: uploads, `report.json`, `markup.pdf`, `report.pdf`,
`metrics.json`, `job.log` (JSON lines, comparison_id-correlated — R9).
