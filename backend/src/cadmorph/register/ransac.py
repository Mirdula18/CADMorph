"""Seeded RANSAC similarity transform (T040, research R5).

Similarity transforms (translation + uniform scale + rotation) are estimated
in the complex plane: new = a*old + b with a = scale*e^{i*rotation}. Two
anchor pairs determine a candidate; the consensus set is refined by closed-
form least squares. The RNG is seeded (Constitution IV) — identical inputs
yield the identical transform. Acceptance: inlier ratio >= 0.6 AND RMS
residual <= 0.5% of the sheet diagonal, else alignment fails (FR-004).
"""

from __future__ import annotations

import math
import random

from cadmorph.determinism import DEFAULT_SEED
from cadmorph.models import RegistrationResult, SimilarityTransform
from cadmorph.register.anchors import AnchorPair

INLIER_RATIO_MIN = 0.6
RMS_RESIDUAL_REL_MAX = 0.005
INLIER_TOL_REL = 0.005
ITERATIONS = 200
MIN_ANCHORS = 3
SCALE_SANITY = (0.2, 5.0)  # reject degenerate 2-point hypotheses


def _least_squares(olds: list[complex], news: list[complex]) -> tuple[complex, complex]:
    o_mean = sum(olds) / len(olds)
    n_mean = sum(news) / len(news)
    numerator = sum(
        (o - o_mean).conjugate() * (n - n_mean) for o, n in zip(olds, news, strict=True)
    )
    denominator = sum(abs(o - o_mean) ** 2 for o in olds)
    a = numerator / denominator
    return a, n_mean - a * o_mean


def estimate_transform(pairs: list[AnchorPair], sheet_diagonal: float) -> RegistrationResult:
    identity = SimilarityTransform(tx=0.0, ty=0.0, scale=1.0, rotation=0.0)
    failed = RegistrationResult(
        transform=identity, inlier_ratio=0.0, rms_residual_rel=1.0,
        status="failed", anchors_used=len(pairs),
    )
    if len(pairs) < MIN_ANCHORS:
        return failed

    olds = [complex(x, y) for (x, y), _ in pairs]
    news = [complex(x, y) for _, (x, y) in pairs]
    tol = INLIER_TOL_REL * sheet_diagonal
    rng = random.Random(DEFAULT_SEED)

    best_inliers: list[int] = []
    for _ in range(ITERATIONS):
        i, j = rng.sample(range(len(pairs)), 2)
        if olds[i] == olds[j]:
            continue
        a = (news[j] - news[i]) / (olds[j] - olds[i])
        if not (SCALE_SANITY[0] <= abs(a) <= SCALE_SANITY[1]):
            continue
        b = news[i] - a * olds[i]
        inliers = [k for k in range(len(pairs)) if abs(a * olds[k] + b - news[k]) <= tol]
        if len(inliers) > len(best_inliers):  # strict '>' keeps the seeded order decisive
            best_inliers = inliers

    if len(best_inliers) < 2:
        return failed

    a, b = _least_squares([olds[k] for k in best_inliers], [news[k] for k in best_inliers])
    residuals = [abs(a * o + b - n) for o, n in zip(olds, news, strict=True)]
    inliers = [r for r in residuals if r <= tol]
    inlier_ratio = len(inliers) / len(pairs)
    rms_rel = (
        math.sqrt(sum(r * r for r in inliers) / len(inliers)) / sheet_diagonal
        if inliers else 1.0
    )
    status = (
        "aligned"
        if inlier_ratio >= INLIER_RATIO_MIN and rms_rel <= RMS_RESIDUAL_REL_MAX
        else "failed"
    )
    return RegistrationResult(
        transform=SimilarityTransform(
            tx=b.real, ty=b.imag, scale=abs(a), rotation=math.atan2(a.imag, a.real)
        ),
        inlier_ratio=round(inlier_ratio, 6),
        rms_residual_rel=round(rms_rel, 9),
        status=status,
        anchors_used=len(pairs),
    )
