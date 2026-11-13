"""A pump on the printer board's bed or hotend output (picker.pump_switch), switched by Klipper
with SET_HEATER_TEMPERATURE, instead of a MOSFET module on the Pi's pin."""

from __future__ import annotations

import pytest

from sortering_pnp.config import ConfigError, Machine
from sortering_pnp.pins import HeaterPump, PiPins
from sortering_pnp.printer import PrinterError
from sortering_pnp.printer.base import PrinterStatus


class FakeKlipper:
    def __init__(self, hotend_c: float | None = 24.0, bed_c: float | None = 23.0) -> None:
        self.sent: list[str] = []
        self.hotend_c, self.bed_c = hotend_c, bed_c
        self.state = "ready"

    def gcode(self, script: str) -> None:
        self.sent.append(script)

    def status(self, tool_macro: str | None = None) -> PrinterStatus:
        return PrinterStatus(state=self.state, hotend_c=self.hotend_c, bed_c=self.bed_c)

    def emergency_stop(self) -> None: ...

    def close(self) -> None: ...


def no_gpio(pin: int) -> None:
    raise AssertionError("a pump on the board's output needs no Pi pin")


def pins(switch: str, klipper: FakeKlipper, mode: str = "suction") -> PiPins:
    m = Machine()
    m.picker.set_type(mode)
    m.picker.pump_switch = switch
    return PiPins(m, output=no_gpio, sleep=lambda s: None, printer=klipper)


@pytest.mark.parametrize("switch,heater", [("bed", "heater_bed"), ("hotend", "extruder")])
def test_grab_and_release_ask_klipper_for_the_heater(switch, heater):
    k = FakeKlipper()
    p = pins(switch, k)
    ok, why = p.status()
    assert ok and f"{switch} output" in why
    p.grab()
    p.release()
    assert k.sent == [
        f"SET_HEATER_TEMPERATURE HEATER={heater} TARGET=60",
        f"SET_HEATER_TEMPERATURE HEATER={heater} TARGET=0",
    ]


def test_off_only_touches_the_heater_after_the_pump_was_on():
    """Stopping the program must not switch off a heater someone is printing with."""
    k = FakeKlipper()
    p = pins("hotend", k)
    p.status()
    p.off()
    p.close()
    assert k.sent == []
    p.grab()
    p.off()
    p.off()
    assert k.sent[-1].endswith("TARGET=0") and len(k.sent) == 2


def test_a_warm_heater_is_still_plugged_in_the_pump_is_refused():
    k = FakeKlipper(bed_c=70.0)
    p = pins("bed", k)
    ok, why = p.status()
    assert not ok and "unplug" in why
    with pytest.raises(PrinterError, match="unplug"):
        p.grab()
    assert k.sent == []


def test_letting_go_is_never_refused():
    k = FakeKlipper()
    p = pins("hotend", k)
    p.grab()
    k.hotend_c = 80.0  # the cartridge was still on the output after all
    p.release()
    assert k.sent[-1] == "SET_HEATER_TEMPERATURE HEATER=extruder TARGET=0"


def test_no_heated_bed_in_klipper():
    p = pins("bed", FakeKlipper(bed_c=None))
    ok, why = p.status()
    assert not ok and "heater_bed" in why


def test_servo_pickers_ignore_the_pump_switch(tmp_path):
    m = Machine()
    m.picker.set_type("magnet")
    m.picker.pump_switch = "bed"
    k = FakeKlipper()
    (tmp_path / "pwmchip0" / "pwm0").mkdir(parents=True)
    p = PiPins(m, pwm_root=tmp_path, output=no_gpio, sleep=lambda s: None, printer=k)
    p.grab()
    assert k.sent == []
    assert (tmp_path / "pwmchip0" / "pwm0" / "enable").read_text() == "1"


def test_changing_the_switch_reopens_the_pins():
    k = FakeKlipper()
    p = pins("mosfet", k)
    opened: list[int] = []

    class Out:
        def on(self) -> None: ...
        def off(self) -> None: ...
        def close(self) -> None: ...

    p._output = lambda pin: opened.append(pin) or Out()
    p.grab()
    assert opened == [12] and k.sent == []
    p.m.picker.pump_switch = "hotend"
    p.grab()
    assert k.sent == ["SET_HEATER_TEMPERATURE HEATER=extruder TARGET=60"]


def test_long_hold_warns(caplog):
    k = FakeKlipper()
    now = [0.0]
    pump = HeaterPump(k, "hotend", 60.0, 50.0, clock=lambda: now[0])
    pump.on()
    now[0] = 18.0
    with caplog.at_level("WARNING"):
        pump.off()
    assert "Klipper stops the printer" in caplog.text


def test_config_checks_the_pump_switch():
    m = Machine()
    m.picker.pump_switch = "fan"
    with pytest.raises(ConfigError, match="pump_switch"):
        m.validate()


def test_the_setup_tab_choice_is_kept_over_a_restart(machine):
    import copy

    from sortering_pnp.layout import Layout
    from sortering_pnp.printer.sim import SimPrinter, SimVision, SimWorld
    from sortering_pnp.runner import Runner
    from sortering_pnp.transform import Transform2D

    lay = Layout.default()
    lay.save(machine.path(machine.paths.layout))
    world = SimWorld(seed=1)
    vision = SimVision(world, lambda: lay, Transform2D.identity)
    runner = Runner(machine, SimPrinter(machine, world), vision)
    st = runner.setup_picker_pump("hotend")
    assert st["picker"]["pump_switch"] == "hotend" and st["picker"]["pump_switches"] == [
        "mosfet",
        "bed",
        "hotend",
    ]
    with pytest.raises(ValueError):
        runner.setup_picker_pump("fan")
    fresh = copy.deepcopy(machine)  # after a restart
    fresh.picker.pump_switch = "mosfet"
    again = Runner(fresh, SimPrinter(fresh, SimWorld()), vision)
    assert again.m.picker.pump_switch == "hotend"
