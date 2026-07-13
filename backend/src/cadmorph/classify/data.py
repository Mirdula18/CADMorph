"""Align extracted entities with synthgen ground-truth records (T020/T022).

synthgen writes entities-vN.json per revision: {uid, kind, semantic, bbox,
text}. Extraction produces one DrawingEntity per synthetic primitive, so a
deterministic one-to-one nearest-center assignment within the same structural
kind recovers labels (semantic → classifier targets) and cross-revision
correspondence (shared uid → matcher positives).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from cadmorph.models import DrawingGraph

ALIGN_TOL_REL = 0.02  # max center distance for a label assignment, rel. to diagonal


def load_records(path: str | Path) -> list[dict[str, Any]]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _center(bbox: list[float] | tuple[float, ...]) -> tuple[float, float]:
    return ((bbox[0] + bbox[2]) / 2.0, (bbox[1] + bbox[3]) / 2.0)


def align_records(graph: DrawingGraph, records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """entity_id -> ground-truth record, one-to-one, globally nearest-first.

    Only same-kind pairs within ALIGN_TOL_REL of each other are eligible;
    entities/records without a counterpart stay unassigned.
    """
    tol = graph.revision.sheet_diagonal * ALIGN_TOL_REL
    candidates: list[tuple[float, str, int]] = []
    for entity in graph.entities:
        ex, ey = _center(entity.bbox)
        for i, record in enumerate(records):
            if record["kind"] != entity.kind:
                continue
            rx, ry = _center(record["bbox"])
            dist = ((ex - rx) ** 2 + (ey - ry) ** 2) ** 0.5
            if dist <= tol:
                candidates.append((dist, entity.entity_id, i))

    assignment: dict[str, dict[str, Any]] = {}
    used_records: set[int] = set()
    for dist, entity_id, i in sorted(candidates, key=lambda c: (c[0], c[1], c[2])):
        if entity_id in assignment or i in used_records:
            continue
        assignment[entity_id] = records[i]
        used_records.add(i)
    return assignment
