"""Grounding gate (T027, Constitution II / FR-009): summary values are
verbatim delta values; the summarizer sees nothing but the delta contract."""

from __future__ import annotations

import ast
import re
import shutil
import subprocess
from pathlib import Path

import pytest

import cadmorph.summarize
from cadmorph.deltas.models import EntityDelta, EntityState, canonical_json
from cadmorph.summarize.render import render_summaries

QUOTED = re.compile(r'"([^"]+)"')
BACKEND_DIR = Path(cadmorph.summarize.__file__).resolve().parents[3]  # .../backend


def _state(**over) -> EntityState:
    base = dict(
        entity_id="e-1",
        kind="dimension",
        bbox=(10.0, 20.0, 60.0, 30.0),
        geometry_signature="sig1",
        text_payload="D11 = 450 cm",
        label="D11",
        dimension_value="450 cm",
    )
    base.update(over)
    return EntityState(**base)


def _deltas() -> list[EntityDelta]:
    return [
        EntityDelta(
            delta_id="d-dim",
            change_type="modified",
            modification_kinds=["dimension_value", "text"],
            before=_state(),
            after=_state(entity_id="e-2", text_payload="D11 = 40 cm", dimension_value="40 cm"),
            anchor_bbox=(10.0, 20.0, 60.0, 30.0),
        ),
        EntityDelta(
            delta_id="d-text",
            change_type="modified",
            modification_kinds=["text"],
            before=_state(
                kind="text", label=None, dimension_value=None,
                text_payload="NOTE: ALL WALLS 200MM U.N.O.",
            ),
            after=_state(
                kind="text", entity_id="e-3", label=None, dimension_value=None,
                text_payload="NOTE: ALL WALLS 250MM U.N.O.",
            ),
            anchor_bbox=(10.0, 20.0, 60.0, 30.0),
        ),
        EntityDelta(
            delta_id="d-add",
            change_type="added",
            before=None,
            after=_state(kind="linework", label=None, dimension_value=None, text_payload=None),
            anchor_bbox=(10.0, 20.0, 60.0, 30.0),
        ),
        EntityDelta(
            delta_id="d-rem",
            change_type="removed",
            after=None,
            before=_state(kind="linework", label=None, dimension_value=None, text_payload=None),
            anchor_bbox=(10.0, 20.0, 60.0, 30.0),
        ),
        EntityDelta(
            delta_id="d-move",
            change_type="modified",
            modification_kinds=["moved"],
            before=_state(kind="linework", label=None, dimension_value=None, text_payload=None),
            after=_state(
                kind="linework", entity_id="e-4", label=None, dimension_value=None,
                text_payload=None, bbox=(40.0, 20.0, 90.0, 30.0),
            ),
            anchor_bbox=(40.0, 20.0, 90.0, 30.0),
        ),
    ]


def test_every_quoted_value_appears_verbatim_in_its_delta():
    deltas = _deltas()
    lines = render_summaries(deltas)
    assert [line.delta_id for line in lines] == [d.delta_id for d in deltas]  # 1:1
    for line, delta in zip(lines, deltas, strict=True):
        payload = canonical_json(delta)
        for value in QUOTED.findall(line.text):
            assert value in payload, (
                f"summary quotes {value!r} not present in delta {delta.delta_id}"
            )
        assert line.values_grounded is True


def test_unavailable_value_renders_explicitly_and_flags_line():
    delta = EntityDelta(
        delta_id="d-null",
        change_type="modified",
        modification_kinds=["dimension_value"],
        before=_state(dimension_value=None),
        after=_state(entity_id="e-9", dimension_value=None),
        anchor_bbox=(10.0, 20.0, 60.0, 30.0),
    )
    line = render_summaries([delta])[0]
    assert "value unavailable" in line.text
    assert line.values_grounded is False


def test_summarize_package_imports_only_the_delta_contract():
    allowed = ("cadmorph.deltas", "jinja2", "pathlib", "__future__", "typing")
    package_dir = Path(cadmorph.summarize.__file__).parent
    offenders = []
    for path in package_dir.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            for name in names:
                if not any(name == p or name.startswith(p + ".") for p in allowed):
                    offenders.append(f"{path.name}: {name}")
    assert not offenders, f"summarizer imports outside the delta contract: {offenders}"


def test_import_linter_contract_green():
    binary = shutil.which("lint-imports")
    if binary is None:
        pytest.skip("import-linter not installed; AST check above still guards")
    result = subprocess.run(
        [binary], cwd=BACKEND_DIR, capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stdout + result.stderr
