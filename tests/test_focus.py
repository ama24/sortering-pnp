"""The manual focus (focus.py, Camera Calibration tab): the raw LensPosition libcamera takes,
its range and step from the camera, old mm values migrated, the value reaching the camera
unchanged."""

from __future__ import annotations

import json
import threading
import urllib.request

import pytest

from sortering_pnp import config as config_mod
from sortering_pnp import focus
from sortering_pnp.camera import controls_for
from sortering_pnp.layout import Layout
from sortering_pnp.printer.sim import SimPrinter, SimVision, SimWorld
from sortering_pnp.runner import Runner
from sortering_pnp.transform import Transform2D
from sortering_pnp.web.server import make_server

IMX708_CONTROLS = {"AfMode": (0, 2, 0), "LensPosition": (0.0, 32.0, 1.0)}  # libcamera's own
IMX708_TUNING = {  # imx708.json (version 2.0), the part that matters
    "version": 2.0,
    "algorithms": [{"rpi.black_level": {}}, {"rpi.af": {"map": [0.0, 445, 15.0, 925]}}],
}


def _runner(machine, vision=None) -> Runner:
    lay = Layout.default()
    lay.save(machine.path(machine.paths.layout))
    world = SimWorld(seed=1)
    vision = vision or SimVision(world, lambda: lay, Transform2D.identity)
    return Runner(machine, SimPrinter(machine, world), vision)


def test_the_range_and_step_come_from_the_camera():
    tmap = focus.tuning_map(IMX708_TUNING)
    assert tmap == [0.0, 445.0, 15.0, 925.0]
    r = focus.focus_range(IMX708_CONTROLS, tmap)
    assert (r["min"], r["max"], r["default"]) == (0.0, 15.0, 1.0)  # mapped 0..15, not 0..32
    assert r["step"] == pytest.approx(1 / 32) and r["source"] == "camera tuning"
    r = focus.focus_range(IMX708_CONTROLS)  # no tuning file: the step is assumed
    assert (r["min"], r["max"], r["step"]) == (0.0, 15.0, focus.LENS_STEP)
    assert focus.focus_range({})["source"] == "assumed"
    assert focus.tuning_map({"algorithms": [{"rpi.awb": {}}]}) is None


def test_values_snap_to_the_lens_steps():
    r = focus.default_range()
    assert focus.snapped(3.125, r) == 3.125  # on a step: unchanged
    assert focus.snapped(3.1, r) == 3.09375
    assert focus.snapped(99, r) == 15.0 and focus.snapped(-1, r) == 0.0


def test_old_mm_values_load_as_dioptres(machine, tmp_path):
    assert focus.lens_dioptres(3.3) == 3.3
    assert focus.lens_dioptres(300) == pytest.approx(3.3333, abs=1e-4)
    y = tmp_path / "machine.yaml"
    y.write_text("camera:\n  adjust:\n    focus: manual\n    lens_position: 250\n")
    assert config_mod.load(y).camera.adjust.lens_position == pytest.approx(4.0)
    machine.paths.machine = "machine.json"
    (tmp_path / "machine.json").write_text(
        json.dumps({"camera_adjust": {"focus": "manual", "lens_position": 400.0}})
    )
    runner = _runner(machine)
    assert runner.m.camera.adjust.lens_position == pytest.approx(2.5)


class _FakeCameraVision(SimVision):
    """A camera that records the controls it is given (as camera.Camera sends them)."""

    def __init__(self, machine, *a) -> None:
        super().__init__(*a)
        self.machine, self.sent = machine, []

    def adjust_camera(self) -> dict:
        c = controls_for(None, self.machine.camera.adjust)
        self.sent.append(c)
        return {"LensPosition": c.get("LensPosition")}

    def focus_range(self) -> dict:
        return focus.focus_range(IMX708_CONTROLS, focus.tuning_map(IMX708_TUNING))


def test_the_page_value_reaches_the_camera_unchanged(machine):
    world = SimWorld(seed=1)
    lay = Layout.default()
    vision = _FakeCameraVision(machine, world, lambda: lay, Transform2D.identity)
    runner = _runner(machine, vision)
    runner.camera_adjust({"focus": "manual"})
    out = runner.camera_adjust({"lens_position": 3.15625})
    assert out["adjust"]["lens_position"] == 3.15625
    assert vision.sent[-1]["AfMode"] == 0 and vision.sent[-1]["LensPosition"] == 3.15625
    assert out["focus_range"]["step"] == pytest.approx(1 / 32)


def test_the_api_gives_the_raw_value_and_its_range(machine):
    server = make_server(_runner(machine), "", 18161, None)
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        url = f"http://127.0.0.1:{port}/api/camera"
        req = urllib.request.Request(
            url + "/adjust",
            data=json.dumps({"focus": "manual", "lens_position": 4.5}).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            assert json.loads(r.read())["adjust"]["lens_position"] == 4.5
        with urllib.request.urlopen(url, timeout=10) as r:
            j = json.loads(r.read())
        assert j["adjust"]["lens_position"] == 4.5 and j["adjust"]["focus"] == "manual"
        fr = j["focus_range"]
        assert (fr["min"], fr["max"], fr["step"]) == (0.0, 15.0, focus.LENS_STEP)
        assert fr["source"] == "assumed"  # the simulator has no lens
    finally:
        server.shutdown()
        server.server_close()
