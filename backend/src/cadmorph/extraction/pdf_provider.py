"""PDF vector extraction via PyMuPDF (research R1).

Entities are vector-exact: geometry from the page display list, text from the
text layer with exact coordinates. Entity IDs are deterministic content
hashes so identical files always yield identical graphs (Constitution IV).

Grouping note: each PyMuPDF drawing item (one path object) becomes one
entity. Multi-path symbols are therefore several linework entities at this
stage; semantic grouping/labeling arrives with the GAT stage (US1, T020-21).
"""

from __future__ import annotations

import hashlib
import re
from collections import Counter
from pathlib import Path
from typing import Literal

import fitz

from cadmorph.determinism import file_sha256
from cadmorph.models import (
    DrawingEntity,
    DrawingGraph,
    DrawingRevision,
    PathSegment,
    StyleAttrs,
)

# Deterministic dimension detection: a text-layer read, not inference.
# Matches e.g. "D14 = 10 cm", "L2=3.5m" — label, '=', measurement.
_DIMENSION_RE = re.compile(r"^\s*(\S{1,24})\s*=\s*(\d+(?:\.\d+)?\s*[a-zA-Z°%\"']{0,8})\s*$")

_ROUND = 3  # coordinate rounding for signatures/IDs (points; 0.001pt is sub-visible)


def _color(c: tuple[float, ...] | None) -> str | None:
    if c is None:
        return None
    return "#" + "".join(f"{int(round(v * 255)):02x}" for v in c)


def _segments(items: list) -> list[PathSegment]:
    segments: list[PathSegment] = []
    for item in items:
        op = item[0]
        if op == "l":
            p1, p2 = item[1], item[2]
            segments.append(PathSegment(kind="line", points=[(p1.x, p1.y), (p2.x, p2.y)]))
        elif op == "re":
            r = item[1]
            segments.append(PathSegment(kind="rect", points=[(r.x0, r.y0), (r.x1, r.y1)]))
        elif op == "c":
            pts = [(p.x, p.y) for p in item[1:5]]
            segments.append(PathSegment(kind="curve", points=pts))
        elif op == "qu":
            q = item[1]
            pts = [(q.ul.x, q.ul.y), (q.ur.x, q.ur.y), (q.ll.x, q.ll.y), (q.lr.x, q.lr.y)]
            segments.append(PathSegment(kind="quad", points=pts))
    return segments


def _signature(kind: str, segments: list[PathSegment], style: StyleAttrs, text: str | None) -> str:
    """Translation-invariant content hash: geometry relative to its centroid."""
    material: list[str] = [kind, style.stroke or "", style.fill or "", f"{style.width or 0:.3f}"]
    if text is not None:
        material.append(text)
    points = [p for seg in segments for p in seg.points]
    if points:
        cx = sum(p[0] for p in points) / len(points)
        cy = sum(p[1] for p in points) / len(points)
        for seg in segments:
            material.append(seg.kind)
            material.extend(f"{p[0] - cx:.{_ROUND}f},{p[1] - cy:.{_ROUND}f}" for p in seg.points)
    return hashlib.sha1("|".join(material).encode("utf-8")).hexdigest()[:16]


class PdfExtractionProvider:
    format = "pdf"

    def extract(
        self,
        path: str | Path,
        revision_id: Literal["old", "new"],
        page_index: int = 0,
    ) -> DrawingGraph:
        path = Path(path)
        doc = fitz.open(path)
        try:
            page = doc[page_index]
            rect = page.rect
            revision = DrawingRevision(
                revision_id=revision_id,
                source_filename=path.name,
                format="pdf",
                page_index=page_index,
                sheet_width=rect.width,
                sheet_height=rect.height,
                sheet_diagonal=(rect.width**2 + rect.height**2) ** 0.5,
                content_hash=file_sha256(path),
            )
            entities = self._path_entities(page) + self._text_entities(page)
            entities = _assign_ids(entities)
            return DrawingGraph(revision=revision, entities=entities, edges=[])
        finally:
            doc.close()

    def _path_entities(self, page: fitz.Page) -> list[DrawingEntity]:
        out: list[DrawingEntity] = []
        for drawing in page.get_drawings():
            segments = _segments(drawing["items"])
            if not segments:
                continue
            style = StyleAttrs(
                stroke=_color(drawing.get("color")),
                fill=_color(drawing.get("fill")),
                width=drawing.get("width"),
            )
            r = drawing["rect"]
            out.append(
                DrawingEntity(
                    entity_id="",  # assigned deterministically afterwards
                    kind="linework",
                    geometry=segments,
                    bbox=(r.x0, r.y0, r.x1, r.y1),
                    geometry_signature=_signature("linework", segments, style, None),
                    style=style,
                )
            )
        return out

    def _text_entities(self, page: fitz.Page) -> list[DrawingEntity]:
        out: list[DrawingEntity] = []
        for block in page.get_text("rawdict")["blocks"]:
            if block.get("type") != 0:
                continue  # image blocks are never entities on the vector path
            for line in block["lines"]:
                for span in line["spans"]:
                    text = "".join(ch["c"] for ch in span["chars"]).strip()
                    if not text:
                        continue
                    x0, y0, x1, y1 = span["bbox"]
                    origin = span["origin"]  # insertion point: content-length-invariant
                    style = StyleAttrs(stroke=None, fill=None, width=round(span["size"], 2))
                    match = _DIMENSION_RE.match(text)
                    kind = "dimension" if match else "text"
                    out.append(
                        DrawingEntity(
                            entity_id="",
                            kind=kind,
                            geometry=[],
                            bbox=(x0, y0, x1, y1),
                            geometry_signature=_signature(kind, [], style, text),
                            style=style,
                            text_payload=text,
                            label=match.group(1).strip() if match else None,
                            dimension_value=match.group(2).strip() if match else None,
                            anchor=(origin[0], origin[1]),
                        )
                    )
        return out


def _assign_ids(entities: list[DrawingEntity]) -> list[DrawingEntity]:
    """Deterministic IDs: signature + rounded position, with ordered collision suffix."""
    entities.sort(
        key=lambda e: (round(e.bbox[1], _ROUND), round(e.bbox[0], _ROUND), e.geometry_signature)
    )
    seen: Counter[str] = Counter()
    for entity in entities:
        base = hashlib.sha1(
            f"{entity.geometry_signature}@{entity.bbox[0]:.{_ROUND}f},{entity.bbox[1]:.{_ROUND}f}".encode()
        ).hexdigest()[:12]
        suffix = seen[base]
        seen[base] += 1
        entity.entity_id = f"e-{base}" if suffix == 0 else f"e-{base}-{suffix}"
    return entities
