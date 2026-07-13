"""Matching + R7 calibration gate (T025, Constitution V, SC-001/SC-002).

Records the CALIBRATED operating points and re-verifies, against generated
ground truth, the evidence that moved them off the research.md starting
values (similarity 0.85 -> 0.30, displacement 5% -> 20% of diagonal):
  - genuine moves across the sweep are reported as modified[moved];
  - the identical-shape "twin" at ~42% of the diagonal is removed+added;
  - true tier-3 similarities stay above, false ones below, the threshold.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from cadmorph.config import CALIBRATED
from cadmorph.deltas.compute import compute_deltas
from cadmorph.extraction.provider import get_provider
from cadmorph.graph.build import build_graph
from cadmorph.match.cascade import match_entities
from cadmorph.match.model import load_encoder

from scoring import delta_matches_expected, score

MOVE_SWEEP = (10.0, 20.0, 40.0, 60.0, 90.0, 120.0, 150.0)
SHEET_DIAGONAL = (842.0**2 + 595.0**2) ** 0.5  # synthgen A4 landscape
TWIN_DISPLACEMENT_REL = 0.4165  # measured: furniture rect -> (390,130) twin


@pytest.fixture(scope="module")
def encoder():
    return load_encoder()


def _detect(pair_dir: Path, encoder):
    provider = get_provider("pdf")
    old = build_graph(provider.extract(pair_dir / "v1.pdf", "old"))
    new = build_graph(provider.extract(pair_dir / "v2.pdf", "new"))
    outcome = match_entities(old, new, encoder)
    deltas = compute_deltas(old, new, outcome)
    key = json.loads((pair_dir / "answer-key.json").read_text(encoding="utf-8"))
    return [d.model_dump(mode="json") for d in deltas], key["expected_changes"], outcome


@pytest.mark.parametrize("distance", MOVE_SWEEP)
def test_genuine_moves_detected_across_sweep(tmp_path, encoder, distance):
    from synthgen import make_pair

    pair_dir = tmp_path / "pair"
    make_pair("floorplan", ["move"], pair_dir, seed=7, move_distance=distance)
    deltas, expected, _ = _detect(pair_dir, encoder)
    result = score(deltas, expected)
    assert result.recall == 1.0, f"move@{distance}pt missed: {result.unmatched_expected}"
    assert result.precision == 1.0, f"move@{distance}pt false positives: {result.extra_deltas}"
    moved = [d for d in deltas if d["change_type"] == "modified"]
    assert len(moved) == 1 and "moved" in moved[0]["modification_kinds"]


def test_twin_is_removed_plus_added_never_moved(tmp_path, encoder):
    from synthgen import make_pair

    pair_dir = tmp_path / "pair"
    make_pair("floorplan", ["twin"], pair_dir, seed=7)
    deltas, expected, _ = _detect(pair_dir, encoder)
    result = score(deltas, expected)
    assert result.recall == 1.0 and result.precision == 1.0
    assert not [d for d in deltas if d["change_type"] == "modified"], (
        "identical-shape twin at 42% of the diagonal must not merge into a move (R7)"
    )


def test_cross_shape_remove_add_not_paired(tmp_path, encoder):
    from synthgen import make_pair

    pair_dir = tmp_path / "pair"
    make_pair("floorplan", ["remove", "add"], pair_dir, seed=7)
    deltas, expected, _ = _detect(pair_dir, encoder)
    result = score(deltas, expected)
    assert result.recall == 1.0 and result.precision == 1.0
    assert not [d for d in deltas if d["change_type"] == "modified"]


def test_hungarian_shadowing_on_pair01(tmp_path, encoder):
    """The 0.567-similarity false pair (removed swing <-> moved rect) is
    shadowed by both entities' true assignments and never selected."""
    from synthgen import make_pair

    pair_dir = tmp_path / "pair"
    make_pair("floorplan", ["dim-change", "add", "remove", "move"], pair_dir, seed=7)
    deltas, expected, outcome = _detect(pair_dir, encoder)
    result = score(deltas, expected)
    assert result.recall == 1.0 and result.precision == 1.0
    learned = [m for m in outcome.matches if m.tier == "learned"]
    assert len(learned) == 1  # only the genuine move reaches tier 3 and pairs


def test_calibrated_operating_points_recorded():
    """The locked values and the geometric margins they rest on (T025)."""
    assert CALIBRATED.similarity == 0.30
    assert CALIBRATED.displacement_rel == 0.20
    # displacement: sweep max < threshold < twin, with margin on both sides
    assert max(MOVE_SWEEP) / SHEET_DIAGONAL < CALIBRATED.displacement_rel - 0.05
    assert TWIN_DISPLACEMENT_REL > CALIBRATED.displacement_rel + 0.05


@pytest.mark.parametrize(
    ("case", "mutation"),
    [("shrink", "dim-change"), ("growth", "dim-grow")],
)
def test_pure_value_change_is_never_moved(tmp_path, encoder, case, mutation):
    """Regression: a dimension value edit changes the rendered string length,
    shifting the bbox CENTER by half the width delta ('450 cm' -> '40 cm':
    2.5pt; '10 cm' -> '10000 cm': ~6.8pt — both over the 1.03pt moved-ε).
    Displacement must use the content-invariant text insertion origin, so
    these report modified[text, dimension_value] with no 'moved'."""
    from synthgen import make_pair

    pair_dir = tmp_path / case
    make_pair("floorplan", [mutation], pair_dir, seed=7)
    deltas, expected, _ = _detect(pair_dir, encoder)
    result = score(deltas, expected)
    assert result.recall == 1.0 and result.precision == 1.0
    (delta,) = [d for d in deltas if d["change_type"] == "modified"]
    assert set(delta["modification_kinds"]) == {"text", "dimension_value"}, case
    assert delta["match"]["tier"] == "attribute"  # label re-key, not learned


def test_combined_move_and_value_change_reports_moved(tmp_path, encoder):
    """A genuine 3pt move with a simultaneous value change must report
    'moved' at roughly the true distance (the case that falsifies bbox-
    anchor heuristics: the width shrink half-cancels the move at the
    center, |Δcenter| ≈ 0.5pt < ε)."""
    from synthgen import make_pair

    pair_dir = tmp_path / "pair"
    make_pair("floorplan", ["dim-change-move"], pair_dir, seed=7)
    deltas, expected, _ = _detect(pair_dir, encoder)
    result = score(deltas, expected)
    assert result.recall == 1.0 and result.precision == 1.0
    (delta,) = [d for d in deltas if d["change_type"] == "modified"]
    assert "moved" in delta["modification_kinds"]
    assert {"text", "dimension_value"} <= set(delta["modification_kinds"])
    # true distance: the leading edge (insertion point) shifted exactly 3pt
    shift = delta["after"]["bbox"][0] - delta["before"]["bbox"][0]
    assert abs(shift - 3.0) < 0.2, f"leading-edge shift {shift:.3f}pt, expected ~3pt"


def test_scoring_rejects_fabricated_grounded_values():
    """Regression: a delta carrying a fabricated dimension_value must NOT
    match an expected move whose states have none (symmetric rule)."""
    expected = {
        "change_type": "modified",
        "kind": "linework",
        "anchor_bbox": [100.0, 100.0, 160.0, 140.0],
        "modification_kinds": ["moved"],
        "before": {
            "kind": "linework", "bbox": [90.0, 100.0, 150.0, 140.0],
            "text_payload": None, "label": None, "dimension_value": None,
        },
        "after": {
            "kind": "linework", "bbox": [100.0, 100.0, 160.0, 140.0],
            "text_payload": None, "label": None, "dimension_value": None,
        },
    }
    delta = {
        "change_type": "modified",
        "anchor_bbox": [100.0, 100.0, 160.0, 140.0],
        "before": {
            "kind": "linework", "text_payload": None, "label": None,
            "dimension_value": None,
        },
        "after": {
            "kind": "linework", "text_payload": None, "label": None,
            "dimension_value": "999 cm",  # fabricated
        },
    }
    assert not delta_matches_expected(delta, expected)
    # sanity: identical delta without the fabricated value does match
    delta["after"]["dimension_value"] = None
    assert delta_matches_expected(delta, expected)
