"""Klipper's side of the install: `sortering-pnp klipper` (install-pi.sh runs it).

It puts klipper/sortering_pnp.cfg next to printer.cfg and makes printer.cfg read it, the way
that works every time (each point is a problem that happened):
- the include is there exactly once (an `echo >>` run twice gave two) and stands after the
  user's own sections, before Klipper's SAVE_CONFIG block: sortering_pnp.cfg sets a few options
  of existing sections (e.g. `[stepper_y]` homing speeds) and in Klipper the later value wins;
- `[safe_z_home]` is commented out: Klipper refuses it next to our `[homing_override]`;
- the include of the old sortering_pnp_picker.cfg is removed (the picker is on the Pi's pins);
- warnings for what it can't fix: KIAUH's placeholder printer.cfg (no printer in it), a missing
  or wrong `[mcu] serial:`, a second `[save_variables]`.
Then Klipper restarts (FIRMWARE_RESTART through Moonraker), never while it prints. Backups:
printer.cfg.sortering-<time> and sortering_pnp.cfg.bak (when it had been edited).
"""

from __future__ import annotations

import json
import logging
import re
import shutil
import time
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger("sortering_pnp.klippercfg")

CFG_NAME = "sortering_pnp.cfg"
INCLUDE = f"[include {CFG_NAME}]"
OLD_INCLUDES = ("sortering_pnp_picker.cfg",)  # files of older versions: no longer read
DISABLED = "#sortering-pnp# "  # prefix of the lines it comments out
_SECTION = re.compile(r"^\[([^\]]+)\]")


@dataclass
class Report:
    changed: bool = False
    done: list[str] = field(default_factory=list)  # what it changed
    warnings: list[str] = field(default_factory=list)  # what the user has to do


def _section(line: str) -> str | None:
    m = _SECTION.match(line.strip())
    return m.group(1).strip().lower() if m else None


def fix_printer_cfg(
    text: str, exists: Callable[[str], bool] = lambda p: True
) -> tuple[str, Report]:
    """printer.cfg's text as it should be, and what was done / is left to do. `exists` tells
    whether a path is there (the `[mcu] serial:` device)."""
    rep = Report()
    lines = text.splitlines()
    autosave = next((i for i, ln in enumerate(lines) if ln.startswith("#*#")), len(lines))
    head, tail = lines[:autosave], lines[autosave:]

    # the includes: ours once, at the end of the user's part; old ones out
    kept, ours = [], 0
    for ln in head:
        sec = _section(ln)
        if sec and sec.startswith("include "):
            name = sec[len("include ") :].strip()
            if name == CFG_NAME:
                ours += 1
                continue
            if name in OLD_INCLUDES:
                rep.done.append(f"removed [include {name}] (no longer used)")
                continue
        kept.append(ln)
    # [safe_z_home] out: Klipper allows it or [homing_override], not both
    out, off = [], False
    for ln in kept:
        sec = _section(ln)
        if sec is not None:
            off = sec == "safe_z_home"
            if off:
                rep.done.append("commented out [safe_z_home] (sortering_pnp.cfg homes Z itself)")
        out.append(DISABLED + ln if off and ln.strip() else ln)
    while out and not out[-1].strip():
        out.pop()
    last = next((ln.strip() for ln in reversed(head) if ln.strip()), "")  # as it was
    if ours == 0:
        rep.done.append(f"added {INCLUDE}")
    elif ours > 1:
        rep.done.append(f"{INCLUDE} was there {ours} times: now once")
    elif last != INCLUDE:
        rep.done.append(f"moved {INCLUDE} after your own sections (its settings win there)")
    out += ["", INCLUDE]
    new = "\n".join(out + ([""] + tail if tail else [])) + "\n"
    rep.changed = new != (text if text.endswith("\n") else text + "\n")

    # what it can't fix
    secs = {_section(ln) for ln in head if _section(ln)}
    if "printer" not in secs or "stepper_x" not in secs:
        rep.warnings.append(
            "printer.cfg has no [printer] / [stepper_x]: it is still KIAUH's placeholder. Copy "
            "your printer's example into it (README, Install, step 1)"
        )
    serial = _option(head, "mcu", "serial")
    if "mcu" in secs and (not serial or "<" in serial):
        rep.warnings.append(
            "[mcu] serial: is not set: write the path `ls /dev/serial/by-id/*` shows"
        )
    elif serial and serial.startswith("/dev/") and not exists(serial):
        rep.warnings.append(
            f"[mcu] serial: {serial} is not there (printer off, or another path: "
            "`ls /dev/serial/by-id/*`)"
        )
    if "save_variables" in secs:
        rep.warnings.append(
            "printer.cfg has its own [save_variables]: Klipper keeps one, so sortering_pnp.cfg's "
            "file wins. Delete yours, or move its variables over"
        )
    if "display" not in secs:
        rep.warnings.append(
            "no [display] in printer.cfg: the printer's own screen shows no Screw sorter menu "
            "(the web page works without it)"
        )
    return new, rep


def _option(lines: list[str], section: str, key: str) -> str | None:
    cur, val = None, None
    for ln in lines:
        sec = _section(ln)
        if sec is not None:
            cur = sec
            continue
        if cur == section:
            m = re.match(rf"^\s*{re.escape(key)}\s*[:=]\s*(.*?)\s*(?:[#;].*)?$", ln)
            if m:
                val = m.group(1)
    return val


def install(config_dir: Path, source: Path, now: str | None = None) -> Report:
    """Copy sortering_pnp.cfg into Klipper's config folder and fix printer.cfg (backups first)."""
    stamp = now or time.strftime("%Y%m%d-%H%M%S")
    printer_cfg = config_dir / "printer.cfg"
    if not printer_cfg.is_file():
        rep = Report()
        rep.warnings.append(f"no {printer_cfg}: install Klipper first (README, Install, step 1)")
        return rep
    target = config_dir / CFG_NAME
    want = source.read_text(encoding="utf-8")
    copied = Report()
    if not target.is_file():
        copied.done.append(f"copied {CFG_NAME}")
    elif target.read_text(encoding="utf-8") != want:
        shutil.copy2(target, target.with_name(CFG_NAME + ".bak"))
        copied.done.append(
            f"updated {CFG_NAME} (the old one is {CFG_NAME}.bak: copy over any changes you made, "
            "e.g. z_home_x/y or the tweezer stepper)"
        )
    if copied.done:
        target.write_text(want, encoding="utf-8")
    text = printer_cfg.read_text(encoding="utf-8")
    new, rep = fix_printer_cfg(text, lambda p: Path(p).exists())
    if rep.changed:
        backup = printer_cfg.with_name(f"printer.cfg.sortering-{stamp}")
        shutil.copy2(printer_cfg, backup)
        printer_cfg.write_text(new, encoding="utf-8")
        rep.done.append(f"printer.cfg saved (the old one is {backup.name})")
    rep.done[:0] = copied.done
    rep.changed = rep.changed or bool(copied.done)
    return rep


def restart(url: str, timeout: float = 5.0) -> str:
    """FIRMWARE_RESTART through Moonraker, unless Klipper prints. What happened, in a line."""

    def call(method: str, path: str) -> dict:
        req = urllib.request.Request(url.rstrip("/") + path, method=method)
        with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 - Moonraker on this Pi
            return json.loads(r.read() or b"{}").get("result") or {}

    try:
        info = call("GET", "/printer/info")
        if info.get("state") == "ready":
            q = call("GET", "/printer/objects/query?print_stats=state")
            if q.get("status", {}).get("print_stats", {}).get("state") in ("printing", "paused"):
                return "Klipper is printing: FIRMWARE_RESTART in Mainsail when it has finished"
        call("POST", "/printer/firmware_restart")
    except OSError as exc:
        return f"Moonraker did not answer ({exc}): FIRMWARE_RESTART in Mainsail"
    return "Klipper restarted (FIRMWARE_RESTART): check that Mainsail says Ready"
