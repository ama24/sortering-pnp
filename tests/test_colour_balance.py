"""White balance on a blue TPU plate, and photos that keep their colours when the sun comes out
(camera.centre_balance, camera.follow_factors, CameraVision._follow)."""

from __future__ import annotations

import argparse
import json
import threading
import types

import numpy as np

from sortering_pnp import camlock
from sortering_pnp.camera import (
    apply_factors,
    area_pixels,
    centre_balance,
    follow_factors,
    grey_reference,
    is_noir,
    linear,
    oriented,
    plate_colour,
    turn_image,
)

H, W = 360, 640
PLATE = (slice(60, 300), slice(160, 480))  # the tray floor: a blue TPU sheet
PLATE_PX = np.array([[160, 60], [480, 60], [480, 300], [160, 300]], float)
LED = np.array([1.0, 1.0, 1.0])  # linear B, G, R of the light
SUN = LED * np.array([0.85, 1.0, 1.3])  # warmer and redder (low sun through a window)


def _reflectance(screws: bool = False) -> np.ndarray:
    rng = np.random.default_rng(1)
    s = np.empty((H, W, 3))
    s[:] = (0.12, 0.12, 0.12)  # the bed
    s[50:310, 150:490] = (0.45, 0.45, 0.45)  # the tray's grey walls
    s[PLATE] = (0.45, 0.20, 0.06)  # blue TPU (B, G, R)
    s[:, :110] = (0.80, 0.80, 0.80)  # a white bin
    s[20:60, 520:620] = (0.08, 0.10, 0.55)  # a red bin
    if screws:
        for y, x in ((120, 220), (150, 300), (220, 400), (260, 250)):
            s[y : y + 12, x : x + 40] = (0.55, 0.55, 0.55)  # zinc-plated screws: grey
    return s * (1 + rng.normal(0, 0.01, s.shape))


def shoot(
    light: np.ndarray, exposure_us: float, gains: tuple[float, float], screws: bool = False
) -> np.ndarray:
    r, b = gains
    lin = _reflectance(screws) * light * exposure_us / 20000 * np.array([b, 1.0, r]) * 0.25
    return (np.clip(lin, 0, 1) ** (1 / 2.2) * 255).astype(np.uint8)


def _balance(light: np.ndarray, exposure: int = 20000, gains=(1.6, 1.4)):
    for _ in range(10):
        exposure, gains, steady = centre_balance(shoot(light, exposure, gains), exposure, gains)
        if steady:
            break
    return exposure, gains


def _ratios(img: np.ndarray, where) -> tuple[float, float]:
    b, g, r = np.median(linear(img[where].reshape(-1, 3)), axis=0)
    return r / g, b / g


def test_the_blue_plate_is_not_made_grey():
    """Grey world on the plate (the old way) would multiply red by about (0.20/0.06): red."""
    exposure, gains = _balance(LED)
    img = shoot(LED, exposure, gains)
    r, b = _ratios(img, (slice(None), slice(0, 100)))
    assert abs(r - 1) < 0.05 and abs(b - 1) < 0.05  # the white bin comes out white
    r, b = _ratios(img, PLATE)
    assert r < 0.35 and b > 2.0  # and the plate stays blue (0.06 / 0.20 red)


def test_nothing_grey_keeps_the_gains():
    px = np.tile(np.array([[200, 120, 40]], np.uint8), (5000, 1))  # only the blue plate
    assert grey_reference(px) is None
    img = np.broadcast_to(np.array([200, 120, 40], np.uint8), (H, W, 3)).copy()
    _, gains, _ = centre_balance(img, 20000, (1.7, 1.5))
    assert gains == (1.7, 1.5)


def test_the_sun_after_the_lock_is_taken_back_out():
    exposure, gains = _balance(LED)
    ref, where = plate_colour(shoot(LED, exposure, gains), PLATE_PX)
    assert where == "plate"
    sunny = shoot(SUN, exposure, gains, screws=True)
    assert _ratios(sunny, PLATE)[0] > 1.2 * ref[2]  # the red cast
    k = follow_factors(sunny, ref, PLATE_PX)
    assert k is not None and k[1] < 0.85 and k[0] > 1.1
    fixed = apply_factors(sunny, *k)
    now, _ = plate_colour(fixed, PLATE_PX)
    assert np.allclose(now, ref, rtol=0.03)  # the plate as at the lock
    r, b = _ratios(fixed, (slice(150, 162), slice(300, 340)))  # a screw: grey again
    assert abs(r - 1) < 0.06 and abs(b - 1) < 0.06


def test_a_small_change_leaves_the_photo_alone():
    exposure, gains = _balance(LED)
    img = shoot(LED, exposure, gains)
    ref, _ = plate_colour(img, PLATE_PX)
    assert follow_factors(img, ref, PLATE_PX) == (1.0, 1.0)
    assert apply_factors(img, 1.0, 1.0) is img


def test_no_plate_in_view_is_not_corrected():
    exposure, gains = _balance(LED)
    ref, _ = plate_colour(shoot(LED, exposure, gains), PLATE_PX)
    red_bin = np.broadcast_to(np.array([60, 70, 200], np.uint8), (H, W, 3)).copy()
    assert follow_factors(red_bin, ref) is None  # far beyond a change of light


def test_the_plate_area_not_the_centre_is_measured():
    img = np.zeros((H, W, 3), np.uint8)
    img[:] = (10, 200, 10)  # green in the middle
    img[:100, :200] = (200, 10, 10)  # the plate, top left
    px, where = area_pixels(img, np.array([[0, 0], [199, 0], [199, 99], [0, 99]], float))
    assert where == "plate" and (px[:, 0] == 200).all()
    px, where = area_pixels(img)
    assert where == "centre" and (px[:, 1] == 200).all()
    px, where = area_pixels(img, np.array([[-50, -50], [-40, -50], [-40, -40]], float))
    assert where == "centre"  # outside the picture: the centre instead


def test_the_lock_turns_its_frames_like_the_photos():
    img = np.arange(4 * 6 * 3, dtype=np.uint8).reshape(4, 6, 3)
    for hf in (False, True):
        for vf in (False, True):
            for t in (False, True):
                want = img[:, ::-1] if hf else img
                want = want[::-1] if vf else want
                assert np.array_equal(oriented(img, hf, vf, t), turn_image(want, t))


def test_noir_is_recognised():
    assert is_noir("imx708_noir") and is_noir("imx708_wide_noir")
    assert not is_noir("imx708") and not is_noir("")


class FakePicam:
    """A camera over the blue-plate scene, under `light`."""

    sensor_modes = [{"size": (4608, 2592), "bit_depth": 10}]
    camera_controls = {"AeMeteringMode": None, "AfMode": None}
    camera_properties = {"Model": "imx708_noir"}

    def __init__(self, light: np.ndarray) -> None:
        self.light = light
        # what the camera's own AWB left: about right, the sun's red not quite taken out
        self.c = {"ExposureTime": 20000, "AnalogueGain": 1.0, "ColourGains": (1.0, 1.0)}

    def create_still_configuration(self, **kw):
        return kw

    def configure(self, cfg): ...
    def start(self): ...
    def stop(self): ...

    def set_controls(self, c):
        self.c |= {k: v for k, v in c.items() if k in ("ExposureTime", "ColourGains")}

    def capture_metadata(self):
        return dict(self.c, LensPosition=3.3)

    def capture_array(self, stream):
        # the camera's own picture is upside down (hflip + vflip in the program)
        img = shoot(self.light, self.c["ExposureTime"], tuple(self.c["ColourGains"]))
        return np.ascontiguousarray(img[::-1, ::-1])


def test_the_lock_keeps_the_plate_colour_and_the_bin_white(tmp_path, monkeypatch, caplog):
    monkeypatch.setattr(camlock.time, "sleep", lambda s: None)
    controls = types.SimpleNamespace(
        AfModeEnum=types.SimpleNamespace(Manual=0),
        AeMeteringModeEnum=types.SimpleNamespace(CentreWeighted=0, Spot=1),
    )
    out = tmp_path / "camera_settings.json"
    args = argparse.Namespace(
        out=str(out),
        settle=0.0,
        distance_mm=300.0,
        exposure_us=None,
        hflip=True,
        vflip=True,
        turn90=False,
        area_px=PLATE_PX.tolist(),
    )
    assert camlock._lock(FakePicam(SUN), controls, args) == 0  # noqa: SLF001
    s = json.loads(out.read_text())
    assert s["centre_balance"]["area"] == "plate" and s["plate_colour"]["area"] == "plate"
    b, g, r = s["plate_colour"]["bgr"]
    assert g == 1.0 and b > 2.0 and r < 0.35  # blue, measured in the program's pixels
    img = shoot(SUN, s["ExposureTime"], tuple(s["ColourGains"]))
    r, b = _ratios(img, (slice(None), slice(0, 100)))
    assert abs(r - 1) < 0.05 and abs(b - 1) < 0.05  # locked in the sun: still no red cast
    assert s["model"] == "imx708_noir" and "infrared" in caplog.text


def _vision(follow: bool = True, source: str = "overview"):
    from sortering_pnp.vision import CameraVision

    exposure, gains = _balance(LED)
    ref, _ = plate_colour(shoot(LED, exposure, gains))
    settings = {"plate_colour": {"bgr": ref.tolist(), "area": "centre"}}
    frame = shoot(SUN, exposure, gains)
    cam = types.SimpleNamespace(locked_settings=settings, grab=lambda: (frame.copy(), {}))
    v = CameraVision.__new__(CameraVision)
    v._cam_lock = threading.Lock()  # noqa: SLF001
    v._camera = lambda: cam  # noqa: SLF001
    v.m = types.SimpleNamespace(camera=types.SimpleNamespace(colour_follow=follow, source=source))
    v.calibration, v.plate_area_mm = None, None
    return v, frame, ref


def test_every_photo_follows_the_plate_colour():
    v, frame, ref = _vision()
    img, _ = v.grab()
    now, where = plate_colour(img)
    assert where == "centre" and np.allclose(now, ref, rtol=0.03)
    for kwargs in ({"follow": False}, {"source": "head"}):
        v, frame, _ = _vision(**kwargs)
        assert np.array_equal(v.grab()[0], frame)  # off, or head-camera tiles: as taken


def test_the_plate_area_comes_from_the_layout_else_the_calibration():
    from sortering_pnp.vision import CameraVision

    v = CameraVision.__new__(CameraVision)
    v.plate_area_mm, v.calibration = None, None
    assert v.plate_area_px() is None  # no calibration: the centre part
    v.calibration = {"working_area_mm": {"origin": [10, 20], "size": [100, 50]}}
    v.cam_full = types.SimpleNamespace(project=lambda X: np.asarray(X)[:, :2] * 2)
    assert v.plate_area_px().tolist() == [[20, 40], [220, 40], [220, 140], [20, 140]]
    v.plate_area_mm = np.array([[0, 0], [5, 0], [5, 5]], float)  # the tray floor, from the layout
    assert v.plate_area_px().tolist() == [[0, 0], [10, 0], [10, 10]]
