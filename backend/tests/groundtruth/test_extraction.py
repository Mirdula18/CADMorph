"""Extraction phase gate (T018, Constitution V): the PDF provider's output is
compared against the synthgen answer key before anything downstream trusts it."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from cadmorph.extraction.provider import get_provider


def _extract_counts(pdf: Path):
    graph = get_provider("pdf").extract(pdf, "old")
    counts = Counter(e.kind for e in graph.entities)
    texts = sorted(e.text_payload for e in graph.entities if e.text_payload is not None)
    return graph, counts, texts


def test_inventory_matches_answer_key(gt_pair: Path):
    key = json.loads((gt_pair / "answer-key.json").read_text(encoding="utf-8"))
    expected = key["inventory"]["v1"]

    graph, counts, texts = _extract_counts(gt_pair / "v1.pdf")

    assert counts["linework"] == expected["counts"]["linework"]
    assert counts["text"] == expected["counts"]["text"]
    assert counts["dimension"] == expected["counts"]["dimension"]
    assert texts == expected["texts"]


def test_dimension_values_read_from_text_layer(gt_pair: Path):
    graph = get_provider("pdf").extract(gt_pair / "v1.pdf", "old")
    dimensions = {
        e.text_payload: e.dimension_value for e in graph.entities if e.kind == "dimension"
    }
    assert dimensions["D14 = 10 cm"] == "10 cm"  # exact value, unit preserved (FR-009)
    assert all(v is not None for v in dimensions.values())


def test_geometry_is_vector_exact(gt_pair: Path):
    graph = get_provider("pdf").extract(gt_pair / "v1.pdf", "old")
    linework = [e for e in graph.entities if e.kind == "linework"]
    assert linework, "expected vector path entities"
    assert all(e.geometry for e in linework)  # coordinates present, no inference fields
    assert all(e.semantic_label is None for e in graph.entities)  # inference arrives in US1
