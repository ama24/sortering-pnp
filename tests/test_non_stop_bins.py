"""The machine keeps going while there is room: a new length shares the bin of its class, and a
bin that was covered when the run started is used once the camera sees it."""

from __future__ import annotations

import time

import numpy as np
import pytest

from sortering_pnp.layout import Bin, Layout
from sortering_pnp.parts import Part
from sortering_pnp.printer.sim import SimPart, SimPrinter, SimVision, SimWorld
from sortering_pnp.rules import claim_class, destination
from sortering_pnp.runner import Runner
from sortering_pnp.transform import Transform2D


def P(cls, length=None):  # noqa: N802
    p = Part(
        1,
        cls,
        0.9,
        (110.0, 110.0),
        0.0,
        np.zeros((0, 2)),
        4.0,
        length,
        True,
        False,
        length is not None,
    )
    p.bed_xy, p.gap_mm = (110.0, 110.0), 10.0
    return p


def _lay() -> Layout:
    lay = Layout(wild_by="part")
    lay.bins = [Bin(marker=100 + i, x=i, y=0) for i in range(2)]
    return lay


def test_claim_class():
    assert claim_class("DIN912_M2x8") == "DIN912_M2"
    assert claim_class("DIN912_M2.5x12.5") == "DIN912_M2.5"
    assert claim_class("DIN934_M2") == "DIN934_M2"


@pytest.mark.parametrize(
    ("share", "part", "bin_"),
    [
        ("class", P("DIN912_M2", 5.0), 100),  # another length: in with M2x8
        ("class", P("DIN912_M3", 5.0), None),  # another size: not by class
        ("family", P("DIN912_M3", 5.0), 100),
        ("none", P("DIN912_M2", 5.0), None),
    ],
)
def test_a_new_kind_shares_a_wild_bin_of_its_class(share, part, bin_):
    lay = _lay()
    claims = {100: "DIN912_M2x8", 101: "DIN933_M2x12"}
    dec = destination(part, lay, 0.5, claims, (), ask=True, share=share)
    if bin_ is None:
        assert dec.bin is None and dec.needs == ("new", part.cls + "x5")
    else:
        assert dec.bin.marker == bin_ and dec.claim is None and "in with DIN912_M2x8" in dec.reason


def test_a_full_bin_is_not_shared():
    dec = destination(P("DIN912_M2", 5.0), _lay(), 0.5, {100: "DIN912_M2x8"}, (100,), True, "class")
    assert dec.bin.marker == 101 and dec.claim == "DIN912_M2x5"  # the free one
    dec = destination(
        P("DIN912_M2", 5.0), _lay(), 0.5, {100: "DIN912_M2x8", 101: "X"}, (100,), True, "class"
    )
    assert dec.bin is None and dec.needs == ("new", "DIN912_M2x5")


def _wait_for(runner: Runner, status: str, timeout: float = 30.0) -> None:
    end = time.time() + timeout
    while runner.state.status != status and time.time() < end:
        time.sleep(0.05)
    assert runner.state.status == status, runner.state.message


def test_a_bin_covered_at_the_start_is_used_once_seen(machine):
    machine.run.fill.take_out_at = 0.0  # any bin with something in it may go (the old rule)
    machine.run.shake.enabled = False
    machine.standby.interval_s = 0.3
    lay = Layout.default()
    lay.bins = [b for b in lay.bins if b.marker in (103, 104, 105)] + [lay.work_bin()]
    for b in lay.bins:
        if b.role != "work":
            b.role = "wild"
    lay.save(machine.path(machine.paths.layout))
    world = SimWorld(seed=1)
    world.layout = lay
    world.plate_thickness = lay.surface_z()
    x0, y0, _, _ = lay.work_rect()
    kinds = [("DIN934_M4", None, (7.0, 7.0), 3.2), ("DIN125A_M4", None, (9.0, 9.0), 0.8)]
    kinds += [("ISO7380_M4", 8.0, (10.0, 7.6), 2.2)]
    for i, (cls, length, size, top) in enumerate(kinds):
        world.parts.append(SimPart(cls, x0 + 25 + 30 * i, y0 + 40, 0.0, length, size, top))
    covered = Layout.from_dict(lay.to_dict())
    covered.bins = [b for b in covered.bins if b.marker != 105]  # its code is covered
    cam = {"layout": covered}
    runner = Runner(
        machine,
        SimPrinter(machine, world),
        SimVision(world, lambda: cam["layout"], Transform2D.identity),
    )
    runner.command("start", "sort")
    _wait_for(runner, "waiting")  # two bins, three kinds
    assert runner.requests and runner.requests[0].why == "new_kind"
    cam["layout"] = Layout.from_dict(lay.to_dict())  # the code is uncovered
    _wait_for(runner, "done")
    assert not world.parts and runner.requests == []
    assert any("bins seen now, used from here on" in e for e in runner.events)
    assert 105 in runner.claims
