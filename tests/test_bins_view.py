"""The bins view (trayview.py): when it looks into the bins, the model sees only the floors of
the bins whose codes are in the photo, each found from its code alone, the codes painted."""

from __future__ import annotations

import numpy as np
import pytest

from sortering_pnp import binspec
from sortering_pnp.layout import Bin, Layout
from sortering_pnp.printer.sim import SimPart, SimPrinter, SimVision, SimWorld
from sortering_pnp.runner import Runner
from sortering_pnp.startup import floor_rect
from sortering_pnp.transform import Transform2D
from sortering_pnp.trayview import bin_floor, bins_area


@pytest.mark.parametrize("rot", [0, 90, 180, 270])
@pytest.mark.parametrize("marker", [100, 140, 66, 220])  # 1x1, 1x2, 1x2 corner, 3x3 tray
def test_a_floor_from_its_code_alone_is_where_the_layout_has_it(marker, rot):
    size = binspec.size_for_marker(marker)
    w, d = (size.d, size.w) if rot in (90, 270) else (size.w, size.d)
    lay = Layout.default()
    b = Bin(marker=marker, x=1, y=1, w=w, d=d, rot=rot, height_u=size.height_u)
    lay.bins = [b]
    floor, keep_out = bin_floor(marker, lay.marker_centre(b), 90.0 + rot)
    x0, y0, x1, y1 = floor_rect(lay, b)
    assert floor.min(axis=0) == pytest.approx((x0, y0), abs=0.1)
    assert floor.max(axis=0) == pytest.approx((x1, y1), abs=0.1)
    centre = np.asarray(lay.marker_centre(b))
    assert keep_out.mean(axis=0) == pytest.approx(centre)  # the code's square on the code


def test_no_bins_no_area_and_a_calibration_code_is_no_bin():
    class M:
        marker, centre, up_deg = 7, (10.0, 10.0), 90.0  # below 50: the calibration board's

    assert bins_area([]) is None and bins_area([M()]) is None


def _runner(machine, lay: Layout, world: SimWorld) -> tuple[Runner, SimVision]:
    lay.save(machine.path(machine.paths.layout))
    vision = SimVision(world, lambda: lay, Transform2D.identity)
    runner = Runner(machine, SimPrinter(machine, world), vision)
    runner.printer.gcode("G28")
    return runner, vision


def _nut(x: float, y: float) -> SimPart:
    return SimPart("DIN934_M4", x, y, 0.0, None, (7.0, 7.0), 3.2)


def test_the_model_sees_the_floors_not_the_codes_nor_between_the_bins(machine):
    lay = Layout.default()
    lay.bins = [b for b in lay.bins if b.marker in (103, 104)] + [lay.work_bin()]
    world = SimWorld(seed=1)
    b104 = lay.bin_by_marker(104)
    cx, cy = lay.bin_centre(b104)
    mx, my = lay.marker_centre(lay.bin_by_marker(103))
    gx = (lay.cells_rect(3, 0, 1, 1)[2] + lay.cells_rect(4, 0, 1, 1)[0]) / 2  # the walls between
    world.parts = [_nut(cx, cy - 8), _nut(mx, my), _nut(gx, cy)]
    runner, vision = _runner(machine, lay, world)
    shot = runner.take_shot(lay, Transform2D.identity(), area="bins", paint="bins")
    assert vision.painted[-1]
    assert [tuple(np.round(p.bed_xy, 1)) for p in shot.parts] == [(cx, cy - 8)]
    machine.camera.bins_margin_mm = 2.0  # more of the edge, short of the gap (2.45 mm away)
    shot = runner.take_shot(lay, Transform2D.identity(), area="bins", paint="bins")
    assert len(shot.parts) == 1


def test_bins_view_off_shows_the_whole_photo(machine):
    lay = Layout.default()
    world = SimWorld(seed=1)
    mx, my = lay.marker_centre(lay.bin_by_marker(103))
    world.parts = [_nut(mx, my)]
    runner, vision = _runner(machine, lay, world)
    machine.camera.bins_mask = False
    shot = runner.take_shot(lay, Transform2D.identity(), area="bins", paint="bins")
    assert not vision.painted[-1] and len(shot.parts) == 1


def test_calibrate_tab_try_save_and_keep_over_a_restart(machine):
    import copy

    lay = Layout.default()
    world = SimWorld(seed=1)
    runner, vision = _runner(machine, lay, world)
    st = runner.binsview_preview(1.5)
    assert st["margin_mm"] == 1.5 and st["changed"] and machine.camera.bins_margin_mm == 0.0
    st = runner.binsview_save(1.5, False)
    assert not st["changed"] and not st["enabled"] and machine.camera.bins_margin_mm == 1.5
    fresh = copy.deepcopy(machine)
    fresh.camera.bins_margin_mm, fresh.camera.bins_mask = 0.0, True
    again = Runner(fresh, SimPrinter(fresh, SimWorld()), vision)
    assert again.m.camera.bins_margin_mm == 1.5 and again.m.camera.bins_mask is False


def test_snippets_without_a_camera_is_still_a_picture(machine):
    runner, _ = _runner(machine, Layout.default(), SimWorld(seed=1))
    jpg = runner.bins_snippets()
    assert jpg[:2] == b"\xff\xd8"  # a JPEG saying why there is nothing to cut out


def test_the_real_camera_paints_all_but_the_floor_of_the_bin_whose_code_it_reads(machine, tmp_path):
    """CameraVision.analyse with the bins view: the codes are read first, then the model gets
    the photo (same size) with only that bin's floor left, the code itself painted."""
    import cv2

    from sortering_pnp.markers import marker_bits
    from sortering_pnp.trayview import BinsView
    from test_vision_no_model import bare_vision

    v = bare_vision(machine, tmp_path)
    w, h = v.nominal.image_size
    img = np.full((h, w), 230, np.uint8)
    cell = 12
    code = np.where(np.kron(marker_bits(120), np.ones((cell, cell))) > 0, 0, 255).astype(np.uint8)
    y0, x0 = h // 2 - code.shape[0] // 2, w // 2 - code.shape[1] // 2
    img[y0 : y0 + code.shape[0], x0 : x0 + code.shape[1]] = code
    photo = tmp_path / "p.png"
    cv2.imwrite(str(photo), img)
    machine.camera.mask_colour = "#FF0000"  # painted: pure red, unlike anything here

    seen = {}

    class Model:  # records what the model is given
        def analyse(self, scene, path):
            seen["image"], seen["scene"] = scene.image.copy(), scene
            return {"objects": [], "timing_s": {"total": 0.0}}

    v.analyzer, v._head_r, v._shapes = Model(), {}, {}
    shot = v.analyse(photo, "p", lambda mid: 0.0, BinsView())
    assert [mk.marker for mk in shot.markers] == [120]
    given, scene = seen["image"], seen["scene"]
    roi = scene.roi or {"x0": 0, "y0": 0}
    assert given.shape[:2] == (roi.get("h", h), roi.get("w", w))  # the ROI's size: its scale
    red = (given[..., 2] == 255) & (given[..., 0] == 0) & (given[..., 1] == 0)
    mk = shot.markers[0]
    floor, _ = bin_floor(120, mk.centre, mk.up_deg)
    cx, cy = floor.mean(axis=0)
    fx, fy = (int(round(c)) for c in scene.cam.project(np.array([[cx, cy, 0.0]]))[0])
    assert not red[fy, fx]  # the floor's middle: as photographed
    assert red[h // 2 - roi["y0"], w // 2 - roi["x0"]]  # the code: painted
    assert red[5, 5] and red[-5, -5]  # far outside the bin: painted
