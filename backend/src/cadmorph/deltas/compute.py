"""Typed EntityDelta computation (T024), including the R7 moved-vs-removed
rule with configurable, ground-truth-calibrated thresholds (cadmorph.config).

Exact-tier matches produce no delta (unchanged). Attribute/learned pairs
become `modified` deltas whose modification_kinds are derived by field-wise
comparison of the two vector-exact states. A learned pair displaced further
than displacement_rel × diagonal is split into removed + added (R7).
"""

from __future__ import annotations

import hashlib

from cadmorph.config import CALIBRATED, ThresholdConfig
from cadmorph.deltas.models import EntityDelta, EntityState
from cadmorph.match.cascade import MatchOutcome
from cadmorph.models import (
    DrawingEntity,
    DrawingGraph,
    EntityMatch,
    SimilarityTransform,
    displacement,
    shape_equivalent,
    style_equivalent,
    transform_point,
)

_KIND_ORDER = ("moved", "geometry", "text", "dimension_value", "style")


def entity_state(e: DrawingEntity) -> EntityState:
    """Verbatim snapshot — every field copied, never recomputed (FR-009)."""
    return EntityState(
        entity_id=e.entity_id,
        kind=e.kind,
        bbox=e.bbox,
        position=e.position,
        geometry_signature=e.geometry_signature,
        layer=e.layer,
        style=e.style.model_dump() if e.style else None,
        text_payload=e.text_payload,
        label=e.label,
        dimension_value=e.dimension_value,
        semantic_label=e.semantic_label,
    )


def _diff_kinds(
    before: DrawingEntity,
    after: DrawingEntity,
    diag: float,
    config: ThresholdConfig,
    transform: SimilarityTransform | None = None,
) -> list[str]:
    kinds: set[str] = set()
    eps = config.position_eps_rel * diag
    if displacement(before, after, transform) > eps:
        kinds.add("moved")
    if not shape_equivalent(before, after, transform, tol=eps):
        kinds.add("geometry")
    if before.text_payload != after.text_payload:
        kinds.add("text")
    if before.dimension_value != after.dimension_value:
        kinds.add("dimension_value")
    if not style_equivalent(before, after, transform.scale if transform else 1.0):
        kinds.add("style")
    return [k for k in _KIND_ORDER if k in kinds]


def _delta_id(change_type: str, before: DrawingEntity | None, after: DrawingEntity | None) -> str:
    material = f"{change_type}|{before.entity_id if before else ''}|{after.entity_id if after else ''}"
    return "d-" + hashlib.sha1(material.encode("utf-8")).hexdigest()[:10]


def _delta(
    change_type: str,
    before: DrawingEntity | None,
    after: DrawingEntity | None,
    kinds: list[str] | None = None,
    match: EntityMatch | None = None,
    transform: SimilarityTransform | None = None,
) -> EntityDelta:
    anchor = after if after is not None else before
    assert anchor is not None
    x0, y0, x1, y1 = anchor.bbox
    if after is None and transform is not None:
        # anchor_bbox is where the highlight is DRAWN — always the V(n)
        # display frame. A removed entity has no V(n) counterpart, so its
        # V(n-1) bbox is mapped through the registration transform here;
        # the `before` state itself stays verbatim source coordinates
        # (FR-009). Identity transforms map bit-exactly.
        ax0, ay0 = transform_point((x0, y0), transform)
        ax1, ay1 = transform_point((x1, y1), transform)
        x0, x1 = min(ax0, ax1), max(ax0, ax1)
        y0, y1 = min(ay0, ay1), max(ay0, ay1)
    return EntityDelta(
        delta_id=_delta_id(change_type, before, after),
        change_type=change_type,  # type: ignore[arg-type]
        modification_kinds=kinds or [],  # type: ignore[arg-type]
        before=entity_state(before) if before else None,
        after=entity_state(after) if after else None,
        match=match,
        anchor_bbox=(x0, y0, x1, y1),
    )


def compute_deltas(
    old: DrawingGraph,
    new: DrawingGraph,
    outcome: MatchOutcome,
    config: ThresholdConfig = CALIBRATED,
    transform: SimilarityTransform | None = None,
) -> list[EntityDelta]:
    diag = new.revision.sheet_diagonal
    old_by_id = {e.entity_id: e for e in old.entities}
    new_by_id = {e.entity_id: e for e in new.entities}

    deltas: list[EntityDelta] = []
    removed_ids = list(outcome.unmatched_old)
    added_ids = list(outcome.unmatched_new)

    for match in outcome.matches:
        if match.tier == "exact":
            continue  # unchanged
        before = old_by_id[match.old_entity_id]  # both sides present on a pairing
        after = new_by_id[match.new_entity_id]
        if (
            match.tier == "learned"
            and displacement(before, after, transform) > config.displacement_rel * diag
        ):
            # R7: same-looking entity but too far away — removed + added,
            # never a false "moved" (calibrated against the twin fixture).
            removed_ids.append(before.entity_id)
            added_ids.append(after.entity_id)
            continue
        kinds = _diff_kinds(before, after, diag, config, transform)
        if not kinds:
            continue  # attribute-identical after all → unchanged
        deltas.append(_delta("modified", before, after, kinds=kinds, match=match))

    deltas.extend(
        _delta("removed", old_by_id[i], None, transform=transform) for i in sorted(removed_ids)
    )
    deltas.extend(_delta("added", None, new_by_id[i]) for i in sorted(added_ids))

    # Canonical report order (data-model.md): change_type, anchor position, delta_id.
    deltas.sort(key=lambda d: (d.change_type, d.anchor_bbox[1], d.anchor_bbox[0], d.delta_id))
    return deltas
