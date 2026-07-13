"""Core domain models (data-model.md).

Geometry, bboxes, and text payloads are vector-exact by construction
(Constitution IV): they are copied from source coordinates/text layers and
never recomputed by inference. The only inference-capable field on an entity
is ``semantic_label``, which must carry provenance and confidence.
"""

from __future__ import annotations

import hashlib
import math
from typing import Literal

from pydantic import BaseModel, ConfigDict, model_validator

Provenance = Literal["vector-exact", "inference"]
EntityKind = Literal["linework", "text", "dimension", "symbol", "hatch"]
EdgeKind = Literal["knn-proximity", "connectivity"]
BBox = tuple[float, float, float, float]
Point = tuple[float, float]


class LabeledValue(BaseModel):
    model_config = ConfigDict(frozen=True)

    value: str | float
    provenance: Provenance
    confidence: float | None = None

    @model_validator(mode="after")
    def _inference_requires_confidence(self) -> LabeledValue:
        if self.provenance == "inference" and self.confidence is None:
            raise ValueError("inference-derived values must carry a confidence")
        return self


class StyleAttrs(BaseModel):
    model_config = ConfigDict(frozen=True)

    stroke: str | None = None
    fill: str | None = None
    width: float | None = None


class PathSegment(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: Literal["line", "curve", "rect", "quad"]
    points: list[Point]


class DrawingRevision(BaseModel):
    revision_id: Literal["old", "new"]
    source_filename: str
    format: Literal["pdf", "dxf"]
    page_index: int = 0
    sheet_width: float
    sheet_height: float
    sheet_diagonal: float
    content_hash: str


class DrawingEntity(BaseModel):
    entity_id: str
    kind: EntityKind
    geometry: list[PathSegment] = []
    bbox: BBox
    geometry_signature: str
    layer: str | None = None
    style: StyleAttrs | None = None
    text_payload: str | None = None
    label: str | None = None  # read from the text layer (e.g. "D14"); never inferred
    dimension_value: str | None = None
    semantic_label: LabeledValue | None = None
    # Text insertion origin from the source text layer (vector-exact). For
    # text-bearing entities the rendered bbox width depends on string content,
    # so bbox-derived positions shift when the text length changes even if the
    # entity never moved; the origin is content-length-invariant.
    anchor: Point | None = None

    @property
    def position(self) -> Point:
        x0, y0, x1, y1 = self.bbox
        return ((x0 + x1) / 2.0, (y0 + y1) / 2.0)


def transform_point(point: Point, t: SimilarityTransform) -> Point:
    """Apply a similarity transform (old frame -> new frame)."""
    x, y = point
    c, s = math.cos(t.rotation), math.sin(t.rotation)
    return (t.scale * (c * x - s * y) + t.tx, t.scale * (s * x + c * y) + t.ty)


def is_identity(t: SimilarityTransform | None) -> bool:
    return t is None or (t.scale == 1.0 and t.rotation == 0.0 and t.tx == 0.0 and t.ty == 0.0)


def displacement(
    a: DrawingEntity, b: DrawingEntity, transform: SimilarityTransform | None = None
) -> float:
    """Displacement between two entities, robust to string-length changes.

    Text-bearing entities compare their source text-insertion origins (exact,
    content-independent); everything else compares bbox centers. A pure
    dimension/text value edit therefore measures 0.0, while a genuine move
    measures its true distance (deltas/compute R7, match/cascade tier 2).
    When a registration ``transform`` is given, ``a`` (the OLD-revision
    entity) is mapped into the new frame first, so distances are measured
    in aligned space (US3).
    """
    if a.anchor is not None and b.anchor is not None:
        (ax, ay), (bx, by) = a.anchor, b.anchor
    else:
        (ax, ay), (bx, by) = a.position, b.position
    if transform is not None:
        ax, ay = transform_point((ax, ay), transform)
    return ((ax - bx) ** 2 + (ay - by) ** 2) ** 0.5


def shape_equivalent(
    a: DrawingEntity,
    b: DrawingEntity,
    transform: SimilarityTransform | None = None,
    tol: float = 0.5,
) -> bool:
    """Geometry equality modulo the registration transform.

    Fast path: shape_signature hashes are translation-invariant, so for a
    pure-translation/identity transform bit-exact hash equality applies.
    Under scale/rotation the hashes diverge for identical shapes, so compare
    centroid-relative points numerically after applying the transform's
    scale+rotation, within ``tol`` (absolute, points).
    """
    if transform is None or (transform.scale == 1.0 and transform.rotation == 0.0):
        return shape_signature(a) == shape_signature(b)
    if len(a.geometry) != len(b.geometry):
        return False
    if not a.geometry:
        return a.kind == b.kind
    a_pts = [p for seg in a.geometry for p in seg.points]
    b_pts = [p for seg in b.geometry for p in seg.points]
    if len(a_pts) != len(b_pts):
        return False
    if any(sa.kind != sb.kind for sa, sb in zip(a.geometry, b.geometry, strict=True)):
        return False
    acx = sum(p[0] for p in a_pts) / len(a_pts)
    acy = sum(p[1] for p in a_pts) / len(a_pts)
    bcx = sum(p[0] for p in b_pts) / len(b_pts)
    bcy = sum(p[1] for p in b_pts) / len(b_pts)
    c, s = math.cos(transform.rotation), math.sin(transform.rotation)
    for (ax, ay), (bx, by) in zip(a_pts, b_pts, strict=True):
        rx, ry = ax - acx, ay - acy
        tx = transform.scale * (c * rx - s * ry)
        ty = transform.scale * (s * rx + c * ry)
        if abs(tx - (bx - bcx)) > tol or abs(ty - (by - bcy)) > tol:
            return False
    return True


def style_equivalent(a: DrawingEntity, b: DrawingEntity, scale: float = 1.0) -> bool:
    """Style equality modulo export scale: text sizes scale with the sheet
    (a scaled export is NOT a style change), stroke widths compare directly."""
    sa, sb = a.style, b.style
    if sa is None or sb is None:
        return sa == sb
    if sa.stroke != sb.stroke or sa.fill != sb.fill:
        return False
    wa, wb = sa.width or 0.0, sb.width or 0.0
    if abs(wa - wb) <= 1e-6:
        return True
    if scale != 1.0:
        expected = wa * scale
        return abs(wb - expected) <= 0.05 * max(abs(wb), abs(expected), 1e-6)
    return False


def shape_signature(entity: DrawingEntity) -> str:
    """Geometry-only, translation-invariant hash — pure shape, no style/text.

    Distinct from ``geometry_signature`` (which hashes style and text too):
    two entities share a shape_signature iff their path geometry is identical
    up to translation. This is what the matching cascade (R6 tier 2) and the
    R7 moved rule mean by "identical geometry"; entities without path
    geometry (text/dimension) degrade to their structural kind.
    """
    if not entity.geometry:
        return f"kindonly:{entity.kind}"
    points = [p for seg in entity.geometry for p in seg.points]
    cx = sum(p[0] for p in points) / len(points)
    cy = sum(p[1] for p in points) / len(points)
    material: list[str] = []
    for seg in entity.geometry:
        material.append(seg.kind)
        material.extend(f"{p[0] - cx:.3f},{p[1] - cy:.3f}" for p in seg.points)
    return hashlib.sha1("|".join(material).encode("utf-8")).hexdigest()[:16]


class GraphEdge(BaseModel):
    model_config = ConfigDict(frozen=True)

    source: str
    target: str
    kind: EdgeKind


class DrawingGraph(BaseModel):
    revision: DrawingRevision
    entities: list[DrawingEntity]
    edges: list[GraphEdge]

    @model_validator(mode="after")
    def _canonical_entity_order(self) -> DrawingGraph:
        self.entities.sort(key=lambda e: e.entity_id)
        self.edges.sort(key=lambda e: (e.source, e.target, e.kind))
        return self


class SimilarityTransform(BaseModel):
    tx: float
    ty: float
    scale: float
    rotation: float


class RegistrationResult(BaseModel):
    transform: SimilarityTransform
    inlier_ratio: float
    rms_residual_rel: float
    status: Literal["aligned", "failed"]
    anchors_used: int


class EntityMatch(BaseModel):
    old_entity_id: str | None
    new_entity_id: str | None
    tier: Literal["exact", "attribute", "learned"]
    similarity: LabeledValue | None = None
