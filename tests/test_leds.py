"""The LEDs (WS2812B over SPI, leds.py) and the Setup tab's Lights step: no hardware needed."""

from __future__ import annotations

import pytest

from sortering_pnp.config import ConfigError
from sortering_pnp.leds import RESET_BYTES, Lights, SimLeds, SpiLeds, encode, parse_hex, scaled
from sortering_pnp.printer.sim import SimPrinter, SimVision, SimWorld
from sortering_pnp.runner import Runner
from sortering_pnp.setup import KEYS
from sortering_pnp.transform import Transform2D


def _bits(data: bytes) -> str:
    return "".join(f"{b:08b}" for b in data)


def test_each_ws2812_bit_is_three_spi_bits():
    data = encode([(0x00, 0xFF, 0x81)])  # GRB: green first
    body = data[RESET_BYTES:-RESET_BYTES]
    assert len(body) == 9  # 3 colour bytes x 3 SPI bytes
    assert data[:RESET_BYTES] == bytes(RESET_BYTES) == data[-RESET_BYTES:]  # low: reset
    want = "".join("110" if bit == "1" else "100" for bit in "11111111" + "00000000" + "10000001")
    assert _bits(body) == want


def test_colour_order_and_brightness():
    rgb = encode([(1, 2, 3)], "RGB")[RESET_BYTES:-RESET_BYTES]
    grb = encode([(2, 1, 3)], "GRB")[RESET_BYTES:-RESET_BYTES]
    assert rgb == grb
    assert parse_hex("#FF8000") == (255, 128, 0) and parse_hex("00ff00") == (0, 255, 0)
    assert scaled((255, 128, 0), 0.5) == (128, 64, 0)
    with pytest.raises(ValueError):
        parse_hex("#12345")


def test_spi_without_the_device_says_what_to_do(machine, tmp_path):
    machine.lights.spi_bus = 99
    ok, why = SpiLeds(machine.lights).status()
    assert not ok and "install-pi.sh" in why


def test_lights_for_photos_only(machine):
    machine.lights.enabled, machine.lights.always_on, machine.lights.settle_s = True, False, 0
    machine.lights.colour, machine.lights.brightness, machine.lights.count = "#ff0000", 1.0, 3
    sim = SimLeds()
    lights = Lights(machine, sim)
    lights.apply()
    assert sim.colours == [(0, 0, 0)] * 3
    with lights.for_photo():
        assert sim.colours == [(255, 0, 0)] * 3
    assert sim.colours == [(0, 0, 0)] * 3
    machine.lights.always_on = True
    lights.apply()
    assert sim.colours == [(255, 0, 0)] * 3
    n = len(sim.frames)
    with lights.for_photo():  # always on: nothing to switch
        pass
    assert len(sim.frames) == n


def test_lights_off_when_not_enabled(machine):
    sim = SimLeds()
    Lights(machine, sim).apply()
    assert sim.frames == []  # machine.lights.enabled is False by default


def test_bad_colour_in_the_config(machine):
    machine.lights.colour = "red"
    with pytest.raises(ConfigError):
        machine.validate()


def _runner(machine) -> Runner:
    world = SimWorld(seed=1)
    return Runner(
        machine, SimPrinter(machine, world), SimVision(world, lambda: None, Transform2D.identity)
    )


def test_lights_come_before_the_camera():
    assert KEYS.index("tip") < KEYS.index("lights") < KEYS.index("camera")


def test_setup_lights_shows_saves_and_confirms(machine):
    r = _runner(machine)
    sim = r.lights.driver
    st = r.setup_lights({"enabled": True, "colour": "#00FF00", "brightness": 0.5})
    assert st["lights"]["enabled"] and st["lights"]["colour"] == "#00ff00"
    assert sim.colours == [(0, 128, 0)] * 8  # shown at once
    st = r.setup_confirm("lights")
    assert next(s for s in st["steps"] if s["key"] == "lights")["done"]
    again = _runner(machine)  # kept in machine.json
    assert again.m.lights.colour == "#00ff00" and again.m.lights.brightness == 0.5
    with pytest.raises(ValueError):
        r.setup_lights({"colour": "green"})
    with pytest.raises(ValueError):
        r.setup_lights({"brightness": 2})


def test_no_lights_completes_the_step_dark(machine):
    r = _runner(machine)
    r.setup_lights({"enabled": True})
    sim = r.lights.driver
    r.setup_lights({"enabled": False})
    assert sim.colours == [(0, 0, 0)] * 8
    st = r.setup_confirm("lights")
    step = next(s for s in st["steps"] if s["key"] == "lights")
    assert step["done"] and step["note"] == "no lights"
