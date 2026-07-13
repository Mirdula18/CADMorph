from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
CONTRACTS_DIR = REPO_ROOT / "specs" / "001-pdf-change-detection" / "contracts"


@pytest.fixture()
def contracts_dir() -> Path:
    return CONTRACTS_DIR


@pytest.fixture()
def gt_pair(tmp_path: Path) -> Path:
    """A clean floorplan pair (no mutations, no export perturbation)."""
    from synthgen import make_pair

    out = tmp_path / "pair"
    make_pair("floorplan", [], out)
    return out
