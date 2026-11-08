"""Buttons that act at once: Recheck, Resync and Change bin stop what runs (after the move in
progress) and automatic mode carries on; every photo shows on the page as soon as it is taken."""

from __future__ import annotations

import time

from sortering_pnp.binswap import BinRequest
from sortering_pnp.layout import Layout
from sortering_pnp.printer.sim import SimPrinter, SimVision, SimWorld
from sortering_pnp.runner import Runner
from sortering_pnp.transform import Transform2D


def _lay() -> Layout:
    lay = Layout.default()
    lay.bins = [b for b in lay.bins if b.marker in (103, 104, 105)] + [lay.work_bin()]
    for b in lay.bins:
        if b.role != "work":
            b.role = "wild"
    return lay


def _runner(machine, out=None) -> tuple[Runner, SimVision]:
    lay = _lay()
    lay.save(machine.path(machine.paths.layout))
    world = SimWorld(seed=1)
    vision = SimVision(world, lambda: lay, Transform2D.identity, out)
    return Runner(machine, SimPrinter(machine, world), vision), vision


def _until(cond, timeout: float = 20.0) -> None:
    end = time.time() + timeout
    while not cond() and time.time() < end:
        time.sleep(0.05)
    assert cond()


def _standby(machine) -> Runner:
    machine.standby.interval_s = 60  # it would wait a minute
    runner, _ = _runner(machine)
    runner.command("auto", "sort")
    _until(lambda: runner.state.status == "standby" and runner.snapshot()["next_look_s"])
    return runner


def test_recheck_while_automatic_mode_stands_by(machine):
    runner = _standby(machine)
    t0 = time.time()
    assert runner.command("startup").startswith("start-up check")
    _until(lambda: runner.startup.finished is not None)
    assert time.time() - t0 < 10  # not after the minute of standby
    assert all(s["state"] == "done" for s in runner.startup.steps)
    _until(lambda: runner.state.status == "standby")  # automatic mode carries on
    assert runner.saved_mode()[0]
    runner.command("stop")
    runner.wait(10)


def test_recheck_while_idle(machine):
    runner, _ = _runner(machine)
    runner.command("startup")
    runner.wait(20)
    assert runner.state.status == "idle" and runner.startup.finished is not None


def test_resync_while_running_takes_over(machine):
    runner = _standby(machine)
    res = runner.scan_bins()
    assert "resync" in res["queued"]
    _until(lambda: any("resync:" in e for e in runner.events))
    _until(lambda: runner.state.status == "standby")
    runner.command("stop")
    runner.wait(10)


def test_change_bin_while_automatic_mode_stands_by(machine):
    runner = _standby(machine)
    runner.requests.append(BinRequest(104, "E1", "full", "B", 30))
    runner.bin_counts[104] = 30
    assert runner.command("change") == "parking"
    _until(lambda: runner.swap_phase == "parked" and runner.state.status == "parked", 5)
    assert runner.command("change") == "checking the bins"
    _until(lambda: not runner.requests, 10)  # the same bin back: emptied
    assert 104 not in runner.bin_counts
    _until(lambda: runner.state.status == "standby")
    runner.command("stop")
    runner.wait(10)


def test_every_photo_shows_before_the_model_has_looked(machine, tmp_path):
    runner, vision = _runner(machine, tmp_path / "runs")
    shown = []
    real = vision.analyse

    def analyse(*a, **k):  # the page already has the photo while the model looks
        shown.append(runner.state.view)
        return real(*a, **k)

    vision.analyse = analyse
    runner.printer.gcode("G28")
    runner.take_shot(runner.layout(), Transform2D.identity(), area="bins", paint=False)
    assert vision.previews and shown and shown[0] and shown[0].endswith("_view.jpg")
    s = runner.snapshot()
    assert s["shot_age_s"] is not None and s["shot_age_s"] < 5
    cells = {m["marker"]: m["cell"] for m in s["markers"]}
    assert cells[103] and cells[104]  # the codes, with their bins' cells


def test_the_page_is_told_what_really_runs(machine):
    """Automatic mode remembered from the last stop is not automatic mode running: after a
    restart that did not start it (Setup unfinished) the page must not show it as on."""
    runner, _ = _runner(machine)
    runner._save_mode(True, "sort")  # on at the last stop, not running now
    s = runner.snapshot()
    assert (s["mode"], s["auto"], s["auto_saved"]) == ("", False, True)
    machine.standby.interval_s = 60
    runner.command("auto", "sort")
    _until(lambda: runner.state.status == "standby")
    assert runner.snapshot()["mode"] == "auto" and runner.snapshot()["auto"]
    runner.command("stop")
    runner.wait(10)
    s = runner.snapshot()
    assert (s["mode"], s["auto"], s["auto_saved"]) == ("", False, False)
    runner.command("step")
    assert runner.snapshot()["mode"] == "step"
    runner.wait(20)
    assert runner.snapshot()["mode"] == ""
