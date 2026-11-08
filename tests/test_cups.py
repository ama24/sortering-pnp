"""Suction cups (printables/cups.py): the user's rules, and that they print without supports."""

from __future__ import annotations

import math

import pytest

from sortering_pnp.printables.cups import (
    MIN_HOLE,
    MIN_LINE,
    MIN_WALL,
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

M2_CORE = 1.57  # the smallest screw's core: no hole may let it in


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
    assert marks["neck_top"] - cup.shank_l >= 20.0
    passage = [r for r, z in poly if z <= marks["folds_top"] and r < cup.body_d / 2 - 0.5]
    assert max(passage) <= cup.bore_d / 2 + 1e-9  # the folds go inwards
    assert cup.fix_depth < (cup.body_d - cup.shank_bore_d) / 2 - 0.5  # blind: no leak


@pytest.mark.parametrize("name", TIPS)
def test_no_screw_goes_through_and_the_sieve_lets_more_air_by(name):
    t = TIPS[name]
    assert t.hole_d < M2_CORE and t.sieve_d < M2_CORE
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
        [f"cup_{n}.stl" for n in TIPS]
        + [f"cup_{n}_sieve.stl" for n in ("AM", "DM", "DL")]
        + ["CUPS.txt"]
    )
    notes = files["CUPS.txt"].decode()
    assert "TPU 95A" in notes and "M3" in notes and all(n in notes for n in TIPS)


def test_every_cup_is_the_same_length():
    """Swapping cups must not change the tip height: every lip at the same distance."""
    rims = {c.name: _profile(c)[1]["rim"] for c in all_cups()}
    assert all(r == pytest.approx(Cup(TIPS["AS"]).length) for r in rims.values()), rims
    for c in all_cups():
        assert build(c).bounding_box()[5] == pytest.approx(c.length)


@pytest.mark.parametrize("cup", all_cups(), ids=lambda c: c.name)
def test_a_04_nozzle_prints_every_wall(cup):
    """Across every layer each wall is two lines or more; only the D skirt thins towards its
    edge, to one line. (A thinner wall was empty in the slicer: the cup above it floated.)"""
    _, marks = _profile(cup)
    ci = _inside(cup)[0]  # the skirt starts at the cup's inside
    for z, a, b in walls(cup):
        width = 2 * b if a < 1e-9 else b - a  # a run from the axis: the dome's top, both sides
        if cup.tip.style == "D" and z >= marks["floor"] and a >= ci - 1e-9:
            assert width >= MIN_LINE - 1e-9, (z, a, b)  # the skirt
        else:
            assert width >= MIN_WALL - 1e-9, (z, a, b)


@pytest.mark.parametrize("cup", [c for c in all_cups() if c.sieve], ids=lambda c: c.name)
def test_a_04_nozzle_prints_the_sieve(cup):
    """Holes big enough not to close up, two lines of TPU between them (thinner webs were
    dropped by the slicer and the holes merged)."""
    d = cup.tip.sieve_d
    assert MIN_HOLE <= d < M2_CORE and cup.tip.hole_d >= MIN_HOLE
    spots = holes(cup)
    for i, (x0, y0) in enumerate(spots):
        for x1, y1 in spots[i + 1 :]:
            assert math.hypot(x1 - x0, y1 - y0) - d >= cup.web - 1e-9
        rho = math.hypot(x0, y0)
        assert rho - d / 2 >= cup.plateau_r + cup.web / 3 - 1e-9  # the plateau stays whole
        assert rho + d / 2 <= _inside(cup)[0] - cup.web / 3 + 1e-9  # off the cup's wall
    assert 2 * cup.plateau_r >= MIN_WALL  # the top the part rests on: two lines
