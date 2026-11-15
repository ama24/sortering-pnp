"""The floating tool holder (printables/floatholder.py): it fits the rail, the printer and the
motor, the springs have room behind the block, it moves and stops where it should, it prints."""

from __future__ import annotations

import pytest
from manifold3d import Manifold

from sortering_pnp.printables import floatholder as F
from sortering_pnp.printables.floatholder import FloatHolder
from sortering_pnp.printables.toolholder import ToolHolder

P = FloatHolder()
PLATE = F.build_plate(P)
LPART = F.build_l(P)


def _vol(a: Manifold, b: Manifold) -> float:
    return (a ^ b).volume()


def _solid_at(body: Manifold, x: float, y: float, z: float, r: float = 0.3) -> float:
    return _vol(body, Manifold.cube([2 * r, 2 * r, 2 * r]).translate([x - r, y - r, z - r]))


def test_two_solids_with_their_holes():
    # plate: the printer's 2 x M3 (the rest are blind); the L: flange, 4 x M2, 4 x M3, and
    # each upper spring screw's hole through the overhang, in and out of its slot
    for body, genus in ((PLATE, 2), (LPART, 1 + 4 + 4 + 4)):
        assert body.status().name == "NoError"
        assert len(body.decompose()) == 1
        assert body.genus() == genus


def test_the_printers_interface_is_the_tool_holders_with_the_heads_sunk():
    t = ToolHolder()
    assert (P.m3_pitch, P.m3_d, P.standoff_h) == (t.m3_pitch, t.m3_d, t.standoff_h)
    assert P.m3_clamp == t.plate_t  # the same M3 screws reach the standoffs
    for x in P.m3_spots():
        assert _solid_at(PLATE, x, 1.0, P.m3_z) == 0.0
        assert _solid_at(PLATE, x + 2.5, P.m3_clamp + 0.5, P.m3_z, r=0.2) == 0.0  # counterbore
        assert _solid_at(PLATE, x + 2.5, P.m3_clamp - 0.5, P.m3_z, r=0.2) > 0
    assert P.m3_clamp + 3.0 <= P.plate_t  # a socket head (3 mm) sinks below the face
    (_, _, _, tz1), (_, _, lz0, _) = P.shims()
    assert tz1 <= P.m3_z + P.above_room and lz0 >= P.m3_z - P.below_room
    for x0, x1, z0, z1 in P.shims():
        assert _solid_at(PLATE, (x0 + x1) / 2, -P.standoff_h + 0.3, (z0 + z1) / 2) > 0
    for x in P.m3_spots():  # room for the standoffs
        assert _solid_at(PLATE, x, -P.standoff_h / 2, P.m3_z, r=1.0) == 0.0
    # one pad higher up on the back, as deep as the standoffs: the plate does not lever. Its
    # ramp starts at 38 mm above the plate's bottom, its step ends at 45
    z38, z45 = P.plate_z0 + 38.0, P.plate_z0 + 45.0
    for x in (-10.0, 0.0, 10.0):
        assert _solid_at(PLATE, x, -P.standoff_h + 0.3, z45 - 1.0, r=0.2) > 0  # its face
        assert _solid_at(PLATE, x, -0.3, z38 + 0.5, r=0.2) > 0  # the ramp's foot
    assert _solid_at(PLATE, 0.0, -0.3, z38 - 0.5, r=0.2) == 0.0  # below the ramp
    assert _solid_at(PLATE, 0.0, -2.0, z38 + 0.5, r=0.2) == 0.0  # the slope
    assert _solid_at(PLATE, 0.0, -0.3, z45 + 0.5, r=0.2) == 0.0  # above the step
    assert PLATE.bounding_box()[1] == pytest.approx(-P.standoff_h)


def test_the_rail_on_a_strip_as_wide_and_long_as_itself():
    rail = F.rail_box(P)
    assert _vol(rail, PLATE) == pytest.approx(0.0, abs=1e-6)
    assert P.rail_len == 100
    # the strip: under the rail's whole foot, no wider
    for z in (P.rail_z0 + 2, 50.0, P.rail_z1 - 1):
        assert _solid_at(PLATE, 0, P.rail_y0 - 0.3, z, r=0.2) > 0
    assert _solid_at(PLATE, P.rail_w / 2 + 0.5, P.rail_y0 - 0.3, 50.0, r=0.2) == 0.0
    holes = P.rail_holes()
    assert len(holes) == 4 and holes[0] - P.rail_z0 == 12.5 and P.rail_z1 - holes[-1] == 12.5
    assert all(b - a == 25 for a, b in zip(holes, holes[1:], strict=False))
    for z in holes:  # self-tapping pilots, blind
        assert _solid_at(PLATE, 0.0, P.rail_y0 - 1, z, r=0.2) == 0.0
        assert _solid_at(PLATE, 0.0, 0.3, z, r=0.2) > 0
    assert _solid_at(PLATE, 0, P.rail_y0 + 1, P.rail_z0 - 0.5) > 0  # the foot end in the column


def test_the_springs_have_room_behind_the_block():
    # the block was 3 mm off the rail's foot; now a mm round each spring, front and back
    assert P.car_y0 - P.plate_t == pytest.approx(P.spring_od + 2.0)
    assert P.spring_y - P.spring_od / 2 - P.plate_t == pytest.approx(1.0)
    assert P.car_y0 - (P.spring_y + P.spring_od / 2) == pytest.approx(1.0)
    assert (
        P.spring_x - P.spring_od / 2 > P.rail_w / 2 and P.spring_x + P.spring_od / 2 < P.car_w / 2
    )
    for rise in (0.0, *P.travels):
        for s in (-1, 1):
            spring = F.spring_body(P, s * P.spring_x, rise)
            for other in (
                PLATE,
                F.block_box(P, rise),
                LPART.translate([0, 0, rise]),
                F.rail_box(P),
            ):
                assert _vol(spring, other) == pytest.approx(0.0, abs=1e-6)
    assert P.post_z - P.low_post_z == pytest.approx(P.spring_len - P.post_short)
    for s in (-1, 1):
        x = s * P.spring_x
        assert _solid_at(PLATE, x, P.plate_t - 1, P.low_post_z, r=0.2) == 0.0  # lower screw
        assert _solid_at(PLATE, x, 0.2, P.low_post_z, r=0.15) > 0  # blind
        # the upper screw: through the leg and the overhang, across the hook's slot, gripping
        # beyond it towards the printer
        for y in (P.leg_y1 - 1, P.spring_y, P.lid_y0 + 0.5):
            assert _solid_at(LPART, x, y, P.post_z, r=0.2) == 0.0
        assert _solid_at(LPART, x, P.spring_y, P.post_z - 2.5, r=0.3) == 0.0  # slot, open below
        assert _solid_at(LPART, x + 2.0, P.lid_y0 + 0.5, P.post_z, r=0.3) > 0
        # its head sunk in the leg: an M3 x 20 reaches past the slot towards the printer
        assert _solid_at(LPART, x + 2.5, P.leg_y1 - 0.5, P.post_z, r=0.2) == 0.0
        assert _solid_at(LPART, x + 2.5, P.leg_y1 - 1.5, P.post_z, r=0.2) > 0
        tip = P.leg_y1 - P.head_sink - 20.0
        assert P.lid_y0 < tip < P.spring_y - P.slot_w / 2 - 1.5


def test_it_moves_freely_and_stops_on_the_column_and_the_dowels():
    for rise in (0.0, 10.0, max(P.travels)):
        lp = LPART.translate([0, 0, rise])
        for other in (PLATE, F.rail_box(P)):
            assert _vol(lp, other) == pytest.approx(0.0, abs=1e-6)
        block = F.block_box(P, rise)
        assert _vol(block, PLATE) == pytest.approx(0.0, abs=1e-6)
        assert _vol(block, lp) == pytest.approx(0.0, abs=1e-6)
        assert _vol(F.motor_box(P, rise), lp) == pytest.approx(0.0, abs=1e-6)
    assert _vol(F.block_box(P, -0.5), PLATE) > 1.0  # the column
    assert P.rail_z0 < 0 and P.car_l + max(P.travels) < P.rail_z1  # never off the rail
    travels = [t for t, _, _ in P.dowels()]
    assert travels == sorted(travels) and min(travels) <= 4 and max(travels) >= 15
    for t, x, z in P.dowels():
        for s in (-1, 1):
            pin = F.dowel(P, s * x, z)
            assert _solid_at(PLATE, s * x, P.plate_t - 1, z, r=0.2) == 0.0  # its hole
            assert _vol(pin, LPART.translate([0, 0, t - 0.3])) == pytest.approx(0.0, abs=1e-6)
            assert _vol(pin, LPART.translate([0, 0, t + 0.5])) > 1.0
            assert _vol(pin, F.spring_body(P, s * P.spring_x, t)) == pytest.approx(0.0, abs=1e-6)


def test_the_l_takes_the_block_and_the_motor_below_its_screws():
    for x, z in P.car_holes():
        assert _solid_at(LPART, x, P.leg_y0 + 0.5, z, r=0.2) == 0.0
    assert P.leg_t - 0.0 + P.car_thread >= 8.0  # M3 x 8: 3.5 mm into the block
    # the motor's top is under the block's lower screws' heads, with a hex key's room
    low = min(z for _, z in P.car_holes())
    assert P.base_z + P.base_t + P.motor_l + P.key_room <= low - P.m3_head / 2 + 1e-9
    t = ToolHolder()
    assert (P.motor_pitch, P.m2_d, P.base_t, P.m2_clamp) == (
        t.motor_pitch,
        t.m2_d,
        t.base_t,
        t.m2_clamp,
    )
    for x, y in P.m2_spots():
        assert _solid_at(LPART, x, y, P.base_z + P.base_t / 2) == 0.0
    flange = Manifold.cylinder(P.base_t, 7.5, 7.5, 64).translate([0, P.motor_y, P.base_z])
    assert _vol(LPART, flange) == pytest.approx(0.0, abs=1e-6)
    # the overhang reaches back towards the printer, past the block, beside the rail
    assert P.lid_y0 < P.car_y0
    assert _solid_at(LPART, P.spring_x + 2.0, P.lid_y0 + 0.5, P.lid_z1 - 1) > 0
    assert _solid_at(LPART, 0, P.rail_y0 + 1, P.lid_z1 - 1) == 0.0  # the rail goes on up
    # with a mm of play round it, each side and in front
    z = P.lid_z1 - 1
    assert _solid_at(LPART, P.rail_w / 2 + 0.8, P.rail_y0 + 4, z, r=0.15) == 0.0
    assert _solid_at(LPART, 0, P.rail_y1 + 0.8, z, r=0.15) == 0.0
    assert _solid_at(LPART, P.rail_w / 2 + 1.3, P.rail_y0 + 4, z, r=0.15) > 0


def test_each_part_prints_flat_without_supports():
    poses = F.print_poses(P)
    for body in poses.values():
        assert body.bounding_box()[2] == pytest.approx(0.0)
    lp = poses["l"]  # on its side
    assert lp.bounding_box()[5] == pytest.approx(2 * P.leg_half)


def test_the_files():
    files = dict(F.holder_files())
    assert sorted(files) == ["FLOAT_HOLDER.txt", "float_l.stl", "float_plate.stl"]
    notes = files["FLOAT_HOLDER.txt"].decode()
    assert "E-BMN12H" in notes and "self-tapping" in notes and "no supports" in notes
    assert "5.5 x 25.5" in notes and "dowel" in notes
    for t in P.travels:
        assert f"{t:g} mm:" in notes
