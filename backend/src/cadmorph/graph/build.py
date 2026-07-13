"""Attributed drawing graph construction (research R3).

Adds kNN-proximity and connectivity edges over the entities of an extracted
DrawingGraph. Purely geometric and deterministic: neighbors from a KD-tree
over entity centroids with canonical tie-breaking, connectivity from bbox
adjacency within a sheet-relative tolerance.
"""

from __future__ import annotations

import numpy as np
from scipy.spatial import cKDTree

from cadmorph.models import DrawingGraph, GraphEdge

KNN_K = 4
CONNECT_TOL_REL = 0.001  # bbox adjacency tolerance as fraction of sheet diagonal


def build_graph(extracted: DrawingGraph) -> DrawingGraph:
    entities = extracted.entities  # already canonically sorted by entity_id
    n = len(entities)
    if n < 2:
        return extracted.model_copy(update={"edges": []})

    centroids = np.array([e.position for e in entities])
    tree = cKDTree(centroids)
    k = min(KNN_K + 1, n)  # +1: query returns the point itself
    _, neighbor_idx = tree.query(centroids, k=k)

    edges: set[tuple[str, str, str]] = set()
    for i, row in enumerate(neighbor_idx):
        for j in row[1:]:
            a, b = sorted((entities[i].entity_id, entities[int(j)].entity_id))
            edges.add((a, b, "knn-proximity"))

    tol = extracted.revision.sheet_diagonal * CONNECT_TOL_REL
    boxes = np.array([e.bbox for e in entities])
    for i in range(n):
        x0, y0, x1, y1 = boxes[i]
        touching = np.where(
            (boxes[:, 0] <= x1 + tol)
            & (boxes[:, 2] >= x0 - tol)
            & (boxes[:, 1] <= y1 + tol)
            & (boxes[:, 3] >= y0 - tol)
        )[0]
        for j in touching:
            if int(j) <= i:
                continue
            a, b = sorted((entities[i].entity_id, entities[int(j)].entity_id))
            edges.add((a, b, "connectivity"))

    graph_edges = [GraphEdge(source=a, target=b, kind=kind) for a, b, kind in sorted(edges)]
    return extracted.model_copy(update={"edges": graph_edges})
