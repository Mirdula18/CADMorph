"""Flattened color-coded overlay PNG for the printable report's overlay page.

Separate from markup.py by design: markup.py adds vector ANNOTATIONS to the
downloadable V(n) PDF, while this draws plain colored rectangles on a COPY
of the page and rasterizes it for embedding in the printable document.
Colors are markup.py's COLORS, so the overlay page, its legend, the
downloadable markup, and the web UI all agree (FR-010). Presentation only
(Constitution I).
"""

from __future__ import annotations

from pathlib import Path

import fitz

from cadmorph.deltas.models import ChangeReport
from cadmorph.report.markup import BOX_MARGIN, COLORS
from cadmorph.report.render import DISPLAY_ZOOM


def render_overlay_png(
    source_pdf: str | Path,
    report: ChangeReport,
    out_png: str | Path,
    page_index: int = 0,
    zoom: float = DISPLAY_ZOOM,
) -> Path:
    doc = fitz.open(source_pdf)
    try:
        page = doc[page_index]
        for delta in report.deltas:
            x0, y0, x1, y1 = delta.anchor_bbox
            rect = fitz.Rect(
                x0 - BOX_MARGIN, y0 - BOX_MARGIN, x1 + BOX_MARGIN, y1 + BOX_MARGIN
            )
            page.draw_rect(rect, color=COLORS[delta.change_type], width=1.5)
        pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom))
        pix.save(out_png)
    finally:
        doc.close()
    return Path(out_png)
