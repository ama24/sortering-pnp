"""The picture's orientation in 90 degree steps (Rotate / Mirror) and the camera adjustments
(focus, white balance, exposure, image) from the Camera Calibration tab."""

from __future__ import annotations

import copy
import itertools
import sys
import types

import numpy as np
import pytest

from sortering_pnp.camera import (
    controls_for,
    merged_settings,
    mirrored,
    orientation,
    rotated,
    rpicam_adjust,
    rpicam_still,
    turn_image,
)
from sortering_pnp.config import CameraAdjust
from sortering_pnp.layout import Layout
from sortering_pnp.printer.sim import SimPrinter, SimVision, SimWorld
from sortering_pnp.runner import Runner
from sortering_pnp.transform import Transform2D
from sortering_pnp.vision import CameraVision

RAW = np.arange(12).reshape(3, 4)  # no symmetry: every orientation looks different
STATES = list(itertools.product([False, True], repeat=3))


def picture(h: bool, v: bool, q: bool) -> np.ndarray:
    """What the page shows: the camera's flips, then the quarter turn in software."""
    img = RAW[:, ::-1] if h else RAW
    img = img[::-1, :] if v else img
    return turn_image(img, q)


@pytest.mark.parametrize("state", STATES)
def test_rotate_turns_the_picture_90_degrees_clockwise(state):
    after = picture(*rotated(*state))
    assert np.array_equal(after, np.rot90(picture(*state), k=-1))
    o0, o1 = orientation(*state), orientation(*rotated(*state))
    assert o1["mirror"] == o0["mirror"] and o1["turn"] == (o0["turn"] + 90) % 360


@pytest.mark.parametrize("state", STATES)
def test_mirror_flips_the_picture_left_right(state):
    assert np.array_equal(picture(*mirrored(*state)), picture(*state)[:, ::-1])
    o0, o1 = orientation(*state), orientation(*mirrored(*state))
    assert o1["mirror"] != o0["mirror"] and o1["turn"] == (-o0["turn"]) % 360


def test_four_turns_come_back():
    s = (False, False, False)
    seen = []
    for _ in range(4):
        seen.append(orientation(*s)["turn"])
        s = rotated(*s)
    assert seen == [0, 90, 180, 270] and s == (False, False, False)
    assert turn_image(np.zeros((2592, 4608)), True).shape == (4608, 2592)


def test_controls_auto_and_manual():
    auto = controls_for(None, CameraAdjust())
    assert auto["AeEnable"] and auto["AwbEnable"] and auto["AfMode"] == 2
    a = CameraAdjust(focus="manual", lens_position=3.3, white_balance="manual", exposure="manual")
    c = controls_for(None, a)
    assert c["AfMode"] == 0 and c["LensPosition"] == 3.3
    assert not c["AwbEnable"] and c["ColourGains"] == (1.8, 1.6)
    assert not c["AeEnable"] and c["ExposureTime"] == 20000
    assert c["Contrast"] == 1.0 and c["Sharpness"] == 1.0
    assert "AfMode" not in controls_for(None, a, has_af=False)


def test_manual_adjustments_go_over_the_lock():
    locked = {"ExposureTime": 9000, "AnalogueGain": 2.0, "ColourGains": [2, 1.5], "LensPosition": 3}
    s = merged_settings(locked, CameraAdjust(focus="manual", lens_position=4.0))
    assert s["LensPosition"] == 4.0 and s["ExposureTime"] == 9000  # the rest stays locked
    c = controls_for(locked, CameraAdjust(exposure="manual", exposure_us=5000, gain=1.5))
    assert c["ExposureTime"] == 5000 and c["AnalogueGain"] == 1.5 and not c["AeEnable"]
    assert c["ColourGains"] == (2.0, 1.5)


def test_rpicam_gets_the_adjustments():
    a = CameraAdjust(focus="manual", lens_position=2.5, white_balance="manual", contrast=1.2)
    opts = rpicam_adjust(a)
    assert opts[:4] == ["--autofocus-mode", "manual", "--lens-position", "2.5"]
    assert "--awbgains" in opts and "1.8,1.6" in opts and "--contrast" in opts
    assert "--shutter" not in opts  # exposure stays automatic
    assert rpicam_still(True, False, a)[-len(opts) :] == opts


def test_the_camera_applies_them(monkeypatch):
    sets = []

    class FakePicam:
        camera_controls = {"AfMode": None}

        def create_still_configuration(self, **kw):
            return kw

        def configure(self, cfg): ...
        def set_controls(self, c):
            sets.append(c)

        def start(self): ...
        def stop(self): ...
        def close(self): ...
        def autofocus_cycle(self):
            return True

        def capture_metadata(self):
            return {"LensPosition": 3.1, "ExposureTime": 1000}

    monkeypatch.setitem(sys.modules, "picamera2", types.SimpleNamespace(Picamera2=FakePicam))
    monkeypatch.setattr("sortering_pnp.camera.time.sleep", lambda s: None)
    from sortering_pnp.camera import Camera

    cam = Camera(None, adjust=CameraAdjust(sharpness=2.0))
    assert sets[-1]["Sharpness"] == 2.0 and sets[-1]["AfMode"] == 2
    cam.set_adjust(CameraAdjust(focus="manual", lens_position=5.0))
    assert sets[-1]["AfMode"] == 0 and sets[-1]["LensPosition"] == 5.0
    assert cam.focus_once() == 3.1
    assert cam.now() == {"ExposureTime": 1000, "LensPosition": 3.1}


def _runner(machine):
    lay = Layout.default()
    lay.save(machine.path(machine.paths.layout))
    world = SimWorld(seed=1)
    return Runner(
        machine, SimPrinter(machine, world), SimVision(world, lambda: lay, Transform2D.identity)
    )


def test_rotate_and_mirror_from_the_page(machine):
    runner = _runner(machine)
    runner.setup.mark("camera")
    machine.camera.hflip = machine.camera.vflip = False
    st = runner.camera_orient("rotate")
    assert st["orientation"] == {"turn": 90, "mirror": False} and machine.camera.turn90
    assert not runner.setup.is_done("camera")
    st = runner.camera_orient("mirror")  # the mirror is told as done first: 90 -> 270
    assert st["orientation"] == {"turn": 270, "mirror": True}
    with pytest.raises(ValueError):
        runner.camera_orient("upside")
    fresh = copy.deepcopy(machine)  # after a restart
    fresh.camera.turn90 = False
    again = Runner(fresh, SimPrinter(fresh, SimWorld()), runner.vision)
    assert again.m.camera.turn90 and again.camera_state()["orientation"]["mirror"]


def test_adjust_from_the_page_is_kept_and_clamped(machine):
    runner = _runner(machine)
    out = runner.camera_adjust({"focus": "manual", "lens_position": 99, "contrast": 1.3})
    assert out["adjust"]["lens_position"] == 15.0 and out["adjust"]["contrast"] == 1.3
    assert out["now"] == {}  # the simulator: accepted, nothing to report
    with pytest.raises(ValueError):
        runner.camera_adjust({"focus": "sharp"})
    with pytest.raises(ValueError):
        runner.camera_focus()  # no autofocus in the simulator
    fresh = copy.deepcopy(machine)
    fresh.camera.adjust = CameraAdjust()
    again = Runner(fresh, SimPrinter(fresh, SimWorld()), runner.vision)
    assert again.m.camera.adjust.focus == "manual" and again.m.camera.adjust.contrast == 1.3


def test_the_nominal_camera_is_taller_after_a_quarter_turn(machine, tmp_path):
    v = object.__new__(CameraVision)
    v.m, v.out, v.store = machine, tmp_path, None
    v.use_models = lambda choice: None
    v.reload_setup()
    w, h = v.nominal.image_size
    machine.camera.turn90 = True
    v.reload_setup()
    assert tuple(v.nominal.image_size) == (h, w)
