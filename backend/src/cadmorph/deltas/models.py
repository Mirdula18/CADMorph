"""EntityDelta contract models — the detection ↔ summarization boundary.

Frozen externally as specs/001-pdf-change-detection/contracts/entity-delta.schema.json.
``canonical_json`` is the single serialization path for anything that must be
byte-identical across repeat runs (Constitution IV, FR-013).
"""

from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import BaseModel, model_validator

from cadmorph.models import BBox, DrawingRevision, EntityKind, EntityMatch, LabeledValue

ChangeType = Literal["added", "removed", "modified"]
ModificationKind = Literal["moved", "geometry", "text", "dimension_value", "style"]


class EntityState(BaseModel):
    entity_id: str
    kind: EntityKind
    bbox: BBox
    position: tuple[float, float] | None = None
    geometry_signature: str
    layer: str | None = None
    style: dict[str, Any] | None = None
    text_payload: str | None = None
    label: str | None = None
    dimension_value: str | None = None
    semantic_label: LabeledValue | None = None


class EntityDelta(BaseModel):
    delta_id: str
    change_type: ChangeType
    modification_kinds: list[ModificationKind] = []
    before: EntityState | None
    after: EntityState | None
    match: EntityMatch | None = None
    anchor_bbox: BBox

    @model_validator(mode="after")
    def _state_invariants(self) -> EntityDelta:
        if self.change_type == "added" and not (self.before is None and self.after is not None):
            raise ValueError("added delta requires before=None and after set (FR-007)")
        if self.change_type == "removed" and not (self.before is not None and self.after is None):
            raise ValueError("removed delta requires before set and after=None (FR-007)")
        if self.change_type == "modified":
            if self.before is None or self.after is None:
                raise ValueError("modified delta requires both states (FR-007)")
            if not self.modification_kinds:
                raise ValueError("modified delta requires modification_kinds")
        return self


class SummaryLine(BaseModel):
    delta_id: str
    text: str
    values_grounded: bool = True


class ChangeReport(BaseModel):
    comparison_id: str
    revisions: dict[Literal["old", "new"], DrawingRevision]
    outcome: Literal["changes_found", "no_changes", "declined"]
    reason: str | None = None
    deltas: list[EntityDelta] = []
    summary_lines: list[SummaryLine] = []
    markup_ref: str | None = None
    metrics_ref: str | None = None
    pipeline_version: str


def _canonical(value: Any) -> Any:
    """Round floats and recurse so identical inputs serialize identically."""
    if isinstance(value, float):
        rounded = round(value, 6)
        return 0.0 if rounded == 0 else rounded
    if isinstance(value, dict):
        return {k: _canonical(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_canonical(v) for v in value]
    return value


def canonical_json(model: BaseModel | dict[str, Any] | list[Any]) -> str:
    data = model.model_dump(mode="json") if isinstance(model, BaseModel) else model
    return json.dumps(_canonical(data), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
