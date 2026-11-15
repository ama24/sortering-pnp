"""Without a camera calibration the model's picture can be moved over the photo (Camera
Calibration, Skip for now: the arrows); only the cut moves, never the camera."""

from __future__ import annotations

import copy

import numpy as np
import pytest

from sortering_pnp.calib.geometry import nominal_camera
from sortering_pnp.layout import Layout
from sortering_pnp.measure.infer import nominal_roi
from sortering_pnp.printer.sim import SimPrinter, SimVision, SimWorld
from sortering_pnp.runner import Runner
from sortering_pnp.transform import Transform2D


def test_the_cut_moves_right_and_down_by_the_mm_asked():
    cam = nominal_camera(height_mm=325.0)
    px_per_mm = cam.K[0, 0] / 325.0
    a, b = nominal_roi(cam), nominal_roi(cam, (10.0, 5.0))
    assert (b["w"], b["h"]) == (a["w"], a["h"])  # the same size: the model's scale is kept
    assert b["x0"] - a["x0"] == pytest.approx(10 * px_per_mm, abs=32)  # right (32 px steps)
    assert b["y0"] - a["y0"] == pytest.approx(5 * px_per_mm, abs=32)  # down
    # the camera is unchanged: a plate point is still seen at the same pixel
    p = np.array([[50.0, 60.0, 0.0]])
    assert np.allclose(cam.project(p), nominal_camera(height_mm=325.0).project(p))


def test_the_arrows_are_checked_and_kept(machine):
    lay = Layout.default()
    lay.save(machine.path(machine.paths.layout))
    vision = SimVision(SimWorld(), lambda: lay, Transform2D.identity)
    runner = Runner(machine, SimPrinter(machine, SimWorld()), vision)
    with pytest.raises(ValueError):
        runner.camera_crop_shift(200.0, 0.0)
    st = runner.camera_crop_shift(12.0, -4.0)
    assert st["crop_shift_mm"] == [12.0, -4.0]
    fresh = copy.deepcopy(machine)  # after a restart
    fresh.camera.crop_shift_mm = [0.0, 0.0]
    Runner.apply_saved(fresh)
    assert fresh.camera.crop_shift_mm == [12.0, -4.0]
