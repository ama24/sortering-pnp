"""Every start on a real printer begins with an empty grid (bed.cols x bed.rows, 5 x 5 by
default): no bins, claims or counts from an earlier session."""

from __future__ import annotations

from sortering_pnp.layout import Layout
from sortering_pnp.printer.sim import SimPrinter, SimVision, SimWorld
from sortering_pnp.runner import Runner
from sortering_pnp.transform import Transform2D


def test_the_default_grid_is_5_by_5(machine):
    assert (machine.bed.cols, machine.bed.rows) == (5, 5)


def test_a_new_session_starts_with_no_bins(machine):
    lay = Layout.default()
    lay.plate_thickness_mm = 2.0
    lay.save(machine.path(machine.paths.layout))
    world = SimWorld()
    runner = Runner(
        machine, SimPrinter(machine, world), SimVision(world, lambda: lay, Transform2D.identity)
    )
    assert runner.layout().bins
    runner.claims[101], runner.bin_counts[101] = "DIN912_M3", 4
    runner.packing.add("screw", 0.4)
    machine.bed.cols, machine.bed.rows = 6, 4  # a bigger machine, set in machine.yaml
    runner.fresh_session()
    fresh = runner.layout()
    assert fresh.bins == [] and fresh.away == [] and fresh.work_marker is None
    assert (fresh.cols, fresh.rows) == (6, 4)
    assert fresh.plate_thickness_mm == 2.0  # the settings stay
    assert runner.claims == {} and runner.bin_counts == {}
    again = Runner(machine, SimPrinter(machine, world), runner.vision)  # read back from disk
    assert again.claims == {} and again.packing.samples  # the learnt packing stays
