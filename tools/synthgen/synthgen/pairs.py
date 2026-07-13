"""Mutation engine, PDF rendering, and answer-key emission."""

from __future__ import annotations

import json
import random
from dataclasses import replace
from pathlib import Path
from typing import Any

import fitz

from synthgen.sheets import PAGE_H, PAGE_W, PRESETS, SynthEntity

MUTATIONS = (
    "dim-change", "add", "remove", "move", "text-edit", "style", "twin",
    "dim-grow", "dim-change-move",
)


def _state(e: SynthEntity) -> dict[str, Any]:
    """EntityState-shaped projection of a synthetic entity (ExpectedChange).

    entity_id and geometry_signature are omitted: both are derived by the
    extractor from parsed content and cannot be known before extraction —
    the scoring rule (README.md) excludes them explicitly.
    """
    kind = e.extraction_kind()
    label = dimension_value = None
    if kind == "dimension":
        label_part, value_part = (part.strip() for part in e.text.split("=", 1))
        label, dimension_value = label_part, value_part
    return {
        "kind": kind,
        "bbox": list(e.bbox()),
        "label": label,
        "text_payload": e.text,
        "dimension_value": dimension_value,
        "style": {"width": e.width},
    }


def _apply_mutations(
    base: list[SynthEntity], mutations: list[str], rng: random.Random, move_distance: float
) -> tuple[list[SynthEntity], list[dict[str, Any]]]:
    v2 = [replace(e) for e in base]
    expected: list[dict[str, Any]] = []

    def record(
        change_type: str,
        before: SynthEntity | None,
        after: SynthEntity | None,
        kinds: list[str] | None = None,
    ) -> None:
        anchor = after if after is not None else before
        assert anchor is not None
        expected.append(
            {
                "change_type": change_type,
                "kind": anchor.extraction_kind(),
                "anchor_bbox": list(anchor.bbox()),
                "before": _state(before) if before is not None else None,
                "after": _state(after) if after is not None else None,
                "modification_kinds": kinds or [],
            }
        )

    for mutation in mutations:
        if mutation == "dim-change":
            target = next(e for e in v2 if e.extraction_kind() == "dimension")
            before_state = replace(target)
            label, old_value = (part.strip() for part in target.text.split("="))
            new_value = "40 cm" if old_value != "40 cm" else "55 cm"
            target.text = f"{label} = {new_value}"
            record("modified", before_state, target, kinds=["dimension_value", "text"])
        elif mutation == "add":
            added = SynthEntity(
                "added01", "rect", points=[(700, 120), (750, 170)], width=1.2, semantic="furniture"
            )
            v2.append(added)
            record("added", None, added)
        elif mutation == "remove":
            target = next(e for e in v2 if e.shape == "line" and e.width == 0.8)  # a door swing
            v2.remove(target)
            record("removed", target, None)
        elif mutation == "move":
            target = next(e for e in v2 if e.shape == "rect" and e.uid.startswith("s") and e.width == 1.0)
            moved = target.moved(move_distance, 0)
            v2[v2.index(target)] = moved
            record("modified", target, moved, kinds=["moved"])
        elif mutation == "text-edit":
            target = next(e for e in v2 if e.text and e.text.startswith("NOTE:"))
            before_state = replace(target)
            target.text = "NOTE: ALL WALLS 250MM U.N.O."
            record("modified", before_state, target, kinds=["text"])
        elif mutation == "style":
            target = next(e for e in v2 if e.shape == "line" and e.width in (2.0, 1.5))
            before_state = replace(target)
            target.width += 1.0
            record("modified", before_state, target, kinds=["style"])
        elif mutation == "dim-grow":
            # Large string GROWTH ("10 cm" -> "10000 cm"): regression fixture
            # for string-length-sensitive position metrics (never "moved").
            target = [e for e in v2 if e.extraction_kind() == "dimension"][-1]
            before_state = replace(target)
            label, _ = (part.strip() for part in target.text.split("="))
            target.text = f"{label} = 10000 cm"
            record("modified", before_state, target, kinds=["dimension_value", "text"])
        elif mutation == "dim-change-move":
            # Genuine small move (3pt) combined with a simultaneous value
            # change: "moved" must be reported with the true distance.
            target = next(e for e in v2 if e.extraction_kind() == "dimension")
            before_state = replace(target)
            moved = target.moved(3.0, 0.0)
            label, old_value = (part.strip() for part in moved.text.split("="))
            moved.text = f"{label} = {'40 cm' if old_value != '40 cm' else '55 cm'}"
            v2[v2.index(target)] = moved
            record("modified", before_state, moved, kinds=["moved", "dimension_value", "text"])
        elif mutation == "twin":
            # Adversarial case for the R7 displacement threshold (T025): an
            # entity is removed AND an identical-shaped twin appears far away
            # (~40% of the sheet diagonal). Merging them into one "moved"
            # delta would be wrong — the key records removed + added.
            target = next(e for e in v2 if e.semantic == "furniture")
            v2.remove(target)
            x0, y0, x1, y1 = target.bbox()
            twin = replace(target, uid="twin01", points=[(390, 130), (390 + (x1 - x0), 130 + (y1 - y0))])
            v2.append(twin)
            record("removed", target, None)
            record("added", None, twin)
        else:
            raise ValueError(f"unknown mutation {mutation!r}; known: {MUTATIONS}")
    return v2, expected


def _check_on_page(
    entities: list[SynthEntity], offset: tuple[float, float], scale: float, revision: str
) -> None:
    """Fail loudly if the export transform pushes any entity off the page.

    A clipped entity silently vanishes from the rendered PDF while the
    inventory and expected_changes still assume it exists — an internally
    contradictory answer key that would fail gates for fixture reasons
    (Constitution V demands the key match the render).
    """
    ox, oy = offset
    for e in entities:
        x0, y0, x1, y1 = e.bbox()
        tx0, ty0 = x0 * scale + ox, y0 * scale + oy
        tx1, ty1 = x1 * scale + ox, y1 * scale + oy
        label = f"{e.uid} ({e.text!r})" if e.text else f"{e.uid} ({e.shape})"
        if tx0 < 0 or ty0 < 0 or tx1 > PAGE_W or ty1 > PAGE_H:
            bound = (
                f"x0={tx0:.2f} < 0" if tx0 < 0
                else f"y0={ty0:.2f} < 0" if ty0 < 0
                else f"x1={tx1:.2f} > page width {PAGE_W}" if tx1 > PAGE_W
                else f"y1={ty1:.2f} > page height {PAGE_H}"
            )
            raise ValueError(
                f"export transform (offset={offset}, scale={scale}) pushes entity "
                f"{label} off-page in {revision}: {bound}; the rendered PDF would "
                "silently drop it and the answer key would be wrong"
            )


def _render(entities: list[SynthEntity], path: Path, offset: tuple[float, float], scale: float) -> None:
    doc = fitz.open()
    page = doc.new_page(width=PAGE_W, height=PAGE_H)
    ox, oy = offset

    def t(p: tuple[float, float]) -> fitz.Point:
        return fitz.Point(p[0] * scale + ox, p[1] * scale + oy)

    for e in entities:
        if e.shape == "line":
            page.draw_line(t(e.points[0]), t(e.points[1]), color=e.color, width=e.width)
        elif e.shape == "rect":
            p0, p1 = t(e.points[0]), t(e.points[1])
            page.draw_rect(fitz.Rect(p0, p1), color=e.color, width=e.width)
        elif e.shape == "text":
            page.insert_text(t(e.pos), e.text, fontsize=e.fontsize * scale, color=e.color)
    # Byte-determinism: same seed must yield identical files (Constitution IV),
    # so strip the timestamp metadata and random trailer /ID PyMuPDF adds.
    doc.set_metadata({})
    doc.save(path, deflate=True, no_new_id=True)
    doc.close()


def _entity_records(
    entities: list[SynthEntity], offset: tuple[float, float] = (0.0, 0.0), scale: float = 1.0
) -> list[dict[str, Any]]:
    """Per-entity ground truth for model training (T020/T022).

    ``uid`` is stable across v1/v2 (mutations preserve it), giving the Siamese
    matcher its correspondence labels; ``semantic`` gives the GAT classifier
    its node labels. Bboxes are in the exported (rendered) coordinate frame.
    Not part of the answer key or its scoring rule.
    """
    ox, oy = offset
    return sorted(
        (
            {
                "uid": e.uid,
                "kind": e.extraction_kind(),
                "semantic": e.semantic,
                "bbox": [
                    e.bbox()[0] * scale + ox,
                    e.bbox()[1] * scale + oy,
                    e.bbox()[2] * scale + ox,
                    e.bbox()[3] * scale + oy,
                ],
                "text": e.text,
            }
            for e in entities
        ),
        key=lambda r: r["uid"],
    )


def _export_frame(
    change: dict[str, Any], offset: tuple[float, float], scale: float
) -> dict[str, Any]:
    """Express display-facing coordinates in the exported v2 frame.

    anchor_bbox is ALWAYS the V(n) display frame — for removed entities the
    pipeline maps the V(n-1) bbox through the registration transform, which
    for a synthetic pair IS the export transform, so the key mirrors that.
    after-state bboxes render in the v2 frame; before-state bboxes stay
    verbatim v1 coordinates (FR-009), matching the delta contract.
    """
    ox, oy = offset

    def tb(bbox: list[float]) -> list[float]:
        return [
            bbox[0] * scale + ox,
            bbox[1] * scale + oy,
            bbox[2] * scale + ox,
            bbox[3] * scale + oy,
        ]

    out = dict(change)
    out["anchor_bbox"] = tb(change["anchor_bbox"])
    if change["after"] is not None:
        after = dict(change["after"])
        after["bbox"] = tb(after["bbox"])
        out["after"] = after
    return out


def _inventory(entities: list[SynthEntity]) -> dict[str, Any]:
    counts = {"linework": 0, "text": 0, "dimension": 0}
    texts: list[str] = []
    for e in entities:
        kind = e.extraction_kind()
        counts[kind] += 1
        if e.text is not None:
            texts.append(e.text)
    return {"counts": counts, "texts": sorted(texts)}


def make_pair(
    preset: str,
    mutations: list[str],
    out_dir: str | Path,
    *,
    seed: int = 7,
    entities: int = 10000,
    move_distance: float = 20.0,
    export_offset: tuple[float, float] = (0.0, 0.0),
    export_scale: float = 1.0,
) -> Path:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    rng = random.Random(seed)

    build = PRESETS[preset]
    base = build(seed, entities) if preset == "dense" else build(seed)

    if preset == "unrelated":
        # deliberately different sheets: v1 = floorplan, v2 = unrelated content
        v1, v2, expected = PRESETS["floorplan"](seed), base, []
    else:
        v1 = base
        v2, expected = _apply_mutations(base, mutations, rng, move_distance)

    _check_on_page(v1, (0.0, 0.0), 1.0, "v1")
    _check_on_page(v2, export_offset, export_scale, "v2")
    _render(v1, out / "v1.pdf", (0.0, 0.0), 1.0)
    _render(v2, out / "v2.pdf", export_offset, export_scale)
    (out / "entities-v1.json").write_text(
        json.dumps(_entity_records(v1), indent=2, sort_keys=True), encoding="utf-8"
    )
    (out / "entities-v2.json").write_text(
        json.dumps(_entity_records(v2, export_offset, export_scale), indent=2, sort_keys=True),
        encoding="utf-8",
    )

    if export_offset != (0.0, 0.0) or export_scale != 1.0:
        expected = [_export_frame(e, export_offset, export_scale) for e in expected]

    key = {
        "preset": preset,
        "seed": seed,
        "mutations": mutations,
        "export": {"offset": list(export_offset), "scale": export_scale},
        "inventory": {"v1": _inventory(v1), "v2": _inventory(v2)},
        "expected_changes": expected,
    }
    key_path = out / "answer-key.json"
    key_path.write_text(json.dumps(key, indent=2, sort_keys=True), encoding="utf-8")
    return key_path
