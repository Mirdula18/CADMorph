"""Deterministic feature encoding of a DrawingGraph for the learned stages.

Features are pure functions of vector-exact entity fields (kind, bbox,
segment structure, style, text shape) — no pixels, no inference inputs.
The classifier additionally sees normalized sheet position; the Siamese
matcher does NOT (a moved entity must embed like its counterpart, R7).
"""

from __future__ import annotations

import torch

from cadmorph.models import DrawingEntity, DrawingGraph

KINDS = ("linework", "text", "dimension", "symbol", "hatch")

# GAT symbol-spotting label set (T020) — matches synthgen `semantic` labels.
CLASSES = ("dimension", "door", "furniture", "linework", "note", "room-label", "title", "wall")

BASE_DIM = 17
FEATURE_DIM = BASE_DIM + 2  # + normalized sheet position (classifier only)


def entity_features(
    entity: DrawingEntity, graph: DrawingGraph, include_position: bool
) -> list[float]:
    diag = graph.revision.sheet_diagonal
    x0, y0, x1, y1 = entity.bbox
    w, h = x1 - x0, y1 - y0
    n_seg = len(entity.geometry)
    seg_counts = {"line": 0, "rect": 0, "curve": 0, "quad": 0}
    for seg in entity.geometry:
        seg_counts[seg.kind] += 1
    denom = max(n_seg, 1)
    text = entity.text_payload or ""
    style_width = entity.style.width if entity.style and entity.style.width else 0.0

    feats = [
        *[1.0 if entity.kind == k else 0.0 for k in KINDS],
        w / diag,
        h / diag,
        min(w / (h + 1e-6), 10.0) / 10.0,
        min(n_seg, 10) / 10.0,
        seg_counts["line"] / denom,
        seg_counts["rect"] / denom,
        (seg_counts["curve"] + seg_counts["quad"]) / denom,
        min(style_width, 20.0) / 20.0,
        1.0 if text else 0.0,
        min(len(text), 32) / 32.0,
        (sum(c.isdigit() for c in text) / len(text)) if text else 0.0,
        (sum(c.isupper() for c in text) / len(text)) if text else 0.0,
    ]
    if include_position:
        feats += [
            ((x0 + x1) / 2.0) / graph.revision.sheet_width,
            ((y0 + y1) / 2.0) / graph.revision.sheet_height,
        ]
    return feats


def graph_tensors(
    graph: DrawingGraph, include_position: bool
) -> tuple[torch.Tensor, torch.Tensor]:
    """(node features [n, F], edge_index [2, E] undirected) in canonical entity order."""
    x = torch.tensor(
        [entity_features(e, graph, include_position) for e in graph.entities],
        dtype=torch.float32,
    )
    index = {e.entity_id: i for i, e in enumerate(graph.entities)}
    pairs: list[tuple[int, int]] = []
    for edge in graph.edges:
        a, b = index[edge.source], index[edge.target]
        pairs.append((a, b))
        pairs.append((b, a))
    if pairs:
        edge_index = torch.tensor(sorted(set(pairs)), dtype=torch.long).t().contiguous()
    else:
        edge_index = torch.zeros((2, 0), dtype=torch.long)
    return x, edge_index
