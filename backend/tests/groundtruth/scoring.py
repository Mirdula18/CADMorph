"""The documented answer-key scoring rule (tools/synthgen/README.md).

An EntityDelta D matches an ExpectedChange E iff ALL of:
  1. D.change_type == E.change_type
  2. D.(after or before).kind == E.kind
  3. IoU(D.anchor_bbox, E.anchor_bbox) >= 0.3
  4. verbatim equality on every grounded field of E's states
     (text_payload, label, dimension_value), in BOTH directions:
     a null in the key must be null in the delta — a fabricated value
     where the answer key has none is a mismatch (FR-009 posture).
One-to-one matching; entity_id / geometry_signature / delta_id / match /
semantic_label / style precision are explicitly excluded.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

GROUNDED_FIELDS = ("text_payload", "label", "dimension_value")
IOU_THRESHOLD = 0.3


def iou(a: list[float], b: list[float]) -> float:
    iw = min(a[2], b[2]) - max(a[0], b[0])
    ih = min(a[3], b[3]) - max(a[1], b[1])
    if iw <= 0 or ih <= 0:
        return 0.0
    inter = iw * ih
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def delta_matches_expected(delta: dict[str, Any], expected: dict[str, Any]) -> bool:
    if delta["change_type"] != expected["change_type"]:
        return False
    state = delta["after"] or delta["before"]
    if state["kind"] != expected["kind"]:
        return False
    if iou(list(delta["anchor_bbox"]), list(expected["anchor_bbox"])) < IOU_THRESHOLD:
        return False
    for side in ("before", "after"):
        exp_state = expected.get(side)
        if exp_state is None:
            continue
        got_state = delta.get(side)
        if got_state is None:
            return False
        for field in GROUNDED_FIELDS:
            # Symmetric equality: a wrong value, a missing value, AND a
            # fabricated value (delta non-null where the key is null) all
            # disqualify the match.
            if got_state.get(field) != exp_state.get(field):
                return False
    return True


@dataclass
class Score:
    matched: int
    n_deltas: int
    n_expected: int
    unmatched_expected: list[dict[str, Any]]
    extra_deltas: list[dict[str, Any]]

    @property
    def precision(self) -> float:
        return self.matched / self.n_deltas if self.n_deltas else 1.0

    @property
    def recall(self) -> float:
        return self.matched / self.n_expected if self.n_expected else 1.0


def score(deltas: list[dict[str, Any]], expected_changes: list[dict[str, Any]]) -> Score:
    """One-to-one: each expected change consumes at most one delta."""
    used: set[int] = set()
    unmatched_expected = []
    for expected in expected_changes:
        hit = next(
            (i for i, d in enumerate(deltas) if i not in used and delta_matches_expected(d, expected)),
            None,
        )
        if hit is None:
            unmatched_expected.append(expected)
        else:
            used.add(hit)
    extra = [d for i, d in enumerate(deltas) if i not in used]
    return Score(
        matched=len(used),
        n_deltas=len(deltas),
        n_expected=len(expected_changes),
        unmatched_expected=unmatched_expected,
        extra_deltas=extra,
    )
