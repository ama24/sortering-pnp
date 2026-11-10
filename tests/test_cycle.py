"""One sorting cycle: photo (parked, picker empty) -> pick -> drop -> park -> next photo."""

from __future__ import annotations

import time

from sortering_pnp import config as config_mod
from sortering_pnp.layout import Layout
from sortering_pnp.printer.sim import SimPrinter, SimVision, SimWorld
from sortering_pnp.runner import Runner
from sortering_pnp.transform import Transform2D


def make(machine, n: int = 5):
    lay = Layout.default()
    lay.save(machine.path(machine.paths.layout))
    world = SimWorld(seed=4)
    world.populate(lay, n=n)
    vision = SimVision(world, lambda: lay, Transform2D.identity)
    printer = SimPrinter(machine, world)
    return Runner(machine, printer, vision), world, printer, vision


def _log_photos(printer: SimPrinter, vision: SimVision) -> None:
    """Each photo leaves a line in the printer's log: where the head was, what it held."""
    snap = vision.snap

    def logged(name):  # noqa: ANN001, ANN202
        x, y = printer.pos[:2]
        held = "held" if vision.world.held is not None else "empty"
        printer.log.append(f"; photo X{x:.1f} Y{y:.1f} {held}")
        return snap(name)

    vision.snap = logged  # type: ignore[method-assign]


def test_photo_pick_drop_park_photo(machine):
    machine.run.shake.enabled = False
    machine.run.scan_bins_on_start = machine.run.only_seen_bins = False  # no bins photo first
    runner, world, printer, vision = make(machine, n=2)
    _log_photos(printer, vision)
    runner.command("start", "sort")
    runner.wait(60)
    assert runner.state.status == "done", runner.state.message
    assert len(world.dropped) == 2
    px, py = machine.printer.photo_position[:2]
    parked = f"; photo X{px:.1f} Y{py:.1f} empty"
    steps = [
        line
        for line in printer.log
        if line.startswith("; photo") or line in ("; pins grab", "; pins release")
    ]
    # every photo parked, picker empty; two cycles and the last look (plate empty: done)
    expect = [parked, "; pins grab", "; pins release"] * 2 + [parked]
    assert steps == expect, steps
    assert all(h is None for h in vision.snaps)
    assert runner.state.timing["cycle_s"] >= 0


def test_a_failed_pick_is_seen_on_the_next_photo(machine):
    machine.run.shake.enabled = False
    machine.run.max_failed_picks = 1
    runner, world, printer, vision = make(machine, n=1)
    world.grab_radius_mm = 0.0  # the picker misses
    world.parts[0].x += 0.5
    runner.command("start")
    end = time.time() + 30
    while runner.state.status != "stuck" and time.time() < end:
        time.sleep(0.05)
    assert runner.state.failed_picks == 1 and runner.state.status == "stuck"
    assert any("missed" in line for line in runner.console)
    runner.command("stop")
    runner.wait(10)


def test_retired_settings_still_load(tmp_path):
    p = tmp_path / "machine.yaml"
    p.write_text("run:\n  pipeline: true\nstandby:\n  settle_s: 8\n", encoding="utf-8")
    m = config_mod.load(p)
    assert not hasattr(m.run, "pipeline") and not hasattr(m.standby, "settle_s")


def _tip_z_after_each_line(machine, printer: SimPrinter) -> list[tuple[str, float]]:
    """Each logged line with the tip Z after it (absolute G1 moves; offset added back)."""
    oz = machine.tool.offset[2]
    z = float("nan")
    out = []
    for line in printer.log:
        if line.startswith("G1") or line.startswith("G0"):
            for w in line.split()[1:]:
                if w.startswith("Z"):
                    z = float(w[1:]) + oz
        out.append((line, z))
    return out


def test_no_rise_above_travel_z_after_a_drop(machine):
    """After the drop the head parks for the next photo at the travel height: no extra Z."""
    machine.run.shake.enabled = False
    machine.run.scan_bins_on_start = machine.run.only_seen_bins = False
    assert machine.printer.photo_position[2] > machine.printer.travel_z  # the old extra rise
    runner, world, printer, vision = make(machine, n=2)
    _log_photos(printer, vision)
    runner.command("start", "sort")
    runner.wait(60)
    assert runner.state.status == "done", runner.state.message
    lines = _tip_z_after_each_line(machine, printer)
    first_drop = next(i for i, (line, _) in enumerate(lines) if line == "; pins release")
    tz = machine.printer.travel_z
    highest = max(z for _, z in lines[first_drop:] if z == z)
    assert highest <= tz + 1e-3, highest
    photos = [z for line, z in lines if line.startswith("; photo")]
    assert photos and all(abs(z - tz) < 1e-3 for z in photos), photos


def test_photo_position_moves_in_xy_only_at_travel_height(machine):
    from sortering_pnp.printer.motion import Motion

    printer = SimPrinter(machine, SimWorld(seed=1))
    printer.gcode("G28")
    motion = Motion(printer, machine)
    tz = machine.printer.travel_z
    motion.move(100.0, 100.0, tz)
    printer.log.clear()
    motion.photo_position()
    assert motion.current_tip() == [*machine.printer.photo_position[:2], tz]
    assert not any(" Z" in line for line in printer.log if line.startswith("G1")), printer.log
    # from lower down it only rises to the travel height, never to photo_position's Z
    motion.move(z=tz - 20)
    motion.photo_position()
    assert motion.current_tip()[2] == tz


def test_photo_position_waits_for_the_bed_to_stop_shaking(machine):
    from sortering_pnp.printer.motion import Motion

    machine.printer.photo_settle_s = 0.7
    printer = SimPrinter(machine, SimWorld(seed=1))
    printer.gcode("G28")
    motion = Motion(printer, machine)
    motion.move(100.0, 100.0, machine.printer.travel_z)
    printer.log.clear()
    motion.photo_position()
    g1 = max(i for i, line in enumerate(printer.log) if line.startswith("G1"))
    dwell = printer.log.index("G4 P700")
    assert dwell > g1 and "M400" in printer.log[dwell + 1 :]
    printer.log.clear()
    motion.photo_position()  # already there: nothing shakes, no wait
    assert not any(line.startswith("G4") for line in printer.log)


def test_photo_is_a_frame_taken_after_the_move(machine, tmp_path):
    import threading

    import cv2
    import numpy as np

    from sortering_pnp.vision import CameraVision

    frames = iter([np.zeros((4, 4, 3), np.uint8), np.full((4, 4, 3), 200, np.uint8)])
    cam = type("Cam", (), {"grab": lambda self: (next(frames), {})})()
    vision = CameraVision.__new__(CameraVision)
    vision._cam_lock = threading.Lock()
    vision._camera = lambda: cam
    path = tmp_path / "photo.jpg"
    vision._snap(path)
    assert cv2.imread(str(path)).mean() > 150  # the stale first frame was thrown away


def test_photo_position_z_when_asked_and_for_the_head_camera(machine):
    from sortering_pnp.printer.motion import Motion

    pz = machine.printer.photo_position[2]
    for keep, source in ((False, "overview"), (True, "head")):
        machine.printer.photo_at_travel_z = keep
        machine.camera.source = source
        printer = SimPrinter(machine, SimWorld(seed=1))
        printer.gcode("G28")
        motion = Motion(printer, machine)
        motion.move(100.0, 100.0, machine.printer.travel_z)
        motion.photo_position()
        assert motion.current_tip()[2] == pz, (keep, source)
