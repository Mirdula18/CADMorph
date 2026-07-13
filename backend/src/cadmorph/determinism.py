"""Determinism rails (research R11, Constitution IV).

Every stochastic component must draw from these seeds; model weights are
hash-checked at load so a silent weight swap cannot change outputs unnoticed.
"""

from __future__ import annotations

import hashlib
import random
from pathlib import Path

DEFAULT_SEED = 1337


def seed_all(seed: int = DEFAULT_SEED) -> None:
    random.seed(seed)
    try:
        import numpy

        numpy.random.seed(seed)
    except ImportError:  # pragma: no cover
        pass
    try:  # torch arrives with the [ml] extra in User Story 1
        import torch

        torch.manual_seed(seed)
        torch.use_deterministic_algorithms(True)
        # Bit-identity across runs also requires a fixed intra-op thread
        # count: deterministic algorithms are only guaranteed per thread
        # configuration (OpenMP reduction order). Pipeline graphs are small;
        # revisit at the T044 perf gate if this ever dominates.
        torch.set_num_threads(1)
    except ImportError:
        pass


def file_sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def check_weights(path: str | Path, expected_sha256: str) -> None:
    actual = file_sha256(path)
    if actual != expected_sha256:
        raise RuntimeError(
            f"model weights at {path} have hash {actual}, expected {expected_sha256}; "
            "refusing to run with unpinned weights (Constitution IV)"
        )
