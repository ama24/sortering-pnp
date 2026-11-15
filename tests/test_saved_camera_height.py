"""The camera's height, turn and lock set in the page are in place when the camera's setup is
built at start-up (it used to start with machine.yaml's values until saved again)."""

from __future__ import annotations

from sortering_pnp import cli, printer
from sortering_pnp.io import write_json
from sortering_pnp.printer.sim import SimPrinter, SimWorld
from sortering_pnp.runner import Runner


def test_a_restart_builds_the_camera_at_the_saved_height(machine, monkeypatch):
    write_json(
        machine.path(machine.paths.machine), {"camera_height_mm": 325.0, "camera_turn90": True}
    )
    machine.printer.driver = "moonraker"
    seen = {}

    class Recorder:
        def __init__(self, m, out, store=None) -> None:
            seen["height"], seen["turn90"] = m.camera.height_mm, m.camera.turn90

    monkeypatch.setattr("sortering_pnp.vision.CameraVision", Recorder)
    monkeypatch.setattr(printer, "make_printer", lambda m, *a: SimPrinter(m, SimWorld()))
    monkeypatch.setattr(Runner, "__init__", lambda self, *a, **k: None)
    cli._build(machine)  # noqa: SLF001
    assert seen == {"height": 325.0, "turn90": True}
