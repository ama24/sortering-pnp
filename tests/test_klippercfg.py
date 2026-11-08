"""`sortering-pnp klipper` (klippercfg.py): printer.cfg made to read sortering_pnp.cfg the way
that works, with every problem we ran into: the include twice or before the user's sections,
[safe_z_home], the old picker file, KIAUH's placeholder, a wrong serial path."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from sortering_pnp import klippercfg
from sortering_pnp.cli import main
from sortering_pnp.klippercfg import INCLUDE, fix_printer_cfg

REPO = Path(__file__).resolve().parents[1]
SOURCE = REPO / "klipper" / "sortering_pnp.cfg"

ENDER = """[include mainsail.cfg]
[include sortering_pnp.cfg]

[stepper_x]
step_pin: PD7

[stepper_y]
step_pin: PC6
homing_speed: 50

[safe_z_home]
home_xy_position: 117, 117
z_hop: 10

[mcu]
serial: /dev/serial/by-id/usb-1a86_USB_Serial-if00-port0

[printer]
kinematics: cartesian

[display]
lcd_type: st7920

[include sortering_pnp_picker.cfg]
[include sortering_pnp.cfg]

#*# <---------------------- SAVE_CONFIG ---------------------->
#*# DO NOT EDIT THIS BLOCK OR BELOW. The contents are auto-generated.
#*#
#*# [extruder]
#*# pid_kp = 21.5
"""

PLACEHOLDER = """[include mainsail.cfg]

[mcu]
serial: /dev/serial/by-id/<your-mcu-id>

[printer]
kinematics: none
max_velocity: 1000
max_accel: 1000
"""


def test_the_include_is_there_once_after_the_users_sections():
    new, rep = fix_printer_cfg(ENDER)
    lines = new.splitlines()
    assert lines.count(INCLUDE) == 1
    at = lines.index(INCLUDE)
    assert at > lines.index("[stepper_y]")  # its [stepper_y] homing speeds win
    assert at < lines.index("#*# <---------------------- SAVE_CONFIG ---------------------->")
    assert "#*# pid_kp = 21.5" in lines  # Klipper's own block untouched, still last
    assert any("2 times" in d for d in rep.done)
    assert rep.changed and not rep.warnings


def test_safe_z_home_and_the_old_picker_file_go():
    new, rep = fix_printer_cfg(ENDER)
    assert "[safe_z_home]" not in new.splitlines()
    assert "#sortering-pnp# [safe_z_home]" in new and "#sortering-pnp# z_hop: 10" in new
    assert "[mcu]" in new.splitlines()  # the next section is left alone
    assert "sortering_pnp_picker.cfg" not in new
    assert any("safe_z_home" in d for d in rep.done)


def test_running_it_again_changes_nothing():
    once, _ = fix_printer_cfg(ENDER)
    twice, rep = fix_printer_cfg(once)
    assert twice == once and not rep.changed and not rep.done


def test_an_include_at_the_top_is_moved_down():
    text = INCLUDE + "\n\n[printer]\nkinematics: cartesian\n\n[stepper_x]\n\n[display]\n"
    new, rep = fix_printer_cfg(text)
    assert new.splitlines()[-1] == INCLUDE
    assert any("moved" in d for d in rep.done)


def test_what_it_cannot_fix_is_told():
    _, rep = fix_printer_cfg(PLACEHOLDER)
    text = " ".join(rep.warnings)
    assert "placeholder" in text and "serial" in text and "[display]" in text
    _, rep = fix_printer_cfg(ENDER, exists=lambda p: False)  # printer off / another path
    assert any("is not there" in w for w in rep.warnings)
    _, rep = fix_printer_cfg(ENDER + "")
    both = ENDER.replace("[display]", "[save_variables]\nfilename: ~/v.cfg\n\n[display]")
    _, rep = fix_printer_cfg(both)
    assert any("save_variables" in w for w in rep.warnings)


def test_install_copies_backs_up_and_is_quiet_the_second_time(tmp_path):
    (tmp_path / "printer.cfg").write_text(ENDER, encoding="utf-8")
    rep = klippercfg.install(tmp_path, SOURCE, now="T1")
    assert (tmp_path / "sortering_pnp.cfg").read_text(encoding="utf-8") == SOURCE.read_text(
        encoding="utf-8"
    )
    assert (tmp_path / "printer.cfg.sortering-T1").read_text(encoding="utf-8") == ENDER
    assert rep.changed
    rep = klippercfg.install(tmp_path, SOURCE, now="T2")
    assert not rep.changed and not rep.done
    assert not (tmp_path / "printer.cfg.sortering-T2").exists()
    (tmp_path / "sortering_pnp.cfg").write_text("# edited by hand\n", encoding="utf-8")
    rep = klippercfg.install(tmp_path, SOURCE, now="T3")
    assert (tmp_path / "sortering_pnp.cfg.bak").read_text(encoding="utf-8") == "# edited by hand\n"
    assert any(".bak" in d for d in rep.done)


def test_no_printer_cfg_is_a_warning(tmp_path):
    rep = klippercfg.install(tmp_path, SOURCE)
    assert not rep.changed and "install Klipper first" in rep.warnings[0]


def test_the_cfg_slows_y_homing_and_has_no_input_shaper():
    text = SOURCE.read_text(encoding="utf-8")
    assert "[stepper_y]\nhoming_speed: 20" in text and "second_homing_speed: 5" in text
    assert "\n[input_shaper]" not in text  # SAVE_CONFIG refuses it in an included file
    assert "\n[safe_z_home]" not in text and "[homing_override]" in text


def _moonraker(state: str, printing: str, posts: list[str]) -> HTTPServer:
    class H(BaseHTTPRequestHandler):
        def _send(self, result: dict) -> None:
            body = json.dumps({"result": result}).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802
            if self.path.startswith("/printer/info"):
                self._send({"state": state})
            else:
                self._send({"status": {"print_stats": {"state": printing}}})

        def do_POST(self) -> None:  # noqa: N802
            posts.append(self.path)
            self._send({})

        def log_message(self, *a) -> None:
            pass

    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def test_klipper_restarts_but_never_while_printing():
    posts: list[str] = []
    srv = _moonraker("ready", "printing", posts)
    url = f"http://127.0.0.1:{srv.server_address[1]}"
    try:
        assert "printing" in klippercfg.restart(url) and posts == []
        srv.shutdown()
        srv = _moonraker("error", "", posts)  # a config error: the restart fixes it
        url = f"http://127.0.0.1:{srv.server_address[1]}"
        assert "restarted" in klippercfg.restart(url) and posts == ["/printer/firmware_restart"]
    finally:
        srv.shutdown()
    assert "did not answer" in klippercfg.restart("http://127.0.0.1:9", timeout=0.5)


def test_the_command(tmp_path, capsys):
    (tmp_path / "printer.cfg").write_text(ENDER, encoding="utf-8")
    cfg = REPO / "configs" / "machine.yaml"
    assert main(["--config", str(cfg), "klipper", "--dir", str(tmp_path), "--no-restart"]) == 0
    out = capsys.readouterr().out
    assert "done  copied sortering_pnp.cfg" in out and "printer.cfg saved" in out
    assert (tmp_path / "printer.cfg").read_text(encoding="utf-8").count(INCLUDE) == 1
