"""The Pi Camera 3 with locked settings, and helpers to check and save its frames.

Picamera2 is only imported when a Camera is opened, so everything else here is testable on the PC.
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any

import numpy as np

log = logging.getLogger("sortering_pnp.camera")

FULL_RES = (4608, 2592)
LIVE_SIZE = (1280, 720)  # the live picture on the page (same view, scaled: 16:9 like FULL_RES)
# tolerances when checking that the camera really runs with the locked settings
TOLERANCE = {"ExposureTime": 0.01, "AnalogueGain": 0.02, "ColourGains": 0.01, "LensPosition": 0.02}


CENTRE_FRACTION = 0.4  # focus, exposure and white balance are measured on this centre part
CENTRE_TARGET = 110.0  # the centre's median brightness (0..255) the lock aims for
HIGHLIGHT_MAX = 235.0  # ... but the brightest 0.5 % of the whole picture stays below this
GAIN_RANGE = (0.5, 8.0)  # colour gains are kept inside this
EXPOSURE_RANGE_US = (50, 200_000)
GAMMA = 2.2  # the frames are gamma-encoded: colour sums are made in linear light (power 2.2)
# a "grey" pixel: red/green and blue/green within this of 1 (natural log: 0.3 = about 35 %).
# The TPU plate is blue or green: far outside, so it never decides the white balance.
GREY_TOLERANCE = 0.3
GREY_TOLERANCE_WIDE = 0.5  # tried when nothing is that grey (a strong cast at the start)
MIN_PIXELS = 200  # fewer usable pixels than this: nothing is changed
SAMPLE_PIXELS = 250_000  # measured on about this many pixels (every n-th row and column)
# each photo: the plate's colour is brought back to its colour at the lock (sun, clouds), by
# at most this factor per channel (more: not a change of light, e.g. no plate in view)
FOLLOW_RANGE = (0.6, 1.6)
FOLLOW_DEADBAND = 0.02  # smaller differences are left alone (no colour jitter between photos)


def centre(img: np.ndarray, fraction: float = CENTRE_FRACTION) -> np.ndarray:
    """The middle `fraction` of a picture (of its width and of its height)."""
    h, w = img.shape[:2]
    ch, cw = max(int(h * fraction), 1), max(int(w * fraction), 1)
    return img[(h - ch) // 2 : (h - ch) // 2 + ch, (w - cw) // 2 : (w - cw) // 2 + cw]


def centre_window(crop_max: tuple[int, int, int, int], fraction: float = CENTRE_FRACTION) -> tuple:
    """The centre part as an autofocus window, in ScalerCropMaximum's pixels (x, y, w, h)."""
    x, y, w, h = (int(v) for v in crop_max)
    cw, ch = int(w * fraction), int(h * fraction)
    return (x + (w - cw) // 2, y + (h - ch) // 2, cw, ch)


def _step(img: np.ndarray) -> int:
    h, w = img.shape[:2]
    return max(1, int(np.sqrt(h * w / SAMPLE_PIXELS)))


def sample(img: np.ndarray) -> np.ndarray:
    """Every n-th row and column, about SAMPLE_PIXELS pixels (BGR, N x 3)."""
    n = _step(img)
    return img[::n, ::n].reshape(-1, 3)


def area_pixels(
    img: np.ndarray, area_px: np.ndarray | None = None, fraction: float = CENTRE_FRACTION
) -> tuple[np.ndarray, str]:
    """The pixels (BGR, N x 3, sampled) of the plate area `area_px` (a polygon in the picture's
    pixels: where the parts lie), or of the centre part without one or when it is hardly in
    the picture: (pixels, "plate" | "centre")."""
    n = _step(img)
    if area_px is not None and len(area_px) >= 3:
        import cv2

        small = img[::n, ::n]
        mask = np.zeros(small.shape[:2], np.uint8)
        pts = np.round(np.asarray(area_px, float) / n).astype(np.int32)
        cv2.fillPoly(mask, [pts], 255)
        if int(np.count_nonzero(mask)) >= MIN_PIXELS:
            return small[mask > 0].reshape(-1, 3), "plate"
    return centre(img, fraction)[::n, ::n].reshape(-1, 3), "centre"


def linear(px: np.ndarray) -> np.ndarray:
    """Gamma-encoded 0..255 values in linear light, 0..1."""
    return (np.asarray(px, np.float64) / 255.0) ** GAMMA


def _usable(px: np.ndarray) -> np.ndarray:
    """Neither clipped in any channel nor dark."""
    return (px.max(axis=1) < 250) & (px.mean(axis=1) > 15)


def grey_reference(px: np.ndarray, tolerance: float = GREY_TOLERANCE) -> np.ndarray | None:
    """The colour of the light (linear B, G, R) from the near-neutral pixels of `px` (BGR): the
    brighter half of the unclipped pixels whose red/green and blue/green are within `tolerance`
    (else GREY_TOLERANCE_WIDE) of grey (white bins, the tray's walls, the codes' white, metal parts). Coloured surfaces
    (the blue or green TPU plate, a red bin) are left out instead of being made grey, as plain
    grey world does. None: too few grey pixels (nothing to go by)."""
    px = px[_usable(px)]
    if len(px) < MIN_PIXELS:
        return None
    lin = linear(px) + 1e-6
    lr, lb = np.log(lin[:, 2] / lin[:, 1]), np.log(lin[:, 0] / lin[:, 1])
    near = (np.abs(lr) < tolerance) & (np.abs(lb) < tolerance)
    if int(near.sum()) < MIN_PIXELS and tolerance < GREY_TOLERANCE_WIDE:
        near = (np.abs(lr) < GREY_TOLERANCE_WIDE) & (np.abs(lb) < GREY_TOLERANCE_WIDE)
    if int(near.sum()) < MIN_PIXELS:
        return None
    grey = lin[near]
    lum = grey.sum(axis=1)
    return np.median(grey[lum >= np.median(lum)], axis=0)


def plate_colour(
    img: np.ndarray, area_px: np.ndarray | None = None, fraction: float = CENTRE_FRACTION
) -> tuple[np.ndarray, str] | None:
    """The plate's colour (linear B, G, R; green = 1) and where it was measured ("plate" or
    "centre"): the median of the area's usable pixels (the parts on it are few), or None."""
    px, where = area_pixels(img, area_px, fraction)
    px = px[_usable(px)]
    if len(px) < MIN_PIXELS:
        return None
    b, g, r = np.median(linear(px), axis=0)
    if g <= 0 or b <= 0 or r <= 0:
        return None
    return np.array([b / g, 1.0, r / g]), where


def centre_balance(
    img: np.ndarray,
    exposure_us: float,
    colour_gains: tuple[float, float],
    fraction: float = CENTRE_FRACTION,
    area_px: np.ndarray | None = None,
) -> tuple[int, tuple[float, float], bool]:
    """One step of the lock's own exposure and white balance, from a frame (BGR) taken with
    `exposure_us` and `colour_gains` (red, blue): (new exposure, new gains, steady).

    White balance: from the grey pixels of the whole picture (grey_reference), never from the
    plate's average: the plate is blue or green, and making it grey gave the red cast (all the
    more in sunlight, when its red channel came out of the dark and was counted). No grey
    pixels: the gains stay as they are (the camera's own AWB). Exposure: the median of the
    plate area (`area_px`, else the centre part) goes to CENTRE_TARGET, unless that would clip
    the brightest of the whole picture (a white bin): then less. In linear light, repeated
    until steady."""
    r_gain, b_gain = (float(g) for g in colour_gains)
    steady = True
    ref = grey_reference(sample(img))
    if ref is not None:
        b, g, r = ref
        nr = float(np.clip(r_gain * g / r, *GAIN_RANGE))
        nb = float(np.clip(b_gain * g / b, *GAIN_RANGE))
        steady = abs(nr / r_gain - 1) < 0.02 and abs(nb / b_gain - 1) < 0.02
        r_gain, b_gain = nr, nb
    px, _ = area_pixels(img, area_px, fraction)
    med = max(float(np.median(px.mean(axis=1))), 1.0)
    top = max(float(np.percentile(sample(img).max(axis=1), 99.5)), 1.0)
    scale = min((CENTRE_TARGET / med) ** GAMMA, (HIGHLIGHT_MAX / top) ** GAMMA)
    scale = float(np.clip(scale, 0.25, 4.0))
    steady = steady and abs(scale - 1) < 0.06
    exposure = int(np.clip(exposure_us * scale, *EXPOSURE_RANGE_US))
    return exposure, (r_gain, b_gain), steady


def follow_factors(
    img: np.ndarray,
    reference: Any,
    area_px: np.ndarray | None = None,
    fraction: float = CENTRE_FRACTION,
) -> tuple[float, float] | None:
    """Per-channel factors (blue, red; linear light) that bring the plate in `img` back to its
    colour at the lock (`reference`: linear B, G, R with green = 1). (1, 1) for a difference
    within FOLLOW_DEADBAND; None when the plate is not measurable or the change is larger than
    a change of light (FOLLOW_RANGE): then the photo is left as it is."""
    now = plate_colour(img, area_px, fraction)
    if now is None:
        return None
    ref = np.asarray(reference, float)
    kb, kr = float(ref[0] / now[0][0]), float(ref[2] / now[0][2])
    lo, hi = FOLLOW_RANGE
    if not (lo <= kb <= hi and lo <= kr <= hi):
        log.info("colour follow: plate %.2f / %.2f off the lock's, left as it is", kb, kr)
        return None
    if abs(kb - 1) < FOLLOW_DEADBAND and abs(kr - 1) < FOLLOW_DEADBAND:
        return 1.0, 1.0
    return kb, kr


def apply_factors(img: np.ndarray, blue: float, red: float) -> np.ndarray:
    """`img` (BGR, uint8) with blue and red scaled in linear light (a lookup table per channel:
    with a power-law gamma, k in linear light is k^(1/2.2) on the encoded values)."""
    if blue == 1.0 and red == 1.0:
        return img
    v = np.arange(256, dtype=np.float64)
    lut = np.stack([np.clip(v * f ** (1 / GAMMA), 0, 255) for f in (blue, 1.0, red)], axis=1)
    lut = np.round(lut).astype(np.uint8)
    try:
        import cv2

        return cv2.LUT(np.ascontiguousarray(img), lut.reshape(1, 256, 3))
    except ImportError:  # pragma: no cover - OpenCV is there wherever photos are taken
        return np.stack([lut[img[..., i], i] for i in range(3)], axis=-1)


def oriented(img: np.ndarray, hflip: bool, vflip: bool, turn90: bool) -> np.ndarray:
    """A frame of the camera without its transform, turned like the program's photos (the
    flips, then the quarter turn): the lock measures in the same pixels as the calibration."""
    if hflip:
        img = img[:, ::-1]
    if vflip:
        img = img[::-1]
    return turn_image(img, turn90)


NOIR_WARNING = (
    "camera %s has no infrared filter (NoIR): sunlight makes the photos red or pink, which no "
    "white balance fully undoes (a standard Camera Module 3, an IR-cut filter, or no direct sun)"
)


def is_noir(model: str) -> bool:
    """The sensor's name says NoIR (libcamera: imx708_noir, imx708_wide_noir)."""
    return "noir" in model.lower()


def focus_metric(gray: np.ndarray, centre_fraction: float = CENTRE_FRACTION) -> float:
    """Variance of the Laplacian on the centre region (higher = sharper)."""
    crop = centre(gray, centre_fraction).astype(np.float64)
    lap = (
        -4 * crop[1:-1, 1:-1] + crop[:-2, 1:-1] + crop[2:, 1:-1] + crop[1:-1, :-2] + crop[1:-1, 2:]
    )
    return float(lap.var())


def best_focus(positions: list[float], scores: list[float]) -> float:
    """Peak of the focus curve with a parabolic fit around the best sample."""
    i = int(np.argmax(scores))
    if 0 < i < len(scores) - 1:
        x = np.array(positions[i - 1 : i + 2])
        y = np.array(scores[i - 1 : i + 2])
        a, b, _ = np.polyfit(x, y, 2)
        if a < 0:
            return float(np.clip(-b / (2 * a), x[0], x[-1]))
    return float(positions[i])


def settings_mismatch(locked: dict[str, Any], metadata: dict[str, Any]) -> list[str]:
    """Differences between the locked settings and the metadata of an actual frame."""
    problems = []
    for key, tol in TOLERANCE.items():
        if key not in locked:
            continue
        want, got = locked[key], metadata.get(key)
        if got is None:
            problems.append(f"{key}: missing in frame metadata")
            continue
        want_a, got_a = (
            np.atleast_1d(np.asarray(want, float)),
            np.atleast_1d(np.asarray(got, float)),
        )
        rel = np.abs(got_a - want_a) / np.maximum(np.abs(want_a), 1e-9)
        if np.any(rel > tol):
            problems.append(f"{key}: locked {want}, camera reports {got}")
    if (
        locked.get("size")
        and metadata.get("size")
        and list(locked["size"]) != list(metadata["size"])
    ):
        problems.append(f"size: locked {locked['size']}, got {metadata['size']}")
    return problems


LIMITED = ("AnalogueGain", "ExposureTime", "LensPosition")  # kept inside what the camera can do


def within_limits(values: dict[str, Any], limits: Any) -> dict[str, Any]:
    """`values` with each of LIMITED clamped to the camera's range (Picamera2's camera_controls:
    name -> (min, max, default)). The Camera Module 3's sensor has no gain under 1.12: asked for
    1.0 it runs at 1.12, and every photo then failed the drift check (settings_mismatch)."""
    out = dict(values)
    for key in LIMITED:
        lim = (limits or {}).get(key) if hasattr(limits, "get") else None
        if key not in out or not isinstance(lim, (tuple, list)) or len(lim) < 2:
            continue
        lo, hi = lim[0], lim[1]
        v = out[key]
        if isinstance(v, (int, float)) and lo is not None and hi is not None and lo < hi:
            c = min(max(float(v), float(lo)), float(hi))
            if c != float(v):
                log.info("camera: %s %s is outside %s..%s, using %s", key, v, lo, hi, c)
            out[key] = int(round(c)) if isinstance(v, int) and not isinstance(v, bool) else c
    return out


IMAGE_KEYS = {
    "brightness": "Brightness",
    "contrast": "Contrast",
    "sharpness": "Sharpness",
    "saturation": "Saturation",
}


def _adj(adjust: Any) -> dict[str, Any]:
    if adjust is None:
        return {}
    return dict(adjust) if isinstance(adjust, dict) else dict(vars(adjust))


def merged_settings(settings: dict[str, Any] | None, adjust: Any) -> dict[str, Any]:
    """The locked settings with the page's manual adjustments over them (what the camera must
    then report: settings_mismatch)."""
    s, a = dict(settings or {}), _adj(adjust)
    if not s:
        return s
    if a.get("focus") == "manual":
        s["LensPosition"] = float(a["lens_position"])
    if a.get("white_balance") == "manual":
        s["ColourGains"] = [float(a["red_gain"]), float(a["blue_gain"])]
    if a.get("exposure") == "manual":
        s["ExposureTime"] = int(a["exposure_us"])
        s["AnalogueGain"] = float(a["gain"])
    for key, ctl in IMAGE_KEYS.items():
        if key in a:
            s[ctl] = float(a[key])
    return s


def controls_for(settings: dict[str, Any] | None, adjust: Any, has_af: bool = True) -> dict:
    """Picamera2 controls: the locked settings (with the manual adjustments over them), or,
    before a lock, the camera's automatic ones where the adjustment says auto."""
    a = _adj(adjust)
    if settings:
        return controls_from_settings(merged_settings(settings, a))
    c: dict[str, Any] = {}
    if a.get("exposure") == "manual":
        c |= {
            "AeEnable": False,
            "ExposureTime": int(a["exposure_us"]),
            "AnalogueGain": float(a["gain"]),
        }
    else:
        c["AeEnable"] = True
    if a.get("white_balance") == "manual":
        c |= {"AwbEnable": False, "ColourGains": (float(a["red_gain"]), float(a["blue_gain"]))}
    else:
        c["AwbEnable"] = True
    if has_af:
        if a.get("focus") == "manual":
            c |= {"AfMode": 0, "LensPosition": float(a["lens_position"])}
        else:
            c["AfMode"] = 2  # controls.AfModeEnum.Continuous: sharp while not locked
    for key, ctl in IMAGE_KEYS.items():
        if key in a:
            c[ctl] = float(a[key])
    return c


def turn_image(img: np.ndarray, turn90: bool) -> np.ndarray:
    """The software part of the picture's orientation: 90 degrees clockwise."""
    return np.ascontiguousarray(np.rot90(img, k=-1)) if turn90 else img


def orientation(hflip: bool, vflip: bool, turn90: bool) -> dict[str, Any]:
    """How the picture is turned, for the page: degrees clockwise and mirrored or not (the
    mirror is applied to the camera's own picture, before the turn)."""
    mirror = hflip != vflip
    base = 180 if vflip else 0  # H: mirrored | V = H then 180 | H+V = 180
    return {"turn": (base + (90 if turn90 else 0)) % 360, "mirror": mirror}


def rotated(hflip: bool, vflip: bool, turn90: bool) -> tuple[bool, bool, bool]:
    """The orientation turned a further 90 degrees clockwise."""
    if not turn90:
        return hflip, vflip, True
    return not hflip, not vflip, False  # two quarter turns = both flips


def mirrored(hflip: bool, vflip: bool, turn90: bool) -> tuple[bool, bool, bool]:
    """The orientation mirrored left-right (in the final picture)."""
    if turn90:  # mirroring after a quarter turn = mirroring top-bottom before it
        return hflip, not vflip, turn90
    return not hflip, vflip, turn90


def rpicam_adjust(adjust: Any) -> list[str]:
    """rpicam-still options for the page's adjustments (no Picamera2)."""
    a, out = _adj(adjust), []
    if not a:
        return out
    if a.get("focus") == "manual":
        out += ["--autofocus-mode", "manual", "--lens-position", f"{float(a['lens_position']):g}"]
    if a.get("white_balance") == "manual":
        out += ["--awbgains", f"{float(a['red_gain']):g},{float(a['blue_gain']):g}"]
    if a.get("exposure") == "manual":
        out += ["--shutter", str(int(a["exposure_us"])), "--gain", f"{float(a['gain']):g}"]
    for key in IMAGE_KEYS:
        if key in a:
            out += [f"--{key}", f"{float(a[key]):g}"]
    return out


def controls_from_settings(s: dict[str, Any]) -> dict[str, Any]:
    """Picamera2 controls that freeze exposure, gain, white balance and focus."""
    c = {
        "AeEnable": False,
        "AwbEnable": False,
        "ExposureTime": int(s["ExposureTime"]),
        "AnalogueGain": float(s["AnalogueGain"]),
        "ColourGains": tuple(float(g) for g in s["ColourGains"]),
        "AfMode": 0,  # controls.AfModeEnum.Manual
        "LensPosition": float(s["LensPosition"]),
    }
    for key in ("Sharpness", "Contrast", "Saturation", "Brightness", "NoiseReductionMode"):
        if key in s:
            c[key] = s[key]
    return c


class Coverage:
    """Where board corners have been seen across the frame (grid of counts)."""

    def __init__(self, size: tuple[int, int] = FULL_RES, cells: tuple[int, int] = (16, 9)) -> None:
        self.size, self.cells = size, cells
        self.grid = np.zeros((cells[1], cells[0]), dtype=int)

    def add(self, corners_px: np.ndarray) -> None:
        w, h = self.size
        cx = np.clip((corners_px[:, 0] / w * self.cells[0]).astype(int), 0, self.cells[0] - 1)
        cy = np.clip((corners_px[:, 1] / h * self.cells[1]).astype(int), 0, self.cells[1] - 1)
        np.add.at(self.grid, (cy, cx), 1)

    @property
    def fraction(self) -> float:
        return float((self.grid > 0).mean())

    def ascii(self) -> str:
        chars = " .:-=+*#"
        top = max(int(self.grid.max()), 1)
        return "\n".join(
            "".join(chars[min(7, int(v * 7 / top))] if v else "_" for v in row) for row in self.grid
        )

    def image(self, scale: int = 40) -> np.ndarray:
        g = (np.clip(self.grid / max(self.grid.max(), 1), 0, 1) * 255).astype(np.uint8)
        return np.kron(g, np.ones((scale, scale), dtype=np.uint8))


def save_capture(
    out_dir: str | os.PathLike[str],
    name: str,
    image_bgr: np.ndarray,
    metadata: dict[str, Any],
    extra: dict[str, Any] | None = None,
) -> Path:
    """Lossless PNG + JSON sidecar with the actual frame metadata."""
    import cv2

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"{name}.png"
    if not cv2.imwrite(str(path), image_bgr):
        raise OSError(f"could not write {path}")
    sidecar = {
        "file": path.name,
        "time": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "metadata": {k: _jsonable(v) for k, v in metadata.items()},
        **(extra or {}),
    }
    path.with_suffix(".json").write_text(json.dumps(sidecar, indent=2), encoding="utf-8")
    return path


def _jsonable(v: Any) -> Any:
    if isinstance(v, (list, tuple)):
        return [_jsonable(x) for x in v]
    if isinstance(v, (int, float, str, bool)) or v is None:
        return v
    if hasattr(v, "tolist"):
        return v.tolist()
    return str(v)


def rpicam_still(hflip: bool = False, vflip: bool = False, adjust: Any = None) -> list[str]:
    """The rpicam-still command for one full-resolution photo (without Picamera2)."""
    cmd = ["rpicam-still", "-n", "-t", "500", "--width", str(FULL_RES[0])]
    cmd += ["--height", str(FULL_RES[1])]
    cmd += (["--hflip"] if hflip else []) + (["--vflip"] if vflip else [])
    return cmd + rpicam_adjust(adjust)


class CameraError(RuntimeError):
    """The camera cannot be used as asked (shown on the page; never ends the program)."""


class Camera:
    """The Pi camera, kept open while the program runs. Locked (`settings` from camlock: the same
    exposure, colours and focus for every photo) or, before the lock, with the camera's own
    automatic settings (only for the live picture and the lock itself). Two streams: "main" at
    full resolution for photos, "lores" (LIVE_SIZE) for the live picture on the page."""

    def __init__(
        self,
        settings: dict | None = None,
        hflip: bool = False,
        vflip: bool = False,
        turn90: bool = False,
        adjust: Any = None,
    ) -> None:
        from picamera2 import Picamera2

        self.locked_settings = dict(settings or {})
        self.adjust = _adj(adjust)
        self.limits: Any = {}
        self.settings = merged_settings(self.locked_settings, self.adjust)
        self.turn90 = bool(turn90)
        extra: dict[str, Any] = {}
        if hflip or vflip:  # done by the camera: every stream comes out turned
            from libcamera import Transform

            extra["transform"] = Transform(hflip=int(hflip), vflip=int(vflip))
        self.locked = bool(self.settings)
        self.picam2 = Picamera2()
        self.limits = getattr(self.picam2, "camera_controls", {}) or {}
        self.model = str((getattr(self.picam2, "camera_properties", {}) or {}).get("Model", ""))
        if is_noir(self.model):
            log.warning(NOIR_WARNING, self.model)
        self.settings = within_limits(self.settings, self.limits)  # what it can really run at
        try:
            mode = self.settings.get("sensor_mode") or {}
            cfg = self.picam2.create_still_configuration(
                main={"size": tuple(self.settings.get("size", FULL_RES)), "format": "RGB888"},
                lores={"size": LIVE_SIZE},
                raw={} if mode else None,
                sensor={"output_size": tuple(mode["size"]), "bit_depth": mode["bit_depth"]}
                if mode
                else {},
                buffer_count=2,
                **extra,
            )
            self.picam2.configure(cfg)
            self.picam2.set_controls(self._controls())
            self.picam2.start()
            time.sleep(1.5)
            if self.locked:
                self.verify()
        except Exception:
            self.close()
            raise

    def _controls(self) -> dict[str, Any]:
        has_af = "AfMode" in self.picam2.camera_controls
        c = within_limits(controls_for(self.locked_settings, self.adjust, has_af), self.limits)
        if not has_af:
            c = {k: v for k, v in c.items() if k not in ("AfMode", "LensPosition")}
        elif c.get("AfMode") == 2:  # continuous autofocus: on the centre, not a bin's edge
            c |= self._af_centre()
        return c

    def _af_centre(self) -> dict[str, Any]:
        """Autofocus windows on the centre part (CENTRE_FRACTION), where the camera has them."""
        crop = (getattr(self.picam2, "camera_properties", {}) or {}).get("ScalerCropMaximum")
        if crop is None or "AfWindows" not in self.picam2.camera_controls:
            return {}
        return {"AfMetering": 1, "AfWindows": [centre_window(crop)]}  # 1: AfMeteringWindows

    def set_adjust(self, adjust: Any) -> None:
        """New adjustments from the page, applied at once (no reopening)."""
        self.adjust = _adj(adjust)
        self.settings = within_limits(
            merged_settings(self.locked_settings, self.adjust), self.limits
        )
        self.picam2.set_controls(self._controls())
        time.sleep(0.5)  # a few frames with the new settings

    def focus_once(self) -> float | None:
        """Autofocus once on what is under the camera; the lens position found (dioptres), or
        None without autofocus."""
        if "AfMode" not in self.picam2.camera_controls:
            return None
        self.picam2.set_controls({"AfMode": 1} | self._af_centre())  # AfModeEnum.Auto, centre
        self.picam2.autofocus_cycle()
        pos = self.picam2.capture_metadata().get("LensPosition")
        return None if pos is None else float(pos)

    def now(self) -> dict[str, Any]:
        """What the camera runs with right now (exposure, gain, colours, focus)."""
        md = self.picam2.capture_metadata()
        keys = ("ExposureTime", "AnalogueGain", "ColourGains", "LensPosition", "ColourTemperature")
        return {k: _jsonable(md[k]) for k in keys if k in md}

    def verify(self) -> None:
        md = dict(self.picam2.capture_metadata())
        md["size"] = list(self.settings.get("size", FULL_RES))
        problems = settings_mismatch(self.settings, md)
        if problems:
            raise CameraError(
                "the camera does not run with the locked settings (Calibrate the camera again): "
                + "; ".join(problems)
            )

    def grab(self, dng_path: Path | None = None) -> tuple[np.ndarray, dict]:
        request = self.picam2.capture_request()
        try:
            img = request.make_array("main")
            md = request.get_metadata()
            if dng_path is not None:
                request.save_dng(str(dng_path))
        finally:
            request.release()
        problems = settings_mismatch(self.settings, md)
        if problems:
            raise CameraError("settings drifted during capture: " + "; ".join(problems))
        return turn_image(img, self.turn90), md

    def preview(self) -> np.ndarray:
        """One frame of the live picture (LIVE_SIZE, BGR)."""
        import cv2

        yuv = self.picam2.capture_array("lores")
        w, h = LIVE_SIZE
        img = cv2.cvtColor(np.ascontiguousarray(yuv[: h * 3 // 2, :w]), cv2.COLOR_YUV2BGR_I420)
        return turn_image(img, self.turn90)

    def close(self) -> None:
        """Stop and release the camera, so another Picamera2 (the lock) can open it."""
        try:
            self.picam2.stop()
        finally:
            self.picam2.close()
