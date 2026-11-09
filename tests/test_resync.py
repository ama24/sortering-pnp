"""Resync: the camera decides where the grid lies, which bins stand where and which way round,
and which one is the plate (the biggest, unless chosen by hand)."""

from __future__ import annotations

import pytest

from sortering_pnp.layout import Bin, Layout
from sortering_pnp.printer.sim import SimPrinter, SimVision, SimWorld
from sortering_pnp.runner import Runner
from sortering_pnp.transform import Transform2D


def truth() -> Layout:
    """A 4x4 tray, a turned 1x2 bin and small bins, on a grid lying at an odd spot."""
    lay = Layout(origin=[23.4, 11.7], cols=6, rows=5)
    lay.bins = [
        Bin(marker=230, x=2, y=0, w=4, d=4),  # the 4x4 tray
        Bin(marker=140, x=0, y=0, w=2, d=1, rot=90),  # 1x2, lying across, shelf to the left
        Bin(marker=100, x=0, y=1),
        Bin(marker=101, x=5, y=4, rot=180),  # shelf to the front
        Bin(marker=102, x=0, y=4, rot=270),
    ]
    return lay


def seen_from(lay: Layout) -> list[tuple[int, tuple[float, float], float]]:
    return [(b.marker, lay.bin_centre(b), float(b.rot)) for b in lay.bins]


def test_resync_finds_the_grid_bins_turns_and_the_plate():
    real = truth()
    lay = Layout.default()  # what the program believed: grid at (5, 5), 3x3 tray 220
    report = lay.resync(seen_from(real))
    assert lay.origin == pytest.approx([23.4 + 0.0, 11.7])  # min cells are 0: same origin
    assert (lay.cols, lay.rows) == (6, 5)
    for b in real.bins:
        got = lay.bin_by_marker(b.marker)
        assert (got.x, got.y, got.w, got.d, got.rot) == (b.x, b.y, b.w, b.d, b.rot), b.marker
    assert lay.work_marker == 230 and lay.bin_by_marker(230).role == "work"  # the biggest
    assert lay.bin_by_marker(220) is None and 220 in report["removed"]  # the old tray is gone
    assert sorted(report["found"]) == [100, 101, 102, 140, 230]
    assert lay.problems() == []


def test_a_plate_chosen_by_hand_is_kept_while_it_is_there():
    real = truth()
    lay = Layout.default()
    lay.resync(seen_from(real))
    lay.set_work(140, auto=False)  # the user wants the 1x2 bin as the plate
    assert lay.bin_by_marker(230).role == "wild" and lay.bin_by_marker(140).role == "work"
    lay.resync(seen_from(real))
    assert lay.work_marker == 140 and not lay.work_auto
    real.bins = [b for b in real.bins if b.marker != 140]  # taken off the bed
    lay.resync(seen_from(real))
    assert lay.work_marker == 230 and lay.work_auto  # back to the biggest


def test_bins_taken_away_keep_their_rules():
    real = truth()
    lay = Layout()
    lay.resync(seen_from(real))
    b = lay.bin_by_marker(100)
    b.role, b.holds = "sort", ["DIN912_M3"]
    gone = Layout.from_dict(real.to_dict())
    gone.bins = [x for x in gone.bins if x.marker != 100]
    lay.resync(seen_from(gone))
    assert lay.bin_by_marker(100) is None and [a.marker for a in lay.away] == [100]
    lay.resync(seen_from(real))  # it is back
    back = lay.bin_by_marker(100)
    assert back.role == "sort" and back.holds == ["DIN912_M3"] and lay.away == []


@pytest.mark.parametrize(
    ("rot", "side"), [(0, "back"), (90, "left"), (180, "front"), (270, "right")]
)
def test_the_plate_area_leaves_out_the_shelf(rot, side):
    lay = Layout(origin=[0.0, 0.0], cols=3, rows=3)
    lay.bins = [Bin(marker=220, x=0, y=0, w=3, d=3, rot=rot)]
    lay.set_work(220, auto=True)
    x0, y0, x1, y1 = lay.work_rect()
    inner = 0.25 + 1.2
    full = (inner, inner, 126 - inner, 126 - inner)
    cut = {"back": (3, -14.0), "left": (0, 14.0), "front": (1, 14.0), "right": (2, -14.0)}[side]
    expected = list(full)
    expected[cut[0]] += cut[1]
    assert (x0, y0, x1, y1) == pytest.approx(tuple(expected))


def test_resync_through_the_camera(machine):
    real = truth()
    lay = Layout.default()
    lay.save(machine.path(machine.paths.layout))
    world = SimWorld()
    vision = SimVision(world, lambda: real, Transform2D.identity)
    runner = Runner(machine, SimPrinter(machine, world), vision)
    runner.setup_home()
    res = runner.scan_bins()
    assert res["problems"] == [] and res["work"] == 230
    saved = runner.layout()
    assert saved.origin == pytest.approx(real.origin, abs=0.05)
    assert {(b.marker, b.x, b.y, b.rot) for b in saved.bins} == {
        (b.marker, b.x, b.y, b.rot) for b in real.bins
    }
    assert runner.setup.is_done("layout")


@pytest.mark.parametrize("yaw", [0.0, 90.0, 180.0, -90.0, 30.0, -135.0, 7.0])
@pytest.mark.parametrize("marker", [100, 140, 50])  # 1x1 shelf, 1x2 shelf, 1x1 corner post
def test_parts_go_to_the_middle_of_a_bin_loose_on_the_bed(machine, yaw, marker):
    """Bins put anywhere on the bed, turned any way: the drop point is where the bin really
    stands (from its code's place and direction), not the centre of the grid cell it falls in,
    which was up to half a cell (21 mm) off."""
    import math

    from sortering_pnp.binspec import marker_offset_for, size_for_marker
    from sortering_pnp.markers import MarkerPose
    from sortering_pnp.vision import Shot

    runner = Runner(
        machine,
        SimPrinter(machine, SimWorld()),
        SimVision(SimWorld(), Layout, Transform2D.identity),
    )
    lay = Layout()
    size = size_for_marker(marker)
    centre = (117.3, 64.9)  # off any 42 mm grid
    ox, oy = marker_offset_for(marker, size.w, size.d)
    c, s = math.cos(math.radians(yaw)), math.sin(math.radians(yaw))
    code = (centre[0] + c * ox - s * oy, centre[1] + s * ox + c * oy)
    others = [MarkerPose(101, (20.0, 20.0), 90.0), MarkerPose(102, (230.0, 200.0), 90.0)]
    shot = Shot("t", [], [MarkerPose(marker, code, 90.0 + yaw), *others])
    lay.resync(runner._seen_bins(lay, shot, Transform2D.identity()))
    b = lay.bin_by_marker(marker)
    assert lay.drop_centre(b) == pytest.approx(centre, abs=0.02)
    assert b.rot == (round(yaw / 90) % 4) * 90  # the cells still follow its turn
    # kept through a save, as the page sends it back
    again = Layout.from_dict(lay.to_dict())
    assert again.drop_centre(again.bin_by_marker(marker)) == pytest.approx(centre, abs=0.02)


def test_a_bin_moved_on_the_page_drops_in_its_new_cells():
    lay = Layout(origin=[0.0, 0.0], cols=5, rows=5)
    lay.resync([(100, (55.0, 70.0), 0.0), (101, (10.0, 10.0), 0.0)])
    b = lay.bin_by_marker(100)
    assert lay.drop_centre(b) == (55.0, 70.0)
    b.x += 2  # dragged two cells to the right: the old measurement is not used
    assert lay.drop_centre(b) == lay.bin_centre(b)
    old = Layout.from_dict({**lay.to_dict()})
    old.bins[0].seen = None  # a layout from before: the cells
    assert old.drop_centre(old.bins[0]) == old.bin_centre(old.bins[0])
