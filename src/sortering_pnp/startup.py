"""The start-up check: the first run after sortering-pnp starts (or the Device tab's button).

  homing        home the printer (and the usual checks before moving)
  layout check  one photo of the bins: resync (where the grid and every bin stand)
  bins check    the model on that same photo (once, through the bins view: only the floors of
                the bins seen, trayview.py): a bin with parts in it collects their kind, an empty one is a
                free wild bin. Nothing is counted on a bin's code (its shelf or post): the
                printed code looks like parts to the model. binscheck.py; Resync does it too
  ready

The Device tab shows the list with a tick for every step done.
"""

from __future__ import annotations

import time
from collections import Counter
from collections.abc import Iterable
from typing import Any

from . import binspec
from .layout import Bin, Layout
from .parts import Part
from .rules import UNKNOWN, wild_key
from .trayview import CODE_KEEPOUT_MM  # around a code: the code, its shelf or post, a little more

STEPS = (
    ("homing", "Homing"),
    ("layout", "Layout check"),
    ("bins", "Bins check"),
    ("ready", "Ready"),
)


class Checklist:
    """The steps and how far they got: pending | running | done | skipped | failed."""

    def __init__(self) -> None:
        self.steps: list[dict[str, str]] = [
            {"key": k, "label": label, "state": "pending", "detail": ""} for k, label in STEPS
        ]
        self.started: float | None = None
        self.finished: float | None = None

    def begin(self) -> None:
        self.__init__()  # type: ignore[misc]
        self.started = time.time()

    def set(self, key: str, state: str, detail: str = "") -> None:
        for s in self.steps:
            if s["key"] == key:
                s["state"], s["detail"] = state, detail
        if key == "ready" and state == "done":
            self.finished = time.time()

    def fail_running(self, why: str) -> None:
        for s in self.steps:
            if s["state"] == "running":
                s["state"], s["detail"] = "failed", why

    def to_dict(self) -> dict[str, Any]:
        return {"steps": self.steps, "started": self.started, "finished": self.finished}


def floor_rect(layout: Layout, b: Bin) -> tuple[float, float, float, float]:
    """A bin's floor, inside its walls (printer X/Y): x0, y0, x1, y1."""
    x0, y0, x1, y1 = layout.cells_rect(b.x, b.y, b.w, b.d)
    inset = binspec.GAP_MM / 2 + binspec.WALL_MM + 1.0
    return x0 + inset, y0 + inset, x1 - inset, y1 - inset


def parts_in_bin(
    layout: Layout,
    b: Bin,
    parts: Iterable[Part],
    min_score: float = 0.0,
    codes: Iterable[tuple[float, float]] = (),
) -> list[Part]:
    """Parts the camera sees on a bin's floor (inside its walls), none on or next to its code:
    where the layout puts the code, nor at `codes` (where the photo shows codes, printer X/Y)."""
    x0, y0, x1, y1 = floor_rect(layout, b)
    h = CODE_KEEPOUT_MM
    spots = [layout.marker_centre(b), *codes]
    return [
        p
        for p in parts
        if p.score >= min_score
        and x0 <= p.bed_xy[0] <= x1
        and y0 <= p.bed_xy[1] <= y1
        and not any(abs(p.bed_xy[0] - x) <= h and abs(p.bed_xy[1] - y) <= h for x, y in spots)
    ]


def kind_of(parts: list[Part], wild_by: str) -> str:
    """What a bin with these parts collects: the most common kind among them (as a wild bin
    names it: part number, class or family). A length not measured: the class. Unknown parts
    only when there is nothing else."""
    known = [p for p in parts if not p.unknown]
    if not known:
        return UNKNOWN
    kinds = Counter(wild_key(p, wild_by) or p.cls for p in known)
    return max(kinds, key=lambda k: (kinds[k], "x" in k, k))
