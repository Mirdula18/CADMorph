# Tasks: PDF Drawing Change Detection (Vector Path)

**Input**: Design documents from `specs/001-pdf-change-detection/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/, quickstart.md

**Tests**: INCLUDED — the constitution mandates ground-truth validation gates
(Principle V), determinism tests (Principle IV), and grounding checks
(Principle II); they are not optional for this project.

**Organization**: Tasks grouped by user story. US1 runs with an identity
registration transform (perfectly aligned exports); US3 replaces it with real
alignment — this keeps every story independently testable.

## Format: `[ID] [P?] [Story] Description`

## Phase 1: Setup (Shared Infrastructure)

- [X] T001 Create repository structure per plan.md (backend/src/cadmorph/{extraction,graph,classify,register,match,deltas,summarize,report,api}, backend/tests/{unit,integration,determinism,groundtruth}, frontend/, tools/synthgen/)
- [X] T002 Initialize backend package with pinned dependencies (FastAPI, uvicorn, PyMuPDF, torch, torch-geometric, pydantic v2, structlog, jinja2, numpy, scipy, pytest) in backend/pyproject.toml
- [X] T003 [P] Initialize React + TypeScript frontend scaffold (Vite, /api dev proxy) in frontend/
- [X] T004 [P] Configure lint/format/typecheck (ruff + mypy backend; eslint + prettier frontend) in backend/pyproject.toml and frontend/.eslintrc
- [X] T005 [P] Add import-linter contract: cadmorph.summarize may import only cadmorph.deltas (never extraction/PyMuPDF/image modules) in backend/pyproject.toml (Constitution II, structural)

---

## Phase 2: Foundational (Blocking Prerequisites)

**⚠️ CRITICAL**: No user story work can begin until this phase is complete —
it contains the common entity interface, the delta contract, synthgen
(Constitution V says fixtures precede implementation), and the determinism
and observability rails every stage uses.

- [X] T006 Core Pydantic models: DrawingRevision, DrawingEntity, EntityState, DrawingGraph, RegistrationResult, EntityMatch, LabeledValue/provenance per data-model.md in backend/src/cadmorph/models.py
- [X] T007 Delta contract models (EntityDelta, SummaryLine, ChangeReport) + canonical JSON serializer (sorted keys, fixed float format) in backend/src/cadmorph/deltas/models.py, with schema-conformance test against specs/001-pdf-change-detection/contracts/entity-delta.schema.json in backend/tests/unit/test_delta_schema.py
- [X] T008 [P] Determinism utilities: global seeding (Python/NumPy/torch), torch deterministic algorithms, weight-hash check helper in backend/src/cadmorph/determinism.py (R11)
- [X] T009 [P] Observability: structlog JSON config bound to comparison_id+stage, stage-timing decorator, metrics.json writer in backend/src/cadmorph/observability.py (R9)
- [X] T010 ExtractionProvider protocol returning DrawingGraph — the single seam for feature 002 — in backend/src/cadmorph/extraction/provider.py; downstream-import rule test in backend/tests/unit/test_provider_seam.py
- [X] T011 Input validation: vector-content detection, raster_or_empty / unreadable rejection reasons (FR-002) in backend/src/cadmorph/extraction/validation.py
- [X] T012 [P] PDF provider (PyMuPDF): path/text extraction, primitive grouping into entities, stable content-hash entity IDs, dimension/text payloads in backend/src/cadmorph/extraction/pdf_provider.py (R1)
- [X] T013 [P] Input-rejection integration test: raster-only PDF → raster_or_empty, corrupt/encrypted file → unreadable, .dxf/non-PDF upload → unsupported_format, each naming the offending file (FR-002); fixtures generated in-test via PyMuPDF in backend/tests/integration/test_input_rejection.py
- [X] T014 Attributed graph construction: kNN-proximity + connectivity edges, normalized geometry signatures in backend/src/cadmorph/graph/build.py (R3)
- [X] T015 synthgen: parameterized base-sheet presets (floorplan, site, dense, unrelated), mutation engine (dim-change, add, remove, move-with-distance, text-edit, style), export offset/scale perturbations, answer keys with EntityState-shaped expected changes (ExpectedChange projection of the delta contract; format + scoring rule in tools/synthgen/README.md), CLI in tools/synthgen/ (R12)
- [X] T016 Filesystem job store + ComparisonJob state machine (pending→…→done | failed | rejected | declined) with TTL metadata in backend/src/cadmorph/pipeline.py
- [X] T017 FastAPI app skeleton: error envelope, POST /api/v1/comparisons (multipart, 202), GET /api/v1/comparisons/{id} status per contracts/api.md in backend/src/cadmorph/api/app.py and backend/src/cadmorph/api/routes.py
- [X] T018 Extraction ground-truth gate: provider output vs synthgen answer keys (entity counts, geometry, text/dimension payloads) in backend/tests/groundtruth/test_extraction.py (Constitution V gate for the extraction phase)
- [X] T019 Determinism harness: run extraction+graph twice on identical files, assert byte-identical canonical JSON in backend/tests/determinism/test_repeat_runs.py

**Checkpoint**: Foundation ready — user stories can begin

---

## Phase 3: User Story 1 — Compare Two Revisions and Get a Change List (P1) 🎯 MVP

**Goal**: Upload two aligned vector PDFs, get a complete grounded change list
with exact before/after values (FR-001..009, FR-012..014).

**Independent Test**: quickstart Scenario 1 — synthgen pair01 deltas match
the answer key (precision/recall), values verbatim, via web UI or pytest.

- [X] T020 [P] [US1] GAT symbol-spotting model + training script on synthgen-labeled sheets, pinned eval-mode weights in backend/src/cadmorph/classify/model.py and backend/src/cadmorph/classify/train.py (R4)
- [X] T021 [US1] Classification stage: type labels + confidence as provenance-flagged LabeledValue; gate test vs synthgen labels in backend/src/cadmorph/classify/stage.py and backend/tests/groundtruth/test_classify.py
- [X] T022 [P] [US1] Siamese graph matcher (shared-weight GAT encoder, cosine similarity) + training script in backend/src/cadmorph/match/model.py and backend/src/cadmorph/match/train.py (R6)
- [X] T023 [US1] Three-tier matching cascade (exact / attribute / learned + Hungarian, deterministic tie-breaks) in backend/src/cadmorph/match/cascade.py (R6)
- [X] T024 [US1] Delta computation incl. R7 moved-vs-removed rule with configurable thresholds (similarity 0.85, displacement 5% diagonal) in backend/src/cadmorph/deltas/compute.py
- [X] T025 [US1] Calibrate R7 thresholds on synthgen move-distance sweep; assert operating points meet SC-001/002; record chosen values in backend/tests/groundtruth/test_matching.py
- [X] T026 [US1] Jinja2 summary templates (entity type × change type) + renderer with "value unavailable" path in backend/src/cadmorph/summarize/templates/ and backend/src/cadmorph/summarize/render.py (R8, FR-009)
- [X] T027 [US1] Grounding gate: every summary value appears verbatim in its delta; unavailable handling; import-linter rule enforced in backend/tests/unit/test_summarizer_grounding.py (Constitution II)
- [X] T028 [US1] Pipeline orchestration extract→classify→registration(identity)→match→diff→summarize with per-stage logging; GET /api/v1/comparisons/{id}/report endpoint in backend/src/cadmorph/pipeline.py and backend/src/cadmorph/api/routes.py
- [X] T029 [US1] End-to-end ground-truth gate on pair01 (dim-change, add, remove, move): score deltas against the answer key using the documented rule (change_type + kind + anchor-bbox IoU ≥ 0.3 + verbatim value equality; entity_id/geometry_signature excluded — see tools/synthgen/README.md), precision/recall assertions, direction FR-014, identical-files→no_changes FR-012, byte-identical repeat run in backend/tests/groundtruth/test_e2e_pair01.py
- [X] T030 [P] [US1] Upload page: two file inputs (V(n-1)/V(n)), page selector, status polling, rejection messages naming the offending file in frontend/src/pages/ComparePage.tsx
- [X] T031 [US1] Change-list view: entries with change type, before/after values, delta_id, revision direction, no-changes state in frontend/src/components/ChangeList.tsx

**Checkpoint**: US1 fully functional — grounded change list from two uploads (MVP)

---

## Phase 4: User Story 2 — Review Changes on a Marked-Up Drawing (P2)

**Goal**: Every change visible at its sheet location, color-coded, linked 1:1
to the list; downloadable marked-up PDF and printable report (FR-010/011/015/017).

**Independent Test**: quickstart Scenario 2 — highlights match answer-key
locations and delta_ids; filter hides/shows list+highlights together.

- [X] T032 [P] [US2] Marked-up vector PDF: color-coded highlight annotations per delta labeled with delta_id, no-changes banner (FR-012) in backend/src/cadmorph/report/markup.py
- [X] T033 [P] [US2] Display renderer: sheet.png per revision + X-Sheet-Transform coordinate mapping header in backend/src/cadmorph/report/render.py and route in backend/src/cadmorph/api/routes.py
- [X] T034 [US2] Printable human-readable report.pdf (summary lines grouped by change type, delta_ids, revision identification) in backend/src/cadmorph/report/document.py and route
- [X] T035 [US2] Markup traceability contract test: report deltas ↔ markup annotations join 1:1 on delta_id in backend/tests/integration/test_markup_traceability.py (SC-004)
- [X] T036 [US2] Sheet viewer with SVG overlay from delta JSON; list entry ↔ highlight selection sync in frontend/src/components/SheetViewer.tsx
- [X] T037 [US2] Change-type filter applied jointly to list and overlay (FR-017) in frontend/src/components/ChangeList.tsx and frontend/src/components/SheetViewer.tsx
- [X] T038 [US2] Results page assembly + markup.pdf / report.pdf download buttons in frontend/src/pages/ResultsPage.tsx

**Checkpoint**: US1 + US2 both work — visual review experience complete

---

## Phase 5: User Story 3 — Compare Imperfectly Aligned Revisions (P3)

**Goal**: Offset/scaled exports align before comparison; unalignable inputs
are declined with a clear message (FR-003/004).

**Independent Test**: quickstart Scenario 3 — pair02 (offset/scale only) →
no_changes; pair03 (unrelated) → declined with alignment_failed.

- [X] T039 [P] [US3] Anchor extraction: unique text strings, dimension entities, unique geometry signatures in backend/src/cadmorph/register/anchors.py (R5)
- [X] T040 [US3] Seeded RANSAC similarity transform + acceptance thresholds (inlier ≥ 0.6, RMS ≤ 0.5% diagonal) in backend/src/cadmorph/register/ransac.py (R5)
- [X] T041 [US3] Pipeline integration: replace identity registration; declined outcome path with reason alignment_failed (FR-004) in backend/src/cadmorph/pipeline.py
- [X] T042 [US3] Frontend declined/rejected outcome messaging ("inputs do not appear to be revisions of the same sheet") in frontend/src/pages/ResultsPage.tsx
- [X] T043 [US3] Alignment ground-truth gates: pair02 → zero deltas; pair03 → declined; offset pair report equals un-offset pair report in backend/tests/groundtruth/test_alignment.py

**Checkpoint**: All user stories independently functional

---

## Phase 6: Polish & Cross-Cutting Concerns

- [X] T044 [P] Performance gate: 10k-entity synthgen pair end-to-end < 120 s with stage timings from metrics.json (SC-006) in backend/tests/integration/test_perf.py; optimize hottest stage if failing
- [X] T045 TTL cleanup job for data/{comparison_id} artifacts in backend/src/cadmorph/pipeline.py
- [X] T046 [P] Self-containment hardening: upload size limits, same-origin CORS, test asserting no outbound network egress during a comparison (FR-016) in backend/src/cadmorph/api/app.py and backend/tests/integration/test_self_contained.py
- [X] T047 Execute all quickstart.md scenarios end-to-end; fix any discrepancy between docs and behavior
- [X] T048 [P] README: project overview, deployment notes, pointer to quickstart in README.md

---

## Dependencies & Execution Order

- **Setup (P1)** → **Foundational (P2)** → user stories.
- **US1** depends only on Foundational. **US2** consumes US1's ChangeReport
  (needs T028's report endpoint) but its backend artifacts (T032–T034) can
  be built against synthgen answer-key deltas in parallel with late US1.
- **US3** touches only register/ + pipeline wiring; independent of US2.
- **Polish** after all desired stories.
- Within stories: models → stages → pipeline wiring → endpoints → frontend;
  gate tests written with (not after) each stage per Constitution V.

### Parallel Opportunities

- Setup: T003, T004, T005 together.
- Foundational: T008+T009 together; T012+T013 together after T010/T011 (T013 also needs T017 for API-level assertions).
- US1: T020 and T022 (two model tracks) in parallel; T030 parallel to backend work.
- US2: T032 and T033 in parallel; frontend T036–T038 after T033.
- US3: T039 parallel with anything; T040 after T039.

## Implementation Strategy

**MVP first**: Phases 1–3 only, then STOP and validate US1 against synthgen
ground truth (quickstart Scenario 1). That alone delivers the trustworthy
change list. Add US2 (visual review), then US3 (real-world alignment), each
with its own checkpoint. Model-training tasks (T020, T022) are the schedule
risk — start them first within US1 since both train on synthgen output (T015).
