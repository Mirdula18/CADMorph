"""Affected-area, severity, and location bins (report extension): exact
assertions, thresholds checked on BOTH sides and each OR clause in
isolation, synthgen-grounded fixtures."""

from __future__ import annotations

import json

import pytest

from cadmorph.config import SeverityConfig
from cadmorph.report.severity import (
    affected_area_pct,
    bbox_union_area,
    location_bin,
    severity,
)


def test_union_area_disjoint_sums_exactly():
    assert bbox_union_area([(0, 0, 10, 10), (20, 20, 30, 30)]) == 200.0


def test_union_area_overlap_not_double_counted():
    # two 10x10 boxes overlapping in a 5x10 strip: 100 + 100 - 50
    assert bbox_union_area([(0, 0, 10, 10), (5, 0, 15, 10)]) == 150.0


def test_union_area_nested_is_outer_only():
    assert bbox_union_area([(0, 0, 10, 10), (2, 2, 4, 4)]) == 100.0


def test_union_area_degenerate_boxes_ignored():
    assert bbox_union_area([(5, 5, 5, 9), (7, 7, 3, 9)]) == 0.0
    assert bbox_union_area([]) == 0.0


def test_affected_area_pct_matches_answer_key_exactly(tmp_path):
    """Synthgen-grounded: the 'add' mutation contributes exactly one known
    50x50 rect; the percentage must equal the hand computation, not approx."""
    from synthgen import make_pair
    from synthgen.sheets import PAGE_H, PAGE_W

    make_pair("floorplan", ["add"], tmp_path / "pair", seed=7)
    key = json.loads((tmp_path / "pair" / "answer-key.json").read_text(encoding="utf-8"))
    (change,) = key["expected_changes"]
    x0, y0, x1, y1 = change["anchor_bbox"]
    expected = 100.0 * (x1 - x0) * (y1 - y0) / (PAGE_W * PAGE_H)
    assert affected_area_pct([(x0, y0, x1, y1)], PAGE_W, PAGE_H) == expected


@pytest.mark.parametrize(
    ("pct", "total", "expected"),
    [
        (15.0, 0, "High"),       # area threshold inclusive
        (14.999, 49, "Medium"),  # just under BOTH High conditions
        (0.0, 50, "High"),       # count threshold inclusive
        (5.0, 0, "Medium"),      # medium area inclusive
        (0.0, 10, "Medium"),     # medium count inclusive
        (4.999, 9, "Low"),       # just under both Medium conditions
        (0.0, 0, "Low"),
        # clause isolation: each OR arm alone, the other arm clearly below
        (15.0, 1, "High"),       # High via area clause alone
        (0.1, 50, "High"),       # High via count clause alone
        (5.0, 1, "Medium"),      # Medium via area clause alone
        (0.1, 10, "Medium"),     # Medium via count clause alone
    ],
)
def test_severity_thresholds_both_sides(pct, total, expected):
    assert severity(pct, total) == expected


def test_severity_config_is_tunable():
    strict = SeverityConfig(area_high=1.0, changes_high=2, area_medium=0.5, changes_medium=1)
    assert severity(1.0, 0, strict) == "High"
    assert severity(0.0, 1, strict) == "Medium"
    assert severity(0.4, 0, strict) == "Low"


@pytest.mark.parametrize(
    ("center", "expected"),
    [
        ((50, 50), "upper left"),
        ((421, 50), "upper center"),
        ((800, 50), "upper right"),
        ((50, 297), "mid left"),
        ((421, 297), "mid center"),
        ((800, 550), "lower right"),
    ],
)
def test_location_bins_9_grid(center, expected):
    cx, cy = center
    bbox = (cx - 1, cy - 1, cx + 1, cy + 1)
    assert location_bin(bbox, 842.0, 595.0) == expected


def test_location_bin_synthgen_title_block_is_lower_right():
    """Grounded in the floorplan preset: the title block rect is drawn at
    (620,480)-(780,540) on an 842x595 sheet — visually bottom-right, and the
    y-down frame must report exactly that (not 'upper right' flipped)."""
    assert location_bin((620.0, 480.0, 780.0, 540.0), 842.0, 595.0) == "lower right"


def test_location_bin_clamps_off_sheet_centers():
    assert location_bin((-30.0, -30.0, -10.0, -10.0), 842.0, 595.0) == "upper left"
    assert location_bin((850.0, 600.0, 900.0, 650.0), 842.0, 595.0) == "lower right"
