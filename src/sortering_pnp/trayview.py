"""Only the tray goes to the model: everything outside the tray's inside (the walls, the bins
around it, their codes and the parts in them) and the corner post are painted over with the
colour of the tray's floor before the model looks at the photo.

The photo keeps its size and so its scale: the model sees the parts exactly as large as in its
training pictures (a plate with the parts, cut at the frame's edge where the lip is). Cropping
and resizing instead would change the scale and spoil the classes and the lengths.

The bins view does the same for looking into the bins (the start-up check, Resync, the checks
after a bin change): only the floors of the bins whose codes are in that very photo are kept,
each found from its code (`bins_area`: the size from the code's number, the place and turn from
the code), so it follows the bins wherever they stand. Their codes (with the shelf or post they
sit on) are painted too: a printed code looks like parts to the model.

The markers are always read from the photo itself, never from the painted one.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from . import binspec
from .drawing import poly as int_poly

# around a code: the code itself, its shelf or post, and a little more (startup.py's too)
CODE_KEEPOUT_MM = max(binspec.SHELF_DEPTH_MM, binspec.POST_MM) / 2 + 3.0
# a code's own pixels, grown by this about its centre, are painted too (it stands on the rim,
# so seen from above it is not where its floor-plane square is)
CODE_GROW = 1.6


def _inside(poly: np.ndarray, xy: tuple[float, float]) -> bool:
    x, y = xy
    n, c = len(poly), False
    for i in range(n):
        (x0, y0), (x1, y1) = poly[i], poly[(i + 1) % n]
        if (y0 > y) != (y1 > y) and x < x0 + (y - y0) * (x1 - x0) / (y1 - y0):
            c = not c
    return c


@dataclass
class WorkArea:
    """What the model sees, in the plate frame (mm, at the floor: z = 0): the tray's inside
    (`outline`), or the bins' floors (`outline` and `more`), minus `holes` (the corner post,
    the codes)."""

    outline: np.ndarray  # (N, 2)
    holes: list[np.ndarray] = field(default_factory=list)  # e.g. the corner post
    more: list[np.ndarray] = field(default_factory=list)  # further kept outlines (bins view)

    @property
    def outlines(self) -> list[np.ndarray]:
        return [self.outline, *self.more]

    def shifted(self, d: np.ndarray) -> WorkArea:
        return WorkArea(self.outline + d, [h + d for h in self.holes], [m + d for m in self.more])

    def contains(self, xy: tuple[float, float]) -> bool:
        return any(_inside(o, xy) for o in self.outlines) and not any(
            _inside(h, xy) for h in self.holes
        )


@dataclass
class BinsView:
    """Asks for the bins view (above): the area is made from the codes found in the photo.
    `margin_mm`: + keeps more of each floor's edge (up the walls), - paints more of it."""

    margin_mm: float = 0.0


def rect(x0: float, y0: float, x1: float, y1: float) -> np.ndarray:
    return np.array([(x0, y0), (x1, y0), (x1, y1), (x0, y1)], dtype=float)


def _turned(centre: np.ndarray, yaw_deg: float, pts: Iterable[tuple[float, float]]) -> np.ndarray:
    c, s = math.cos(math.radians(yaw_deg)), math.sin(math.radians(yaw_deg))
    return np.array([(centre[0] + c * x - s * y, centre[1] + s * x + c * y) for x, y in pts])


def bin_floor(
    marker: int, code_xy: tuple[float, float], up_deg: float, margin_mm: float = 0.0
) -> tuple[np.ndarray, np.ndarray] | None:
    """A bin's floor (inside its walls) and its code's keep-out square, in the frame of the
    code's position (plate or printer mm), from its code alone: the size from the number, the
    bin's back where the code's top edge points. None for a code that is no bin's."""
    size = binspec.size_for_marker(marker)
    if size is None:
        return None
    yaw = up_deg - 90.0  # the bin frame's +Y (its back) is the code's top edge
    ox, oy = binspec.marker_offset_for(marker, size.w, size.d)
    code = np.asarray(code_xy, dtype=float)
    centre = code - _turned(np.zeros(2), yaw, [(ox, oy)])[0]
    hw = binspec.outer_mm(size.w) / 2 - binspec.WALL_MM - 1.0 + margin_mm
    hd = binspec.outer_mm(size.d) / 2 - binspec.WALL_MM - 1.0 + margin_mm
    floor = _turned(centre, yaw, [(-hw, -hd), (hw, -hd), (hw, hd), (-hw, hd)])
    k = CODE_KEEPOUT_MM
    keep_out = _turned(code, yaw, [(-k, -k), (k, -k), (k, k), (-k, k)])
    return floor, keep_out


def bins_area(markers: Iterable[Any], margin_mm: float = 0.0) -> WorkArea | None:
    """The bins view's area from the codes in a photo (markers.MarkerPose: `marker`, `centre`,
    `up_deg`, plate frame): every bin's floor, its code kept out. None when there is no bin."""
    floors, holes = [], []
    for mk in markers:
        got = bin_floor(int(mk.marker), mk.centre, float(mk.up_deg), margin_mm)
        if got is not None:
            floors.append(got[0])
            holes.append(got[1])
    if not floors:
        return None
    return WorkArea(floors[0], holes, floors[1:])


def code_quads_px(corners: Iterable[np.ndarray], grow: float = CODE_GROW) -> list[np.ndarray]:
    """Each code's own pixel corners, grown about its centre: painted in the bins view."""
    out = []
    for c in corners:
        q = np.asarray(c, dtype=float).reshape(-1, 2)
        m = q.mean(axis=0)
        out.append(m + (q - m) * grow)
    return out


def parse_colour(text: str) -> tuple[int, int, int] | None:
    """A colour "#RRGGBB" -> BGR; "auto" -> None (the floor's own colour)."""
    t = text.strip().lstrip("#")
    if text.strip().lower() == "auto":
        return None
    if len(t) != 6:
        raise ValueError(f"camera.mask_colour: auto or #RRGGBB, not {text!r}")
    r, g, b = (int(t[i : i + 2], 16) for i in (0, 2, 4))
    return b, g, r


def paint_outside(
    image: np.ndarray,
    keep_px: np.ndarray | list[np.ndarray],
    holes_px: list[np.ndarray],
    colour: tuple[int, int, int] | None = None,
) -> np.ndarray:
    """A copy of `image` (BGR) with everything outside `keep_px` (one outline or several) and
    inside `holes_px` painted: `colour`, or the median colour of what is kept (the floor: the
    parts are few)."""
    import cv2

    keeps = keep_px if isinstance(keep_px, list) else [keep_px]
    mask = np.zeros(image.shape[:2], np.uint8)
    cv2.fillPoly(mask, [int_poly(k) for k in keeps], 255)
    for h in holes_px:
        cv2.fillPoly(mask, [int_poly(h)], 0)
    if colour is None:
        floor = image[mask > 0]
        colour = tuple(int(v) for v in np.median(floor, axis=0)) if len(floor) else (200,) * 3
    out = image.copy()
    out[mask == 0] = colour
    return out
