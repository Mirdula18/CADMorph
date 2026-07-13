"""Classification gate (T021, Constitution V): pinned GAT semantic labels
scored against synthgen ground truth on a held-out seed; labels are
provenance-flagged inference and never touch vector-exact fields."""

from __future__ import annotations

import pytest

from cadmorph.classify.data import align_records, load_records
from cadmorph.classify.model import load_classifier
from cadmorph.classify.stage import classify_graph
from cadmorph.extraction.provider import get_provider
from cadmorph.graph.build import build_graph

HELDOUT_SEED = 202  # training used seeds 1-20, its own eval used 101


@pytest.fixture(scope="module")
def classified_pair(tmp_path_factory):
    from synthgen import make_pair

    pair_dir = tmp_path_factory.mktemp("classify") / "pair"
    make_pair("floorplan", ["dim-change", "add", "remove", "move"], pair_dir, seed=HELDOUT_SEED)
    plain = build_graph(get_provider("pdf").extract(pair_dir / "v1.pdf", "old"))
    classified = classify_graph(plain, load_classifier())
    assignment = align_records(plain, load_records(pair_dir / "entities-v1.json"))
    return plain, classified, assignment


def test_labels_match_synthgen_ground_truth(classified_pair):
    _, graph, assignment = classified_pair
    labeled = [e for e in graph.entities if e.entity_id in assignment]
    assert labeled, "alignment produced no ground-truth labels"
    correct = sum(
        1
        for e in labeled
        if e.semantic_label is not None
        and e.semantic_label.value == assignment[e.entity_id]["semantic"]
    )
    accuracy = correct / len(labeled)
    assert accuracy >= 0.9, f"held-out label accuracy {accuracy:.3f} below the 0.9 gate"


def test_labels_are_provenance_flagged_inference(classified_pair):
    _, graph, _ = classified_pair
    for entity in graph.entities:
        assert entity.semantic_label is not None
        assert entity.semantic_label.provenance == "inference"
        assert entity.semantic_label.confidence is not None
        assert 0.0 <= entity.semantic_label.confidence <= 1.0


def test_classification_never_alters_vector_exact_fields(classified_pair):
    plain, classified, _ = classified_pair
    for before, after in zip(plain.entities, classified.entities, strict=True):
        assert before.entity_id == after.entity_id
        assert before.geometry == after.geometry
        assert before.bbox == after.bbox
        assert before.text_payload == after.text_payload
        assert before.dimension_value == after.dimension_value
