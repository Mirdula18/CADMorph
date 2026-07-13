"""Three-tier matching cascade (T023, research R6).

Cheapest first: (1) exact — identical full content signature within ε of the
same registered position; (2) attribute — deterministically re-keyable
entities that changed payload in place (dimension label, text position,
linework shape); (3) learned — Siamese similarity + Hungarian assignment
over the remainder, deterministic tie-breaks (scipy's assignment is
deterministic; candidates are canonically ordered).

Both graphs must already be in a common coordinate frame (US1: identity
registration; US3 applies the RANSAC transform before calling this).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from scipy.optimize import linear_sum_assignment

from cadmorph.config import CALIBRATED, ThresholdConfig
from cadmorph.match.model import SiameseEncoder, embed_graph, similarity_matrix
from cadmorph.models import (
    DrawingEntity,
    DrawingGraph,
    EntityMatch,
    LabeledValue,
    SimilarityTransform,
    displacement,
    shape_equivalent,
    style_equivalent,
    transform_point,
)


@dataclass
class MatchOutcome:
    matches: list[EntityMatch] = field(default_factory=list)
    unmatched_old: list[str] = field(default_factory=list)
    unmatched_new: list[str] = field(default_factory=list)
    tier_counts: dict[str, int] = field(default_factory=dict)
    similarity_histogram: dict[str, int] = field(default_factory=dict)  # R9 signal


def _iou(a: DrawingEntity, b: DrawingEntity, transform: SimilarityTransform | None) -> float:
    ax0, ay0, ax1, ay1 = a.bbox
    if transform is not None:
        ax0, ay0 = transform_point((ax0, ay0), transform)
        ax1, ay1 = transform_point((ax1, ay1), transform)
    bx0, by0, bx1, by1 = b.bbox
    iw = min(ax1, bx1) - max(ax0, bx0)
    ih = min(ay1, by1) - max(ay0, by0)
    if iw <= 0 or ih <= 0:
        return 0.0
    inter = iw * ih
    union = (ax1 - ax0) * (ay1 - ay0) + (bx1 - bx0) * (by1 - by0) - inter
    return inter / union if union > 0 else 0.0


def _greedy_one_to_one(
    candidates: list[tuple[float, DrawingEntity, DrawingEntity]],
    taken_old: set[str],
    taken_new: set[str],
) -> list[tuple[DrawingEntity, DrawingEntity]]:
    """Deterministic nearest-first assignment: sort by (distance, ids)."""
    pairs = []
    ordered = sorted(candidates, key=lambda c: (c[0], c[1].entity_id, c[2].entity_id))
    for _, old_e, new_e in ordered:
        if old_e.entity_id in taken_old or new_e.entity_id in taken_new:
            continue
        taken_old.add(old_e.entity_id)
        taken_new.add(new_e.entity_id)
        pairs.append((old_e, new_e))
    return pairs


def match_entities(
    old: DrawingGraph,
    new: DrawingGraph,
    encoder: SiameseEncoder | None,
    config: ThresholdConfig = CALIBRATED,
    transform: SimilarityTransform | None = None,
) -> MatchOutcome:
    diag = new.revision.sheet_diagonal
    eps = config.position_eps_rel * diag
    tol2 = config.tier2_tol_rel * diag
    outcome = MatchOutcome()
    taken_old: set[str] = set()
    taken_new: set[str] = set()

    def _dist(a: DrawingEntity, b: DrawingEntity) -> float:
        # String-length-robust AND registration-aware: old-revision points
        # are mapped into the new frame before measuring (US3).
        return displacement(a, b, transform)

    # The hash fast path is an OPTIMIZATION gate only: signatures are
    # translation-invariant, so it is valid for identity and pure-offset
    # fits. Fitted offsets can carry float dust in scale (e.g.
    # 0.9999999999999998), which routes them to the numeric path — correct
    # there too, just slower.
    hash_exact = transform is None or (transform.scale == 1.0 and transform.rotation == 0.0)

    def emit(old_e: DrawingEntity, new_e: DrawingEntity, tier: str, sim: float | None = None) -> None:
        similarity = None
        if sim is not None:
            similarity = LabeledValue(
                value=round(sim, 6), provenance="inference", confidence=round(sim, 6)
            )
        outcome.matches.append(
            EntityMatch(
                old_entity_id=old_e.entity_id,
                new_entity_id=new_e.entity_id,
                tier=tier,  # type: ignore[arg-type]
                similarity=similarity,
            )
        )
        outcome.tier_counts[tier] = outcome.tier_counts.get(tier, 0) + 1

    # ---- Tier 1: exact (identical content at the registered position ±ε) ----
    if hash_exact:
        new_by_sig: dict[str, list[DrawingEntity]] = {}
        for e in new.entities:
            new_by_sig.setdefault(e.geometry_signature, []).append(e)
        tier1 = [
            (_dist(old_e, new_e), old_e, new_e)
            for old_e in old.entities
            for new_e in new_by_sig.get(old_e.geometry_signature, [])
            if _dist(old_e, new_e) <= eps
        ]
    else:
        # Scaled/rotated exports: same kind+text at the registered position,
        # geometry and style equivalent modulo the transform -> unchanged.
        new_by_key: dict[tuple[str, str | None], list[DrawingEntity]] = {}
        for e in new.entities:
            new_by_key.setdefault((e.kind, e.text_payload), []).append(e)
        scale = transform.scale if transform else 1.0
        tier1 = [
            (_dist(old_e, new_e), old_e, new_e)
            for old_e in old.entities
            for new_e in new_by_key.get((old_e.kind, old_e.text_payload), [])
            if _dist(old_e, new_e) <= eps
            and shape_equivalent(old_e, new_e, transform, tol=eps)
            and style_equivalent(old_e, new_e, scale)
        ]
    for old_e, new_e in _greedy_one_to_one(tier1, taken_old, taken_new):
        emit(old_e, new_e, "exact")

    # ---- Tier 2: attribute (payload changed in place, deterministic keys) ----
    rem_old = [e for e in old.entities if e.entity_id not in taken_old]
    rem_new = [e for e in new.entities if e.entity_id not in taken_new]

    tier2: list[tuple[float, DrawingEntity, DrawingEntity]] = []
    for old_e in rem_old:
        for new_e in rem_new:
            if old_e.kind != new_e.kind:
                continue
            d = _dist(old_e, new_e)
            if old_e.kind == "dimension" and old_e.label and old_e.label == new_e.label:
                if d <= tol2:
                    tier2.append((d, old_e, new_e))
            elif old_e.kind in ("text", "dimension"):
                if d <= tol2:
                    tier2.append((d, old_e, new_e))
            elif shape_equivalent(old_e, new_e, transform, tol=eps) and d <= tol2:
                tier2.append((d, old_e, new_e))  # same shape in place, style changed
            elif _iou(old_e, new_e, transform) >= 0.8:
                tier2.append((d, old_e, new_e))  # geometry edited in place
    for old_e, new_e in _greedy_one_to_one(tier2, taken_old, taken_new):
        emit(old_e, new_e, "attribute")

    # ---- Tier 3: learned (Siamese similarity + Hungarian, R6/R7) ----
    rem_old = [e for e in rem_old if e.entity_id not in taken_old]
    rem_new = [e for e in rem_new if e.entity_id not in taken_new]
    if encoder is not None and rem_old and rem_new:
        idx_old = {e.entity_id: i for i, e in enumerate(old.entities)}
        idx_new = {e.entity_id: i for i, e in enumerate(new.entities)}
        emb_old = embed_graph(old, encoder)
        emb_new = embed_graph(new, encoder)
        sim_full = similarity_matrix(emb_old, emb_new)
        rows = [idx_old[e.entity_id] for e in rem_old]
        cols = [idx_new[e.entity_id] for e in rem_new]
        sim = sim_full[rows][:, cols].numpy().astype("float64")
        for i, old_e in enumerate(rem_old):  # kind mismatch is never a pairing
            for j, new_e in enumerate(rem_new):
                if old_e.kind != new_e.kind:
                    sim[i, j] = -1.0
        row_ind, col_ind = linear_sum_assignment(-sim)
        for i, j in zip(row_ind, col_ind, strict=True):
            s = float(sim[i, j])
            bucket = f"{max(min(s, 0.999), -1.0):.1f}"
            outcome.similarity_histogram[bucket] = outcome.similarity_histogram.get(bucket, 0) + 1
            if s >= config.similarity:
                emit(rem_old[i], rem_new[j], "learned", sim=s)
                taken_old.add(rem_old[i].entity_id)
                taken_new.add(rem_new[j].entity_id)

    outcome.unmatched_old = sorted(e.entity_id for e in old.entities if e.entity_id not in taken_old)
    outcome.unmatched_new = sorted(e.entity_id for e in new.entities if e.entity_id not in taken_new)
    return outcome
