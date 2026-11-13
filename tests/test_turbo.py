"""Speed and mode (Device tab): the speed slider scales every move; turbo makes several picks
from one photo and analyses the next photo while it goes on picking."""

from __future__ import annotations

import copy
import time

import pytest

from sortering_pnp.layout import Layout
from sortering_pnp.printer.sim import SimPrinter, SimVision, SimWorld
from sortering_pnp.runner import Runner
from sortering_pnp.transform import Transform2D


def make(machine, n: int = 12, seed: int = 5, delay_s: float = 0.0):
    machine.run.shake.enabled = False
    lay = Layout.default()
    lay.bins = [b for b in lay.bins if b.role in ("wild", "work", "unknown", "unsure")]
    lay.save(machine.path(machine.paths.layout))
    world = SimWorld(seed=seed)
    world.populate(lay, n=n)
    vision = SimVision(world, lambda: lay, Transform2D.identity)
    vision.delay_s = delay_s
    return Runner(machine, SimPrinter(machine, world), vision), world, vision


def _sort(runner: Runner) -> None:
    runner.command("start", "sort")
    runner.wait(60)
    assert runner.state.status == "done", runner.state.message


def test_turbo_sorts_everything_with_fewer_photos(machine):
    runner, world, vision = make(machine)
    runner.set_mode("turbo", 4)
    machine.run.turbo_keep_away_mm = 0.0  # every part from the list (the sim's parts never move)
    _sort(runner)
    picks = len(world.dropped)
    assert picks == 12 and not world.parts
    assert len(vision.previews) <= picks // 4 + 3  # a photo per 4 picks, not per pick
    assert runner.state.picks == 12 and runner.state.failed_picks == 0  # each pick checked
    assert sum(runner.bin_counts.values()) == 12


def test_single_mode_takes_a_photo_per_pick(machine):
    runner, world, vision = make(machine)
    assert machine.run.mode == "single"
    _sort(runner)
    assert len(world.dropped) == 12 and len(vision.previews) >= 12


def test_turbo_keeps_away_from_parts_near_a_pick(machine):
    """Parts near a pick made since their photo may have been nudged: they wait for the next
    photo. With a huge keep-away every photo gives one pick."""
    runner, world, vision = make(machine, n=6)
    runner.set_mode("turbo", 5)
    machine.run.turbo_keep_away_mm = 1000.0
    _sort(runner)
    assert len(world.dropped) == 6 and len(vision.previews) >= 6


def test_turbo_picks_while_the_photo_is_analysed(machine):
    runner, world, vision = make(machine, delay_s=0.4)
    runner.set_mode("turbo", 3)
    machine.run.turbo_keep_away_mm = 0.0
    held_at_snap = []
    snap = vision.snap

    def counting_snap(name):
        held_at_snap.append(len(world.dropped))
        return snap(name)

    vision.snap = counting_snap
    _sort(runner)
    assert len(world.dropped) == 12
    # between two photos it did not wait for the analysis: more picks than one photo's worth
    # happened before the analyses were all done (the photos were taken every 3 picks)
    gaps = [b - a for a, b in zip(held_at_snap, held_at_snap[1:], strict=False)]
    assert any(g >= 3 for g in gaps)


def test_a_missed_pick_in_turbo_is_found_by_the_next_photo(machine):
    runner, world, _ = make(machine, n=6)
    runner.set_mode("turbo", 3)
    machine.run.turbo_keep_away_mm = 0.0
    grab = world.grab
    missed = []

    def flaky(tip):
        if not missed:  # the first grab slips
            missed.append(tip)
            return
        grab(tip)

    world.grab = flaky
    _sort(runner)
    assert not world.parts and len(world.dropped) == 6
    assert runner.state.failed_picks == 1  # found by the photo after it, and picked again
    assert sum(runner.bin_counts.values()) == 6  # the missed one counted once, when it worked


def test_the_mode_can_change_while_sorting(machine):
    runner, world, _ = make(machine, n=10, delay_s=0.05)
    runner.set_mode("turbo", 3)
    runner.command("start", "sort")
    end = time.time() + 10
    while len(world.dropped) < 3 and time.time() < end:
        time.sleep(0.02)
    runner.set_mode("single")
    runner.wait(60)
    assert runner.state.status == "done" and not world.parts


def test_speed_and_mode_are_checked_and_kept(machine):
    runner, _, vision = make(machine, n=1)
    with pytest.raises(ValueError):
        runner.set_speed(20)
    with pytest.raises(ValueError):
        runner.set_mode("warp")
    st = runner.set_speed(150)
    assert st["pct"] == 150 and runner.snapshot()["speed"]["pct"] == 150
    runner.set_mode("turbo", 7)
    fresh = copy.deepcopy(machine)  # after a restart
    fresh.run.speed_pct, fresh.run.mode, fresh.run.turbo_picks = 100.0, "single", 5
    again = Runner(fresh, SimPrinter(fresh, SimWorld()), vision)
    assert again.speed_state() == {
        "pct": 150,
        "range": [50.0, 300.0],
        "mode": "turbo",
        "turbo_picks": 7,
    }


def test_klipper_capping_z_is_said_once(machine):
    runner, _, _ = make(machine, n=1)
    runner.printer.z_velocity_limit = lambda: 5.0  # an Ender 3's printer.cfg
    runner._z_limit_note()  # noqa: SLF001
    runner._z_limit_note()  # noqa: SLF001
    said = [e for e in runner.events if "Klipper caps Z at 5 mm/s" in e]
    assert len(said) == 1
