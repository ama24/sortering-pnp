"""Only the tray goes to the model: everything outside the tray's inside (the walls, the bins
around it, their codes and the parts in them) and the corner post are painted over with the
colour of the tray's floor before the model looks at the photo.

The photo keeps its size and so its scale: the model sees the parts exactly as large as in its
training pictures (a plate with the parts, cut at the frame's edge where the lip is). Cropping
and resizing instead would change the scale and spoil the classes and the lengths.

The bins view does the same for looking into the bins (the start-up check, Resync, the checks
after a bin change): only the floors of the bins whose codes are in that very photo are kept,
each found from its code (`bins_area`: the size from the code's number, the place and turn from
the code), so it follows the bins wherever they stand. Each piece is projected at its own
height (`bin_floor`): the floor at the floor, seen through the opening at the rim; the lip that
carries the code (a shelf bin's whole back shelf, a corner bin's post with its sides) and the
code with its light border are painted, but not the open cavity in front of them: a printed
code looks like parts to the model, and parts lie right up to the lip.

The markers are always read from the photo itself, never from the painted one.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from . import binspec
from .drawing import poly as int_poly

# around a code: the code, its shelf or post, and a little more (startup.py's parts count)
CODE_KEEPOUT_MM = max(binspec.SHELF_DEPTH_MM, binspec.POST_MM) / 2 + 3.0
# the bins view paints a code with its light border and this much more, never past its lip
CODE_MARGIN_MM = 1.0


def _inside(poly: np.ndarray, xy: tuple[float, float]) -> bool:
    x, y = xy
    pts = np.asarray(poly)[:, :2]
    n, c = len(pts), False
    for i in range(n):
        (x0, y0), (x1, y1) = pts[i], pts[(i + 1) % n]
        if (y0 > y) != (y1 > y) and x < x0 + (y - y0) * (x1 - x0) / (y1 - y0):
            c = not c
    return c


def _shift(poly: np.ndarray, d: np.ndarray) -> np.ndarray:
    out = np.array(poly, dtype=float)
    out[:, :2] += np.asarray(d, dtype=float)[:2]
    return out


@dataclass
class WorkArea:
    """What the model sees, in the plate frame (mm): the tray's inside (`outline`), or the
    bins' floors (`outline` and `more`), minus `holes` (the corner post, the codes).

    A polygon is (N, 2), at the floor (z = 0), or (N, 3), each point at its own height: such a
    hole is a solid, painted as far as the camera sees it (the hull of its points' pixels).
    `clips`, one per outline (or none): only what is also inside it is kept, each projected at
    its own height (a bin's floor seen through the opening at its rim)."""

    outline: np.ndarray  # (N, 2) or (N, 3)
    holes: list[np.ndarray] = field(default_factory=list)  # e.g. the corner post
    more: list[np.ndarray] = field(default_factory=list)  # further kept outlines (bins view)
    clips: list[np.ndarray | None] = field(default_factory=list)  # [] or one per outline

    @property
    def outlines(self) -> list[np.ndarray]:
        return [self.outline, *self.more]

    def shifted(self, d: np.ndarray) -> WorkArea:
        return WorkArea(
            _shift(self.outline, d),
            [_shift(h, d) for h in self.holes],
            [_shift(m, d) for m in self.more],
            [None if c is None else _shift(c, d) for c in self.clips],
        )

    def contains(self, xy: tuple[float, float]) -> bool:
        clips = self.clips or [None] * len(self.outlines)
        return any(
            _inside(o, xy) and (c is None or _inside(c, xy))
            for o, c in zip(self.outlines, clips, strict=True)
        ) and not any(_inside(h, xy) for h in self.holes)

    def in_pixels(
        self, project: Callable[[np.ndarray], np.ndarray]
    ) -> tuple[list[np.ndarray], list[np.ndarray | None], list[np.ndarray]]:
        """(outlines, clips, holes) in pixels for paint_outside; `project`: (N, 3) plate mm ->
        (N, 2) pixels (the camera model)."""

        def px(poly: np.ndarray) -> np.ndarray:
            p = np.asarray(poly, dtype=float)
            if p.shape[1] == 2:
                p = np.c_[p, np.zeros(len(p))]
            return np.asarray(project(p), dtype=float).reshape(-1, 2)

        def solid(poly: np.ndarray) -> np.ndarray:
            q = px(poly)
            if np.asarray(poly).shape[1] == 3:
                import cv2

                q = cv2.convexHull(q.astype(np.float32)).reshape(-1, 2).astype(float)
            return q

        clips = self.clips or [None] * len(self.outlines)
        return (
            [px(o) for o in self.outlines],
            [None if c is None else px(c) for c in clips],
            [solid(h) for h in self.holes],
        )


@dataclass
class BinsView:
    """Asks for the bins view (above): the area is made from the codes found in the photo.
    `margin_mm`: + keeps more of each floor's edge (up the walls), - paints more of it."""

    margin_mm: float = 0.0


@dataclass
class BinFloor:
    """One bin as the bins view sees it, in the frame of its code (plate or printer mm), each
    (N, 3): every point at its own height."""

    floor: np.ndarray  # the floor inside the walls, at the floor's height
    opening: np.ndarray  # the walls' inside at the rim: the floor is seen through it
    lip: np.ndarray  # what carries the code: the whole back shelf (its top), or the post
    code: np.ndarray  # the code with its light border and CODE_MARGIN_MM, at its height


def rect(x0: float, y0: float, x1: float, y1: float) -> np.ndarray:
    return np.array([(x0, y0), (x1, y0), (x1, y1), (x0, y1)], dtype=float)


def _turned(centre: np.ndarray, yaw_deg: float, pts: Iterable[tuple[float, float]]) -> np.ndarray:
    c, s = math.cos(math.radians(yaw_deg)), math.sin(math.radians(yaw_deg))
    return np.array([(centre[0] + c * x - s * y, centre[1] + s * x + c * y) for x, y in pts])


def _at(xy: np.ndarray, z: float) -> np.ndarray:
    return np.c_[xy, np.full(len(xy), float(z))]


def bin_floor(
    marker: int,
    code_xy: tuple[float, float],
    up_deg: float,
    margin_mm: float = 0.0,
    code_z: float = 0.0,
) -> BinFloor | None:
    """A bin's floor, opening, lip and code, from its code alone: the size (and so the rim
    height) from the number, the bin's back where the code's top edge points, `code_z` the
    height of the code's top (in the frame of `code_xy`). None for a code that is no bin's.

    The lip is the whole shelf along the back wall (its top at the rim: its underside, at 45
    degrees, faces down and is never seen) or the corner post, from its top down to the floor
    (its sides are seen). The code is painted with its light border and CODE_MARGIN_MM more,
    never past its lip into the open cavity."""
    size = binspec.size_for_marker(marker)
    if size is None:
        return None
    yaw = up_deg - 90.0  # the bin frame's +Y (its back) is the code's top edge
    ox, oy = binspec.marker_offset_for(marker, size.w, size.d)
    code = np.asarray(code_xy, dtype=float)
    centre = code - _turned(np.zeros(2), yaw, [(ox, oy)])[0]
    rim_z = code_z - binspec.MARKER_INK_MM
    floor_z = (
        rim_z - binspec.rim_height_mm(size.height_u) + binspec.BASE_HEIGHT_MM + binspec.FLOOR_MM
    )
    iw = binspec.outer_mm(size.w) / 2 - binspec.WALL_MM  # the walls' inside, from the centre
    idp = binspec.outer_mm(size.d) / 2 - binspec.WALL_MM
    hw, hd = iw - 1.0 + margin_mm, idp - 1.0 + margin_mm
    floor = _turned(centre, yaw, [(-hw, -hd), (hw, -hd), (hw, hd), (-hw, hd)])
    ow, od = iw + margin_mm, idp + margin_mm
    opening = _turned(centre, yaw, [(-ow, -od), (ow, -od), (ow, od), (-ow, od)])
    grow = max(0.0, -margin_mm)  # - paints more: the lip's edge too
    out = binspec.WALL_MM + 1.0  # on over the walls: no sliver between the lip and the opening
    if binspec.style_for_marker(marker) == "corner":
        p = binspec.POST_MM + grow
        top = _turned(
            centre,
            yaw,
            [(iw - p, idp - p), (iw + out, idp - p), (iw + out, idp + out), (iw - p, idp + out)],
        )
        lip = np.r_[_at(top, rim_z), _at(top, floor_z)]  # straight down to the floor
        half = binspec.POST_MM / 2
    else:  # the shelf runs the bin's whole width
        f = idp - binspec.SHELF_DEPTH_MM - grow
        shelf = [(-iw - out, f), (iw + out, f), (iw + out, idp + out), (-iw - out, idp + out)]
        lip = _at(_turned(centre, yaw, shelf), rim_z)
        half = binspec.SHELF_DEPTH_MM / 2
    k = (binspec.MARKER_CELLS / 2 + binspec.MARKER_QUIET_CELLS) * binspec.MARKER_CELL_MM
    k = min(k + CODE_MARGIN_MM, half + grow)
    code_sq = _at(_turned(code, yaw, [(-k, -k), (k, -k), (k, k), (-k, k)]), code_z)
    return BinFloor(_at(floor, floor_z), _at(opening, rim_z), lip, code_sq)


def bins_area(
    markers: Iterable[Any],
    margin_mm: float = 0.0,
    heights: Callable[[int], float] | None = None,
) -> WorkArea | None:
    """The bins view's area from the codes in a photo (markers.MarkerPose: `marker`, `centre`,
    `up_deg`, plate frame; `heights`: a code's height in that frame, 0 without): every bin's
    floor seen through its opening, its lip and code left out. None when there is no bin."""
    floors, openings, holes = [], [], []
    for mk in markers:
        z = float(heights(int(mk.marker))) if heights is not None else 0.0
        got = bin_floor(int(mk.marker), mk.centre, float(mk.up_deg), margin_mm, z)
        if got is not None:
            floors.append(got.floor)
            openings.append(got.opening)
            holes += [got.lip, got.code]
    if not floors:
        return None
    return WorkArea(floors[0], holes, floors[1:], openings)


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
    clips_px: list[np.ndarray | None] | None = None,
) -> np.ndarray:
    """A copy of `image` (BGR) with everything outside `keep_px` (one outline or several, each
    cut to its `clips_px` polygon when it has one) and inside `holes_px` painted: `colour`, or
    the median colour of what is kept (the floor: the parts are few)."""
    import cv2

    keeps = keep_px if isinstance(keep_px, list) else [keep_px]
    clips = clips_px or [None] * len(keeps)
    mask = np.zeros(image.shape[:2], np.uint8)
    for k, c in zip(keeps, clips, strict=True):
        one = np.zeros_like(mask)
        cv2.fillPoly(one, [int_poly(k)], 255)
        if c is not None:
            cut = np.zeros_like(mask)
            cv2.fillPoly(cut, [int_poly(c)], 255)
            one &= cut
        mask |= one
    for h in holes_px:
        cv2.fillPoly(mask, [int_poly(h)], 0)
    if colour is None:
        floor = image[mask > 0]
        colour = tuple(int(v) for v in np.median(floor, axis=0)) if len(floor) else (200,) * 3
    out = image.copy()
    out[mask == 0] = colour
    return out
