"""Classification stage (T021): semantic type labels for every entity.

Runs the pinned GAT in eval mode over the drawing graph and attaches
``semantic_label`` as a provenance-flagged LabeledValue — the ONLY
inference-derived field on an entity (Constitution IV). Geometry, text, and
dimension values are never touched here.
"""

from __future__ import annotations

import torch

from cadmorph.classify.features import CLASSES, graph_tensors
from cadmorph.classify.model import GATClassifier
from cadmorph.models import DrawingGraph, LabeledValue


def classify_graph(graph: DrawingGraph, model: GATClassifier) -> DrawingGraph:
    """Return a copy of ``graph`` with semantic_label set on every entity."""
    if not graph.entities:
        return graph
    x, edge_index = graph_tensors(graph, include_position=True)
    with torch.no_grad():
        probabilities = torch.softmax(model(x, edge_index), dim=1)
        confidences, predictions = probabilities.max(dim=1)
    entities = []
    for entity, pred, conf in zip(graph.entities, predictions, confidences, strict=True):
        entities.append(
            entity.model_copy(
                update={
                    "semantic_label": LabeledValue(
                        value=CLASSES[int(pred)],
                        provenance="inference",
                        confidence=round(float(conf), 6),
                    )
                }
            )
        )
    return graph.model_copy(update={"entities": entities})


def low_confidence_count(graph: DrawingGraph, threshold: float = 0.5) -> int:
    """Observability signal (R9): inference-derived fields below confidence 0.5."""
    return sum(
        1
        for e in graph.entities
        if e.semantic_label is not None and (e.semantic_label.confidence or 0.0) < threshold
    )
