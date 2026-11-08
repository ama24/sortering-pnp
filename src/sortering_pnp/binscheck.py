"""The bins check: what each storage bin holds, from one model pass on the whole board.

Only Resync and the start-up check's Bins check do it (sorting photos keep the tray only,
painted, see trayview.py). The model runs once on the whole calibrated picture at its trained
scale (nothing cropped or painted); every detection is given to the bin whose floor (inside its
walls) holds it. Detections on or next to a bin's code are dropped: the printed code looks like
parts to the model ("unknown", or any class). The code is kept out twice: where the layout puts
it, and where the photo shows it (a code sits on the rim, so seen from above it appears shifted
outwards on the floor plane the parts are measured on).

The picture (`draw`) shows it: each bin's floor with its cell and code, the parts counted
in it, the dropped ones crossed out, the code areas, and what each bin collects now.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from .layout import Bin, Layout
from .parts import Part
from .startup import CODE_KEEPOUT_MM, floor_rect, parts_in_bin
from .transform import Transform2D

log = logging.getLogger("sortering_pnp.binscheck")


@dataclass
class BinLook:
    """One bin after the check: the parts counted in it and what it collects now."""

    marker: int
    cell: str
    parts: list[Part] = field(default_factory=list)
    result: str = ""  # written on the picture: "DIN912_M3 (4)", "empty: free", ...
    changed: bool = False  # what it collects was set from what was seen


def code_spots(shot: Any, T: Transform2D | None) -> dict[int, tuple[float, float]]:
    """Where each code appears on the floor plane (printer X/Y): its centre in the photo (view
    pixels) back through the plate (z = 0) homography. Codes stand on a rim, so this is not
    their real place: it is where the model sees them."""
    H = getattr(shot, "view_h", None)
    if T is None or H is None:
        return {}
    Hi = np.linalg.inv(np.asarray(H, dtype=float))
    out = {}
    for mk in getattr(shot, "markers", []):
        if mk.view_px is None:
            continue
        x, y, w = Hi @ np.array([mk.view_px[0], mk.view_px[1], 1.0])
        bx, by = (float(v) for v in T.apply([x / w, y / w]))
        out[mk.marker] = (bx, by)
    return out


def sort_out(
    layout: Layout,
    parts: Sequence[Part],
    min_score: float,
    spots: dict[int, tuple[float, float]],
) -> tuple[dict[int, list[Part]], list[Part]]:
    """The parts in each storage bin (by code), and those dropped for lying on a code."""
    codes = list(spots.values())
    per_bin: dict[int, list[Part]] = {}
    for b in layout.bins:
        if b.role != "work":
            per_bin[b.marker] = parts_in_bin(layout, b, parts, min_score, codes)
    counted = {id(p) for ps in per_bin.values() for p in ps}
    dropped = [
        p
        for p in parts
        if id(p) not in counted
        and p.score >= min_score
        and any(_on_code(layout, b, p, codes) for b in layout.bins if b.role != "work")
    ]
    return per_bin, dropped


def _on_code(layout: Layout, b: Bin, p: Part, codes: Iterable[tuple[float, float]]) -> bool:
    x0, y0, x1, y1 = floor_rect(layout, b)
    if not (x0 <= p.bed_xy[0] <= x1 and y0 <= p.bed_xy[1] <= y1):
        return False
    h = CODE_KEEPOUT_MM
    spots = [layout.marker_centre(b), *codes]
    return any(abs(p.bed_xy[0] - x) <= h and abs(p.bed_xy[1] - y) <= h for x, y in spots)


# ---------------------------------------------------------------- the picture
_BGR = [(139, 143, 95), (60, 135, 176), (179, 127, 111), (63, 85, 180), (102, 142, 91)]


def _colour(cls: str) -> tuple[int, int, int]:
    h = 0
    for c in cls:
        h = (h * 31 + ord(c)) & 0xFFFFFFFF
    return _BGR[h % len(_BGR)]


def draw(
    view: Path,
    view_h: Sequence[Sequence[float]],
    T: Transform2D,
    layout: Layout,
    looks: Sequence[BinLook],
    dropped: Sequence[Part],
    spots: dict[int, tuple[float, float]],
    out: Path,
) -> Path | None:
    """The page's photo with the bins check drawn on it (same size as `view`, so the page's
    overlay still fits). None when it cannot be drawn."""
    try:
        import cv2
    except ImportError:
        return None
    img = cv2.imread(str(view), cv2.IMREAD_COLOR)
    if img is None:
        return None
    H = np.asarray(view_h, dtype=float)
    Ti = T.inverse()
    k = max(img.shape[:2]) / 1600.0
    fs, lw = 0.5 * max(k, 0.6), max(1, round(2 * k))

    def px_plate(pts: np.ndarray) -> np.ndarray:
        p = np.c_[np.asarray(pts, dtype=float).reshape(-1, 2), np.ones(len(pts))] @ H.T
        return (p[:, :2] / p[:, 2:3]).round().astype(np.int32)

    def px_bed(pts: Sequence[Sequence[float]]) -> np.ndarray:
        return px_plate(Ti.apply(np.asarray(pts, dtype=float)))

    def label(at: Sequence[float], text: str, bg: tuple[int, int, int]) -> int:
        """A label with its top-left corner at `at`; returns the y just below it."""
        (w, h), base = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, fs, 1)
        x = max(0, min(int(at[0]), img.shape[1] - w - 6))
        y = max(0, int(at[1]))
        cv2.rectangle(img, (x, y), (x + w + 6, y + h + base + 6), bg, -1)
        cv2.putText(img, text, (x + 3, y + h + 3), cv2.FONT_HERSHEY_SIMPLEX, fs, (255, 255, 255), 1)
        return y + h + base + 8

    shade = img.copy()
    for b in layout.bins:  # the code areas (kept out) on each floor: shaded
        if b.role == "work":
            continue
        h = CODE_KEEPOUT_MM
        fx0, fy0, fx1, fy1 = floor_rect(layout, b)
        for x, y in [layout.marker_centre(b), *([spots[b.marker]] if b.marker in spots else [])]:
            x0, y0 = max(x - h, fx0), max(y - h, fy0)
            x1, y1 = min(x + h, fx1), min(y + h, fy1)
            if x0 < x1 and y0 < y1:
                sq = px_bed([(x0, y0), (x1, y0), (x1, y1), (x0, y1)])
                cv2.fillPoly(shade, [sq], (80, 80, 200))
    cv2.addWeighted(shade, 0.25, img, 0.75, 0, dst=img)

    for p in dropped:  # on a code: crossed out, faint
        poly = px_plate(p.polygon) if len(p.polygon) > 2 else None
        if poly is not None:
            cv2.polylines(img, [poly], True, (150, 150, 150), lw, cv2.LINE_AA)
            x0, y0 = poly.min(axis=0)
            x1, y1 = poly.max(axis=0)
            cv2.line(img, (int(x0), int(y0)), (int(x1), int(y1)), (60, 60, 200), lw, cv2.LINE_AA)
            cv2.line(img, (int(x0), int(y1)), (int(x1), int(y0)), (60, 60, 200), lw, cv2.LINE_AA)

    by_marker = {lk.marker: lk for lk in looks}
    for b in layout.bins:
        x0, y0, x1, y1 = floor_rect(layout, b)
        rect = px_bed([(x0, y0), (x1, y0), (x1, y1), (x0, y1)])
        lk = by_marker.get(b.marker)
        if b.role == "work":
            cv2.polylines(img, [rect], True, (200, 120, 40), lw, cv2.LINE_AA)
            label(rect.min(axis=0) + 3, f"{layout.bin_name(b)} tray", (200, 120, 40))
            continue
        full = lk is not None and bool(lk.parts)
        colour = (60, 150, 60) if full else (140, 140, 140)
        cv2.polylines(img, [rect], True, colour, lw + (1 if full else 0), cv2.LINE_AA)
        for p in lk.parts if lk else []:
            if len(p.polygon) > 2:
                c = _colour(p.cls)
                cv2.polylines(img, [px_plate(p.polygon)], True, c, lw, cv2.LINE_AA)
        x, y = rect.min(axis=0) + 3
        below = label((x, y), f"{layout.bin_name(b)} | {b.marker}", colour)
        if lk is not None and lk.result:
            label((x, below), lk.result, (40, 40, 40))
    out.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(out), img, [cv2.IMWRITE_JPEG_QUALITY, 85]):
        log.warning("could not write %s", out)
        return None
    return out
