"""Parameterized base-sheet generators.

A sheet is a flat list of SynthEntity primitives. Each primitive renders as
exactly one PDF draw/insert call, so the expected extraction inventory is
directly countable: line/rect -> one linework entity, text -> one text or
dimension entity (dimension iff the text matches the `LABEL = VALUE UNIT`
pattern the extractor reads deterministically).
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field, replace

PAGE_W, PAGE_H = 842.0, 595.0  # A4 landscape, points


@dataclass
class SynthEntity:
    uid: str
    shape: str  # "line" | "rect" | "text"
    points: list[tuple[float, float]] = field(default_factory=list)  # line: 2 pts, rect: 2 corners
    text: str | None = None
    pos: tuple[float, float] | None = None
    fontsize: float = 10.0
    color: tuple[float, float, float] = (0.0, 0.0, 0.0)
    width: float = 1.0
    semantic: str = "linework"  # ground-truth class for GAT training (T020/T021)

    def bbox(self) -> tuple[float, float, float, float]:
        if self.shape == "text":
            assert self.pos and self.text
            x, y = self.pos
            w = len(self.text) * self.fontsize * 0.6
            return (x, y - self.fontsize, x + w, y)
        xs = [p[0] for p in self.points]
        ys = [p[1] for p in self.points]
        return (min(xs), min(ys), max(xs), max(ys))

    def extraction_kind(self) -> str:
        if self.shape == "text":
            assert self.text is not None
            parts = self.text.split("=")
            if len(parts) == 2 and parts[1].strip() and any(c.isdigit() for c in parts[1]):
                return "dimension"
            return "text"
        return "linework"

    def moved(self, dx: float, dy: float) -> "SynthEntity":
        return replace(
            self,
            points=[(x + dx, y + dy) for x, y in self.points],
            pos=(self.pos[0] + dx, self.pos[1] + dy) if self.pos else None,
        )


def floorplan(seed: int = 7) -> list[SynthEntity]:
    rng = random.Random(seed)
    ents: list[SynthEntity] = []
    n = 0

    def uid() -> str:
        nonlocal n
        n += 1
        return f"s{n:04d}"

    # outer walls
    ents.append(SynthEntity(uid(), "rect", points=[(60, 60), (780, 540)], width=2.0, semantic="wall"))
    # inner walls: vertical + horizontal partitions
    for x in (240, 420, 600):
        ents.append(
            SynthEntity(uid(), "line", points=[(x, 60), (x, 380 + rng.uniform(0, 40))], semantic="wall")
        )
    ents.append(SynthEntity(uid(), "line", points=[(60, 380), (780, 380)], semantic="wall"))
    # door symbols: jamb line + swing chord per door
    for x in (150, 330, 510, 690):
        ents.append(SynthEntity(uid(), "line", points=[(x, 380), (x, 350)], width=1.5, semantic="door"))
        ents.append(SynthEntity(uid(), "line", points=[(x, 350), (x + 24, 374)], width=0.8, semantic="door"))
    # furniture-ish rects
    for i in range(4):
        x = 90 + i * 180 + rng.uniform(-8, 8)
        y = 430 + rng.uniform(-6, 6)
        ents.append(SynthEntity(uid(), "rect", points=[(x, y), (x + 60, y + 40)], semantic="furniture"))
    # room labels
    for label, pos in (
        ("KITCHEN", (120, 200)),
        ("LIVING ROOM", (300, 200)),
        ("BEDROOM", (480, 200)),
        ("BATH", (660, 200)),
    ):
        ents.append(SynthEntity(uid(), "text", text=label, pos=pos, fontsize=12, semantic="room-label"))
    # dimensions
    for i, (pos, value) in enumerate(
        (((120, 420), "450 cm"), ((300, 420), "380 cm"), ((480, 420), "410 cm"), ((150, 100), "10 cm"))
    ):
        ents.append(
            SynthEntity(uid(), "text", text=f"D{i + 11} = {value}", pos=pos, fontsize=9, semantic="dimension")
        )
    # notes + title block
    ents.append(
        SynthEntity(uid(), "text", text="NOTE: ALL WALLS 200MM U.N.O.", pos=(90, 560), fontsize=8, semantic="note")
    )
    ents.append(SynthEntity(uid(), "rect", points=[(620, 480), (780, 540)], semantic="title"))
    ents.append(SynthEntity(uid(), "text", text="SHEET A-101", pos=(640, 510), fontsize=10, semantic="title"))
    return ents


def dense(seed: int = 7, entities: int = 10000) -> list[SynthEntity]:
    ents = floorplan(seed)
    rng = random.Random(seed + 1)
    i = 0
    while len(ents) < entities:
        x = rng.uniform(70, 760)
        y = rng.uniform(70, 520)
        i += 1
        ents.append(
            SynthEntity(f"d{i:05d}", "line", points=[(x, y), (x + rng.uniform(4, 30), y + rng.uniform(-10, 10))], width=0.5)
        )
    return ents


def site(seed: int = 7) -> list[SynthEntity]:
    rng = random.Random(seed)
    ents: list[SynthEntity] = [
        SynthEntity("s0001", "rect", points=[(80, 80), (760, 520)], width=2.0, semantic="wall")
    ]
    for i in range(8):
        x, y = rng.uniform(120, 680), rng.uniform(120, 460)
        ents.append(
            SynthEntity(f"s{i + 2:04d}", "rect", points=[(x, y), (x + 50, y + 35)], semantic="furniture")
        )
    ents.append(SynthEntity("s0100", "text", text="SITE PLAN", pos=(400, 550), fontsize=12, semantic="title"))
    ents.append(SynthEntity("s0101", "text", text="P1 = 24 m", pos=(120, 100), fontsize=9, semantic="dimension"))
    return ents


def unrelated(seed: int = 99) -> list[SynthEntity]:
    """A different sheet entirely — used to test alignment failure."""
    rng = random.Random(seed)
    ents: list[SynthEntity] = []
    for i in range(20):
        x, y = rng.uniform(100, 700), rng.uniform(100, 480)
        ents.append(SynthEntity(f"u{i:04d}", "line", points=[(x, y), (x + 80, y + 40)]))
    ents.append(SynthEntity("u0100", "text", text="ELEVATION B-B", pos=(350, 60), fontsize=12, semantic="title"))
    return ents


PRESETS = {"floorplan": floorplan, "dense": dense, "site": site, "unrelated": unrelated}
