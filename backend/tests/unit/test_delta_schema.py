"""EntityDelta Pydantic models must conform to the frozen JSON Schema contract (T007)."""

from __future__ import annotations

import json

import jsonschema
import pytest

from cadmorph.deltas.models import EntityDelta, EntityState, canonical_json
from cadmorph.models import EntityMatch, LabeledValue


def _state(entity_id: str = "e-1", text: str | None = None, dim: str | None = None) -> EntityState:
    return EntityState(
        entity_id=entity_id,
        kind="dimension" if dim else "text" if text else "linework",
        bbox=(10.0, 20.0, 30.0, 40.0),
        position=(20.0, 30.0),
        geometry_signature="sig-abc",
        text_payload=text,
        label=text.split("=")[0].strip() if text and "=" in text else None,
        dimension_value=dim,
        semantic_label=LabeledValue(value="dimension", provenance="inference", confidence=0.93),
    )


def _validator(contracts_dir):
    schema = json.loads((contracts_dir / "entity-delta.schema.json").read_text(encoding="utf-8"))
    return jsonschema.Draft202012Validator(schema)


def test_added_removed_modified_conform(contracts_dir):
    validator = _validator(contracts_dir)
    deltas = [
        EntityDelta(delta_id="d-1", change_type="added", before=None, after=_state(),
                    anchor_bbox=(10, 20, 30, 40)),
        EntityDelta(delta_id="d-2", change_type="removed", before=_state("e-2"), after=None,
                    anchor_bbox=(10, 20, 30, 40)),
        EntityDelta(
            delta_id="d-3",
            change_type="modified",
            modification_kinds=["dimension_value", "text"],
            before=_state("e-3", text="D14 = 10 cm", dim="10 cm"),
            after=_state("e-3", text="D14 = 40 cm", dim="40 cm"),
            match=EntityMatch(old_entity_id="e-3", new_entity_id="e-3b", tier="attribute"),
            anchor_bbox=(10, 20, 30, 40),
        ),
    ]
    for delta in deltas:
        payload = json.loads(canonical_json(delta))
        validator.validate(payload)


def test_invariants_enforced():
    with pytest.raises(ValueError):
        EntityDelta(delta_id="x", change_type="added", before=_state(), after=_state(),
                    anchor_bbox=(0, 0, 1, 1))
    with pytest.raises(ValueError):
        EntityDelta(delta_id="x", change_type="modified", before=_state(), after=_state(),
                    modification_kinds=[], anchor_bbox=(0, 0, 1, 1))
    with pytest.raises(ValueError):
        LabeledValue(value="door", provenance="inference")  # confidence required


def test_canonical_json_is_stable():
    delta = EntityDelta(delta_id="d-1", change_type="added", before=None, after=_state(),
                        anchor_bbox=(10.0000004, 20, 30, 40))
    assert canonical_json(delta) == canonical_json(delta.model_copy(deep=True))
    assert "10.0," in canonical_json(delta)  # float canonicalization applied
