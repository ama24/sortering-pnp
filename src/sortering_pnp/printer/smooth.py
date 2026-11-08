"""The X/Y acceleration profile: the speed profile of a move that changes X or Y.

Klipper has one acceleration for all axes and only trapezoidal ramps. For an X/Y move Motion
sets the acceleration that keeps each axis within its own limit (SET_VELOCITY_LIMIT) and, with
the `s_curve` profile, splits the straight move
into short G1 steps whose speeds follow a smooth S: v(t) = V * (3u^2 - 2u^3), u = t / T, so the
speed starts and ends with no jump in acceleration. Klipper's lookahead runs the steps without
stopping between them and ramps between their speeds at the lowered acceleration, which is the
curve's peak: the steps follow the S closely.
"""

from __future__ import annotations

import math

# the smoothstep ramp from 0 to V in time T: peak acceleration 1.5 V / T, distance V T / 2
_PEAK = 1.5


def _smooth(u: float) -> float:
    return u * u * (3.0 - 2.0 * u)


def _ramp_distance(u: float) -> float:
    """Distance covered by the ramp up to u = t / T, in units of V * T."""
    return u**3 - u**4 / 2.0


def path_limits(
    length: float,
    parts: list[tuple[float, float, float | None]],
    feed: float,
) -> tuple[float, float]:
    """Feed (mm/min) and acceleration (mm/s^2) along a straight move of `length` mm, so that each
    axis in `parts` (its part of the move in mm, its acceleration limit, its max feed or None)
    stays within its limits: the path's acceleration is the largest whose part along every axis
    is at most that axis' limit, i.e. min(limit / share) over the axes that move."""
    a, f = math.inf, feed
    for d, accel, max_feed in parts:
        share = abs(d) / length if length > 0 else 0.0
        if share < 1e-9:
            continue
        a = min(a, accel / share)
        if max_feed is not None:
            f = min(f, max_feed / share)
    if math.isinf(a):  # no axis of `parts` moves
        a = min(accel for _, accel, _ in parts)
    return f, a


def s_curve(
    length: float, feed: float, accel: float, steps: int, min_step_mm: float
) -> list[tuple[float, float]]:
    """Steps of an S-shaped speed profile along a move of `length` mm at `feed` mm/min with peak
    acceleration `accel` mm/s^2: (distance from the start at the step's end, feed in mm/min).
    The last distance is `length`. Short moves get fewer steps, or one (the plain move)."""
    if length <= 0:
        return [(length, feed)]
    v = feed / 60.0
    v = min(v, math.sqrt(length * accel / _PEAK))  # both ramps (v T together) fit in the move
    ramp_time = _PEAK * v / accel
    ramp = v * ramp_time / 2.0  # distance of one ramp
    n = min(steps, int(ramp / min_step_mm + 1e-9))
    if n < 2:
        return [(length, feed)]
    up = [
        (2 * ramp * _ramp_distance(k / n), 60.0 * v * _smooth((k - 0.5) / n))
        for k in range(1, n + 1)
    ]
    out = list(up)
    if length - 2 * ramp > 1e-6:
        out.append((length - ramp, 60.0 * v))  # cruise
    # down: the mirror of the ramp up
    ends = [length - d for d, _ in reversed(up[:-1])] + [length]
    speeds = [f for _, f in reversed(up)]
    out += list(zip(ends, speeds, strict=True))
    return out
