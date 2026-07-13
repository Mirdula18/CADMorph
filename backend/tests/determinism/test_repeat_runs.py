"""Determinism gate (T019, Constitution IV / FR-013): identical inputs must
produce byte-identical canonical structured output."""

from __future__ import annotations

from pathlib import Path

from cadmorph.deltas.models import canonical_json
from cadmorph.determinism import seed_all
from cadmorph.extraction.provider import get_provider
from cadmorph.graph.build import build_graph


def _run(pdf: Path) -> str:
    seed_all()
    graph = get_provider("pdf").extract(pdf, "old")
    graph = build_graph(graph)
    return canonical_json(graph)


def test_extraction_and_graph_are_byte_identical(gt_pair: Path):
    first = _run(gt_pair / "v1.pdf")
    second = _run(gt_pair / "v1.pdf")
    assert first == second


def test_regenerated_pair_is_byte_identical(tmp_path: Path):
    """synthgen itself must be deterministic: same seed -> same PDFs."""
    from synthgen import make_pair

    make_pair("floorplan", ["dim-change", "add"], tmp_path / "a", seed=13)
    make_pair("floorplan", ["dim-change", "add"], tmp_path / "b", seed=13)
    key_a = (tmp_path / "a" / "answer-key.json").read_text(encoding="utf-8")
    key_b = (tmp_path / "b" / "answer-key.json").read_text(encoding="utf-8")
    assert key_a == key_b
    assert _run(tmp_path / "a" / "v1.pdf") == _run(tmp_path / "b" / "v1.pdf")
