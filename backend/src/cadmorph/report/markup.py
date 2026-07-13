"""Marked-up vector PDF (T032, FR-010/011/012).

The original V(n) PDF gains one rectangle annotation per delta — color-coded
by change type, carrying its delta_id in the annotation content (the 1:1
join key for SC-004) — plus a small visible delta_id label. Vector fidelity
is preserved: the source content stream is never redrawn. Presentation only
(Constitution I): nothing here feeds back into detection.
"""

from __future__ import annotations

from pathlib import Path

import fitz

from cadmorph.deltas.models import ChangeReport

# One color per change type (FR-010). Keep in sync with the frontend overlay.
COLORS: dict[str, tuple[float, float, float]] = {
    "added": (0.04, 0.60, 0.10),
    "removed": (0.85, 0.10, 0.10),
    "modified": (0.95, 0.55, 0.00),
}
LABEL_FONTSIZE = 5.0
BOX_MARGIN = 2.0  # pt of breathing room around the anchor bbox


def write_markup(
    source_pdf: str | Path,
    report: ChangeReport,
    out_path: str | Path,
    page_index: int = 0,
) -> Path:
    doc = fitz.open(source_pdf)
    try:
        if report.outcome == "no_changes":
            _banner_page(doc, report)
        else:
            page = doc[page_index]
            for delta in report.deltas:
                x0, y0, x1, y1 = delta.anchor_bbox
                rect = fitz.Rect(
                    x0 - BOX_MARGIN, y0 - BOX_MARGIN, x1 + BOX_MARGIN, y1 + BOX_MARGIN
                )
                color = COLORS[delta.change_type]
                annot = page.add_rect_annot(rect)
                annot.set_colors(stroke=color)
                annot.set_border(width=1.5)
                # content = delta_id: the machine-readable 1:1 join (FR-011)
                annot.set_info(title=delta.change_type, content=delta.delta_id)
                annot.update()
                label_y = rect.y0 - 2 if rect.y0 > 12 else rect.y1 + 7
                page.insert_text(
                    fitz.Point(rect.x0, label_y),
                    delta.delta_id,
                    fontsize=LABEL_FONTSIZE,
                    color=color,
                )
        doc.set_metadata({})
        doc.save(out_path, deflate=True, no_new_id=True)
    finally:
        doc.close()
    return Path(out_path)


def _banner_page(doc: fitz.Document, report: ChangeReport) -> None:
    """FR-012: an explicit banner page, never a silently unmarked sheet."""
    first = doc[0]
    banner = doc.new_page(pno=0, width=first.rect.width, height=first.rect.height)
    old_name = report.revisions["old"].source_filename
    new_name = report.revisions["new"].source_filename
    banner.insert_textbox(
        fitz.Rect(40, 40, banner.rect.width - 40, 200),
        "No changes detected\n\n"
        f"V(n-1): {old_name}\n"
        f"V(n):   {new_name}\n\n"
        f"Pipeline: {report.pipeline_version}",
        fontsize=14,
    )
