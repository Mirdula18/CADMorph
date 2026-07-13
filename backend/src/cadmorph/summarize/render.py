"""Grounded summary rendering (T026, research R8, FR-009).

The summarizer's ONLY input is the typed delta list (Constitution II); this
module may import nothing beyond the delta contract and Jinja2 — enforced by
import-linter and tests/unit/test_summarizer_grounding.py. Every value in a
sentence renders through q(), which either quotes the delta field verbatim
or emits "value unavailable" and clears values_grounded (FR-009). Templates
are resolved by (entity kind × change type) with a default fallback.
"""

from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from cadmorph.deltas.models import EntityDelta, SummaryLine

_TEMPLATES = Path(__file__).parent / "templates"
_env = Environment(
    loader=FileSystemLoader(str(_TEMPLATES)),
    undefined=StrictUndefined,
    trim_blocks=True,
    lstrip_blocks=True,
    autoescape=False,
)


def _template_for(kind: str, change_type: str):
    for name in (f"{kind}_{change_type}.j2", f"default_{change_type}.j2"):
        if (_TEMPLATES / name).exists():
            return _env.get_template(name)
    raise FileNotFoundError(f"no summary template for ({kind}, {change_type})")


def render_summary(delta: EntityDelta) -> SummaryLine:
    state = delta.after if delta.after is not None else delta.before
    assert state is not None  # delta invariants guarantee one side
    flags = {"grounded": True}

    def q(value: object) -> str:
        """Quote a delta field verbatim, or flag the line as ungrounded."""
        if value is None or value == "":
            flags["grounded"] = False
            return "value unavailable"
        return f'"{value}"'

    semantic = state.semantic_label.value if state.semantic_label is not None else None
    text = _template_for(state.kind, delta.change_type).render(
        before=delta.before,
        after=delta.after,
        kinds=delta.modification_kinds,
        kind=state.kind,
        semantic=semantic,
        q=q,
    )
    return SummaryLine(
        delta_id=delta.delta_id,
        text=" ".join(text.split()),  # collapse template whitespace
        values_grounded=flags["grounded"],
    )


def render_summaries(deltas: list[EntityDelta]) -> list[SummaryLine]:
    """One SummaryLine per EntityDelta, 1:1, same order (Principle III)."""
    return [render_summary(d) for d in deltas]
