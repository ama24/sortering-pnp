"""Points drawn with OpenCV are plain ints within 32 bits (drawing.py).

OpenCV 5 refuses anything else ("Can't parse 'center'. Sequence item with index 0 has a wrong
type"): floats, numpy floats, and ints too big for 32 bits, e.g. a keypoint thrown far off the
picture. The strict fakes below refuse the same, whatever OpenCV is installed.
"""

from __future__ import annotations

import cv2
import numpy as np
import pytest

from sortering_pnp.calibjob import CalibrationJob
from sortering_pnp.drawing import LIMIT, finite, poly, pt
from sortering_pnp.measure.infer import Scene, draw

INT32 = 2**31


def _check_point(name: str, p: object) -> None:
    assert isinstance(p, tuple) and len(p) == 2, f"{name}: {p!r}"
    for v in p:
        assert type(v) is int, f"{name}: {type(v).__name__} in {p!r}"
        assert -INT32 <= v < INT32, f"{name}: {v} does not fit in 32 bits"


@pytest.fixture
def strict_cv2(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """cv2's drawing calls, refusing points that are not two plain 32-bit ints."""
    calls: list[str] = []

    def wrap(fn_name: str, point_args: tuple[int, ...]) -> None:
        real = getattr(cv2, fn_name)

        def fake(*args: object, **kw: object) -> object:
            for i in point_args:
                _check_point(fn_name, args[i])
            calls.append(fn_name)
            return real(*args, **kw)

        monkeypatch.setattr(cv2, fn_name, fake)

    wrap("circle", (1,))
    wrap("line", (1, 2))
    wrap("rectangle", (1, 2))
    wrap("putText", (2,))
    return calls


def test_pt_gives_plain_ints_in_range() -> None:
    for v in (np.float64(3.6), np.float32(3.6), np.int64(4), 3.6, np.array([3.6])[0]):
        assert pt(v, v) == (4, 4)
        assert all(type(c) is int for c in pt(v, v))
    assert pt(1e12, -1e12) == (LIMIT, -LIMIT)
    assert pt(np.inf, -np.inf) == (LIMIT, -LIMIT)
    assert pt(np.nan, 2) == (-LIMIT, 2)
    assert not finite(np.nan, 1) and not finite(None) and finite(np.float32(2), 3)


def test_poly_is_int32_in_range() -> None:
    a = poly([[1.4, 2.6], [1e12, np.nan], [-np.inf, 3]])
    assert a.dtype == np.int32 and a.shape == (3, 2)
    assert a.tolist() == [[1, 3], [LIMIT, -LIMIT], [-LIMIT, 3]]


def test_measurement_picture_with_numpy_and_far_off_keypoints(strict_cv2: list[str]) -> None:
    scene = Scene(np.zeros((200, 300, 3), np.uint8), None, {}, "fixed")  # type: ignore[arg-type]
    obj = {
        "class": "M3x10",
        "polygon": np.array([[10.2, 10.7], [80.5, 12.1], [79.9, 30.3], [11.1, 29.8]]),
        "box": (np.float64(10.2), np.float64(10.7), np.float64(80.5), np.float64(30.3)),
        "length": {"length_mm": 10.0, "length_raw_mm": 10.1, "confidence": 0.9},
        "keypoints": {
            "keypoints": {
                "head_top": [np.float64(12.4), np.float32(20.6)],
                "bearing": [3.0e12, -7.5e11],  # thrown far off the picture: must not fail
                "tip": [float("nan"), 20.0],  # not drawn
            }
        },
    }
    img = draw(scene, {"objects": [obj]}, max_side=2048)
    assert img.shape == (200, 300, 3)
    assert strict_cv2.count("circle") == 2  # head_top and the far-off bearing, not the NaN
    assert img[21, 12].tolist() == [0, 0, 255]  # head_top's red dot at its rounded place


def test_calibration_overlay_with_numpy_float_corners(strict_cv2: list[str]) -> None:
    job = CalibrationJob(photos=None, frame=lambda: None)
    job.phase = "lens"
    job.grid = np.array([[1, 0], [0, 1]], dtype=np.int64)
    job.seen = np.array([[10.4, 20.6], [np.float64(5e11), 3.0], [np.nan, 1.0]], np.float32)
    out = job.draw(np.zeros((120, 160, 3), np.uint8))
    assert out.shape == (120, 160, 3)
    assert strict_cv2.count("rectangle") == 2
    assert strict_cv2.count("circle") == 2  # the NaN corner is skipped
    assert out[21, 10].tolist()[1] > 200  # the green dot at the rounded corner


def test_real_opencv_takes_the_points() -> None:
    img = np.zeros((20, 20, 3), np.uint8)
    for x, y in ((np.float64(5.5), np.float32(6.5)), (np.int64(4), 3.2), (1e13, -1e13)):
        cv2.circle(img, pt(x, y), 2, (255, 255, 255), -1)
        cv2.line(img, pt(x, y), pt(0, 0), (255, 255, 255), 1)
        cv2.putText(img, "a", pt(x, y), cv2.FONT_HERSHEY_SIMPLEX, 0.3, (255, 255, 255), 1)
    cv2.polylines(img, [poly([[1.5, 1.5], [1e12, 2.0], [3.0, np.nan]])], True, (255, 0, 0), 1)
    assert img.any()
