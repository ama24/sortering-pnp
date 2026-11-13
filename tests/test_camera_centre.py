"""Exposure, white balance and focus from the centre of the picture (the tray), not the whole of
it: a white bin at the side neither brightens nor tints the photos (camera.centre_balance)."""

from __future__ import annotations

import argparse
import json
import sys
import types

import numpy as np
import pytest

from sortering_pnp import camlock
from sortering_pnp.camera import centre, centre_balance, centre_window

H, W = 360, 640


def _scene() -> np.ndarray:
    """Linear BGR radiance: a grey tray under a warm light, a white bin along the left side."""
    rng = np.random.default_rng(0)
    s = np.empty((H, W, 3))
    s[:] = (0.20, 0.22, 0.30)  # grey, but the light is warm: more red than blue
    s[:, :120] = (0.85, 0.95, 1.30)  # the white bin, same light: by far the brightest
    return s + rng.normal(0, 0.004, s.shape)


SCENE = _scene()


def shoot(exposure_us: float, gains: tuple[float, float]) -> np.ndarray:
    r, b = gains
    lin = SCENE * exposure_us / 20000 * np.array([b, 1.0, r])
    return (np.clip(lin, 0, 1) ** (1 / 2.2) * 255).astype(np.uint8)


def _neutral_and_unclipped(img: np.ndarray) -> None:
    b, g, r = centre(img).reshape(-1, 3).mean(axis=0)
    assert abs(r - g) < 4 and abs(b - g) < 4  # the tray comes out grey
    assert 95 < g < 125  # at about the target brightness
    assert (img.max(axis=2) >= 250).mean() < 0.001  # the white bin is not burnt out


def test_the_centre_balance_settles_grey_and_keeps_the_white_bin():
    exposure, gains = 40000, (1.0, 1.0)  # what the camera's own AE/AWB left: too bright, tinted
    assert (shoot(exposure, gains).max(axis=2) >= 254).mean() > 0.1  # the bin burnt out
    for _ in range(6):
        exposure, gains, steady = centre_balance(shoot(exposure, gains), exposure, gains)
        if steady:
            break
    assert steady
    _neutral_and_unclipped(shoot(exposure, gains))


def test_a_dark_tray_does_not_burn_out_the_white_bin():
    global SCENE
    old = SCENE
    SCENE = SCENE.copy()
    SCENE[:, 120:] *= 0.15  # a black TPU sheet
    try:
        exposure, gains = 20000, (1.5, 1.5)
        for _ in range(8):
            exposure, gains, steady = centre_balance(shoot(exposure, gains), exposure, gains)
        img = shoot(exposure, gains)
        assert (img.max(axis=2) >= 250).mean() < 0.001  # the bin decides how far it may go
    finally:
        SCENE = old


def test_the_autofocus_window_is_the_centre():
    assert centre_window((0, 0, 4608, 2592)) == (1382, 778, 1843, 1036)
    assert centre_window((16, 8, 1000, 500), 0.5) == (266, 133, 500, 250)


class FakePicam:
    """A camera over SCENE: what it shoots follows the exposure and the colour gains it is set."""

    sensor_modes = [{"size": (4608, 2592), "bit_depth": 10}]
    camera_controls = {"AeMeteringMode": None, "AfMode": None}

    def __init__(self) -> None:
        self.c = {"ExposureTime": 40000, "AnalogueGain": 1.0, "ColourGains": (1.0, 1.0)}
        self.sent: list[dict] = []

    def create_still_configuration(self, **kw):
        return kw

    def configure(self, cfg): ...
    def start(self): ...
    def stop(self): ...

    def set_controls(self, c):
        self.sent.append(dict(c))
        self.c |= {k: v for k, v in c.items() if k in ("ExposureTime", "ColourGains")}
        self.c |= {k: v for k, v in c.items() if k == "LensPosition"}

    def capture_metadata(self):
        return dict(self.c, LensPosition=self.c.get("LensPosition", 3.3))

    def capture_array(self, stream):
        return shoot(self.c["ExposureTime"], tuple(self.c["ColourGains"]))


def test_the_lock_uses_the_centre(tmp_path, monkeypatch):
    monkeypatch.setattr(camlock.time, "sleep", lambda s: None)
    controls = types.SimpleNamespace(
        AfModeEnum=types.SimpleNamespace(Manual=0),
        AeMeteringModeEnum=types.SimpleNamespace(Spot=1),
    )
    cam = FakePicam()
    out = tmp_path / "camera_settings.json"
    args = argparse.Namespace(out=str(out), settle=0.0, distance_mm=300.0, exposure_us=None)
    assert camlock._lock(cam, controls, args) == 0  # noqa: SLF001
    assert cam.sent[0]["AeMeteringMode"] == 1  # spot metering while AE settles
    s = json.loads(out.read_text())
    assert 1 <= s["centre_balance"]["steps"] <= 5
    _neutral_and_unclipped(shoot(s["ExposureTime"], tuple(s["ColourGains"])))


def test_continuous_autofocus_looks_at_the_centre(monkeypatch):
    sent = []

    class Picam:
        camera_controls = {"AfMode": None, "AfWindows": None}
        camera_properties = {"ScalerCropMaximum": (0, 0, 4608, 2592)}

        def create_still_configuration(self, **kw):
            return kw

        def configure(self, cfg): ...
        def set_controls(self, c):
            sent.append(dict(c))

        def start(self): ...
        def stop(self): ...
        def close(self): ...

    monkeypatch.setitem(sys.modules, "picamera2", types.SimpleNamespace(Picamera2=Picam))
    monkeypatch.setattr("sortering_pnp.camera.time.sleep", lambda s: None)
    from sortering_pnp.camera import Camera

    Camera(None)  # not locked yet: continuous autofocus
    assert sent[0]["AfMode"] == 2 and sent[0]["AfMetering"] == 1
    assert sent[0]["AfWindows"] == [centre_window((0, 0, 4608, 2592))]


@pytest.mark.parametrize("fraction", [0.4, 1.0])
def test_centre_keeps_the_middle(fraction):
    img = np.arange(100 * 200).reshape(100, 200)
    c = centre(img, fraction)
    assert c.shape == (int(100 * fraction), int(200 * fraction))
    assert c[c.shape[0] // 2, c.shape[1] // 2] == img[50, 100]
