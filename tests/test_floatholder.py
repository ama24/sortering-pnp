"""The floating tool holder (printables/floatholder.py): it fits the rail, the printer and the
motor, it moves and stops where it should, every spring fits, it prints."""

from __future__ import annotations

import pytest
from manifold3d import Manifold

from sortering_pnp.printables import floatholder as F
from sortering_pnp.printables.floatholder import SPRINGS, FloatHolder
from sortering_pnp.printables.toolholder import ToolHolder

P = FloatHolder()
PLATE = F.build_plate(P)
CAR = F.build_carriage(P)
STOP = F.build_stop(P)


def _vol(a: Manifold, b: Manifold) -> float:
    return (a ^ b).volume()


def _solid_at(body: Manifold, x: float, y: float, z: float, r: float = 0.3) -> float:
    return _vol(body, Manifold.cube([2 * r, 2 * r, 2 * r]).translate([x - r, y - r, z - r]))


def test_three_solids_with_their_holes():
    for body, genus in ((PLATE, 2 + 2 * len(SPRINGS)), (CAR, 1 + 4 + 4 + 2), (STOP, 2)):
        assert body.status().name == "NoError"
        assert len(body.decompose()) == 1
        assert body.genus() == genus


def test_the_printers_interface_is_the_tool_holders_with_the_heads_sunk():
    t = ToolHolder()
    assert (P.m3_pitch, P.m3_d, P.standoff_h) == (t.m3_pitch, t.m3_d, t.standoff_h)
    assert P.m3_clamp == t.plate_t  # the same M3 screws reach the standoffs
    for x in P.m3_spots():
        assert _solid_at(PLATE, x, 1.0, P.m3_z) == 0.0  # through
        # a socket head (Ø5.5, 3 mm) sits in the counterbore, below the rail's foot
        assert _solid_at(PLATE, x + 2.5, P.m3_clamp + 0.5, P.m3_z, r=0.2) == 0.0
        assert _solid_at(PLATE, x + 2.5, P.m3_clamp - 0.5, P.m3_z, r=0.2) > 0
        assert P.m3_clamp + 3.0 < P.rail_y0
    # the shims rest on the head inside its face, a lever as on the tool holder
    (_, _, _, tz1), (_, _, lz0, _) = P.shims()
    assert tz1 <= P.m3_z + P.above_room and lz0 >= P.m3_z - P.below_room
    for x0, x1, z0, z1 in P.shims():
        assert _solid_at(PLATE, (x0 + x1) / 2, -P.standoff_h + 0.3, (z0 + z1) / 2) > 0
    for x in P.m3_spots():  # room for the standoffs
        assert _solid_at(PLATE, x, -P.standoff_h / 2, P.m3_z, r=1.0) == 0.0


def test_the_rail_lies_in_its_groove_and_notch_with_four_holes():
    rail = F.rail_box(P)
    assert _vol(rail, PLATE) == pytest.approx(0.0, abs=1e-6)
    assert P.rail_len == 100 and P.rail_z1 <= PLATE.bounding_box()[5]
    holes = P.rail_holes()
    assert len(holes) == 4 and holes[0] - P.rail_z0 == 12.5 and P.rail_z1 - holes[-1] == 12.5
    assert all(b - a == 25 for a, b in zip(holes, holes[1:], strict=False))
    for z in holes:  # pilot holes for M3 self-tapping, blind (nothing pokes out behind)
        assert _solid_at(PLATE, 0.0, P.plate_t - 1, z, r=0.2) == 0.0
        assert _solid_at(PLATE, 0.0, 0.3, z, r=0.2) > 0
    # the groove holds it straight: plate on both sides of the rail's foot
    assert _solid_at(PLATE, P.rail_w / 2 + 0.5, P.plate_t - 0.3, 80, r=0.2) > 0
    # the foot end stands in the ledge's notch
    assert _solid_at(PLATE, 0, P.rail_y0 + 1, P.rail_z0 - 0.5) > 0


def test_it_moves_freely_its_whole_travel_and_no_further():
    for rise in (0.0, P.travel / 2, P.travel):
        car = CAR.translate([0, 0, rise])
        for other in (PLATE, STOP, F.rail_box(P)):
            assert _vol(car, other) == pytest.approx(0.0, abs=1e-6)
        block = F.block_box(P, rise)
        assert _vol(block, PLATE) == pytest.approx(0.0, abs=1e-6)
        assert _vol(block, STOP) == pytest.approx(0.0, abs=1e-6)
        assert _vol(F.motor_box(P, rise), car) == pytest.approx(0.0, abs=1e-6)
    assert _vol(CAR.translate([0, 0, P.travel + 0.5]), STOP) > 1.0  # the stop block
    assert _vol(CAR.translate([0, 0, -0.5]), PLATE) > 1.0  # the ledge
    # the block stays on the rail, and does not touch the ledge (the 90° piece does)
    assert P.rail_z0 < 0 and P.car_l + P.travel < P.rail_z1
    assert _vol(F.block_box(P, -P.ledge_play + 0.1), PLATE) == pytest.approx(0.0, abs=1e-6)


def test_the_90_degree_piece_takes_the_block_and_the_motor():
    assert P.leg_y0 == pytest.approx(P.rail_y0 + P.car_h)  # on the block's top
    for x, z in P.car_holes():
        assert _solid_at(CAR, x, P.leg_y0 + 0.3, z, r=0.2) == 0.0
        r = P.car_head_d / 2 - 0.4
        assert _solid_at(CAR, x + r, P.leg_y1 - 0.5, z, r=0.2) == 0.0  # counterbore
        assert _solid_at(CAR, x + r, P.leg_y0 + 0.5, z, r=0.2) > 0
    assert 6 - P.car_clamp <= P.car_thread  # M3 x 6 does not bottom out
    # the motor seat is the tool holder's
    t = ToolHolder()
    assert (P.motor_pitch, P.m2_d, P.base_t, P.m2_clamp) == (
        t.motor_pitch,
        t.m2_d,
        t.base_t,
        t.m2_clamp,
    )
    for x, y in P.m2_spots():
        assert _solid_at(CAR, x, y, P.base_t / 2) == 0.0
    flange = Manifold.cylinder(P.base_t, 7.5, 7.5, 64).translate([0, P.motor_y, 0])
    assert _vol(CAR, flange) == pytest.approx(0.0, abs=1e-6)
    # the tool's axis is clear of the ledge below
    assert P.motor_y - (P.flange_d + P.flange_play) / 2 > PLATE.bounding_box()[4]


@pytest.mark.parametrize(("od", "length"), SPRINGS)
def test_each_spring_fits_with_a_little_stretch(od, length):
    for x in (-P.spring_x, P.spring_x):
        assert _solid_at(PLATE, x, P.plate_t - 1, P.plate_post_z(length), r=0.2) == 0.0
        for rise in (0.0, P.travel):
            spring = F.spring_body(P, od, length, x, rise)
            for other in (PLATE, CAR.translate([0, 0, rise]), F.block_box(P, rise)):
                assert _vol(spring, other) == pytest.approx(0.0, abs=1e-6)
    assert P.spring_y - od / 2 >= P.plate_t  # off the plate's face
    assert P.post_z - P.plate_post_z(length) == pytest.approx(length - P.post_short)
    for x in (-P.spring_x, P.spring_x):  # the moving posts
        assert _solid_at(CAR, x, P.leg_y0 + 1, P.post_z, r=0.2) == 0.0
    # an M3 x 18 from the ear's front ends just short of the plate: a hook can't slip off
    tip = P.leg_y1 - 18
    assert P.plate_t < tip < P.spring_y - od / 2 + 1


def test_each_part_prints_flat_without_supports():
    poses = F.print_poses(P)
    for body in poses.values():
        assert body.bounding_box()[2] == pytest.approx(0.0)
    stop = poses["stop"]  # on its back: the holes stand up
    assert stop.bounding_box()[5] == pytest.approx(P.stop_t)


def test_the_files():
    files = dict(F.holder_files())
    assert sorted(files) == [
        "FLOAT_HOLDER.txt",
        "float_carriage.stl",
        "float_plate.stl",
        "float_stop.stl",
    ]
    notes = files["FLOAT_HOLDER.txt"].decode()
    assert "E-BMN12H" in notes and "self-tapping" in notes and "no supports" in notes
    for od, length in SPRINGS:
        assert f"{od:g} x {length:g}" in notes
