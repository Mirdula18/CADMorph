"""The ExtractionProvider seam holds: nothing downstream touches fitz or a
concrete provider (T010; the plug point for feature 002)."""

from __future__ import annotations

import ast
from pathlib import Path

import cadmorph

SRC = Path(cadmorph.__file__).parent


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def test_fitz_confined_to_extraction():
    offenders = []
    for path in SRC.rglob("*.py"):
        # extraction/ owns parsing; report/ is presentation-only rendering
        # (Constitution I: display output, no comparison logic consumes
        # pixels — research R10 mandates PyMuPDF for markup annotations).
        # Every analysis stage in between still may not touch fitz.
        if "extraction" in path.parts or "report" in path.parts:
            continue
        if any(name == "fitz" or name.startswith("fitz.") for name in _imports(path)):
            offenders.append(path.name)
    assert not offenders, f"fitz imported outside extraction/: {offenders}"


def test_analysis_stages_never_consume_display_artifacts():
    """Directional seam: match/, deltas/, classify/, graph/ must never import
    the report renderers — sheet.png and markup.pdf are display artifacts,
    not analysis inputs (Constitution I). Guards against a future feature
    quietly turning presentation output into a detection signal."""
    analysis_packages = {"match", "deltas", "classify", "graph"}
    offenders = []
    for path in SRC.rglob("*.py"):
        if not analysis_packages.intersection(path.parts):
            continue
        for name in _imports(path):
            if name == "cadmorph.report" or name.startswith("cadmorph.report."):
                offenders.append(f"{path.parent.name}/{path.name}: {name}")
    assert not offenders, f"analysis stage imports a display renderer: {offenders}"


def test_concrete_provider_not_imported_downstream():
    offenders = []
    for path in SRC.rglob("*.py"):
        if "extraction" in path.parts:
            continue
        if any("pdf_provider" in name for name in _imports(path)):
            offenders.append(path.name)
    assert not offenders, f"concrete provider imported outside extraction/: {offenders}"
