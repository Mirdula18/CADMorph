# synthgen — answer-key format & scoring rule

Generates ground-truth revision pairs for CADMorph validation gates
(Constitution V). Each `make-pair` run writes `v1.pdf`, `v2.pdf`, and
`answer-key.json`.

## Answer-key format

```json
{
  "preset": "floorplan", "seed": 7, "mutations": ["dim-change"],
  "export": { "offset": [0, 0], "scale": 1.0 },
  "inventory": { "v1": { "counts": {...}, "texts": [...] }, "v2": {...} },
  "expected_changes": [ ExpectedChange, ... ]
}
```

`ExpectedChange` is a projection of the `EntityDelta` contract
(specs/001-pdf-change-detection/contracts/entity-delta.schema.json, v1.1.0):

| Field | Same as EntityDelta? | Notes |
|-------|----------------------|-------|
| change_type | ✅ identical enum | added / removed / modified |
| modification_kinds | ✅ identical enum | moved / geometry / text / dimension_value / style |
| kind | ✅ identical enum (subset) | linework / text / dimension |
| anchor_bbox | ✅ same meaning | always the V(n) display frame (removed entities' V(n-1) bboxes are mapped through the export/registration transform); text bboxes are ESTIMATES (baseline + width heuristic) — compare by IoU, never equality |
| before / after | ✅ EntityState-shaped | populated per the same invariants (added → after set, removed → before set) |
| entity_id, geometry_signature | ❌ omitted | derived by the extractor from parsed content; unknowable before extraction |
| delta_id, match, semantic_label, position, layer | ❌ omitted | produced by the pipeline, not the generator |

## Scoring rule (used by groundtruth gates, incl. T029)

An `EntityDelta` D matches an `ExpectedChange` E iff ALL of:

1. `D.change_type == E.change_type`
2. `D.(after or before).kind == E.kind`
3. IoU(`D.anchor_bbox`, `E.anchor_bbox`) ≥ **0.3** (low threshold because
   text-bbox estimates are approximate; raise only with evidence from gates)
4. Value equality on every grounded field of E's states —
   `text_payload`, `label`, `dimension_value` — compared verbatim
   (string-equal, units included) against D's corresponding state, in BOTH
   directions: a null in the key must be null in the delta. A fabricated
   value where the key has none is a mismatch (FR-009 posture).

Matching is one-to-one (each E consumes at most one D). Precision =
matched/|deltas|, recall = matched/|expected_changes| (SC-001/SC-002).

**Explicitly excluded from scoring**: `entity_id` and `geometry_signature`
(unknowable before extraction), `delta_id`, `match`, `semantic_label`
(inference output, gated separately in T021), and style float precision.

## Training artifacts (not scored)

Each pair also writes `entities-v1.json` / `entities-v2.json`: per-entity
ground truth `{uid, kind, semantic, bbox, text}` in the exported coordinate
frame. `uid` is stable across revisions (correspondence labels for the
Siamese matcher, T022); `semantic` is the node label for GAT symbol-spotting
training (T020/T021). These files feed model training and per-stage gates
only — the answer-key scoring rule above never reads them.

The `twin` mutation removes an entity and adds an identical-shaped twin far
away (~40% of the sheet diagonal): the calibration fixture (T025) proving
the moved-vs-removed displacement threshold does not merge distant
remove+add pairs into a false "moved".
