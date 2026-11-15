"""The manual focus of the Camera Calibration tab: the raw lens position libcamera takes
(``LensPosition``, dioptres = 1 / metres), its range and its smallest step.

Picamera2's ``camera_controls["LensPosition"]`` gives (min, max, default) but no step: libcamera
exposes a float. The lens itself is moved by a voice-coil driver in whole codes (the Camera
Module 3: a DW9807, 10 bits), and the camera's tuning file (``rpi.af`` ``map``: dioptres ->
driver code) says which codes the range covers. For the Camera Module 3 (imx708.json) that is
0..15 dioptres -> codes 445..925, so one code is 15 / 480 = 1/32 dioptre: positions in between
are rounded to the same code. Without a tuning file that step is assumed.
"""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)

LENS_RANGE = (0.0, 15.0)  # dioptres: the Camera Module 3's tuning map (imx708.json, rpi.af)
LENS_STEP = 15.0 / 480  # dioptres per driver code there (codes 445..925)
LENS_DEFAULT = 1.0  # what libcamera reports as the default
MM_ABOVE = 20.0  # a saved lens position above this is an old distance in mm, not dioptres


def lens_dioptres(value: float) -> float:
    """A saved lens position in dioptres; an old value in mm (above MM_ABOVE: no lens here
    focuses closer than 50 mm) becomes 1000 / mm once."""
    v = float(value)
    if v > MM_ABOVE:
        log.info("camera focus: %g looks like mm, using %.4f dioptres", v, 1000.0 / v)
        return 1000.0 / v
    return v


def default_range() -> dict[str, Any]:
    lo, hi = LENS_RANGE
    return {"min": lo, "max": hi, "step": LENS_STEP, "default": LENS_DEFAULT, "source": "assumed"}


def _tuning_map(picam2: Any) -> list[float] | None:
    """The ``rpi.af`` map (dioptres, code, dioptres, code, ...) from the camera's tuning file."""
    try:
        from picamera2 import Picamera2

        model = str((getattr(picam2, "camera_properties", {}) or {}).get("Model", ""))
        if not model:
            return None
        tuning = Picamera2.load_tuning_file(f"{model}.json")
    except Exception as exc:  # noqa: BLE001 - no tuning file: the step is assumed
        log.debug("camera focus: no tuning file (%s)", exc)
        return None
    return tuning_map(tuning)


def tuning_map(tuning: Any) -> list[float] | None:
    """``rpi.af``'s map from a loaded tuning file (version 2: a list of algorithms)."""
    algos = (tuning or {}).get("algorithms", []) if isinstance(tuning, dict) else []
    for algo in algos:
        if isinstance(algo, dict) and "rpi.af" in algo:
            m = (algo["rpi.af"] or {}).get("map")
            if isinstance(m, list) and len(m) >= 4 and len(m) % 2 == 0:
                return [float(x) for x in m]
    return None


def focus_range(controls: Any, tmap: list[float] | None = None) -> dict[str, Any]:
    """min / max / step / default of the lens position, from the camera's controls (min, max,
    default) and the tuning map (range and step), else LENS_RANGE / LENS_STEP."""
    out = default_range()
    lim = controls.get("LensPosition") if hasattr(controls, "get") else None
    if isinstance(lim, (tuple, list)) and len(lim) >= 2 and None not in lim[:2] and lim[0] < lim[1]:
        out |= {"min": float(lim[0]), "max": float(lim[1]), "source": "camera"}
        if len(lim) > 2 and isinstance(lim[2], (int, float)):
            out["default"] = float(lim[2])
    if tmap:
        d, c = tmap[0::2], tmap[1::2]
        steps = [
            abs(d[i + 1] - d[i]) / abs(c[i + 1] - c[i])
            for i in range(len(d) - 1)
            if c[i + 1] != c[i]
        ]
        if steps:
            # libcamera's control may say more (e.g. 0..32) than the lens is mapped to
            out["min"], out["max"] = max(out["min"], min(d)), min(out["max"], max(d))
            out["step"] = min(steps)
            out["source"] = "camera tuning"
    elif out["source"] == "camera":
        out["min"], out["max"] = max(out["min"], LENS_RANGE[0]), min(out["max"], LENS_RANGE[1])
    out["default"] = min(max(out["default"], out["min"]), out["max"])
    return out


def camera_focus_range(picam2: Any) -> dict[str, Any]:
    """The open Picamera2's lens position range (no autofocus: the default range)."""
    controls = getattr(picam2, "camera_controls", {}) or {}
    return focus_range(controls, _tuning_map(picam2))


def snapped(value: float, r: dict[str, Any]) -> float:
    """`value` inside the range, on its step grid (counted from min)."""
    lo, hi, step = float(r["min"]), float(r["max"]), float(r["step"])
    v = min(max(float(value), lo), hi)
    if step > 0:
        v = min(hi, lo + round((v - lo) / step) * step)
    return round(v, 6)
