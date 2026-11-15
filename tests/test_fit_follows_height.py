"""Camera to printer's points keep the camera height they were seen with: a later change of the
height (no camera calibration) moves them, so the fit and the drawn bins stay right."""

from __future__ import annotations

import numpy as np
import pytest

from sortering_pnp.calib.geometry import nominal_camera
from sortering_pnp.layout import Layout
from sortering_pnp.printer.sim import SimPrinter, SimVision, SimWorld
from sortering_pnp.runner import Runner
from sortering_pnp.transform import BedCalibration, Transform2D


def _runner(machine, height: float) -> Runner:
    lay = Layout.default()
    lay.save(machine.path(machine.paths.layout))
    vision = SimVision(SimWorld(), lambda: lay, Transform2D.identity)
    vision.calibration = None  # as CameraVision without calibration.json
    vision.nominal = nominal_camera(height_mm=height)
    vision.nominal_height_mm = height
    return Runner(machine, SimPrinter(machine, SimWorld()), vision)


def _pairs(seen_at: float, real: float = 325.0, with_height: bool = True) -> list[dict]:
    """Codes truly at `bed` (plate frame = printer frame here), seen by a camera really `real`
    high but taken to be `seen_at` high: their plate mm are scaled about the lens' nadir."""
    nadir = np.array([110.0, 110.0])
    out = []
    for i, (x, y, z) in enumerate([(20, 30, 21), (200, 40, 21), (190, 200, 42), (30, 190, 21)]):
        bed = np.array([x, y], float)
        plate = nadir + (bed - nadir) * (seen_at - z) / (real - z)
        p = {"marker": 100 + i, "plate": plate.tolist(), "bed": bed.tolist(), "z": z}
        if with_height:
            p["cam_height_mm"] = seen_at
        out.append(p)
    return out


def test_points_taken_at_300_fit_again_at_325(machine):
    runner = _runner(machine, 325.0)
    old = BedCalibration.fit(_pairs(300.0))
    assert abs(old.transform.scale - 1.0) > 0.05  # the stale fit: about 8 % off at 325
    old.save(runner.transform_path)
    cal = runner.calibration()
    assert cal is not None
    assert cal.transform.scale == pytest.approx(1.0, abs=1e-3)
    assert max(cal.residuals_mm) < 0.05
    assert all(p["cam_height_mm"] == 325.0 for p in cal.pairs)
    assert BedCalibration.load(runner.transform_path).transform.scale == pytest.approx(
        1.0, abs=1e-3
    )


def test_points_without_their_height_are_left_and_said_once(machine):
    runner = _runner(machine, 325.0)
    BedCalibration.fit(_pairs(300.0, with_height=False)).save(runner.transform_path)
    runner.calibration()
    runner.calibration()
    said = [e for e in runner.console if "before its camera height was kept" in e]
    assert len(said) == 1


def test_a_new_point_keeps_the_height(machine):
    runner = _runner(machine, 325.0)
    assert runner._nominal_height() == 325.0  # noqa: SLF001
    runner.vision.calibration = {"roi": {}}  # calibrated: plate mm do not depend on a height
    assert runner._nominal_height() is None  # noqa: SLF001
