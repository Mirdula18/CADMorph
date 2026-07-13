"""Detection thresholds (research R6/R7) — calibrated, not guessed.

research.md supplies starting points (similarity 0.85, displacement 5% of the
sheet diagonal) and mandates that the operating points be validated on
synthgen pairs with known moves before the defaults are trusted
(Constitution V). The values below are the CALIBRATED operating points; the
calibration evidence and assertions live in
backend/tests/groundtruth/test_matching.py (T025). Change them only together
with that test.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ThresholdConfig:
    # Learned-tier acceptance: minimum Siamese cosine similarity for a
    # cross-revision pairing (R6 tier 3). Calibrated on the gap between
    # true-correspondence similarities and best false-pair similarities.
    similarity: float

    # R7 moved-vs-removed: a learned-tier pair further apart than this
    # fraction of the sheet diagonal is split into removed + added.
    # Calibrated on the synthgen move-distance sweep (genuine moves up to
    # ~15% of the diagonal) vs the "twin" fixture (identical shape
    # re-appearing at ~40% of the diagonal, which must NOT merge).
    displacement_rel: float

    # Exact-tier position tolerance (R6 tier 1): ε as fraction of diagonal.
    position_eps_rel: float = 0.001

    # Attribute-tier "same place" tolerance (R6 tier 2): entities whose
    # centers moved less than this are candidates for in-place modification.
    tier2_tol_rel: float = 0.01


# Calibrated operating points (T025). research.md starting points were
# similarity=0.85, displacement_rel=0.05. Measured on the synthgen sweep
# (see test_matching.py): true tier-3 pairs range 0.549..1.0 (the GAT
# encoder is neighborhood-sensitive, so far-moved entities lose similarity);
# one-sided false pairs top out at -0.05. similarity=0.30 splits that gap
# with ~0.25 margin each way. Genuine moves reach 0.146 of the diagonal;
# the identical-shape twin sits at 0.417 — displacement_rel=0.20 separates
# them with margin on both sides.
CALIBRATED = ThresholdConfig(similarity=0.30, displacement_rel=0.20)


@dataclass(frozen=True)
class SeverityConfig:
    """Printable-report severity thresholds (report/severity.py).

    Deterministic classification from measured change volume:
        affected_area_pct >= area_high   OR total >= changes_high   -> High
        affected_area_pct >= area_medium OR total >= changes_medium -> Medium
        otherwise                                                   -> Low
    Tune here, never inline in report code.
    """

    area_high: float = 15.0
    changes_high: int = 50
    area_medium: float = 5.0
    changes_medium: int = 10


SEVERITY = SeverityConfig()
