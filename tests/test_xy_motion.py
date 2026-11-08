"""The X/Y acceleration profile (printer.xy_motion): an acceleration limit per axis (the head X
quicker, the bed Y gentle), the directional acceleration of each move, and an S-shaped speed."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from sortering_pnp import config as config_mod
from sortering_pnp.printer import Motion
from sortering_pnp.printer.base import PrinterStatus
from sortering_pnp.printer.sim import SimPrinter, SimWorld
from sortering_pnp.printer.smooth import s_curve


class FakePrinter:
    def __init__(self, position: list[float], max_accel: float | None = 3000.0) -> None:
        self.st = PrinterStatus(
            state="ready", homed="xyz", position=position, tool="picker", max_accel=max_accel
        )
        self.sent: list[str] = []

    def gcode(self, script: str) -> None:
        self.sent.append(script)

    def status(self, tool_macro=None) -> PrinterStatus:
        return self.st

    def emergency_stop(self) -> None:
        pass

    def close(self) -> None:
        pass


@pytest.fixture(autouse=True)
def _figures(machine, monkeypatch, request):
    """These tests check the maths with round figures: a bed of 1000 mm/s^2 at feed_xy, 8 steps
    a ramp, and Klipper's corners left alone (but in the tests marked `corners`)."""
    xm = machine.printer.xy_motion
    xm.accel_y, xm.max_feed_y, xm.steps = 1000.0, None, 8
    if "corners" not in request.node.name:
        monkeypatch.setattr(Motion, "_corner_velocity", lambda self: 0.0)


def g1(line: str) -> dict[str, float]:
    return {a: float(v) for a, v in re.findall(r"([XYZF])(-?\d+(?:\.\d+)?)", line)}


def moves(script: str) -> list[dict[str, float]]:
    return [g1(ln) for ln in script.splitlines() if ln.startswith("G1 ")]


def test_y_travel_is_an_s_curve_with_lowered_accel(machine):
    fp = FakePrinter([10.0, 0.0, 50.0])
    Motion(fp, machine).move(y=200.0)
    lines = fp.sent[-1].splitlines()
    assert lines[0] == "G90"
    assert lines[1] == "SET_VELOCITY_LIMIT ACCEL=1000"
    assert lines[-1] == "SET_VELOCITY_LIMIT ACCEL=3000"  # set back for X and Z
    ms = moves(fp.sent[-1])
    # 6000 mm/min at 1000 mm/s^2: 7.5 mm ramps, 1 mm steps at least: 7 up, cruise, 7 down
    assert len(ms) == 15
    assert lines[-2] == "G1 Y200.000 F87"  # the exact end point
    assert all(set(m) == {"Y", "F"} for m in ms)  # X and Z do not move
    ys = [m["Y"] for m in ms]
    assert ys == sorted(ys) and ys[-1] == 200.0
    fs = [m["F"] for m in ms]
    peak = fs.index(max(fs))
    assert fs[: peak + 1] == sorted(fs[: peak + 1])  # rises ...
    assert fs[peak:] == sorted(fs[peak:], reverse=True)  # ... and falls
    assert max(fs) == machine.printer.feed_xy
    # S-shaped: the speed steps are small at both ends of the ramp, largest in its middle
    ramp = fs[:7]
    jumps = [b - a for a, b in zip([0.0, *ramp], ramp, strict=False)]
    assert jumps[0] < jumps[3] and jumps[-1] < jumps[3]


def test_s_curve_peak_accel_and_distances():
    steps = s_curve(200.0, 6000.0, 1000.0, 8, 1.0)
    assert steps[-1][0] == pytest.approx(200.0)
    ends = [d for d, _ in steps]
    assert ends == sorted(ends)
    # accelerating from one step's speed to the next never needs more than the peak accel
    prev_v, prev_d = 0.0, 0.0
    for d, f in steps[:8]:
        v = f / 60.0
        assert (v * v - prev_v * prev_v) / (2 * (d - prev_d)) <= 1000.0 * 1.6
        prev_v, prev_d = v, d


def test_short_moves_get_few_or_no_steps(machine):
    assert len(s_curve(5.0, 6000.0, 1000.0, 8, 1.0)) < 8
    assert s_curve(1.0, 6000.0, 1000.0, 8, 1.0) == [(1.0, 6000.0)]
    fp = FakePrinter([10.0, 100.0, 50.0])
    Motion(fp, machine).move(y=101.0)  # a 1 mm nudge: one G1, still at the gentle accel
    assert fp.sent[-1].splitlines() == [
        "G90",
        "SET_VELOCITY_LIMIT ACCEL=1000",
        "G1 Y101.000 F6000",
        "SET_VELOCITY_LIMIT ACCEL=3000",
    ]


def test_xy_move_stays_on_a_straight_line(machine):
    machine.tool.offset = [5.0, -2.0, 0.0]
    fp = FakePrinter([0.0, 0.0, 50.0])
    mo = Motion(fp, machine)
    mo.move(x=105.0, y=148.0)  # tip; toolhead (100, 150): from (0, 0)
    ms = moves(fp.sent[-1])
    assert len(ms) > 3
    for m in ms[:-1]:
        assert m["X"] / 100.0 == pytest.approx(m["Y"] / 150.0, abs=1e-4)
    assert (ms[-1]["X"], ms[-1]["Y"]) == (100.0, 150.0)
    # the bed gets 1000 mm/s^2: the path, which is longer than its Y part, a bit more
    accel = float(fp.sent[-1].splitlines()[1].split("=")[1])
    assert accel == pytest.approx(1000.0 * (100**2 + 150**2) ** 0.5 / 150.0, abs=1)


def test_steps_stay_inside_the_limits(machine):
    machine.printer.limits_y = [0.0, 220.0]
    fp = FakePrinter([0.0, 220.0, 50.0])
    Motion(fp, machine).move(x=220.0, y=0.0)
    for m in moves(fp.sent[-1]):
        assert 0.0 <= m["X"] <= 220.0 and 0.0 <= m["Y"] <= 220.0


def accel_of(script: str) -> float | None:
    """The acceleration a move runs at (its first SET_VELOCITY_LIMIT), None: the printer's."""
    for ln in script.splitlines():
        if ln.startswith("SET_VELOCITY_LIMIT ACCEL="):
            return float(ln.split("=")[1])
    return None


def test_x_moves_get_the_heads_accel_and_an_s_curve(machine):
    fp = FakePrinter([10.0, 20.0, 50.0])
    mo = Motion(fp, machine)
    mo.move(x=150.0)  # accel_x 3000 = the printer's own: nothing to set, still an S
    assert accel_of(fp.sent[-1]) is None
    ms = moves(fp.sent[-1])
    assert len(ms) > 1 and all(set(m) == {"X", "F"} for m in ms)
    assert fp.sent[-1].splitlines()[-1].startswith("G1 X150.000 F")  # the exact end point
    machine.printer.xy_motion.accel_x = 2000.0
    mo.move(x=10.0, y=20.0)  # Y given but not changing: an X move
    lines = fp.sent[-1].splitlines()
    assert lines[1] == "SET_VELOCITY_LIMIT ACCEL=2000"
    assert lines[-1] == "SET_VELOCITY_LIMIT ACCEL=3000"  # set back after the move


def test_z_moves_are_unchanged(machine):
    fp = FakePrinter([10.0, 20.0, 50.0])
    Motion(fp, machine).move(z=10.0)
    assert fp.sent[-1] == "G90\nG1 Z10.000 F1200"


@pytest.mark.parametrize(
    ("dx", "dy", "want"),
    [
        (0.0, 150.0, 1000.0),  # pure Y: the bed's limit
        (150.0, 0.0, 2000.0),  # pure X: the head's limit
        (100.0, 150.0, 1000.0 * (100**2 + 150**2) ** 0.5 / 150.0),  # Y binds: 1202
        (150.0, 10.0, 2000.0 * (150**2 + 10**2) ** 0.5 / 150.0),  # X binds: 2004
    ],
)
def test_each_axis_stays_within_its_limit(machine, dx, dy, want):
    machine.printer.xy_motion.accel_x = 2000.0
    fp = FakePrinter([10.0, 20.0, 50.0], max_accel=10000.0)
    mo = Motion(fp, machine)
    assert mo.xy_accel(dx, dy) == pytest.approx(want)
    mo.move(x=10.0 + dx, y=20.0 + dy)
    a = accel_of(fp.sent[-1])
    assert a == pytest.approx(want, abs=0.5)
    length = (dx * dx + dy * dy) ** 0.5
    assert a * dx / length <= 2000.0 + 0.5 and a * dy / length <= 1000.0 + 0.5


def test_carrying_a_part_is_gentler_on_x_only(machine):
    """The part hangs on the head (X): only accel_x is lowered while it is held."""
    machine.printer.xy_motion.carrying = 0.6
    machine.printer.accel = 3000.0
    pr = SimPrinter(machine, SimWorld())
    pr.gcode("G28")
    mo = Motion(pr, machine)
    mo.move(z=50.0)
    mo.pick(100.0, 100.0, 1.0)
    assert mo.carrying
    assert mo.xy_accel(80.0, 0.0) == pytest.approx(1800.0)  # head: 0.6 x 3000
    assert mo.xy_accel(0.0, 80.0) == pytest.approx(1000.0)  # bed: unchanged
    pr.log.clear()
    mo.travel(100.0, 180.0)  # to the bin along Y, with the part: the bed's own 1000
    assert "SET_VELOCITY_LIMIT ACCEL=1000" in pr.log
    assert "SET_VELOCITY_LIMIT ACCEL=600" not in pr.log
    mo.drop(100.0, 180.0, 20.0)
    assert not mo.carrying
    assert mo.xy_accel(80.0, 0.0) == pytest.approx(3000.0)


def test_disabled_is_the_old_single_move(machine):
    machine.printer.xy_motion.enabled = False
    fp = FakePrinter([10.0, 0.0, 50.0])
    mo = Motion(fp, machine)
    mo.move(y=200.0)
    assert fp.sent[-1] == "G90\nG1 Y200.000 F6000"
    mo.move(x=150.0, y=20.0)
    assert fp.sent[-1] == "G90\nG1 X150.000 Y20.000 F6000"
    assert not any("SET_VELOCITY_LIMIT" in s for s in fp.sent)


def test_trapezoid_profile_and_max_feed(machine):
    ym = machine.printer.xy_motion
    ym.profile = "trapezoid"
    ym.max_feed_y = 3000.0
    fp = FakePrinter([10.0, 0.0, 50.0])
    Motion(fp, machine).move(y=200.0)
    assert fp.sent[-1].splitlines() == [
        "G90",
        "SET_VELOCITY_LIMIT ACCEL=1000",
        "G1 Y200.000 F3000",
        "SET_VELOCITY_LIMIT ACCEL=3000",
    ]


def test_printer_accel_is_the_one_restored(machine):
    machine.printer.accel = 2000.0
    fp = FakePrinter([10.0, 0.0, 50.0], max_accel=None)
    Motion(fp, machine).move(y=50.0)
    assert fp.sent[-1].splitlines()[-1] == "SET_VELOCITY_LIMIT ACCEL=2000"
    machine.printer.accel = None
    fp = FakePrinter([10.0, 0.0, 50.0], max_accel=None)  # unknown: left lowered (safe side)
    Motion(fp, machine).move(y=50.0)
    lines = fp.sent[-1].splitlines()
    assert lines[1] == "SET_VELOCITY_LIMIT ACCEL=1000" and "ACCEL" not in lines[-1]


def test_gentle_accel_never_above_the_normal_one(machine):
    machine.printer.xy_motion.accel_y = 5000.0
    fp = FakePrinter([10.0, 0.0, 50.0])
    Motion(fp, machine).move(y=100.0)
    assert "SET_VELOCITY_LIMIT" not in fp.sent[-1]


def test_shake_keeps_its_sharp_moves(machine):
    fp = FakePrinter([0.0, 200.0, 60.0])
    Motion(fp, machine).shake()
    shake = fp.sent[-1]
    assert "SET_VELOCITY_LIMIT" not in shake
    assert f"G1 Y4.00 F{machine.run.shake.feed:.0f}" in shake


def test_sim_follows_and_ends_exactly(machine):
    pr = SimPrinter(machine, SimWorld())
    pr.gcode("G28")
    mo = Motion(pr, machine)
    mo.move(z=50.0)
    mo.move(x=37.5, y=181.25)
    assert pr.pos[:2] == [37.5, 181.25]
    assert pr.accel == 3000.0
    assert "SET_VELOCITY_LIMIT ACCEL=1021" in pr.log  # 1000 for the bed: Y is 98% of the path


def test_config_checks_the_profile(tmp_path):
    p = tmp_path / "m.yaml"
    p.write_text("printer:\n  xy_motion:\n    profile: jerk\n", encoding="utf-8")
    with pytest.raises(config_mod.ConfigError, match="profile"):
        config_mod.load(p)
    p.write_text("printer:\n  xy_motion:\n    carrying: 0\n", encoding="utf-8")
    with pytest.raises(config_mod.ConfigError, match="carrying"):
        config_mod.load(p)
    p.write_text("printer:\n  xy_motion:\n    accel_x: 2500\n    accel_y: 600\n", encoding="utf-8")
    xm = config_mod.load(p).printer.xy_motion
    assert (xm.accel_x, xm.accel_y, xm.enabled) == (2500, 600, True)


def test_an_old_y_motion_is_read_as_xy_motion(tmp_path):
    p = tmp_path / "m.yaml"
    p.write_text(
        "printer:\n  y_motion:\n    accel: 600\n    max_feed: 3000\n    profile: trapezoid\n",
        encoding="utf-8",
    )
    xm = config_mod.load(p).printer.xy_motion
    assert (xm.accel_y, xm.max_feed_y, xm.profile) == (600, 3000, "trapezoid")
    assert xm.accel_x == 3000.0  # the head keeps its default


def test_the_bed_ramps_like_a_mill_by_default(tmp_path):
    """Defaults (and machine.yaml): long, soft ramps for the bed; the head as Klipper's."""
    xm = config_mod.XYMotion()
    assert (xm.accel_y, xm.max_feed_y, xm.steps, xm.accel_x) == (200.0, 3000.0, 12, 3000.0)
    m = config_mod.load(Path(__file__).resolve().parents[1] / "configs" / "machine.yaml")
    assert (m.printer.xy_motion.accel_y, m.printer.xy_motion.max_feed_y) == (200.0, 3000.0)
    assert not m.standby.motors_off  # no homing (a sharp stop of the bed) between looks
    # 50 mm/s at 200 mm/s^2 along an S: the ramp takes 0.375 s and 9.4 mm, in 9 steps
    ramp = [f for _, f in s_curve(200.0, 3000.0, 200.0, 12, 1.0)][:9]
    assert ramp == sorted(ramp) and ramp[-1] < 3000.0


def test_bed_moves_take_no_corners_at_speed(machine):
    """Z then Y: Klipper would run the corner at its square corner velocity, a jump in the
    bed's speed; bed moves are sent with SQUARE_CORNER_VELOCITY=0 and it is set back after."""
    pr = SimPrinter(machine, SimWorld())
    pr.gcode("G28")
    mo = Motion(pr, machine)
    mo.move(z=50.0)
    pr.log.clear()
    mo.move(y=150.0)
    log = pr.log
    i0 = log.index("SET_VELOCITY_LIMIT SQUARE_CORNER_VELOCITY=0")
    i1 = log.index("SET_VELOCITY_LIMIT SQUARE_CORNER_VELOCITY=5")
    g1s = [i for i, ln in enumerate(log) if ln.startswith("G1 ")]
    assert i0 < min(g1s) and i1 > max(g1s) and pr.scv == 5.0
    pr.log.clear()
    mo.move(x=150.0)  # the head alone: corners left as they are
    assert not any("SQUARE_CORNER_VELOCITY" in ln for ln in pr.log)


def test_homing_moves_the_bed_gently_corners(machine):
    machine.printer.xy_motion.accel_y = 200.0
    pr = SimPrinter(machine, SimWorld())
    Motion(pr, machine).home()
    log = pr.log
    g28 = log.index("G28")
    assert log[:g28] == [
        "SET_VELOCITY_LIMIT ACCEL=200",
        "SET_VELOCITY_LIMIT SQUARE_CORNER_VELOCITY=0",
    ]
    assert log[g28 + 1 :] == [
        "SET_VELOCITY_LIMIT SQUARE_CORNER_VELOCITY=5",
        "SET_VELOCITY_LIMIT ACCEL=3000",
    ]
    assert (pr.accel, pr.scv) == (3000.0, 5.0)
