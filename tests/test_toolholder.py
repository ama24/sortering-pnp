"""The tool holder (printables/toolholder.py): the user's sizes, the motor fits, it prints."""

from __future__ import annotations

import pytest
from manifold3d import Manifold

from sortering_pnp.printables.toolholder import ToolHolder, build, holder_files, motor_box

P = ToolHolder()
BODY = build(P)


def _solid_at(x: float, y: float, z: float, r: float = 0.3) -> float:
    return (BODY ^ Manifold.cube([2 * r, 2 * r, 2 * r]).translate([x - r, y - r, z - r])).volume()


def test_one_solid_with_its_seven_holes():
    assert BODY.status().name == "NoError"
    assert len(BODY.decompose()) == 1
    assert BODY.genus() == 7  # the flange, 4 x M2.5, 2 x M3


def test_the_printers_interface_two_m3_14_apart_above_the_motor():
    assert P.m3_pitch == 14.0
    xs = P.m3_spots()
    assert xs[1] - xs[0] == pytest.approx(14.0)
    for x in xs:  # through the printer plate
        assert _solid_at(x, P.plate_t / 2, P.m3_z) == 0.0
    # the screws sit higher than the motor is long, a hex key's way over its top
    assert P.m3_z - P.m3_head_d / 2 >= P.motor_top + 3.0
    assert P.m3_z - P.base_t > P.motor_l


def test_the_motor_fits_inside_the_l_its_flange_through_the_plate():
    assert (BODY ^ motor_box(P)).volume() == pytest.approx(0.0, abs=1e-6)
    flange = Manifold.cylinder(P.base_t, 7.5, 7.5, 64).translate([0, P.motor_y, 0])  # Ø15
    assert P.flange_d == 15.0 and (BODY ^ flange).volume() == pytest.approx(0.0, abs=1e-6)
    for x, y in P.m25_spots():  # 4 x M2.5 on a 16 mm square, through the motor plate
        assert _solid_at(x, y, P.base_t / 2) == 0.0
    sq = P.m25_spots()
    assert {abs(x) for x, _ in sq} == {8.0} and max(y for _, y in sq) - min(y for _, y in sq) == 16


def test_the_plates_are_at_90_degrees_with_a_rib_each_side():
    lo = BODY.bounding_box()
    assert lo[2] == pytest.approx(0.0) and lo[1] == pytest.approx(0.0)  # flat on the motor plate
    # the printer plate stands at y = 0..plate_t up to the top; the motor plate along y at z = 0
    assert _solid_at(0, P.plate_t / 2, P.height - 1) > 0
    assert _solid_at(0, P.base_d - 1, P.base_t / 2) > 0
    # the ribs: beside the motor, halfway up between the plates
    z = P.base_t + P.rib_h / 3
    y = P.plate_t + 2.0
    for x in (P.half_w - P.rib_t / 2, -P.half_w + P.rib_t / 2):
        assert _solid_at(x, y, z) > 0
    assert _solid_at(0, y + 4, z) == 0.0  # the motor's place stays free


def test_the_files():
    files = dict(holder_files())
    assert sorted(files) == ["TOOL_HOLDER.txt", "tool_holder.stl"]
    notes = files["TOOL_HOLDER.txt"].decode()
    assert "M3" in notes and "M2.5" in notes and "no supports" in notes
