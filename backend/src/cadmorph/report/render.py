"""Display renderer (T033): sheet.png for the browser viewer.

Presentation ONLY (Constitution I): the raster is never an analysis input.
The X-Sheet-Transform mapping lets the SVG overlay convert delta coordinates
(PDF points, top-left origin) to pixels: px = x * scale + dx, py = y * scale + dy.
"""

from __future__ import annotations

from pathlib import Path

import fitz

DISPLAY_ZOOM = 2.0  # 144 dpi — crisp on ordinary screens without huge PNGs


def render_sheet(
    pdf_path: str | Path,
    out_png: str | Path,
    page_index: int = 0,
    zoom: float = DISPLAY_ZOOM,
) -> dict[str, float]:
    """Render one page to PNG; returns the coordinate transform."""
    doc = fitz.open(pdf_path)
    try:
        page = doc[page_index]
        pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom))
        pix.save(out_png)
        return {
            "scale": zoom,
            "dx": 0.0,
            "dy": 0.0,
            "width": float(pix.width),
            "height": float(pix.height),
        }
    finally:
        doc.close()


def transform_header(transform: dict[str, float]) -> str:
    """Serialize for the X-Sheet-Transform response header (contracts/api.md)."""
    return (
        f"scale={transform['scale']};dx={transform['dx']};dy={transform['dy']};"
        f"width={transform['width']};height={transform['height']}"
    )
