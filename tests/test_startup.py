"""The start-up check (homing, layout, bins, ready) and automatic mode's countdown."""

from __future__ import annotations

import time

import numpy as np

from sortering_pnp.layout import Layout
from sortering_pnp.parts import Part
from sortering_pnp.printer.sim import SimPart, SimPrinter, SimVision, SimWorld
from sortering_pnp.runner import Runner
from sortering_pnp.startup import kind_of, parts_in_bin
from sortering_pnp.transform import Transform2D


def P(cls, xy, length=None, score=0.9, unknown=False):  # noqa: N802
    p = Part(
        1, cls, score, xy, 0.0, np.zeros((0, 2)), 4.0, length, True, unknown, length is not None
    )
    p.bed_xy, p.gap_mm = xy, 10.0
    return p


def _lay() -> Layout:
    lay = Layout.default()
    lay.bins = [b for b in lay.bins if b.marker in (103, 104, 105)] + [lay.work_bin()]
    for b in lay.bins:
        if b.role != "work":
            b.role = "wild"
    return lay


def test_nothing_is_counted_on_the_code():
    lay = _lay()
    b = lay.bin_by_marker(103)
    cx, cy = lay.bin_centre(b)
    mx, my = lay.marker_centre(b)
    parts = [
        P("DIN934_M4", (cx, cy - 8)),
        P("DIN934_M4", (mx + 2, my - 2)),
        P("X", (cx, cy), score=0.2),
    ]
    assert parts_in_bin(lay, b, parts, min_score=0.5) == parts[:1]  # not on the code, not unsure


def test_kind_of_a_bin():
    xy = (0.0, 0.0)
    ps = [P("DIN912_M3", xy, 8.0), P("DIN912_M3", xy, 8.0), P("DIN912_M3", xy), P("DIN934_M3", xy)]
    assert kind_of(ps, "part") == "DIN912_M3x8"
    assert kind_of(ps, "class") == "DIN912_M3"
    assert kind_of([P("DIN912_M3", xy)], "part") == "DIN912_M3"  # length not seen: the class
    assert kind_of([P("UNKNOWN", xy, unknown=True)], "part") == "UNKNOWN"


def _wait_for(runner: Runner, status: str, timeout: float = 30.0) -> None:
    end = time.time() + timeout
    while runner.state.status != status and time.time() < end:
        time.sleep(0.05)
    assert runner.state.status == status, runner.state.message


def test_startup_check_reads_what_each_bin_holds(machine):
    machine.run.startup_check = True
    lay = _lay()
    lay.save(machine.path(machine.paths.layout))
    world = SimWorld(seed=1)
    b104, b103 = lay.bin_by_marker(104), lay.bin_by_marker(103)
    cx, cy = lay.bin_centre(b104)
    for dx in (-8, 0, 8):
        world.parts.append(SimPart("DIN934_M4", cx + dx, cy - 6, 0.0, None, (7.0, 7.0), 3.2))
    mx, my = lay.marker_centre(b103)
    world.parts.append(SimPart("DIN934_M4", mx, my, 0.0, None, (7.0, 7.0), 3.2))  # on the code
    runner = Runner(
        machine, SimPrinter(machine, world), SimVision(world, lambda: lay, Transform2D.identity)
    )
    runner.claims[105], runner.bin_counts[105] = "DIN912_M3x8", 30  # from an earlier session
    runner.claims[103] = "ISO7380_M4x8"
    assert runner.snapshot()["startup"]["started"] is None
    assert runner.command("startup").startswith("start-up check")
    _wait_for(runner, "idle")
    steps = runner.snapshot()["startup"]["steps"]
    assert [s["key"] for s in steps] == ["homing", "layout", "bins", "ready"]
    assert all(s["state"] == "done" for s in steps), steps
    assert runner.claims == {104: "DIN934_M4"} and runner.bin_counts[104] == 3
    assert 105 not in runner.bin_counts  # empty now: a free wild bin
    assert "1 with parts" in steps[2]["detail"] and "2 empty" in steps[2]["detail"]


def test_the_first_run_does_the_check_once(machine):
    machine.run.startup_check = True
    machine.run.shake.enabled = False
    lay = _lay()
    lay.save(machine.path(machine.paths.layout))
    world = SimWorld(seed=1)
    runner = Runner(
        machine, SimPrinter(machine, world), SimVision(world, lambda: lay, Transform2D.identity)
    )
    runner.command("start", "sort")
    _wait_for(runner, "done")
    first = runner.startup.started
    assert first is not None and runner.startup.finished is not None
    runner.command("start", "sort")
    _wait_for(runner, "done")
    assert runner.startup.started == first  # not again


def test_automatic_mode_counts_down(machine):
    machine.standby.interval_s = 30
    lay = _lay()
    lay.save(machine.path(machine.paths.layout))
    world = SimWorld(seed=1)
    runner = Runner(
        machine, SimPrinter(machine, world), SimVision(world, lambda: lay, Transform2D.identity)
    )
    runner.command("auto", "sort")
    _wait_for(runner, "standby")
    end = time.time() + 10
    while runner.snapshot()["next_look_s"] is None and time.time() < end:
        time.sleep(0.05)
    snap = runner.snapshot()
    assert 0 < snap["next_look_s"] <= 30
    assert "next look in 30 s" in snap["message"]
    runner.command("stop")
    runner.wait(10)
    assert runner.snapshot()["next_look_s"] is None
