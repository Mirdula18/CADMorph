"""Anchor extraction for registration (T039, research R5).

Candidate correspondences from high-distinctiveness entities:
  - unique text strings (including dimension texts): exact, deterministic —
    the same string appearing exactly once on each sheet IS the same object;
    paired at the content-invariant text insertion origin;
  - unique geometry signatures (linework): valid for offset-only exports
    (signatures are translation-invariant; under scaling they diverge and
    the text anchors carry the alignment alone).
Anchors are emitted in sorted key order — fully deterministic input to the
seeded RANSAC (Constitution IV).
"""

from __future__ import annotations

from collections import Counter

from cadmorph.models import DrawingEntity, DrawingGraph, Point

AnchorPair = tuple[Point, Point]  # (old-frame point, new-frame point)


def _point(entity: DrawingEntity) -> Point:
    return entity.anchor if entity.anchor is not None else entity.position


def _unique_by(entities: list[DrawingEntity], key) -> dict[str, DrawingEntity]:
    counts = Counter(key(e) for e in entities if key(e) is not None)
    return {key(e): e for e in entities if key(e) is not None and counts[key(e)] == 1}


def build_anchor_pairs(old: DrawingGraph, new: DrawingGraph) -> list[AnchorPair]:
    pairs: list[AnchorPair] = []

    # Unique text strings (text + dimension entities)
    old_texts = _unique_by(old.entities, lambda e: e.text_payload)
    new_texts = _unique_by(new.entities, lambda e: e.text_payload)
    for text in sorted(set(old_texts) & set(new_texts)):
        pairs.append((_point(old_texts[text]), _point(new_texts[text])))

    # Unique geometry signatures (linework only; centroid-paired)
    old_lines = [e for e in old.entities if e.kind == "linework"]
    new_lines = [e for e in new.entities if e.kind == "linework"]
    old_sigs = _unique_by(old_lines, lambda e: e.geometry_signature)
    new_sigs = _unique_by(new_lines, lambda e: e.geometry_signature)
    for signature in sorted(set(old_sigs) & set(new_sigs)):
        pairs.append((old_sigs[signature].position, new_sigs[signature].position))

    return pairs
