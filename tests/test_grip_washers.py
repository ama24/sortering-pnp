"""Washers by a suction cup or a magnet: on the ring between the hole and the outside, not on
the hole in the middle (grip.ring_grip, vision.parts_from_result)."""

from __future__ import annotations

import math

import numpy as np
import pytest

from sortering_pnp.grip import ring_grip, ring_width, washer_hole_d
from sortering_pnp.vision import parts_from_result


def circle(cx: float, cy: float, r: float, n: int = 72) -> np.ndarray:
    a = np.linspace(0, 2 * math.pi, n, endpoint=False)
    return np.c_[cx + r * np.cos(a), cy + r * np.sin(a)]


def test_washer_holes_by_thread_size():
    assert washer_hole_d("DIN125A_M4") == 4.3
    assert washer_hole_d("ISO7089_M3") == 3.2
    assert washer_hole_d("DIN9021_M8") == 8.4  # the large ones: the same hole
    assert washer_hole_d("DIN127_M5") == 5.3
    assert washer_hole_d("DIN934_M4") is None  # a nut: no ring to aim at
    assert washer_hole_d("DIN912_M4") is None


def test_the_grip_is_on_the_middle_of_the_ring():
    # DIN 125 M4: Ø9 outside, Ø4.3 hole -> ring from r 2.15 to 4.5, its middle at r 3.325
    poly = circle(10.0, 20.0, 4.5, n=360)
    g = ring_grip(poly, 4.3, toward_deg=90.0)
    assert g is not None and g.method == "ring"
    assert g.com == pytest.approx((10.0, 20.0), abs=1e-3)  # the centre is still the centre
    r = math.dist(g.point, g.com)
    assert 2.15 < r < 4.5 and r == pytest.approx((2.15 + 4.5) / 2, abs=0.01)
    assert g.point == pytest.approx((10.0, 20.0 + r), abs=1e-3)  # on the side asked for
    assert ring_width(poly, 4.3) == pytest.approx(4.5 - 2.15, abs=0.01)


def test_no_ring_no_ring_grip():
    assert ring_grip(circle(0, 0, 2.3), 4.3) is None  # outline hardly bigger than the hole


def _washer(i: int, x: float, y: float, cls: str = "DIN125A_M4", r: float = 4.5) -> dict:
    return {
        "id": i,
        "class": cls,
        "score": 0.9,
        "polygon": (circle(x, y, r) * 10).tolist(),  # px = 0.1 mm
        "position_mm": [x, y],
        "orientation_deg": 0.0,
    }


def _parts(objs, aim):
    return parts_from_result(
        {"objects": objs},
        lambda px, h: np.c_[np.asarray(px, float) * 0.1, np.full(len(px), h)],
        lambda c: None,
        None,
        aim,
    )


def test_cup_and_magnet_take_a_washer_on_its_ring_away_from_its_neighbour():
    w, other = _washer(1, 50.0, 50.0), _washer(2, 30.0, 50.0)  # the neighbour on the -X side
    p = _parts([w, other], "head")[0]
    assert p.grip_method == "ring"
    dx, dy = p.grip_plate[0] - 50.0, p.grip_plate[1] - 50.0
    assert 2.15 < math.hypot(dx, dy) < 4.5  # on the ring, not in the hole
    assert dx > 3.0 and abs(dy) < 0.05  # on the +X side, away from the neighbour
    alone = _parts([_washer(1, 50.0, 50.0)], "head")[0]
    assert alone.grip_method == "ring"


def test_tweezers_and_other_parts_keep_the_centre():
    p = _parts([_washer(1, 50.0, 50.0)], "centre")[0]  # tweezers close on the outside
    assert p.grip_method == "outline" and p.grip_plate == pytest.approx((50.0, 50.0), abs=0.05)
    nut = _parts([_washer(1, 50.0, 50.0, cls="DIN934_M4", r=4.0)], "head")[0]
    assert nut.grip_method == "outline" and nut.grip_plate == pytest.approx((50.0, 50.0), abs=0.05)
