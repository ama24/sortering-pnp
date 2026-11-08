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
    assert BODY.genus() == 7  # the flange, 4 x M2, 2 x M3


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
    for x, y in P.m2_spots():  # 4 x M2 on a 16 mm square, through the motor plate
        assert _solid_at(x, y, P.base_t / 2) == 0.0
    sq = P.m2_spots()
    assert {abs(x) for x, _ in sq} == {8.0} and max(y for _, y in sq) - min(y for _, y in sq) == 16


def test_the_plates_are_at_90_degrees_with_a_rib_each_side():
    lo = BODY.bounding_box()
    assert lo[2] == pytest.approx(0.0)  # flat on the motor plate
    assert lo[1] == pytest.approx(-P.standoff_h)  # only the shims reach behind the plate
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
    assert "M3" in notes and "M2 x 5" in notes and "no supports" in notes and "shim" in notes


def test_m2_x_5_screws_reach_the_motor_and_their_heads_sit_flush():
    """Only M2 x 5 at hand: the counterbores leave m2_clamp of plate under the heads, so 2.5 mm
    of thread goes into the motor (a 4 mm plate left 1 mm)."""
    assert P.m2_screw_l == 5.0 and P.m2_d < 2.5  # M2, not M2.5
    assert P.m2_thread == pytest.approx(2.5)
    cb = P.base_t - P.m2_clamp
    assert cb >= 2.0  # an M2 socket head (2 mm) stays inside the plate
    for x, y in P.m2_spots():
        r = P.m2_head_d / 2 - 0.3
        assert _solid_at(x + r, y, cb / 2, r=0.2) == 0.0  # the counterbore, from below
        assert _solid_at(x + r, y, cb + P.m2_clamp / 2, r=0.2) > 0  # the plate under the head
    # round the counterbores the motor plate stays whole (the flange hole is not cut into)
    for x, y in P.m2_spots():
        d = ((x**2 + (y - P.motor_y) ** 2) ** 0.5) - P.m2_head_d / 2
        assert d - (P.flange_d + P.flange_play) / 2 >= 1.0


def test_the_shims_make_a_lever_on_the_printers_head():
    """The plate's back is standoff_h off the head (the standoffs); a shim at the top and one
    low down touch the head, inside the room the head's face gives (7.4 mm above the screws,
    15 mm below), clear of the standoffs."""
    s = P.standoff_h
    assert s == 4.5
    assert P.height - P.m3_z <= P.above_room  # the plate ends below the head's top
    (tx0, tx1, tz0, tz1), (lx0, lx1, lz0, lz1) = P.shims()
    assert tz1 <= P.m3_z + P.above_room and lz0 >= P.m3_z - P.below_room
    for x0, x1, z0, z1 in P.shims():  # each face is on the head's plane, y = -standoff_h
        xm, zm = (x0 + x1) / 2, (z0 + z1) / 2
        assert _solid_at(xm, -s + 0.3, zm) > 0
        assert _solid_at(xm, -s - 0.3, zm) == 0.0
    # the standoffs (at the screws, standoff_d across) have room: nothing behind the plate there
    for x in P.m3_spots():
        for dz in (-P.standoff_d / 2 + 0.2, 0.0, P.standoff_d / 2 - 0.2):
            assert _solid_at(x, -s / 2, P.m3_z + dz, r=0.5) == 0.0
    # a lever: the shims are well away from the screws on both sides
    assert tz1 - P.m3_z >= 6.5 and P.m3_z - lz0 >= 14.0
    # the shims print upright: their undersides are 45 deg, not flat
    for x0, x1, z0, _ in P.shims():
        xm = (x0 + x1) / 2
        assert _solid_at(xm, -0.5, z0 - 0.5 - 0.3) > 0  # near the plate it starts lower
        assert _solid_at(xm, -s + 0.3, z0 - 1.0) == 0.0  # at the face it does not
