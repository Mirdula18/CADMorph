"""ExtractionProvider — the ONE common entity interface.

Everything downstream of extraction consumes only ``DrawingGraph`` /
``DrawingEntity`` (cadmorph.models); no downstream module may import a
concrete provider or its parsing library. This is the seam where feature 002
(raster fallback) plugs in: a raster provider returns the same DrawingGraph
with its own provenance values, and nothing downstream changes.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal, Protocol, runtime_checkable

from cadmorph.models import DrawingGraph


@runtime_checkable
class ExtractionProvider(Protocol):
    format: str

    def extract(
        self,
        path: str | Path,
        revision_id: Literal["old", "new"],
        page_index: int = 0,
    ) -> DrawingGraph: ...


def get_provider(fmt: str) -> ExtractionProvider:
    if fmt == "pdf":
        from cadmorph.extraction.pdf_provider import PdfExtractionProvider

        return PdfExtractionProvider()
    raise ValueError(f"no extraction provider for format {fmt!r} (feature 001 is PDF-only)")
