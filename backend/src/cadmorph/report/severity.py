"""Severity, affected-area, and location descriptors for the printable
report (report/document.py).

Pure functions over vector-exact coordinates — deterministic arithmetic,
no inference and no pixel guessing (Constitution II/IV). Severity
thresholds live in cadmorph.config.SEVERITY:
    affected_area_pct >= 15 OR total_changes >= 50 -> "High"
    affected_area_pct >= 5  OR total_changes >= 10 -> "Medium"
    otherwise                                      -> "Low"
"""

from __future__ import annotations

from cadmorph.config import SEVERITY, SeverityConfig
from cadmorph.models import BBox


def bbox_union_area(bboxes: list[BBox]) -> float:
    """Exact area of the union of axis-aligned rectangles.

    Coordinate-compression sweep: overlapping delta bboxes must not double
    count and inflate the affected-area percentage. Degenerate boxes
    (zero/negative extent) contribute nothing. O(n^3) in the number of
    boxes — deltas are tens, not thousands.
    """
    boxes = [b for b in bboxes if b[2] > b[0] and b[3] > b[1]]
    if not boxes:
        return 0.0
    xs = sorted({x for b in boxes for x in (b[0], b[2])})
    ys = sorted({y for b in boxes for y in (b[1], b[3])})
    area = 0.0
    for i in range(len(xs) - 1):
        for j in range(len(ys) - 1):
            cx = (xs[i] + xs[i + 1]) / 2.0
            cy = (ys[j] + ys[j + 1]) / 2.0
            if any(b[0] <= cx <= b[2] and b[1] <= cy <= b[3] for b in boxes):
                area += (xs[i + 1] - xs[i]) * (ys[j + 1] - ys[j])
    return area


def affected_area_pct(
    anchor_bboxes: list[BBox], sheet_width: float, sheet_height: float
) -> float:
    """Union area of the delta anchors as a percentage of the sheet area."""
    sheet = sheet_width * sheet_height
    if sheet <= 0:
        return 0.0
    return 100.0 * bbox_union_area(anchor_bboxes) / sheet


def severity(
    affected_pct: float, total_changes: int, config: SeverityConfig = SEVERITY
) -> str:
    if affected_pct >= config.area_high or total_changes >= config.changes_high:
        return "High"
    if affected_pct >= config.area_medium or total_changes >= config.changes_medium:
        return "Medium"
    return "Low"


_COLUMNS = ("left", "center", "right")
_ROWS = ("upper", "mid", "lower")


def location_bin(bbox: BBox, sheet_width: float, sheet_height: float) -> str:
    """9-bin location descriptor from the bbox center — exact coordinates.

    Coordinate frame: PDF points as extracted by PyMuPDF — origin TOP-left,
    y increasing downward — so a center in the first third of sheet_height
    is "upper". Thirds are half-open ([0, 1/3) etc.); centers outside the
    sheet clamp to the outermost bin (a removed entity's registered anchor
    can land slightly off-sheet after transformation).
    """
    cx = (bbox[0] + bbox[2]) / 2.0
    cy = (bbox[1] + bbox[3]) / 2.0
    col = min(2, max(0, int(cx / sheet_width * 3))) if sheet_width > 0 else 1
    row = min(2, max(0, int(cy / sheet_height * 3))) if sheet_height > 0 else 1
    return f"{_ROWS[row]} {_COLUMNS[col]}"
