"""Where to take a part, and which way it lies: its centre of mass, its long axis, and the grip
point (where the tweezers close or the cup touches).

Screws, standoffs and rod: the three keypoints the model already finds (head_top, bearing, tip)
give the axis and the length; with the head's size from the catalogue the centre of mass
follows (the head is heavy: on short screws it lies near or inside the head). The tweezers
close on the shank: at the centre of mass, but never on the head and not at the very tip.
A suction cup or a magnet takes a screw by its head instead (head_grip): the middle of the head
seen from above; headless parts (set screws, rod, standoffs) at their centre.
Everything else (nuts, washers, brackets, unknown parts): the centre and the long axis of the
outline, from its area moments.
Washers by a suction cup or a magnet (ring_grip): not the centre, which is the hole (the cup
would suck air, the magnet touch nothing), but the middle of the ring, between the hole (the
standard clearance hole of its thread size) and the outside (from the outline).
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass

import numpy as np

WASHER_FAMILIES = ("DIN125", "DIN127", "DIN433", "DIN6340", "DIN9021", "ISO7089", "ISO7090")
WASHER_FAMILIES += ("ISO7092", "ISO7093")
# the hole of a washer (ISO 7089 / DIN 125 d1, the same for DIN 9021 / ISO 7093), by thread size
WASHER_HOLE = {2.0: 2.2, 2.5: 2.7, 3.0: 3.2, 4.0: 4.3, 5.0: 5.3, 6.0: 6.4, 8.0: 8.4, 10.0: 10.5}
WASHER_HOLE |= {12.0: 13.0, 14.0: 15.0, 16.0: 17.0, 20.0: 21.0}
MIN_RING_MM = 0.6  # a ring narrower than this (or no hole found): the centre after all
THREAD_FILL = 0.85  # a threaded shank weighs about this share of a smooth one
SOCKET_FILL = 0.85  # socket heads: the hex socket takes some of the head away


@dataclass
class Grip:
    point: tuple[float, float]  # plate mm: where to take it
    axis_deg: float  # direction of the long axis (plate frame), 0..180
    com: tuple[float, float]  # centre of mass, plate mm
    method: str  # "axis" (keypoints) | "head" | "outline"


@dataclass
class Shape:
    """What the grip needs to know about a class (from the catalogue)."""

    d: float  # thread diameter
    head_r: float = 0.0  # head radius (or half the hex size); 0 = no head
    head_k: float = 0.0  # head height along the axis; 0 = headless (set screw, rod, standoff)
    socket: bool = False


def com_from_bearing(length: float, s: Shape) -> float:
    """Centre of mass along the axis, mm from the underside of the head towards the tip
    (negative: inside the head). `length` = bearing to tip."""
    shank = math.pi * (s.d / 2) ** 2 * max(length, 0.0) * THREAD_FILL
    if s.head_k <= 0 or s.head_r <= 0:
        return length / 2
    head = math.pi * s.head_r**2 * s.head_k * (SOCKET_FILL if s.socket else 1.0)
    return (shank * length / 2 - head * s.head_k / 2) / (shank + head)


def axis_grip(
    kp: Mapping[str, tuple[float, float]],
    s: Shape,
    min_from_head_mm: float = 1.5,
    min_from_tip_mm: float = 1.0,
) -> Grip:
    """Grip of a part with an axis, from its keypoints in plate mm."""
    ht, br, tp = (np.asarray(kp[k], dtype=float) for k in ("head_top", "bearing", "tip"))
    v = tp - ht
    n = float(np.linalg.norm(v))
    u = v / n if n > 1e-9 else np.array([1.0, 0.0])
    axis = math.degrees(math.atan2(u[1], u[0])) % 180.0
    headless = s.head_k <= 0 or float(np.linalg.norm(br - ht)) < 0.3
    if headless:
        com = (ht + tp) / 2
        return Grip(_t(com), axis, _t(com), "axis")
    length = float(np.dot(tp - br, u))
    at = com_from_bearing(length, s)
    com = br + u * at
    lo, hi = min_from_head_mm, length - min_from_tip_mm
    grip_at = min(max(at, lo), hi) if hi > lo else length / 2  # on the shank
    return Grip(_t(br + u * grip_at), axis, _t(com), "axis")


def head_grip(kp: Mapping[str, tuple[float, float]], s: Shape) -> Grip:
    """Cup or magnet: the middle of the head (between head_top and the underside of the head);
    a headless part at its centre of mass. Axis and centre of mass as for the tweezers."""
    g = axis_grip(kp, s)
    ht, br = (np.asarray(kp[k], dtype=float) for k in ("head_top", "bearing"))
    if s.head_k <= 0 or float(np.linalg.norm(br - ht)) < 0.3:
        return g
    return Grip(_t((ht + br) / 2), g.axis_deg, g.com, "head")


def outline_grip(poly: np.ndarray) -> Grip | None:
    """Centre of area and long axis of an outline (N, 2), from its area moments."""
    p = np.asarray(poly, dtype=float).reshape(-1, 2)
    if len(p) < 3:
        return None
    x, y = p[:, 0], p[:, 1]
    x1, y1 = np.roll(x, -1), np.roll(y, -1)
    c = x * y1 - x1 * y
    a = c.sum() / 2
    if abs(a) < 1e-9:
        return None
    if a < 0:  # clockwise outline: the same moments with the sign of the area turned
        c, a = -c, -a
    cx = ((x + x1) * c).sum() / (6 * a)
    cy = ((y + y1) * c).sum() / (6 * a)
    # second moments about the origin, then about the centroid
    ixx = ((x**2 + x * x1 + x1**2) * c).sum() / 12 - a * cx**2
    iyy = ((y**2 + y * y1 + y1**2) * c).sum() / 12 - a * cy**2
    ixy = ((x * y1 + 2 * x * y + 2 * x1 * y1 + x1 * y) * c).sum() / 24 - a * cx * cy
    axis = math.degrees(0.5 * math.atan2(2 * ixy, ixx - iyy)) % 180.0
    return Grip((float(cx), float(cy)), axis, (float(cx), float(cy)), "outline")


def washer_hole_d(cls: str) -> float | None:
    """The hole of a washer class (e.g. DIN125A_M4 -> 4.3), None for anything else."""
    import re

    if not cls.startswith(WASHER_FAMILIES):
        return None
    m = re.search(r"_M(\d+(?:\.\d+)?)", cls)
    if not m:
        return None
    d = float(m.group(1))
    return WASHER_HOLE.get(d, round(d * 1.06 + 0.1, 2))


def ring_grip(poly: np.ndarray, hole_d: float, toward_deg: float = 0.0) -> Grip | None:
    """Washer by a cup or a magnet: on the middle of the ring, between the hole (hole_d) and the
    outside (the outline's equivalent circle), on the side `toward_deg` (plate frame). None if
    the outline is not a ring around that hole."""
    g = outline_grip(poly)
    if g is None:
        return None
    p = np.asarray(poly, dtype=float).reshape(-1, 2)
    x, y = p[:, 0], p[:, 1]
    area = abs(float((x * np.roll(y, -1) - np.roll(x, -1) * y).sum())) / 2
    r_out, r_in = math.sqrt(area / math.pi), hole_d / 2
    if r_out - r_in < MIN_RING_MM:
        return None
    r = (r_in + r_out) / 2
    a = math.radians(toward_deg)
    cx, cy = g.com
    return Grip((cx + r * math.cos(a), cy + r * math.sin(a)), g.axis_deg, g.com, "ring")


def ring_width(poly: np.ndarray, hole_d: float) -> float:
    """How wide a washer's ring is (outside radius - hole radius), mm."""
    p = np.asarray(poly, dtype=float).reshape(-1, 2)
    x, y = p[:, 0], p[:, 1]
    area = abs(float((x * np.roll(y, -1) - np.roll(x, -1) * y).sum())) / 2
    return math.sqrt(area / math.pi) - hole_d / 2


def jaw_angle(axis_deg: float, offset_deg: float = 0.0) -> float:
    """Tweezer rotation (0..180) that closes the jaws across a part lying along `axis_deg`:
    at 0 the jaws close along printer X."""
    return (axis_deg + 90.0 + offset_deg) % 180.0


def _t(v: np.ndarray) -> tuple[float, float]:
    return float(v[0]), float(v[1])
