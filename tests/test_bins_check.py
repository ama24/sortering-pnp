"""The bins check (binscheck.py): Resync and the start-up check run the model on the whole board,
give each detection to its bin, drop those on the codes and set what each bin collects."""

from __future__ import annotations

import numpy as np

from sortering_pnp import binscheck
from sortering_pnp.layout import Layout
from sortering_pnp.markers import MarkerPose
from sortering_pnp.parts import Part
from sortering_pnp.printer.sim import SimPart, SimPrinter, SimVision, SimWorld
from sortering_pnp.runner import Runner
from sortering_pnp.transform import Transform2D
from sortering_pnp.vision import Shot


def _lay() -> Layout:
    lay = Layout.default()
    lay.bins = [b for b in lay.bins if b.marker in (103, 104, 105)] + [lay.work_bin()]
    for b in lay.bins:
        if b.role != "work":
            b.role = "wild"
    return lay


def _screw(cls: str, x: float, y: float) -> SimPart:
    return SimPart(cls, x, y, 0.0, None, (7.0, 7.0), 3.2)


def _runner(machine, lay, world, out=None):  # noqa: ANN001, ANN202
    lay.save(machine.path(machine.paths.layout))
    vision = SimVision(world, lambda: lay, Transform2D.identity, out)
    runner = Runner(machine, SimPrinter(machine, world), vision)
    runner.setup_home()
    return runner, vision


def test_resync_looks_into_every_bin(machine, tmp_path):
    lay = _lay()
    world = SimWorld(seed=1)
    b104, b103 = lay.bin_by_marker(104), lay.bin_by_marker(103)
    cx, cy = lay.bin_centre(b104)
    world.parts += [_screw("DIN912_M3", cx - 6, cy - 6), _screw("DIN912_M3", cx + 6, cy - 6)]
    mx, my = lay.marker_centre(b103)
    world.parts.append(_screw("UNKNOWN", mx, my))  # the code itself, seen as a part
    world.parts[-1].cls = "DIN933_M5"  # ... or as any class
    runner, vision = _runner(machine, lay, world, tmp_path / "runs")
    runner.claims[105] = "ISO7380_M4x8"  # from an earlier session: empty now
    res = runner.scan_bins()
    assert vision.painted[-1] is True  # the bins view: only the bins' floors
    assert runner.claims == {104: "DIN912_M3"} and runner.bin_counts[104] == 2
    assert "1 with parts" in res["bins_check"] and "2 empty" in res["bins_check"]
    assert "on codes" not in res["bins_check"]  # the codes are painted before the model looks
    view = runner.snapshot()["view"]
    assert view.endswith("_bins.jpg") and (tmp_path / "runs" / view).is_file()


def test_sorting_photos_stay_painted(machine):
    lay = _lay()
    runner, vision = _runner(machine, lay, SimWorld(seed=1))
    runner.take_shot(runner.layout(), runner.transform())
    assert vision.painted[-1] is True


def test_a_bin_with_rules_keeps_them(machine):
    lay = _lay()
    b = lay.bin_by_marker(104)
    b.role, b.holds = "sort", ["DIN934*"]
    world = SimWorld(seed=1)
    cx, cy = lay.bin_centre(b)
    world.parts.append(_screw("DIN912_M3", cx, cy - 6))
    runner, _ = _runner(machine, lay, world)
    runner.scan_bins()
    assert 104 not in runner.claims and runner.layout().bin_by_marker(104).holds == ["DIN934*"]
    assert any("its rules take DIN934*" in line for line in runner.console)


def _part(cls: str, xy: tuple[float, float]) -> Part:
    p = Part(1, cls, 0.9, xy, 0.0, np.zeros((0, 2)), 4.0, None, True, False, False)
    p.bed_xy = xy
    return p


def test_the_code_is_kept_out_where_the_photo_shows_it():
    """A code stands on the rim: seen from above it appears shifted outwards on the floor plane
    the parts are measured on. What the model finds there is not counted either."""
    lay = _lay()
    b = lay.bin_by_marker(104)
    mx, my = lay.marker_centre(b)
    cx, cy = lay.bin_centre(b)
    seen_at = (mx - 13.0, my - 13.0)  # where the photo shows the code (parallax)
    k = 4.0  # view pixels per mm, plate = bed
    H = [[k, 0.0, 0.0], [0.0, k, 0.0], [0.0, 0.0, 1.0]]
    mk = MarkerPose(104, (mx, my), 90.0, view_px=(seen_at[0] * k, seen_at[1] * k))
    shot = Shot("x", [], [mk], view_h=H)
    spots = binscheck.code_spots(shot, Transform2D.identity())
    assert np.allclose(spots[104], seen_at)
    ghost, real = _part("UNKNOWN", seen_at), _part("DIN912_M3", (cx + 8, cy - 8))
    per_bin, dropped = binscheck.sort_out(lay, [ghost, real], 0.5, spots)
    assert per_bin[104] == [real] and dropped == [ghost]


def test_code_labels_sit_on_the_codes(machine, tmp_path):
    """The page draws each code's label at its centre in the photo (view_px), not at its plate
    X/Y through the floor-plane homography (that lands beside a code on a rim)."""
    lay = _lay()
    runner, _ = _runner(machine, lay, SimWorld(seed=1), tmp_path / "runs")
    runner.take_shot(runner.layout(), runner.transform(), paint=False)
    snap = runner.snapshot()
    H = np.asarray(snap["view_h"])
    for mk in snap["markers"]:
        b = lay.bin_by_marker(mk["marker"])
        x, y = lay.marker_centre(b)
        u, v, w = H @ np.array([x, y, 1.0])
        assert np.allclose(mk["view_px"], (u / w, v / w), atol=0.2)
