"""The LEDs (WS2812B over SPI, leds.py) and the Setup tab's Lights step: no hardware needed."""

from __future__ import annotations

import time

import pytest

from sortering_pnp import leds
from sortering_pnp.config import ConfigError
from sortering_pnp.leds import (
    RESET_BYTES,
    SPI_HZ,
    SPI_IOC_MESSAGE_1,
    Lights,
    SimLeds,
    SpiLeds,
    clock_warning,
    encode,
    parse_hex,
    scaled,
    transfer,
)
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


def test_preview_shows_at_once_and_saves_nothing(machine):
    r = _runner(machine)
    r.setup_lights({"enabled": True, "colour": "#ffffff", "brightness": 1.0})
    sim = r.lights.driver
    out = r.lights_preview({"colour": "#FF0000", "brightness": 1.0})
    assert out == {"colour": "#ff0000", "brightness": 1.0, "shown": True, "error": None}
    assert sim.colours == [(255, 0, 0)] * 8  # on the LEDs at once
    assert _runner(machine).m.lights.colour == "#ffffff"  # kept only when the bar is let go
    r.setup_lights({"colour": "#ff0000"})
    assert _runner(machine).m.lights.colour == "#ff0000"
    with pytest.raises(ValueError):
        r.lights_preview({"brightness": 3})


def test_no_lights_completes_the_step_dark(machine):
    r = _runner(machine)
    r.setup_lights({"enabled": True})
    sim = r.lights.driver
    r.setup_lights({"enabled": False})
    assert sim.colours == [(0, 0, 0)] * 8
    st = r.setup_confirm("lights")
    step = next(s for s in st["steps"] if s["key"] == "lights")
    assert step["done"] and step["note"] == "no lights"


def test_exact_bytes_for_red():
    """GRB, MSB first, 1 = 110 and 0 = 100: red is green 0x00, red 0xff, blue 0x00."""
    body = encode([(255, 0, 0)])[RESET_BYTES:-RESET_BYTES]
    assert body == bytes.fromhex("924924db6db6924924")
    # the reset low before and after: 30 bytes at 2.4 MHz = 100 us (WS2812B: > 80 us)
    assert RESET_BYTES * 8 / SPI_HZ > 80e-6


def test_every_write_carries_its_speed(machine, monkeypatch):
    """SpiLeds sends one SPI_IOC_MESSAGE with speed_hz and 8 bits in the transfer itself."""
    import ctypes
    import struct
    import sys
    import types

    calls: list[tuple[int, bytes, bytes | None]] = []

    def ioctl(fd: int, req: int, arg: bytes) -> int:
        sent = None
        if req == SPI_IOC_MESSAGE_1:
            tx, rx, n, hz, _delay, bits, *_ = struct.unpack("=QQIIHBBBBBB", arg)
            assert rx == 0 and hz == SPI_HZ and bits == 8 and len(arg) == 32
            sent = ctypes.string_at(tx, n)
        calls.append((req, arg, sent))
        return 0

    monkeypatch.setitem(sys.modules, "fcntl", types.SimpleNamespace(ioctl=ioctl))
    monkeypatch.setattr(leds.os, "open", lambda path, flags: 7)
    machine.lights.count = 2
    spi = SpiLeds(machine.lights)
    spi.show([(255, 0, 0), (0, 0, 255)])
    spi.show([(0, 0, 0)] * 2)
    msgs = [c[2] for c in calls if c[0] == SPI_IOC_MESSAGE_1]
    assert msgs == [encode([(255, 0, 0), (0, 0, 255)]), encode([(0, 0, 0)] * 2)]
    assert [c[0] for c in calls].count(leds.SPI_IOC_WR_MAX_SPEED_HZ) == 1  # opened once
    assert transfer(1, 2, 3)[:24] == struct.pack("=QQII", 1, 0, 2, 3)


def test_clock_not_fixed_is_told(tmp_path):
    model = tmp_path / "model"
    model.write_bytes(b"Raspberry Pi 4 Model B Rev 1.1\0")
    cfg = {"core_freq": 500, "core_freq_min": 200}
    why = clock_warning(model, cfg.get)
    assert why and "core_freq_min=500" in why and "white" in why
    cfg["core_freq_min"] = 500
    assert clock_warning(model, cfg.get) is None  # fixed
    model.write_bytes(b"Raspberry Pi 5 Model B Rev 1.0\0")
    assert clock_warning(model, {"core_freq": 910, "core_freq_min": 500}.get) is None
    assert clock_warning(tmp_path / "none", cfg.get) is None  # not a Pi


def test_warning_shows_in_the_state(machine):
    r = _runner(machine)
    r.setup_lights({"enabled": True})
    assert r.setup_state()["lights"]["warning"] is None
    r.lights.driver.warn = "the core clock is not fixed"
    assert r.setup_state()["lights"]["warning"] == "the core clock is not fixed"


def test_off_is_written_even_if_thought_dark(machine):
    """OFF darkens the LEDs at once, whatever they showed before (e.g. before a restart)."""
    machine.lights.enabled, machine.lights.always_on = True, False
    sim = SimLeds()
    lights = Lights(machine, sim)
    lights.off()
    assert sim.colours == [(0, 0, 0)] * machine.lights.count


def test_photos_only_changes_light_at_once_then_dark(machine, monkeypatch):
    """For photos only: every change on the page lights the LEDs at once, for a moment."""
    monkeypatch.setattr(Lights, "PREVIEW_S", 0.05)
    r = _runner(machine)
    sim = r.lights.driver
    r.setup_lights({"enabled": True, "always_on": False, "colour": "#0000ff", "brightness": 1})
    assert sim.colours == [(0, 0, 255)] * 8  # at once
    r.lights_preview({"colour": "#00ff00", "brightness": 1.0})
    assert sim.colours == [(0, 255, 0)] * 8  # a bar's move too
    time.sleep(0.3)
    assert sim.colours == [(0, 0, 0)] * 8  # dark again
    r.setup_lights({"always_on": True})
    assert sim.colours == [(0, 255, 0)] * 8
    r.setup_lights({"enabled": False})  # OFF
    assert sim.colours == [(0, 0, 0)] * 8
