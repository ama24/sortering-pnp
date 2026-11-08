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


def test_turning_back_reloads_the_nominal_camera_too(machine):
    """Rotate twice (0 -> 90 -> 180): the quarter turn goes off again, and the picture size the
    photos are checked against must follow both times, not only the first."""
    runner = _runner(machine)
    machine.camera.hflip = machine.camera.vflip = machine.camera.turn90 = False
    seen = []
    runner.vision.reload_setup = lambda: seen.append(machine.camera.turn90)
    runner.camera_orient("rotate")
    runner.camera_orient("rotate")
    assert seen == [True, False]
    runner.camera_orient("mirror")  # no quarter turn changes: nothing to reload
    assert seen == [True, False]


IMX708 = {  # Camera Module 3: what Picamera2's camera_controls says (min, max, default)
    "AfMode": (0, 2, 0),
    "AnalogueGain": (1.1228070259094238, 16.0, 1.0),
    "ExposureTime": (26, 220417486, 20000),
    "LensPosition": (0.0, 15.0, 1.0),
}


def test_values_are_kept_inside_what_the_camera_can_do():
    from sortering_pnp.camera import within_limits

    v = within_limits({"AnalogueGain": 1.0, "ExposureTime": 10, "LensPosition": 3.0}, IMX708)
    assert v["AnalogueGain"] == pytest.approx(1.1228070259094238)
    assert v["ExposureTime"] == 26 and isinstance(v["ExposureTime"], int)
    assert v["LensPosition"] == 3.0  # inside: untouched
    assert within_limits({"AnalogueGain": 1.0}, {}) == {"AnalogueGain": 1.0}  # no limits known


def test_a_gain_under_the_sensors_minimum_does_not_fail_every_photo(monkeypatch):
    """The Pi said: settings drifted during capture: AnalogueGain: locked 1.0, camera reports
    1.1228070259094238 (manual exposure from the page, gain 1.0: below the IMX708's minimum)."""
    sets = []

    class Request:
        def make_array(self, name):
            return np.zeros((4, 4, 3), np.uint8)

        def get_metadata(self):  # what the sensor really runs at
            return {
                "ExposureTime": 20000,
                "AnalogueGain": 1.1228070259094238,
                "ColourGains": (2.0, 1.5),
                "LensPosition": 3.0,
            }

        def release(self): ...

    class FakePicam:
        camera_controls = IMX708

        def create_still_configuration(self, **kw):
            return kw

        def configure(self, cfg): ...
        def set_controls(self, c):
            sets.append(c)

        def start(self): ...
        def stop(self): ...
        def close(self): ...
        def capture_metadata(self):
            return Request().get_metadata()

        def capture_request(self):
            return Request()

    monkeypatch.setitem(sys.modules, "picamera2", types.SimpleNamespace(Picamera2=FakePicam))
    monkeypatch.setattr("sortering_pnp.camera.time.sleep", lambda s: None)
    from sortering_pnp.camera import Camera

    locked = {
        "ExposureTime": 20000,
        "AnalogueGain": 1.3,
        "ColourGains": [2.0, 1.5],
        "LensPosition": 3.0,
    }
    adjust = CameraAdjust(exposure="manual", exposure_us=20000, gain=1.0)
    cam = Camera(locked, adjust=adjust)  # verify() at start: passes now
    assert sets[-1]["AnalogueGain"] == pytest.approx(1.1228070259094238)  # asked what it can do
    img, md = cam.grab()  # no "settings drifted during capture"
    assert img.shape == (4, 4, 3)
