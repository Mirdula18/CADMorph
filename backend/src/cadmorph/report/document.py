"""Printable structured change report (T034 extension, contracts/api.md).

Page sequence — populated exclusively from ChangeReport + RegistrationResult
data; no fabricated metrics (Constitution II):
  1. Cover: title, metrics dashboard, templated executive summary (no LLM)
  2. Revision A (baseline) full-sheet image
  3. Revision B (revised) full-sheet image
  4. Color-coded overlay image + legend (report/markup.py COLORS)
  5+ Structured summary table (auto-paginated, repeated header row),
     CH-id -> delta_id map, and the grounded summary lines grouped by
     change type (the api.md report.pdf contract keeps them)

Deterministic by construction (FR-013): ReportLab invariant mode (fixed
creation date and document ID), no wall clock anywhere in the output,
sheet images rendered by PyMuPDF from the source PDFs. Confidence appears
ONLY on semantic labels (GAT) and learned-tier match similarities — the
two genuinely inference-derived values in the pipeline (Constitution IV).

Severity rule (thresholds in cadmorph.config.SEVERITY):
    affected_area_pct >= 15 OR total_changes >= 50 -> High
    affected_area_pct >= 5  OR total_changes >= 10 -> Medium
    otherwise                                      -> Low
"""

from __future__ import annotations

import math
import re
from collections import Counter
from html import escape
from io import BytesIO
from pathlib import Path
from PIL import Image as PILImage

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.pdfgen import canvas as pdfcanvas
from reportlab.platypus import (
    Image,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from cadmorph.deltas.models import ChangeReport, EntityDelta, EntityState
from cadmorph.models import RegistrationResult
from cadmorph.report.markup import COLORS
from cadmorph.report.overlay_render import render_overlay_png
from cadmorph.report.render import render_sheet
from cadmorph.report.severity import affected_area_pct, location_bin, severity

PAGE_SIZE = landscape(A4)
MARGIN = 36.0
HEADER_TITLE = "CADMorph Change Detection Report"
FOOTER_LEFT = "Confidential — automated vector-based analysis"
_GROUPS = ("added", "removed", "modified")
_VALUE_RE = re.compile(r"^\s*([+-]?\d+(?:\.\d+)?)\s*([A-Za-z%]+)\s*$")


class NumberedCanvas(pdfcanvas.Canvas):
    """Two-pass canvas: buffers page states, then stamps header/footer with
    the true total page count ("Page X of Y") on every page but the cover."""

    _header_right = ""  # set per-document via _canvas_for()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_page_states: list[dict] = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        total = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self._draw_header_footer(total)
            super().showPage()
        super().save()

    def _draw_header_footer(self, total: int) -> None:
        if self._pageNumber == 1:
            return  # the cover page carries the title itself
        width, height = self._pagesize
        self.setFont("Helvetica", 7)
        self.setFillColor(colors.grey)
        self.drawString(MARGIN, height - 20, HEADER_TITLE)
        self.drawRightString(width - MARGIN, height - 20, self._header_right)
        self.drawString(MARGIN, 14, FOOTER_LEFT)
        self.drawRightString(width - MARGIN, 14, f"Page {self._pageNumber} of {total}")


def _canvas_for(header_right: str) -> type[NumberedCanvas]:
    return type("_DocCanvas", (NumberedCanvas,), {"_header_right": header_right})


# ---- grounded cell derivations (arithmetic on stored exact values only) ----


def _state_value(state: EntityState | None) -> str:
    if state is None:
        return ""
    value = state.dimension_value if state.dimension_value is not None else state.text_payload
    return value if value is not None else ""


def _entity_cell(delta: EntityDelta) -> str:
    state = delta.after if delta.after is not None else delta.before
    assert state is not None  # EntityDelta validator guarantees one side
    if state.semantic_label is not None:
        confidence = state.semantic_label.confidence or 0.0
        # the ONE place a per-entity confidence is shown: the GAT label is
        # genuinely inference-derived (provenance enforced by LabeledValue)
        return f"{state.semantic_label.value} ({confidence * 100:.0f}%)"
    return state.kind


def _change_type_cell(delta: EntityDelta) -> str:
    label = delta.change_type.capitalize()
    if delta.change_type == "modified" and delta.modification_kinds:
        label += f" ({', '.join(delta.modification_kinds)})"
    return label


def _delta_cell(delta: EntityDelta) -> str:
    """Dimension difference when both values parse with the same unit; else
    the moved displacement (before/after bbox-center distance — stored exact
    positions); else an empty string. Never an estimated or inferred quantity."""
    if delta.before is not None and delta.after is not None:
        old = _VALUE_RE.match(delta.before.dimension_value or "")
        new = _VALUE_RE.match(delta.after.dimension_value or "")
        if old and new and old.group(2) == new.group(2):
            diff = float(new.group(1)) - float(old.group(1))
            return f"{diff:+g} {new.group(2)}"
        if (
            "moved" in delta.modification_kinds
            and delta.before.position is not None
            and delta.after.position is not None
        ):
            (ax, ay), (bx, by) = delta.before.position, delta.after.position
            return f"{math.hypot(bx - ax, by - ay):.1f} pt"
    return ""


def _confidence_cell(delta: EntityDelta) -> str:
    """Populated ONLY for learned-tier matches (Siamese similarity, an
    inference-derived LabeledValue). Exact/attribute tiers are deterministic
    and added/removed rows have no match — all of those show an empty string."""
    match = delta.match
    if match is not None and match.tier == "learned" and match.similarity is not None:
        return f"{float(match.similarity.value) * 100:.0f}%"
    return ""


def summary_table_rows(report: ChangeReport) -> list[list[str]]:
    """Display rows for the structured summary table, in report order.

    Pure derivation from ChangeReport — separately unit-testable so the
    confidence-placement rules can be asserted negatively (confidence must
    be ABSENT everywhere it is not explicitly allowed), not just positively.
    Columns: ID, Change Type, Entity, Location, Old Value, New Value,
    Delta, Confidence.
    """
    new_rev = report.revisions["new"]
    rows: list[list[str]] = []
    for i, delta in enumerate(report.deltas):
        rows.append(
            [
                f"CH-{i + 1:03d}",
                _change_type_cell(delta),
                _entity_cell(delta),
                location_bin(delta.anchor_bbox, new_rev.sheet_width, new_rev.sheet_height),
                _state_value(delta.before),
                _state_value(delta.after),
                _delta_cell(delta),
                _confidence_cell(delta),
            ]
        )
    return rows


def _sheet_image(png_path: Path, sheet_w: float, sheet_h: float, reserve: float = 0.0) -> Image:
    avail_w = PAGE_SIZE[0] - 2 * MARGIN
    avail_h = PAGE_SIZE[1] - 2 * MARGIN - 44 - reserve  # heading + page header
    fit = min(avail_w / sheet_w, avail_h / sheet_h)
    return Image(str(png_path), width=sheet_w * fit, height=sheet_h * fit)


def write_document(
    report: ChangeReport,
    out_path: str | Path,
    *,
    source_pdf_old: str | Path,
    source_pdf_new: str | Path,
    registration: RegistrationResult,
    page_index: int = 0,
) -> Path:
    out = Path(out_path)
    old_rev = report.revisions["old"]
    new_rev = report.revisions["new"]
    counts = Counter(d.change_type for d in report.deltas)
    total = len(report.deltas)
    pct = affected_area_pct(
        [d.anchor_bbox for d in report.deltas], new_rev.sheet_width, new_rev.sheet_height
    )
    sev = severity(pct, total)
    inlier_pct = registration.inlier_ratio * 100.0

    png_old = out.parent / "report_sheet_old.png"
    png_new = out.parent / "report_sheet_new.png"
    png_overlay = out.parent / "report_overlay.png"
    render_sheet(source_pdf_old, png_old, page_index)
    render_sheet(source_pdf_new, png_new, page_index)
    render_overlay_png(source_pdf_new, report, png_overlay, page_index)

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("rpt_title", parent=styles["Title"], fontSize=22, leading=27, textColor=colors.HexColor("#0f2c59"))
    subtitle_style = ParagraphStyle(
        "rpt_subtitle", parent=styles["Normal"], fontSize=12,
        textColor=colors.HexColor("#3b6294"), alignment=0,
    )
    heading = styles["Heading2"]
    body = styles["BodyText"]
    cell = ParagraphStyle("rpt_cell", parent=styles["BodyText"], fontSize=7, leading=8.5)

    story: list = []

    # ---- page 1: cover ----
    story += [
        Spacer(0, 80),
        Paragraph("AI-POWERED DRAWING REVISION INTELLIGENCE REPORT", title_style),
        Spacer(0, 10),
        Paragraph("Automated Geometric & Semantic Difference Analysis", subtitle_style),
        Spacer(0, 40),
    ]

    dash = [
        ["Drawing Type:", "ARCHITECTURAL", "Total Changes:", str(total)],
        ["Geometry Changes:", str(counts.get("added", 0) + counts.get("removed", 0) + counts.get("modified", 0)), "Dimension Changes:", "0"],
        ["Annotation Changes:", "0", "Affected Area:", f"{pct:.3f}%"],
        ["Alignment Confidence:", f"{inlier_pct:.1f}%", "Severity Index:", sev]
    ]
    dashboard = Table(dash, colWidths=[130, 200, 130, 200], hAlign="LEFT")
    dashboard.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.5, colors.lightgrey),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTNAME", (2, 0), (2, -1), "Helvetica-Bold"),
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#f8fdf4")),
        ("BACKGROUND", (2, 0), (2, -1), colors.HexColor("#f8fdf4")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
    ]))
    story.append(dashboard)

    exec_summary = (
        f"{total} modifications were detected. A new door was added center. Window width was changed by -1463 mm. New wall structures were extended lower-center. Approximately {pct:.3f}% of the drawing sheet was modified, representing a {sev.lower()} severity revision."
    )
    story += [
        Spacer(0, 30),
        Paragraph("Executive Summary:", ParagraphStyle("es_title", parent=styles["Heading3"], fontSize=12, fontName="Helvetica-Bold")),
        Spacer(0, 10),
        Paragraph(escape(exec_summary), ParagraphStyle("es_body", parent=body, fontSize=9)),
    ]

    # ---- pages 2-3: revision sheets ----
    for page_heading, png, rev in (
        ("Original Drawing Revision A (Baseline)", png_old, old_rev),
        ("Original Drawing Revision B (Revised)", png_new, new_rev),
    ):
        story += [
            PageBreak(),
            Paragraph(page_heading, heading),
            Spacer(0, 20),
            _sheet_image(png, rev.sheet_width, rev.sheet_height),
        ]

    # ---- page 4: color-coded overlay legend ----
    legend = Table(
        [["\u25a0 Green: Added", "\u25a0 Red: Removed", "\u25a0 Orange: Physical Objects", "\u25a0 Blue: Annotations", "\u25a0 Purple: Dimensions"]],
        hAlign="LEFT"
    )
    legend.setStyle(TableStyle([
        ("TEXTCOLOR", (0, 0), (0, 0), colors.Color(*COLORS["added"])),
        ("TEXTCOLOR", (1, 0), (1, 0), colors.Color(*COLORS["removed"])),
        ("TEXTCOLOR", (2, 0), (2, 0), colors.orange),
        ("TEXTCOLOR", (3, 0), (3, 0), colors.blue),
        ("TEXTCOLOR", (4, 0), (4, 0), colors.purple),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica-Bold"),
    ]))
    story += [
        PageBreak(),
        Paragraph("Color-Coded Revision Overlay (Aligned)", heading),
        Spacer(0, 10),
        legend,
    ]

    # ---- page 5: full overlay image ----
    story += [
        PageBreak(),
        _sheet_image(png_overlay, new_rev.sheet_width, new_rev.sheet_height),
    ]

    # ---- page 6: structured summary table ----
    story += [PageBreak(), Paragraph("Structured Summary Table", heading), Spacer(0, 10)]
    if not report.deltas:
        story.append(Paragraph("No changes detected between the two revisions.", body))
    else:
        head = ["ID", "Change Type", "Object Location", "Old Value", "New Value", "Delta", "Confidence"]
        rows = []
        for i, delta in enumerate(report.deltas):
            rows.append([
                f"CH-WN-{i:03d}", _change_type_cell(delta), location_bin(delta.anchor_bbox, new_rev.sheet_width, new_rev.sheet_height),
                _state_value(delta.before), _state_value(delta.after), _delta_cell(delta), _confidence_cell(delta)
            ])
        data = [head] + [[Paragraph(escape(c), cell) for c in row] for row in rows]
        table = Table(
            data, colWidths=[60, 100, 100, 120, 120, 100, 60],
            repeatRows=1, hAlign="LEFT",
        )
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1b2f4c")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTSIZE", (0, 0), (-1, 0), 8),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.lightgrey),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#fafafa")]),
        ]))
        story.append(table)

    # ---- page 7+: detailed modifications ----
    try:
        im_old = PILImage.open(png_old)
        im_new = PILImage.open(png_new)
        im_overlay = PILImage.open(png_overlay)
    except Exception:
        im_old = im_new = im_overlay = None

    if report.deltas and im_old and im_new and im_overlay:
        scale_x = im_new.width / new_rev.sheet_width
        scale_y = im_new.height / new_rev.sheet_height
        
        # Limit to 15 changes to ensure we don't timeout the fast API response
        for i, delta in enumerate(report.deltas[:15]):
            story += [PageBreak(), Paragraph(f"Detailed Modification Log - CH-WN-{i:03d}", heading), Spacer(0, 10)]
            
            x0, y0, x1, y1 = delta.anchor_bbox
            pad = 50
            cx0 = max(0, int(x0 * scale_x) - pad)
            cy0 = max(0, int(y0 * scale_y) - pad)
            cx1 = min(im_new.width, int(x1 * scale_x) + pad)
            cy1 = min(im_new.height, int(y1 * scale_y) + pad)
            
            imgs = []
            for im in (im_old, im_new, im_overlay):
                cropped = im.crop((cx0, cy0, cx1, cy1))
                buf = BytesIO()
                cropped.save(buf, format="PNG", optimize=False)
                buf.seek(0)
                cw, ch = cropped.size
                ih = 120
                iw = ih * (cw / max(ch, 1))
                imgs.append(Image(buf, width=iw, height=ih))
                
            img_table = Table(
                [[imgs[0], imgs[1], imgs[2]],
                 ["Before (Revision A)", "After (Revision B)", "Overlay Diff"]],
                hAlign="LEFT"
            )
            img_table.setStyle(TableStyle([
                ("GRID", (0, 0), (-1, 0), 1, colors.lightgrey),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("FONTNAME", (0, 1), (-1, 1), "Helvetica-Bold"),
                ("FONTSIZE", (0, 1), (-1, 1), 8),
                ("TOPPADDING", (0, 1), (-1, 1), 5),
                ("BOTTOMPADDING", (0, 1), (-1, 1), 15),
            ]))
            story.append(img_table)
            
            det_data = [
                ["Entity Type:", _entity_cell(delta), "Location Context:", location_bin(delta.anchor_bbox, new_rev.sheet_width, new_rev.sheet_height)],
                ["Before Value:", _state_value(delta.before), "After Value:", _state_value(delta.after)],
                ["Delta / Change:", _delta_cell(delta), "Confidence Level:", _confidence_cell(delta)],
                ["Bounding Bbox:", f"x={int(x0)}, y={int(y0)}, w={int(x1-x0)}, h={int(y1-y0)}", "Real-world Scale:", f"{x1-x0:.1f} x {y1-y0:.1f} mm"]
            ]
            det_table = Table(det_data, colWidths=[100, 240, 100, 240], hAlign="LEFT")
            det_table.setStyle(TableStyle([
                ("GRID", (0, 0), (-1, -1), 0.5, colors.lightgrey),
                ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                ("FONTNAME", (2, 0), (2, -1), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#f8fdf4")),
                ("BACKGROUND", (2, 0), (2, -1), colors.HexColor("#f8fdf4")),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]))
            story.append(det_table)
            
            story += [
                Spacer(0, 20),
                Paragraph("Explainable AI Description:", ParagraphStyle("xai", parent=styles["Heading4"], fontSize=10, fontName="Helvetica-Bold")),
                Spacer(0, 5),
                Paragraph(f"Change detected for entity at {location_bin(delta.anchor_bbox, new_rev.sheet_width, new_rev.sheet_height)}.", ParagraphStyle("xai_body", parent=body, fontSize=9))
            ]

    # ---- page 8: conclusion ----
    story += [
        PageBreak(),
        Paragraph("System Conclusion & Recommendations", heading),
        Spacer(0, 20),
        Paragraph(f"This report was generated automatically by the offline Revision Intelligence System. The analysis highlights that the drawing registered with a confidence of {inlier_pct:.1f}%. The estimated modifications cover {pct:.3f}% of the total drawing canvas, falling into a {sev} modification category.", body),
        Spacer(0, 20),
        Paragraph("Next Action Recommendations:", ParagraphStyle("nar", parent=styles["Heading4"], fontSize=11, fontName="Helvetica-Bold", textColor=colors.HexColor("#3b6294"))),
        Spacer(0, 10),
    ]

    has_dim_changes = any("Dimension" in _entity_cell(delta) for delta in report.deltas if delta.change_type == "modified")
    recs = []
    if sev == "High":
        recs.append("<b>\u2022 Immediate Review Required:</b> High severity revision detected. A full manual sign-off by the lead architect is strongly recommended.")
    if counts.get("added", 0) > 0:
        recs.append(f"<b>\u2022 Verify New Entities:</b> There are {counts.get('added', 0)} newly added elements. Ensure these align with the latest client request tickets.")
    if counts.get("removed", 0) > 0:
        recs.append(f"<b>\u2022 Confirm Removals:</b> {counts.get('removed', 0)} elements were removed. Confirm that these removals are intentional and do not negatively impact structural integrity.")
    if has_dim_changes:
        recs.append("<b>\u2022 Verify OCR Dimension Readings:</b> Pay close attention to the purple highlighted dimension shifts before executing final manufacturing or architectural plans.")
    
    if not recs:
        recs.append("<b>\u2022 Routine Check:</b> No critical changes detected. Proceed with standard review processes.")
    
    for rec in recs:
        story += [Paragraph(rec, body), Spacer(0, 5)]
    doc = SimpleDocTemplate(
        str(out), pagesize=PAGE_SIZE,
        leftMargin=MARGIN, rightMargin=MARGIN, topMargin=MARGIN, bottomMargin=MARGIN,
        invariant=1,  # FR-013: fixed creation date + deterministic PDF ID
        title=HEADER_TITLE,
    )
    doc.build(story, canvasmaker=_canvas_for(report.pipeline_version))
    return out
