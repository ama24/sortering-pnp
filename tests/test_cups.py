"""Suction cups (printables/cups.py): the user's rules, and that they print without supports."""

from __future__ import annotations

import math

import pytest

from sortering_pnp.printables.cups import TIPS, Cup, _profile, all_cups, build, cup_files, holes

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
        [f"cup_{n}{s}.stl" for n in TIPS for s in ("", "_sieve")] + ["CUPS.txt"]
    )
    notes = files["CUPS.txt"].decode()
    assert "TPU 95A" in notes and "M3" in notes and all(n in notes for n in TIPS)
