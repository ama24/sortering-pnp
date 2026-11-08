"""Points for OpenCV's drawing calls (circle, line, rectangle, putText, ...).

OpenCV 5 takes a point only as two plain ints that fit in 32 bits: a float (Python or numpy)
or a bigger int fails with "Can't parse 'center'. Sequence item with index 0 has a wrong type".
Every point drawn goes through `pt`, every polygon through `poly`.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

LIMIT = 1 << 20  # px: far outside any picture, well inside OpenCV's int range


def _coord(v: Any) -> int:
    f = float(v)
    if not math.isfinite(f):
        return -LIMIT if math.isnan(f) or f < 0 else LIMIT  # NaN: off the picture
    return max(-LIMIT, min(LIMIT, round(f)))


def pt(x: Any, y: Any) -> tuple[int, int]:
    """(x, y) rounded to plain ints and kept within OpenCV's range (far-off points stay off
    the picture)."""
    return _coord(x), _coord(y)


def poly(points: Any) -> np.ndarray:
    """An (N, 2) int32 array for polylines/fillPoly: rounded, within the same range."""
    a = np.nan_to_num(np.asarray(points, dtype=float).reshape(-1, 2), nan=-LIMIT)
    return np.round(np.clip(a, -LIMIT, LIMIT)).astype(np.int32)


def finite(*values: Any) -> bool:
    """All values are finite numbers (worth drawing)."""
    try:
        return all(math.isfinite(float(v)) for v in values)
    except (TypeError, ValueError):
        return False
