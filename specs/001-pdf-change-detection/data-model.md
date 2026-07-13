# Data Model: PDF Drawing Change Detection (Vector Path)

**Feature**: [spec.md](./spec.md) | **Plan**: [plan.md](./plan.md) | **Date**: 2026-07-04

All models are Pydantic v2; the `EntityDelta` family is additionally frozen as
a JSON Schema contract in [contracts/entity-delta.schema.json](./contracts/entity-delta.schema.json)
because it is the boundary between detection and summarization
(Constitution: Pipeline Constraints).

## Provenance vocabulary (used across models)

`Provenance = "vector-exact" | "inference"` — every field that can be
inference-derived carries `(value, provenance, confidence)`; vector-exact
fields carry provenance implicitly at the object level. This is the
Principle IV flag and the seam feature 002 (raster) will reuse with its own
provenance value.

## DrawingRevision

| Field | Type | Notes |
|-------|------|-------|
| revision_id | str | `"old"` (V(n-1)) or `"new"` (V(n)) within a comparison |
| source_filename | str | as uploaded |
| format | enum: pdf, dxf | detected, not extension-trusted |
| page_index | int | page compared (multi-page PDFs: chosen page, reported to user) |
| sheet_width, sheet_height | float | source units |
| sheet_diagonal | float | basis for all relative thresholds (R5–R7) |
| content_hash | str | SHA-256 of file bytes; key for determinism tests |

**Validation**: must contain usable vector content, else the comparison is
rejected with `reason = raster_or_empty` (FR-002). Encrypted/corrupt files →
`reason = unreadable`.

## DrawingEntity

| Field | Type | Notes |
|-------|------|-------|
| entity_id | str | stable + deterministic: DXF → source handle; PDF → hash of (normalized geometry, position, style, text) with deterministic collision suffix |
| kind | enum: linework, text, dimension, symbol, hatch | structural kind (deterministic) |
| geometry | list[PathSegment] | exact source coordinates (vector-exact) |
| bbox | [x0, y0, x1, y1] | from coordinates, never inferred (Principle IV) |
| geometry_signature | str | normalized translation/rotation-invariant hash (R3) |
| layer, style | str, StyleAttrs | layer name (DXF) / stroke-fill style (PDF) |
| text_payload | str \| null | exact text from text layer (vector-exact) |
| dimension_value | str \| null | dimension text as annotated, unit string preserved (no conversion) |
| semantic_label | LabeledValue \| null | GAT type label: (value, provenance="inference", confidence) |

**Validation**: geometry, bbox, text_payload, dimension_value MUST originate
from source coordinates/text (FR-009); semantic_label is the only
inference-derived field on an entity.

## DrawingGraph

| Field | Type | Notes |
|-------|------|-------|
| revision | DrawingRevision | |
| entities | list[DrawingEntity] | sorted by entity_id (canonical order) |
| edges | list[(entity_id, entity_id, EdgeKind)] | EdgeKind: knn-proximity, connectivity |

`DrawingGraph` is the output type of `ExtractionProvider` — the ONE common
interface. Downstream stages may not import provider modules.

## RegistrationResult

| Field | Type | Notes |
|-------|------|-------|
| transform | {tx, ty, scale, rotation} | similarity transform old→new frame |
| inlier_ratio | float | accept ≥ 0.6 (R5) |
| rms_residual_rel | float | relative to sheet diagonal; accept ≤ 0.005 (R5) |
| status | enum: aligned, failed | failed → comparison declined (FR-004) |
| anchors_used | int | logged for observability (R9) |

## EntityMatch

| Field | Type | Notes |
|-------|------|-------|
| old_entity_id, new_entity_id | str \| null | null on one side = added/removed |
| tier | enum: exact, attribute, learned | R6 cascade tier |
| similarity | LabeledValue \| null | present iff tier = learned (provenance="inference") |

## EntityState

Snapshot of one entity at one revision, embedded in deltas (before/after):
`{entity_id, kind, bbox, position, geometry_signature, layer, style,
text_payload, dimension_value, semantic_label}` — all copied verbatim from
the `DrawingEntity`, never recomputed.

## EntityDelta  ← detection ↔ summarization contract

| Field | Type | Notes |
|-------|------|-------|
| delta_id | str | stable; shared by list entry + markup highlight (FR-011) |
| change_type | enum: added, removed, modified | exactly one (FR-006) |
| modification_kinds | list[enum: moved, geometry, text, dimension_value, style] | non-empty iff modified; "moved" per R7 rule |
| before | EntityState \| null | null iff added (FR-007) |
| after | EntityState \| null | null iff removed (FR-007) |
| match | EntityMatch \| null | provenance of the pairing decision |
| anchor_bbox | [x0, y0, x1, y1] | where the highlight is drawn — always the V(n) display frame; a removed entity's V(n-1) bbox is mapped through the registration transform (its `before` state stays verbatim V(n-1) coordinates per FR-009) |

**Validation**: `added → before is null ∧ after present`; `removed →
after is null ∧ before present`; `modified → both present ∧
modification_kinds non-empty`. Every user-facing report line MUST reference
exactly one delta_id (Principle III).

## SummaryLine

| Field | Type | Notes |
|-------|------|-------|
| delta_id | str | 1:1 with EntityDelta |
| text | str | rendered from template over delta fields only (R8) |
| values_grounded | bool | false only when a value was unavailable and the line says so (FR-009) |

## ChangeReport

| Field | Type | Notes |
|-------|------|-------|
| comparison_id | str | job key; correlates logs, files, API resources |
| revisions | {old, new: DrawingRevision} | direction explicit (FR-014) |
| outcome | enum: changes_found, no_changes, declined | declined carries reason (FR-004/FR-012) |
| deltas | list[EntityDelta] | canonical order: change_type, then anchor position, then delta_id |
| summary_lines | list[SummaryLine] | 1:1 with deltas |
| markup_ref | path | marked-up vector PDF artifact (FR-010) |
| metrics_ref | path | metrics.json (R9) |
| pipeline_version | str | code version + model-weight hashes (audit/determinism) |

## ComparisonJob (state machine)

```
pending → extracting → classifying → registering → matching → diffing
        → summarizing → reporting → done
any state → failed(reason)          # unexpected error
extracting → rejected(reason)       # raster/corrupt input (FR-002)
registering → declined(reason)      # alignment failure (FR-004)
```

| Field | Type | Notes |
|-------|------|-------|
| comparison_id | str | UUIDv4 assigned at upload |
| state | enum (above) | exposed by status API |
| created_at, finished_at | datetime | SC-006 measurement basis |
| stage_timings | dict[stage, ms] | from observability layer (R9) |

Jobs and artifacts live on the filesystem under `data/{comparison_id}/` and
are ephemeral (TTL cleanup); no database, accounts, or persistent review
state in v1 (FR-017).
