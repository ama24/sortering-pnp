"""The start-up check: the first run after sortering-pnp starts (or the Device tab's button).

  homing        home the printer (and the usual checks before moving)
  layout check  one photo of the bins: resync (where the grid and every bin stand)
  bins check    the model on that same photo (once, on the whole calibrated picture, nothing
                painted over): a bin with parts in it collects their kind, an empty one is a
                free wild bin. Nothing is counted on a bin's code (its shelf or post): the
                printed code looks like parts to the model
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

STEPS = (
    ("homing", "Homing"),
    ("layout", "Layout check"),
    ("bins", "Bins check"),
    ("ready", "Ready"),
)

# around a code: the code itself, its shelf or post, and a little more
CODE_KEEPOUT_MM = max(binspec.SHELF_DEPTH_MM, binspec.POST_MM) / 2 + 3.0


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


def parts_in_bin(
    layout: Layout, b: Bin, parts: Iterable[Part], min_score: float = 0.0
) -> list[Part]:
    """Parts the camera sees on a bin's floor (inside its walls), none on or next to its code."""
    x0, y0, x1, y1 = layout.cells_rect(b.x, b.y, b.w, b.d)
    inset = binspec.GAP_MM / 2 + binspec.WALL_MM + 1.0
    x0, y0, x1, y1 = x0 + inset, y0 + inset, x1 - inset, y1 - inset
    mx, my = layout.marker_centre(b)
    h = CODE_KEEPOUT_MM
    return [
        p
        for p in parts
        if p.score >= min_score
        and x0 <= p.bed_xy[0] <= x1
        and y0 <= p.bed_xy[1] <= y1
        and not (abs(p.bed_xy[0] - mx) <= h and abs(p.bed_xy[1] - my) <= h)
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
