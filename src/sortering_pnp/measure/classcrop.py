"""The classifier's crops and what its answer may change (shared format: training-synth's
model_card.json `classifier_crop`).

A classifier trained on `fixed` crops saw every part at one scale: the whole render shrunk so its
longest side is `longest_side_px` (the stage-1 scale), then a `size_px` square around the part's
box centre, padded with `pad`, never resized. Cut the same way from the real photo, a part's size
is in its pixels, so the classifier may change the whole class (when it was trained on classes).

A classifier without that block (older ones, folder datasets, `scaled` crops) saw every part
enlarged to fill its picture: it cannot judge sizes, so it may only change the type (DIN912 ->
DIN7984), never the size, which stays stage 1's.
"""

from __future__ import annotations

import re
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import cv2
import numpy as np

CROP_VERSION = 1
_INTERP = {"area": cv2.INTER_AREA, "linear": cv2.INTER_LINEAR}
# the size token in a class name: a thread size (M4, M2.5) or an extrusion profile (2020)
_SIZE_TOKEN = re.compile(r"_(M\d+(?:\.\d+)?|\d{4})(?=_|$)")


@dataclass(frozen=True)
class CropSpec:
    """model_card.json `classifier_crop` (version 1, mode fixed)."""

    longest_side_px: int = 1024
    size_px: int = 256
    pad: tuple[int, int, int] = (114, 114, 114)
    interpolation: str = "area"
    labels: str = "class"  # class: the labels include the size | type: they do not

    @classmethod
    def from_card(cls, card: Mapping[str, Any] | None) -> CropSpec | None:
        """The crop block of a model card; None when there is none (crop like before, change
        the type only). A block this version cannot read raises ValueError."""
        block = (card or {}).get("classifier_crop")
        if not block:
            return None
        if int(block.get("version", 0)) != CROP_VERSION:
            raise ValueError(
                f"classifier_crop version {block.get('version')} is not supported "
                f"(this sortering-pnp reads version {CROP_VERSION}): update sortering-pnp"
            )
        if block.get("mode") != "fixed":
            raise ValueError(f"classifier_crop mode {block.get('mode')!r}: only 'fixed' is known")
        if block.get("centre", "box") != "box":
            raise ValueError(f"classifier_crop centre {block.get('centre')!r}: only 'box'")
        spec = cls(
            longest_side_px=int(block.get("longest_side_px", 1024)),
            size_px=int(block.get("size_px", 256)),
            pad=tuple(int(v) for v in block.get("pad", (114, 114, 114)))[:3],  # type: ignore[arg-type]
            interpolation=str(block.get("interpolation", "area")),
            labels=str(block.get("labels", "class")),
        )
        if spec.interpolation not in _INTERP:
            raise ValueError(f"classifier_crop interpolation {spec.interpolation!r} is unknown")
        if spec.labels not in ("class", "type"):
            raise ValueError(f"classifier_crop labels {spec.labels!r}: 'class' or 'type'")
        if spec.size_px <= 0 or spec.longest_side_px <= 0 or len(spec.pad) != 3:
            raise ValueError("classifier_crop: size_px, longest_side_px and pad must be valid")
        return spec

    def shrink(self, image: np.ndarray) -> tuple[np.ndarray, float]:
        """The whole picture with its longest side at longest_side_px, and that scale."""
        h, w = image.shape[:2]
        s = self.longest_side_px / max(h, w)
        size = (max(1, round(w * s)), max(1, round(h * s)))
        return cv2.resize(image, size, interpolation=_INTERP[self.interpolation]), s

    def crop(self, small: np.ndarray, s: float, box: Sequence[float]) -> np.ndarray:
        """size_px square around the box centre (box in full-resolution pixels) in the shrunk
        picture; what lies outside the picture is the pad colour."""
        n = self.size_px
        cx = ((box[0] + box[2]) / 2 + 0.5) * s - 0.5
        cy = ((box[1] + box[3]) / 2 + 0.5) * s - 0.5
        x0, y0 = round(cx - n / 2), round(cy - n / 2)
        h, w = small.shape[:2]
        out = np.empty((n, n, small.shape[2]), small.dtype)
        out[:] = self.pad
        sx0, sy0, sx1, sy1 = max(0, x0), max(0, y0), min(w, x0 + n), min(h, y0 + n)
        if sx1 > sx0 and sy1 > sy0:
            out[sy0 - y0 : sy1 - y0, sx0 - x0 : sx1 - x0] = small[sy0:sy1, sx0:sx1]
        return out


def legacy_crop(image: np.ndarray, box: Sequence[float]) -> np.ndarray:
    """The crop for a classifier without a crop block: the box and a margin, full resolution."""
    x0, y0, x1, y1 = box
    m = 0.25 * max(x1 - x0, y1 - y0) + 16
    h, w = image.shape[:2]
    return image[
        max(0, int(y0 - m)) : min(h, int(y1 + m)), max(0, int(x0 - m)) : min(w, int(x1 + m))
    ]


def _last_size(cls: str) -> re.Match[str] | None:
    found = list(_SIZE_TOKEN.finditer(cls))
    return found[-1] if found else None


def split_size(cls: str) -> tuple[str, str | None]:
    """(type, size) of a class name: DIN912_M4 -> (DIN912, M4); TNUT_DROP_S6_M4 ->
    (TNUT_DROP_S6, M4); BRACKET_2020 -> (BRACKET, 2020); UNKNOWN -> (UNKNOWN, None)."""
    m = _last_size(cls)
    if m is None:
        return cls, None
    return cls[: m.start()] + cls[m.end() :], m.group(1)


def with_type(cls: str, new_type: str) -> str | None:
    """`cls` with its type replaced and its size kept (DIN912_M4, DIN7984 -> DIN7984_M4);
    None when it has no size to keep."""
    t, size = split_size(cls)
    if size is None:
        return None
    m = _last_size(cls)
    assert m is not None
    suffix = cls[m.end() :]  # e.g. a style after a profile
    if suffix and new_type.endswith(suffix):
        new_type = new_type[: -len(suffix)]
    return f"{new_type}_{size}{suffix}"


def corrected_class(
    stage1: str, said: str, spec: CropSpec | None, known: Collection[str], unknown: str
) -> tuple[str, str]:
    """The class after the classifier said `said` (already confident enough), and why.

    With a crop block trained on classes: its answer. Otherwise only the type changes: the
    classifier's type with stage 1's size, when that class exists in `known` (stage 1's
    classes); else stage 1's class stays. A part called unknown is unknown either way."""
    if said == stage1:
        return stage1, "agrees"
    if said == unknown:
        return unknown, "classifier: unknown part"
    if spec is not None and spec.labels == "class":
        return said, "classifier"
    new_type = said if spec is not None else split_size(said)[0]  # labels "type": a type
    if stage1 == unknown:
        return stage1, "kept: the classifier cannot give an unknown part its size"
    new = with_type(stage1, new_type)
    if new == stage1:  # only the size differed
        return stage1, "kept: this classifier cannot judge sizes"
    if new is None or new not in known:
        return stage1, f"kept: {new or said} is not a class of the stage-1 model"
    return new, "classifier (type only)"
