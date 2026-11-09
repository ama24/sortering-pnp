"""The PLA tip for an earphone's ear tip (printables/eartip.py): the user's sizes, one solid
that prints standing on its shank."""

from __future__ import annotations

import pytest

from sortering_pnp.printables.cups import TIPS, Cup
from sortering_pnp.printables.eartip import EarTip, build, profile, volume_mm3


def test_the_sizes_asked_for():
    t = EarTip()
    assert (t.bore_d, t.groove_d, t.collar_d, t.groove_l) == (4.2, 5.5, 7.5, 2.0)
    m = t.marks()
    assert m["collar"] - m["shoulder"] == pytest.approx(2.0)  # the clearance that traps it


def test_it_fits_the_cups_socket():
    t, c = EarTip(), Cup(TIPS["AS"])
    assert (t.body_d, t.shank_l, t.fix_z, t.fix_d) == (c.body_d, c.shank_l, c.fix_z, c.fix_d)


def test_one_watertight_solid_with_a_bore_through():
    t = EarTip()
    body = build(t)
    assert body.genus() == 1  # a tube: one hole through it, the screws' holes are blind
    holes = 3 * 3.1416 * (t.fix_d / 2) ** 2 * t.fix_depth
    assert body.volume() == pytest.approx(volume_mm3(t) - holes, rel=0.03)
    lo, hi = body.bounding_box()[2], body.bounding_box()[5]
    assert (lo, hi) == pytest.approx((0.0, t.length))


def test_no_overhang_but_the_collars_underside():
    """Going up the outside, the radius only grows at the collar's underside (1 mm, bridged)."""
    p = profile(EarTip())
    out = p[1:8]
    grows = [
        (a, b) for a, b in zip(out, out[1:], strict=False) if b[0] > a[0] + 1e-9 and b[1] == a[1]
    ]
    assert grows == [((5.5 / 2, out[4][1]), (7.5 / 2, out[4][1]))]
    for a, b in zip(out, out[1:], strict=False):  # the rest: vertical, inwards, or 45 deg
        if b[1] > a[1]:
            assert b[0] - a[0] <= 1e-9 or (b[0] - a[0]) <= (b[1] - a[1])


@pytest.mark.parametrize(
    "bad",
    [dict(groove_d=4.8), dict(fix_depth=1.2), dict(length=12.0)],
)
def test_sizes_that_would_not_print_or_leak_are_refused(bad):
    with pytest.raises(ValueError):
        EarTip(**bad).check()
