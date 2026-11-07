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


def focus_metric(gray: np.ndarray, centre_fraction: float = 0.4) -> float:
    """Variance of the Laplacian on the centre region (higher = sharper)."""
    h, w = gray.shape[:2]
    ch, cw = int(h * centre_fraction), int(w * centre_fraction)
    crop = gray[(h - ch) // 2 : (h + ch) // 2, (w - cw) // 2 : (w + cw) // 2].astype(np.float64)
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
        self.settings = merged_settings(self.locked_settings, self.adjust)
        self.turn90 = bool(turn90)
        extra: dict[str, Any] = {}
        if hflip or vflip:  # done by the camera: every stream comes out turned
            from libcamera import Transform

            extra["transform"] = Transform(hflip=int(hflip), vflip=int(vflip))
        self.locked = bool(self.settings)
        self.picam2 = Picamera2()
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
        c = controls_for(self.locked_settings, self.adjust, has_af)
        if not has_af:
            c = {k: v for k, v in c.items() if k not in ("AfMode", "LensPosition")}
        return c

    def set_adjust(self, adjust: Any) -> None:
        """New adjustments from the page, applied at once (no reopening)."""
        self.adjust = _adj(adjust)
        self.settings = merged_settings(self.locked_settings, self.adjust)
        self.picam2.set_controls(self._controls())
        time.sleep(0.5)  # a few frames with the new settings

    def focus_once(self) -> float | None:
        """Autofocus once on what is under the camera; the lens position found (dioptres), or
        None without autofocus."""
        if "AfMode" not in self.picam2.camera_controls:
            return None
        self.picam2.set_controls({"AfMode": 1})  # controls.AfModeEnum.Auto
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
