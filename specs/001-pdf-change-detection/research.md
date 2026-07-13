# Phase 0 Research: PDF Drawing Change Detection (Vector Path)

**Feature**: [spec.md](./spec.md) | **Plan**: [plan.md](./plan.md) | **Date**: 2026-07-04

All Technical Context unknowns are resolved below, including the two design
items deferred from `/speckit-clarify`: the moved-vs-removed matching
threshold (R7) and the observability approach (R9).

## R1. PDF vector extraction

- **Decision**: PyMuPDF (`fitz`) — `page.get_drawings()` for vector paths,
  `page.get_text("rawdict")` for text spans with exact coordinates and font
  metadata.
- **Rationale**: Only mainstream Python library exposing both the full vector
  display list (paths, strokes, fills, transforms) and positioned text from
  one parse; mature, fast on large sheets.
- **Alternatives considered**: `pdfminer.six`/`pdfplumber` (text-first, weak
  vector path fidelity, slow on dense sheets); `pikepdf` (object-level access
  only — would require writing a content-stream interpreter).

## R2. DXF extraction

- **Decision**: ezdxf, reading modelspace/paperspace entities with native
  handles, layers, and dimension objects.
- **Rationale**: DXF entities carry authoritative identity (handles) and true
  dimension semantics — the highest-fidelity input the common interface can
  receive; de-facto standard Python DXF library.
- **Alternatives considered**: dxfgrabber (unmaintained); ODA File Converter
  round-trips (external binary, conflicts with self-contained deployment).

## R3. Attributed drawing graph representation

- **Decision**: Nodes are `DrawingEntity` objects (primitives grouped into
  candidate entities by connectivity and style); node attributes: normalized
  translation/rotation-invariant geometry signature, bounding box,
  layer/style, text payload. Edges: k-nearest-neighbor spatial proximity plus
  endpoint-connectivity relations. Materialized as PyTorch Geometric `Data`
  for the learned stages; plain Pydantic objects everywhere else.
- **Rationale**: One graph feeds both learned components (GAT, Siamese
  matcher) and deterministic geometry logic; invariant signatures make moved
  entities recognizable (R7).
- **Alternatives considered**: Flat entity list (loses spatial context the GAT
  needs); full constraint graph (over-engineered for diffing).

## R4. Entity-type classification

- **Decision**: Graph Attention Network (GAT) symbol spotting over the drawing
  graph, producing an entity-type label + confidence per node; trained on
  synthgen-generated labeled sheets; pinned weights, eval mode at inference.
- **Rationale**: Symbol identity (door, valve, dimension, north arrow) is not
  present in PDF vector data; a GAT exploits neighborhood structure, which is
  how symbols differ from ambient linework. Confidence output satisfies the
  Principle IV flagging requirement.
- **Alternatives considered**: Rule-based heuristics (brittle across symbol
  libraries, no confidence signal — rejected in plan Complexity Tracking);
  CNN on rendered patches (rasterizes vector data — Constitution I violation
  on the primary path).

## R5. Sheet registration (alignment)

- **Decision**: Two-stage: (1) build candidate anchor correspondences from
  high-distinctiveness entities (unique text strings, dimension entities,
  unique geometry signatures); (2) estimate a similarity transform
  (translation + uniform scale + rotation) with seeded RANSAC over anchor
  pairs. Accept if inlier ratio ≥ 0.6 and RMS residual ≤ 0.5% of sheet
  diagonal; otherwise declare alignment failure and decline (FR-004).
- **Rationale**: CAD exports differ by page placement/scale (spec US3), fully
  captured by a similarity transform; unique text anchors are exact,
  deterministic correspondences, so RANSAC mostly confirms rather than
  searches. Fixed seed preserves identical output run to run.
- **Alternatives considered**: ICP over all geometry (slow at 10k entities,
  degrades under large content changes); title-block-only alignment (fails
  when the title block itself changed).

## R6. Cross-revision entity matching

- **Decision**: Three-tier cascade, cheapest first:
  1. **Exact tier (deterministic)**: identical geometry signature + identical
     attributes + registered position within ε = 0.1% of sheet diagonal →
     matched unchanged.
  2. **Attribute tier (deterministic)**: identical geometry signature at the
     same position with differing text/attribute payload → matched modified.
  3. **Learned tier**: remaining unmatched nodes scored by a Siamese graph
     matcher (shared-weight GAT encoder, embedding cosine similarity), solved
     as one-to-one assignment (Hungarian) over pairs with similarity ≥ 0.85;
     deterministic tie-breaking (highest score, then smallest entity ID).
- **Rationale**: Most of a revised sheet is unchanged — the deterministic
  tiers handle it exactly and fast, reserving learned matching for genuinely
  changed entities, minimizing the inference surface per Principle IV.
- **Alternatives considered**: Learned matching for everything (discards the
  vector path's exactness, larger nondeterminism risk); geometry hashing only
  (cannot pair modified entities — defeats the feature's purpose).

## R7. Moved-vs-removed threshold (deferred item 1)

- **Decision**: After registration, an entity of V(n-1) unmatched by tiers
  1–2 is classified as:
  - **modified (moved)** if the learned tier pairs it with a V(n) entity with
    similarity ≥ 0.85 AND identical geometry signature AND displacement ≤ 5%
    of the sheet diagonal;
  - **modified (geometry/attribute)** if similarity ≥ 0.85 with a differing
    signature or payload at ≤ 5% displacement;
  - **removed** otherwise (and the unpaired V(n) counterpart, if any, is
    **added**).
  Both thresholds (0.85 similarity, 5% displacement) are configuration
  values whose operating points MUST be validated on synthgen pairs
  containing known moves at varying distances before the defaults are
  trusted (Constitution V) — tuned against ground truth, not demo files.
- **Rationale**: An entity that kept its exact shape and landed nearby is a
  move — reporting it as removed+added double-counts and misleads reviewers
  (spec edge case). Sheet-diagonal-relative bounds keep the rule
  scale-independent; the ground-truth gate keeps the numbers honest.
- **Alternatives considered**: Absolute distance threshold in page units
  (breaks across sheet sizes); treating every unmatched pair as
  removed+added (simpler, but contradicts the spec's moved-entity edge case).

## R8. Grounded summary generation

- **Decision**: Deterministic template generation — Jinja2 templates keyed by
  (entity type × change type), rendering only `EntityDelta` fields, e.g.
  "Dimension {label} changed from {before.value} to {after.value}". Values
  absent from the delta render as "value unavailable" (FR-009). The
  summarizer package imports only the delta contract — a lint/test rule
  forbids importing extraction, PyMuPDF, or image modules.
- **Rationale**: Templates cannot hallucinate — Principle II compliance is
  structural, not behavioral; output is deterministic (Principle IV) and
  self-contained (FR-016). For a fixed domain of change types, template
  sentences are fully adequate without a language model.
- **Alternatives considered**: Self-hosted local LLM paraphrasing delta JSON
  (permitted by FR-016; a possible later enhancement behind the same delta
  contract, but adds nondeterminism, model ops, and grounding-audit burden
  for marginal fluency gain in v1); hosted LLM APIs (prohibited by FR-016).

## R9. Observability & logging (deferred item 2)

- **Decision**: `structlog` emitting JSON lines to stdout and a per-job log
  file, every event bound to `comparison_id` and `stage`. Each pipeline stage
  logs entity counts in/out, wall time, and stage-specific quality signals —
  registration inlier ratio + RMS residual, matcher similarity histogram,
  per-tier match counts, delta counts by change type, and count of
  inference-derived fields with confidence < 0.5. Each completed comparison
  also writes a `metrics.json` artifact beside the report (machine-readable
  run record shared by debugging and ground-truth evaluation). No
  third-party telemetry or crash reporting — logs never leave the deployment
  (FR-016); log payloads reference entity IDs, never embed drawing content.
- **Rationale**: Per-stage quality signals are exactly what Constitution V
  gates measure, so validation and production observability share one
  instrumentation path; `comparison_id` correlation makes any failed job
  fully reconstructable from its log alone.
- **Alternatives considered**: OpenTelemetry + collector (operational
  overhead unjustified for single-tenant v1; revisit if deployments grow);
  plain-text logs (not machine-parseable for evaluation tooling).

## R10. Web application stack & result viewing

- **Decision**: FastAPI backend; comparisons run as background jobs on a
  single-worker in-process queue; results stored on the filesystem under
  `comparison_id`. React + TypeScript frontend: upload page and results page
  showing the change list (filterable by change type, FR-017) beside a sheet
  view — a server-rendered raster image of the V(n) sheet used for *display
  only*, with change highlights drawn as an SVG overlay from delta JSON
  (list entry ↔ highlight linked by delta ID, FR-011). The downloadable
  marked-up drawing is the original vector PDF with color-coded highlight
  annotations added via PyMuPDF (vector fidelity preserved; FR-010/FR-015).
- **Rationale**: Display rendering is presentation, not analysis — no
  comparison logic touches pixels, so Constitution I is intact. Overlays
  driven by delta JSON keep the viewer traceable to entities (Principle
  III). A single worker meets SC-006 without distributed infrastructure.
- **Alternatives considered**: pdf.js client-side rendering (viable, but
  server-side rendering keeps delta-to-pixel coordinate mapping in one
  place); Celery/Redis job queue (unneeded for one-job-at-a-time v1).

## R11. Determinism engineering

- **Decision**: Global fixed seeds (Python, NumPy, torch); torch
  `use_deterministic_algorithms(True)`; models in eval mode with pinned,
  hash-checked weight artifacts; canonical JSON serialization (sorted keys,
  fixed float formatting) for deltas and reports so repeat runs are
  byte-identical (FR-013, SC-007).
- **Rationale**: Constitution IV requires identical structured deltas for
  identical inputs; each mechanism closes a specific nondeterminism source
  (RNG, CUDA kernels, dict ordering, float repr).
- **Alternatives considered**: Tolerance-based repeatability (approximate
  report comparison) — rejected: byte-identity is stricter and testable.

## R12. Synthetic ground-truth generation

- **Decision**: `tools/synthgen` programmatically composes base sheets
  (parameterized floor-plan/site-plan generators with dimension chains, text
  notes, symbol placements), then applies scripted mutations — dimension
  value change, entity add/remove, entity move (parameterized distance),
  text edit, style change, plus export-level offset/scale perturbations —
  exporting both revisions as vector PDFs together with an answer-key JSON
  whose expected changes are an **ExpectedChange projection** of the delta
  contract: EntityState-shaped before/after states, with `entity_id` and
  `geometry_signature` omitted as unknowable before extraction (see
  tools/synthgen/README.md for the format and scoring rule).
- **Rationale**: Constitution V demands known change sets; EntityState-shaped
  expected changes let phase gates score matcher output against the key with
  one documented rule (change_type + kind + bbox-IoU + value equality) —
  no per-test ad-hoc adapters. Parameterized move distances are what
  calibrate the R7 thresholds.
- **Alternatives considered**: Hand-labeled real revision pairs (no
  exhaustive answer key, high labeling cost; retained later as a small
  acceptance-check set, not the validation basis).
