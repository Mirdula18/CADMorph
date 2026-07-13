# Implementation Plan: PDF Drawing Change Detection (Vector Path)

**Branch**: `001-pdf-change-detection` | **Date**: 2026-07-04 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `specs/001-pdf-change-detection/spec.md`

## Summary

Compare two CAD-exported vector PDFs of the same sheet and produce a grounded
change report (marked-up drawing + human-readable change list) via a web app.
Vector path only: parse exact geometry with PyMuPDF (PDF) / ezdxf (DXF) into an
attributed drawing graph behind a single `ExtractionProvider` interface; enrich
entity types with a GAT symbol-spotting model; register the two revisions with
entity-anchor correspondences + seeded RANSAC; match entities across revisions
with a Siamese graph matcher; emit structured typed deltas; generate summaries
by deterministic templating over deltas only; assemble the report. A future
raster fallback (feature 002) plugs into the same interface; no raster
components are designed or implemented here.

## Technical Context

**Language/Version**: Python 3.11+

**Primary Dependencies**: FastAPI + Uvicorn (web API), PyMuPDF (PDF vector
extraction), ezdxf (DXF extraction), PyTorch + PyTorch Geometric (GAT
symbol-spotting, Siamese graph matcher), NumPy/SciPy (geometry, seeded RANSAC),
Pydantic v2 (typed deltas / API schemas), structlog (JSON structured logging),
Jinja2 (summary templates), lightweight React + TypeScript frontend rendering
the sheet with an SVG highlight overlay driven by delta data

**Storage**: Local filesystem job store (uploads, intermediate artifacts,
reports) keyed by comparison ID; no database in v1 (no accounts, no persistent
review state per FR-017)

**Testing**: pytest; synthetic ground-truth pair generator (`tools/synthgen`)
providing per-phase validation gates (Constitution V); determinism tests
asserting byte-identical delta output across repeated runs (Constitution IV)

**Target Platform**: Self-hosted server (Linux or Windows), modern browser
client; fully self-contained deployment — no third-party service calls with
drawing content (FR-016)

**Project Type**: Web application (backend + frontend)

**Performance Goals**: Comparison of a single sheet with up to 10,000 entities
completes in under 2 minutes end to end (SC-006); detection ≥95% overall /
≥99% on dimension values, false positives ≤2% on ground-truth pairs
(SC-001/002)

**Constraints**: Vector-native only — raster/scanned inputs rejected with a
clear message (FR-002); one sheet per comparison; deterministic pipeline
(seeded stochastic components, fixed model weights in eval mode); all values
in outputs sourced from coordinates/text layers, never fabricated (FR-009)

**Scale/Scope**: Single-tenant deployments for AEC firms; one comparison job
at a time per worker; sheets up to A0 with ≤10k entities

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| # | Principle | Status | How the design complies |
|---|-----------|--------|-------------------------|
| I | Vector-Native First | PASS | PyMuPDF/ezdxf parse exact vector geometry; inputs without a usable vector layer are rejected (FR-002), never rasterized. Server-side rendering of the sheet for *display* in the browser viewer is presentation only — no comparison logic consumes pixels. |
| II | Grounded Outputs | PASS | The summarizer's only input is the typed `EntityDelta` list; it is template-based (Jinja2 over delta fields), so it cannot fabricate values. It has no access to pixels or raw files by construction (module boundary + tests). |
| III | Entity-Level Traceability | PASS | Every `EntityDelta` carries a stable entity ID, change type, and full before/after `EntityState`. Report lines and markup highlights are generated 1:1 from deltas and share the delta ID (FR-007/FR-011). |
| IV | Determinism Where Possible | PASS (with flagged inference, justified below) | Geometry, bounding boxes, dimension values, and text come exclusively from PDF/DXF coordinates and text layers. Inference is used ONLY for semantic enrichment that has no deterministic source: entity-type labels (GAT) and cross-revision correspondence scores (Siamese matcher). Both are flagged `inference-derived` with confidence in delta provenance. RANSAC is seeded; models run in eval mode with fixed weights → identical inputs produce identical deltas. |
| V | Ground-Truth Validation Before Trust | PASS | `tools/synthgen` generates synthetic revision pairs with known injected changes; each phase (extraction, classification, registration, matching, deltas, summary) has a validation gate with precision/recall reporting before downstream phases build on it. |

**Principle IV justification (recorded in Complexity Tracking)**: The
constitution permits inference "only where deterministic extraction is
impossible". Entity-type labels (e.g., "door symbol") and cross-revision
entity correspondence do not exist in PDF/DXF source data — they are semantic
facts with no deterministic source, so inference is the only option. The
design confines inference to those two facts: it never produces geometry,
boxes, dimension values, text, or the existence of a change, and every
inference-derived field is provenance-flagged with confidence.

**FR-016 gate**: GAT, Siamese matcher, and summary generation all run
in-process on the operator's infrastructure. Templated summarization (not a
hosted LLM) is the v1 summarizer. No drawing content leaves the deployment.

**Post-design re-check (after Phase 1)**: PASS — the `EntityDelta` contract
(`contracts/entity-delta.schema.json`) carries `provenance` and
`confidence` fields on every inference-derived attribute; the summarizer
contract consumes only that schema; the API contract exposes rejection
responses for raster/corrupt inputs and alignment failure. No new violations
introduced by the design artifacts.

## Project Structure

### Documentation (this feature)

```text
specs/001-pdf-change-detection/
├── plan.md              # This file (/speckit-plan command output)
├── research.md          # Phase 0 output (/speckit-plan command)
├── data-model.md        # Phase 1 output (/speckit-plan command)
├── quickstart.md        # Phase 1 output (/speckit-plan command)
├── contracts/           # Phase 1 output (/speckit-plan command)
│   ├── api.md           # Web API contract (upload, status, results, errors)
│   └── entity-delta.schema.json  # Typed delta contract (detection ↔ summary)
└── tasks.md             # Phase 2 output (/speckit-tasks command - NOT created by /speckit-plan)
```

### Source Code (repository root)

```text
backend/
├── src/cadmorph/
│   ├── extraction/          # ONE common entity interface + vector providers
│   │   ├── provider.py      # ExtractionProvider protocol → DrawingGraph (the plug point for feature 002)
│   │   ├── pdf_provider.py  # PyMuPDF vector extraction
│   │   ├── dxf_provider.py  # ezdxf extraction
│   │   └── validation.py    # vector-content check, reject raster/corrupt (FR-002)
│   ├── graph/               # attributed drawing graph construction (nodes=entities, edges=spatial relations)
│   ├── classify/            # GAT symbol-spotting → entity-type labels + confidence
│   ├── register/            # entity-anchor correspondence + seeded RANSAC transform (FR-003/004)
│   ├── match/               # Siamese graph matcher → cross-revision correspondence
│   ├── deltas/              # typed EntityDelta computation incl. moved-vs-removed rule
│   ├── summarize/           # Jinja2 templated grounded summaries (deltas in, sentences out)
│   ├── report/              # marked-up PDF overlay + downloadable report assembly (FR-010/015)
│   ├── pipeline.py          # stage orchestration, per-stage timing, comparison job lifecycle
│   ├── observability.py     # structlog config, per-stage metrics, comparison_id correlation
│   └── api/                 # FastAPI app: upload, status, results, markup, download
└── tests/
    ├── unit/
    ├── integration/
    ├── determinism/         # byte-identical delta runs (Constitution IV)
    └── groundtruth/         # per-phase gates against synthetic pairs (Constitution V)

frontend/
├── src/
│   ├── components/          # upload form, change list w/ type filter (FR-017), sheet viewer + SVG overlay
│   ├── pages/               # compare page, results page
│   └── services/            # API client
└── tests/

tools/
└── synthgen/                # synthetic ground-truth pair generator + answer keys
```

**Structure Decision**: Web application layout (backend + frontend) with a
separate `tools/synthgen` package. All pipeline stages downstream of
`extraction/provider.py` depend only on the `DrawingGraph`/`DrawingEntity`
interface, never on PyMuPDF/ezdxf types — this is the single seam where the
feature-002 raster provider will attach.

## Complexity Tracking

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| Inference (GAT, Siamese matcher) on the vector path — strict reading of Principle IV reserves inference for the raster path | Entity-type labels and cross-revision correspondence have no deterministic source in PDF/DXF data; without them the report cannot name entities ("Dimension D14", "door symbol") or distinguish moved from removed+added | Rule-based type heuristics (e.g., "closed polyline = room") collapse on real symbol libraries and produce silently wrong labels with no confidence signal; exact-geometry hashing alone cannot match entities whose attributes changed, which is precisely the "modified" case this feature exists to detect. Inference outputs are confined to labels/correspondence, seeded and eval-mode for determinism, and provenance-flagged with confidence — geometry and values remain coordinate-derived |
