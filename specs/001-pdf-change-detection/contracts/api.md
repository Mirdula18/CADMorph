# Web API Contract: PDF Drawing Change Detection

**Feature**: [../spec.md](../spec.md) | **Data model**: [../data-model.md](../data-model.md)

Base path `/api/v1`. All responses JSON unless noted. No authentication in
v1 (single-tenant, self-hosted; FR-017 excludes accounts). All processing
stays inside the deployment (FR-016).

## POST /comparisons

Start a comparison. `multipart/form-data`:

| Part | Type | Required | Notes |
|------|------|----------|-------|
| file_old | file (.pdf) | yes | V(n-1) |
| file_new | file (.pdf) | yes | V(n) |
| page | int | no | page index for multi-page PDFs (default 0; echoed in result) |

**202 Accepted** → `{ "comparison_id": "<uuid>" }`

**400** (validation, synchronous) → error envelope (below) with code
`missing_file`, `too_many_pages_requested`, or `unsupported_format`.
`.dxf` (and any non-PDF) uploads are rejected with `unsupported_format`;
DXF support is deferred to a later feature.

**413** (oversized, synchronous) → error envelope with code
`file_too_large`, naming the offending file. Per-file limit 50 MiB by
default (`CADMORPH_MAX_UPLOAD_MB`); requests whose declared Content-Length
exceeds two files' worth (+1 MiB form overhead) are refused before the
body is buffered.

## GET /comparisons/{id}

Job status. **200** →
`{ "comparison_id", "state", "created_at", "finished_at" | null,
   "outcome" | null, "reason" | null }`
where `state` follows the ComparisonJob state machine (data-model.md) and
`outcome ∈ changes_found | no_changes | declined` once done.
Rejections/declines surface here with machine-readable `reason`
(`raster_or_empty`, `unreadable`, `alignment_failed`) plus a human-readable
`message` naming the offending file (FR-002/FR-004). **404** unknown id.

## GET /comparisons/{id}/report

Full change report for the UI. **200** → `ChangeReport` JSON (per
entity-delta.schema.json for the `deltas` array; includes `summary_lines`,
revision identification (FR-014), and outcome). This endpoint powers the
browser UI; it is internal plumbing, not the out-of-scope user-facing
structured export. **409** if job not finished.

## GET /comparisons/{id}/sheet.png

Server-rendered display image of the compared sheet (V(n); V(n-1) available
via `?revision=old`). Presentation only — never an analysis input
(Constitution I). **200** `image/png` + header `X-Sheet-Transform` giving the
delta-coordinate→pixel mapping for the SVG overlay.

## GET /comparisons/{id}/markup.pdf

Downloadable marked-up drawing: original vector PDF of V(n) with color-coded
highlight annotations, one per delta, labeled with `delta_id`
(FR-010/FR-011). Includes a "no changes detected" banner page when outcome
is `no_changes` (FR-012). **200** `application/pdf`.

## GET /comparisons/{id}/report.pdf

Downloadable human-readable report: change list rendered as a printable
document (summary lines grouped by change type, each labeled with delta_id),
plus revision identification. Human-readable only per clarification — no
CSV/JSON download endpoints exist. **200** `application/pdf`.

## Error envelope (all non-2xx)

```json
{
  "error": {
    "code": "raster_or_empty | unreadable | alignment_failed | file_too_large | not_found | conflict | internal",
    "message": "human-readable, names the offending input where applicable",
    "comparison_id": "<uuid, when applicable>"
  }
}
```

## Contract invariants (tested)

- Every delta in `/report` has a matching highlight in `markup.pdf` and vice
  versa, joined on `delta_id` (FR-011, SC-004).
- Two runs over byte-identical uploads produce byte-identical `/report`
  payloads (FR-013, SC-007) — timestamps and comparison_id excluded via
  canonicalization in the determinism test harness.
- No endpoint accepts or emits drawing content to any third-party origin;
  CORS locked to same origin (FR-016).
