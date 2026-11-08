"""Suction cups (printables/cups.py): the user's rules, and that they print without supports."""

from __future__ import annotations

import math

import pytest

from sortering_pnp.printables.cups import (
    HEAD_COVER,
    MIN_HOLE,
    MIN_LINE,
    SOFT_WALL,
    TIPS,
    Cup,
    _inside,
    _profile,
    all_cups,
    build,
    cup_files,
    holes,
    walls,
)

TWO_LINES = 0.85  # the sieve's webs and the plateau the part rests on


@pytest.mark.parametrize("cup", all_cups(), ids=lambda c: c.name)
def test_one_watertight_solid_with_its_holes(cup):
    body = build(cup)
    assert body.status().name == "NoError"
    # a tube (genus 1); with the sieve the air goes through its holes instead
    assert body.genus() == (len(holes(cup)) if cup.sieve else 1)


@pytest.mark.parametrize("cup", all_cups(), ids=lambda c: c.name)
def test_it_prints_standing_on_the_shank_without_supports(cup):
    poly, _ = _profile(cup)
    for (r0, z0), (r1, z1) in zip(poly, poly[1:] + poly[:1], strict=True):
        if abs(z1 - z0) > 1e-9:
            assert abs(r1 - r0) <= abs(z1 - z0) + 1e-9, ((r0, z0), (r1, z1))  # 45 deg or steeper
    assert min(z for _, z in poly) == 0.0  # flat on the shank's end


@pytest.mark.parametrize("cup", all_cups(), ids=lambda c: c.name)
def test_the_body_is_straight_and_no_channel_is_wider_than_the_tube(cup):
    poly, marks = _profile(cup)
    neck = [r for r, z in poly if z <= marks["neck_top"] + 1e-9]
    assert max(neck) == pytest.approx(cup.body_d / 2)  # Ø7 straight, shank and neck
    assert marks["neck_top"] - cup.shank_l >= cup.min_neck - 1e-9
    assert cup.min_neck == (4.0 if cup.wide else 10.0)
    rb = cup.bore_d / 2
    inside = [(z, a) for z, a, _ in walls(cup) if z <= marks["folds_top"]]  # the inside's radius
    assert max(a for z, a in inside if z <= marks["neck_top"]) <= rb + 1e-9  # the tube
    if cup.wide:  # a chamber, not a channel: never narrower than the tube, wider in the folds
        assert min(a for z, a in inside if z > marks["neck_top"]) >= rb - 1e-9
        assert max(a for _, a in inside) > rb + 1.0
    else:
        assert max(a for _, a in inside) <= rb + 1e-9  # the folds go inwards
    assert cup.fix_depth < (cup.body_d - cup.shank_bore_d) / 2 - 0.5  # blind: no leak


@pytest.mark.parametrize("name", TIPS)
def test_the_head_covers_the_hole_and_the_sieve_lets_more_air_by(name):
    """The screw's head lies on the lip and closes the cup: the hole only has to be smaller
    than the smallest head the tip picks. Wider than the folds' passage would gain nothing."""
    t = TIPS[name]
    c = Cup(t)
    assert t.hole_d <= HEAD_COVER * t.min_head_d
    assert t.hole_d <= 2 * (c.bore_d / 2 - t.amp) + 1e-9  # the folds' narrowest passage
    assert t.hole_d > 2.0 or name in ("AS", "DS")  # bigger than before (Ø1.2-1.4)
    if not t.sieve_d:
        assert name in ("AS", "DS")  # no room for a printable sieve in a Ø3 cup
        with pytest.raises(ValueError):
            holes(Cup(t, True))
        return
    sieve = Cup(t, True)
    spots = holes(sieve)
    assert len(spots) >= 3
    assert all(
        math.hypot(x, y) > sieve.plateau_r + t.sieve_d / 2 for x, y in spots
    )  # not under the part
    assert len(spots) * t.sieve_d**2 >= t.hole_d**2  # at least as much open area
    _, marks = _profile(sieve)
    assert marks["rim"] - marks["dome_top"] == pytest.approx(sieve.recess)  # the lip seals first


def test_the_files_and_notes():
    files = dict(cup_files())
    assert sorted(files) == sorted(
        [f"cup_{n}{w}.stl" for n in TIPS for w in ("", "_wide")]
        + [f"cup_{n}_sieve{w}.stl" for n in ("AM", "DM", "DL") for w in ("", "_wide")]
        + ["CUPS.txt"]
    )
    notes = files["CUPS.txt"].decode()
    assert "TPU 95A" in notes and "M3" in notes and all(n in notes for n in TIPS)
    assert "37 mm" in notes and all(f"{n}_wide" in notes for n in TIPS)


def test_every_cup_is_the_same_length():
    """Swapping cups must not change the tip height: every lip at the same distance."""
    rims = {c.name: _profile(c)[1]["rim"] for c in all_cups()}
    assert Cup(TIPS["AS"]).length == 37.0  # 10 mm shorter than the first ones
    assert all(r == pytest.approx(37.0) for r in rims.values()), rims
    assert len(rims) == 16  # 8 normal, 8 wide
    for c in all_cups():
        assert build(c).bounding_box()[5] == pytest.approx(c.length)


@pytest.mark.parametrize("cup", all_cups(), ids=lambda c: c.name)
def test_a_04_nozzle_prints_every_wall(cup):
    """Across every layer each wall is one line or more (a thinner wall was empty in the
    slicer: the cup above it floated)."""
    for z, a, b in walls(cup):
        width = 2 * b if a < 1e-9 else b - a  # a run from the axis: the dome's top, both sides
        assert width >= MIN_LINE - 1e-9, (z, a, b)


@pytest.mark.parametrize("cup", all_cups(), ids=lambda c: c.name)
def test_the_folds_and_the_cup_are_soft(cup):
    """The printed ones were too stiff (folds 0.9-1.0, cup 0.9-1.0 mm: they did not compress,
    the tip felt like PLA). Above the neck every wall is at most SOFT_WALL across, the folds
    and the lip one line; the floor round the hole is a thin cone, not a solid wedge."""
    t = cup.tip
    assert t.fold_t <= 0.5 and t.rim_t <= 0.5 and _inside(cup)[1] <= SOFT_WALL
    _, marks = _profile(cup)
    z_soft = marks["neck_top"] + (cup.body_d / 2 - (cup.bore_d / 2 + t.fold_t))  # past the chamfer
    for z, a, b in walls(cup):
        if z_soft + 0.05 < z < marks["folds_top"]:
            assert b - a <= t.fold_t + 1e-6, (z, a, b)  # the folds: one line
        if z > marks["folds_top"] and a > 1e-9:  # the floor (no solid wedge) and the cup
            # where a sieve's dome meets the wall, the ring holding it: dome + wall
            most = cup.floor_t + SOFT_WALL if cup.sieve else SOFT_WALL
            assert b - a <= most + 1e-6, (z, a, b)


@pytest.mark.parametrize("cup", [c for c in all_cups() if c.sieve], ids=lambda c: c.name)
def test_a_04_nozzle_prints_the_sieve(cup):
    """Holes big enough not to close up, two lines of TPU between them (0.45 mm webs were
    dropped by the slicer and the holes merged)."""
    d = cup.tip.sieve_d
    assert MIN_HOLE <= d < cup.tip.hole_d and cup.tip.hole_d >= MIN_HOLE
    spots = holes(cup)
    for i, (x0, y0) in enumerate(spots):
        for x1, y1 in spots[i + 1 :]:
            assert math.hypot(x1 - x0, y1 - y0) - d >= cup.web - 1e-9
        rho = math.hypot(x0, y0)
        assert rho - d / 2 >= cup.plateau_r + cup.web / 3 - 1e-9  # the plateau stays whole
        assert rho + d / 2 <= _inside(cup)[0] - cup.web / 3 + 1e-9  # off the cup's wall
    assert 2 * cup.plateau_r >= TWO_LINES  # the top the part rests on: two lines


@pytest.mark.parametrize("cup", [c for c in all_cups() if c.wide], ids=lambda c: c.name)
def test_the_wide_set_has_a_wider_deeper_bellows(cup):
    """The same tip on a wider bellows with deeper folds: softer (a fold's axial rate goes with
    D x t^3 / depth^3), the same walls, holes and length as the normal cup."""
    normal = Cup(cup.tip, cup.sieve)
    (pn, mn), (pw, mw) = _profile(normal), _profile(cup)

    def bellows_out(poly, marks):
        return max(r for r, z in poly if marks["neck_top"] < z < marks["folds_top"])

    assert bellows_out(pw, mw) == pytest.approx(cup.wide_d / 2)
    assert bellows_out(pw, mw) > bellows_out(pn, mn) + 1.0
    assert bellows_out(pw, mw) > cup.body_d / 2  # wider than the neck
    assert cup.wide_amp > 1.5 * cup.tip.amp  # deeper folds
    assert cup.wide_amp <= cup.wide_pitch / 2 + 1e-9  # 45 deg
    assert mw["rim"] == pytest.approx(mn["rim"])
    if cup.sieve:
        assert holes(cup) == holes(normal)

    def tip(poly, marks):  # the cup above the folds
        top = marks["folds_top"]
        return sorted((round(r, 6), round(z - top, 6)) for r, z in poly if z > top + 1e-9)

    assert tip(pw, mw) == tip(pn, mn)
