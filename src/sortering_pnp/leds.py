"""Addressable LEDs (WS2812B, e.g. the Opulo LumenPnP ring: 8 of them) on the Pi's own SPI.

sortering-pnp drives them itself, like the picker's pins: no Klipper set-up and no extra
Python package. The data line goes to SPI0 MOSI (GPIO10, header pin 19); every WS2812 bit is
sent as 3 SPI bits at 2.4 MHz (1 = 110, 0 = 100), so the SPI hardware makes the timing.

Wiring (the ring's JST XH: 5V, DIN, GND; drawn in the Setup tab's Lights step):
  5V  -> a 5 V buck converter on the printer's 24 V supply (not the Pi's 5 V pins);
         8 LEDs at full white take about 0.5 A
  GND -> pin 20 (ground), joined with the converter's minus
  DIN -> pin 19 (GPIO10, SPI0 MOSI)
The Pi's 3.3 V data line drives a short lead to WS2812B at 5 V in practice; if the LEDs
flicker or show wrong colours, put a 74AHCT125 level shifter (or one 1N4001 diode in the
ring's 5 V lead) in between.
SPI must be on (`dtparam=spi=on` in config.txt) and the core clock fixed on a Pi 4
(`core_freq_min=500`), else the SPI clock and so the timing drifts: install-pi.sh adds both.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Protocol

from .config import Lights as LightsConfig
from .config import Machine

log = logging.getLogger("sortering_pnp.leds")

SPI_HZ = 2_400_000  # 3 SPI bits per WS2812 bit: 417 ns each
RESET_BYTES = 30  # > 80 us low: the LEDs take the new colours
# linux/spi/spidev.h: _IOW('k', nr, size)
SPI_IOC_WR_MODE = 0x40016B01
SPI_IOC_WR_BITS_PER_WORD = 0x40016B03
SPI_IOC_WR_MAX_SPEED_HZ = 0x40046B04

RGB = tuple[int, int, int]


def parse_hex(colour: str) -> RGB:
    """#RRGGBB (or RRGGBB) -> (r, g, b)."""
    s = colour.strip().lstrip("#")
    if len(s) != 6 or any(c not in "0123456789abcdefABCDEF" for c in s):
        raise ValueError(f"colour must be #RRGGBB, got {colour!r}")
    return int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16)


def to_hex(rgb: RGB) -> str:
    return "#{:02x}{:02x}{:02x}".format(*rgb)


def scaled(rgb: RGB, brightness: float) -> RGB:
    b = min(max(float(brightness), 0.0), 1.0)
    return tuple(round(c * b) for c in rgb)  # type: ignore[return-value]


def _byte_bits(value: int) -> int:
    """One colour byte as 24 SPI bits (each WS2812 bit -> 110 or 100)."""
    out = 0
    for i in range(7, -1, -1):
        out = (out << 3) | (0b110 if value >> i & 1 else 0b100)
    return out


_TABLE = [_byte_bits(v).to_bytes(3, "big") for v in range(256)]


def encode(colours: list[RGB], order: str = "GRB") -> bytes:
    """The SPI bytes for these LED colours: a low lead-in, the bits, a reset (low) after."""
    idx = ["RGB".index(ch) for ch in order.upper()]
    body = b"".join(_TABLE[c[i]] for c in colours for i in idx)
    return bytes(RESET_BYTES) + body + bytes(RESET_BYTES)


class LedDriver(Protocol):
    def show(self, colours: list[RGB]) -> None: ...

    def status(self) -> tuple[bool, str]: ...

    def close(self) -> None: ...


class SpiLeds:
    """WS2812B on /dev/spidevB.D (standard library only: os + fcntl)."""

    def __init__(self, cfg: LightsConfig) -> None:
        self.cfg = cfg
        self.path = Path(f"/dev/spidev{cfg.spi_bus}.{cfg.spi_device}")
        self._fd: int | None = None

    def status(self) -> tuple[bool, str]:
        if not self.path.exists():
            return False, f"{self.path} missing: run install-pi.sh (turns SPI on), then reboot"
        if not os.access(self.path, os.W_OK):
            return False, f"no access to {self.path}: install-pi.sh adds you to the spi group"
        return True, f"{self.cfg.count} LEDs on GPIO10 (pin 19)"

    def _open(self) -> int:
        if self._fd is None:
            import fcntl
            import struct

            fd = os.open(self.path, os.O_WRONLY)
            fcntl.ioctl(fd, SPI_IOC_WR_MODE, struct.pack("B", 0))
            fcntl.ioctl(fd, SPI_IOC_WR_BITS_PER_WORD, struct.pack("B", 8))
            fcntl.ioctl(fd, SPI_IOC_WR_MAX_SPEED_HZ, struct.pack("I", SPI_HZ))
            self._fd = fd
        return self._fd

    def show(self, colours: list[RGB]) -> None:
        os.write(self._open(), encode(colours, self.cfg.order))

    def close(self) -> None:
        if self._fd is not None:
            os.close(self._fd)
            self._fd = None


class SimLeds:
    """The simulator's LEDs: the last colours shown, nothing else."""

    def __init__(self) -> None:
        self.frames: list[list[RGB]] = []
        self.ok, self.why = True, "simulated LEDs"

    @property
    def colours(self) -> list[RGB]:
        return self.frames[-1] if self.frames else []

    def show(self, colours: list[RGB]) -> None:
        self.frames.append(list(colours))

    def status(self) -> tuple[bool, str]:
        return self.ok, self.why

    def close(self) -> None:
        pass


class Lights:
    """The lights as the machine uses them: the chosen colour and brightness, on all the time
    (`always_on`) or only while a photo is taken; a preview from the Setup tab shows the
    colour for a few seconds even when they are on only for photos."""

    PREVIEW_S = 5.0

    def __init__(self, m: Machine, driver: LedDriver) -> None:
        self.m = m
        self.driver = driver
        self._lock = threading.Lock()
        self._lit = False
        self._photo = 0
        self._timer: threading.Timer | None = None
        self.error: str | None = None

    @property
    def cfg(self) -> LightsConfig:
        return self.m.lights

    def colour(self) -> RGB:
        return scaled(parse_hex(self.cfg.colour), self.cfg.brightness)

    def _show(self, on: bool) -> None:
        if not self.cfg.enabled:
            return
        ok, why = self.driver.status()
        if not ok:
            self.error = why
            return
        try:
            self.driver.show([self.colour() if on else (0, 0, 0)] * self.cfg.count)
            self._lit, self.error = on, None
        except OSError as exc:
            self.error = str(exc)
            log.warning("LEDs: %s", exc)

    def apply(self) -> None:
        """Show the saved state: lit when always on (or during a photo), else dark."""
        with self._lock:
            self._show(self.cfg.always_on or self._photo > 0)

    def preview(self) -> None:
        """The chosen colour now; dark again after a few seconds unless always on."""
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None
            self._show(True)
            if not self.cfg.always_on and self.cfg.enabled:
                self._timer = threading.Timer(self.PREVIEW_S, self.apply)
                self._timer.daemon = True
                self._timer.start()

    @contextmanager
    def for_photo(self) -> Iterator[None]:
        """Lit while a photo is taken (and a moment before, for the exposure)."""
        if not self.cfg.enabled or self.cfg.always_on:
            yield
            return
        with self._lock:
            self._photo += 1
            self._show(True)
        if self.cfg.settle_s > 0:
            time.sleep(self.cfg.settle_s)
        try:
            yield
        finally:
            with self._lock:
                self._photo -= 1
                if self._photo == 0:
                    self._show(False)

    def off(self) -> None:
        with self._lock:
            if self._lit:
                self._show(False)

    def close(self) -> None:
        if self._timer is not None:
            self._timer.cancel()
        self.off()
        self.driver.close()

    def state(self) -> dict[str, Any]:
        ok, why = self.driver.status() if self.cfg.enabled else (True, "no lights")
        if ok and self.error:
            ok, why = False, self.error
        c = self.cfg
        return {
            "enabled": c.enabled,
            "colour": c.colour,
            "brightness": c.brightness,
            "always_on": c.always_on,
            "count": c.count,
            "lit": self._lit,
            "ok": ok,
            "message": why,
        }


def make_leds(m: Machine, printer: object) -> LedDriver:
    """The simulator's LEDs with the simulated printer, the Pi's SPI otherwise."""
    from .printer.sim import SimPrinter

    if isinstance(printer, SimPrinter):
        return SimLeds()
    return SpiLeds(m.lights)
