"""machine.yaml: how this printer, its picker and the sorting run are set up.

Every section is a dataclass with defaults, so a config file only needs the keys that differ.
Relative paths are resolved against the folder of the config file. Lengths in mm, speeds in
mm/min, angles in degrees.
"""

from __future__ import annotations

import dataclasses
import logging
import typing
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .fill import Fill
from .headcam import HeadCamera
from .photos import Calibration
from .pickers import MODES as PICKER_MODES
from .pickers import PickerType, picker_type

PRINTER_DRIVERS = ("moonraker", "sim")
# settings that are gone (section class, key): an old machine.yaml with them still loads
RETIRED = {("Run", "pipeline"), ("Standby", "settle_s")}

log = logging.getLogger(__name__)


class ConfigError(ValueError):
    pass


@dataclass
class Paths:
    vision: str | None = (
        None  # vision.yaml (nominal camera, measurement); None = Files tab / built-in
    )
    calibration: str | None = None  # calibration.json of the camera; None = nominal camera
    head_calibration: str | None = None  # the same for the head camera (camera.source: head)
    models: str = "../models"  # models uploaded in the web page (Models tab)
    model: str | None = None  # fallback when no model is active: weights or NCNN folder
    stage2: str | None = None  # keypoint model; None = classical measurement only
    layout: str = "../data/layout.yaml"  # bins and working area (edited in the web page)
    transform: str = "../data/bed_transform.json"  # plate mm -> printer X/Y (calibrate tab)
    runs: str = "../runs"  # photos and results of every run
    claims: str = "../data/wild_bins.json"  # what each wild bin collects (kept across runs)
    users: str = "../data/users.json"  # web page accounts (create the first one in the page)
    state: str = "../data/state.json"  # automatic mode on/off (it survives restarts)
    tool: str = "../data/tool.json"  # tip height measured in the Calibrate tab
    setup: str = "../data/setup.json"  # the Setup tab's checklist
    machine: str = "../data/machine.json"  # limits/positions set in the Setup tab (over this file)
    files: str = "../data/files"  # files dropped in the Files tab (calibration, items.json, ...)
    todo: str = "../data/todo.json"  # the Setup tab's "On the machine" ticks
    captures: str = "../data/captures"  # calibration photos, locked camera settings
    sessions: str = "../data/real"  # real-photo sessions (Photos tab), the format screw-synth reads
    klipper_config: str = (
        "~/printer_data/config"  # Klipper's printer.cfg folder (`sortering-pnp klipper`)
    )


@dataclass
class CameraAdjust:
    """Camera adjustments from the page (Camera Calibration tab), over the automatic or locked
    settings; applied to photos and the live picture (camera.controls_for)."""

    focus: str = "auto"  # auto (continuous, or the locked lens position) | manual
    lens_position: float = 2.0  # dioptres (1 / metres): 2.0 = 500 mm, 3.3 = 300 mm
    white_balance: str = "auto"  # auto (or locked) | manual
    red_gain: float = 1.8
    blue_gain: float = 1.6
    exposure: str = "auto"  # auto (or locked) | manual
    exposure_us: int = 20000  # shutter time
    gain: float = 1.0  # analogue gain
    brightness: float = 0.0  # -1 .. 1
    contrast: float = 1.0  # 0 .. 2 (1: as the camera gives it)
    sharpness: float = 1.0  # 0 .. 4
    saturation: float = 1.0  # 0 .. 2


@dataclass
class Camera:
    settings: str | None = (
        None  # locked camera settings (camlock.py: focus/exposure); None = rpicam-still
    )
    # overview: fixed above the bed, one photo sees everything | head: on the tool head, moved
    # over the tray (sorting) or the whole grid (Resync, bin changes); see headcam.py
    source: str = "overview"
    head: HeadCamera = field(default_factory=HeadCamera)
    # only the tray's inside goes to the model: the rest is painted over (trayview.py); the
    # photo keeps its size, so the model sees the parts at its trained scale
    mask: bool = True
    mask_colour: str = "auto"  # auto: the tray floor's own colour | #RRGGBB, e.g. #FFFFFF
    # + keeps this much of the wall's foot, - paints this much more of the floor's edge
    # (Calibrate tab: Camera cropping)
    mask_margin_mm: float = 0.0
    # the picture flipped by the camera itself (photos and live picture; Calibrate tab):
    # both = turned 180 degrees, e.g. a camera mounted the other way round
    # (on by default: the camera on this machine is mounted the other way round)
    hflip: bool = True
    vflip: bool = True
    turn90: bool = False  # then turned 90 degrees clockwise (in software: the photo is taller)
    adjust: CameraAdjust = field(default_factory=CameraAdjust)
    # lens above the tray floor (TPU top), used while there is no camera calibration: the
    # camera is taken as straight down over the picture's centre (Calibrate tab: Skip for now)
    # None: vision.yaml's nominal_camera.height_mm
    height_mm: float | None = None


@dataclass
class Lights:
    """Addressable LEDs (WS2812B, e.g. the LumenPnP ring) on the Pi's SPI MOSI, GPIO10 (pin 19):
    leds.py. Set in the Setup tab (Lights); machine.json keeps what is chosen there."""

    enabled: bool = False  # there are lights (Setup tab: Lights)
    count: int = 8  # LEDs in the chain (the LumenPnP ring: 8)
    colour: str = "#ffffff"  # #RRGGBB
    brightness: float = 0.5  # 0..1 (8 LEDs at full white: about 0.5 A from the Pi's 5 V)
    always_on: bool = True  # on while sortering-pnp runs (False: only while a photo is taken)
    settle_s: float = 0.3  # only for photos: lit this long before the photo (exposure)
    order: str = "GRB"  # the colour order the LEDs expect (WS2812B: GRB)
    spi_bus: int = 0  # /dev/spidev<bus>.<device>: SPI0 MOSI is GPIO10
    spi_device: int = 0


@dataclass
class XYMotion:
    """The X/Y acceleration profile: a limit per axis (the bed, Y on a bed-slinger, carries
    the loose parts: gentle; the head, X, can be quicker). Klipper has one acceleration for all
    axes, so each move that changes X or Y gets the largest one that keeps both its X and its Y
    part within their limits, and it is set back after the move."""

    enabled: bool = True  # False: plain moves (one G1 at the printer's acceleration)
    accel_x: float = 3000.0  # mm/s^2 of the head (the X part of a move)
    accel_y: float = 200.0  # mm/s^2 of the bed (the Y part): long, soft ramps, loose parts on it
    carrying: float = 0.6  # accel_x x this while the picker holds a part (1: no change)
    # trapezoid: one G1, Klipper's own ramp: the speed rises in a straight line (smooth) |
    # s_curve: short G1 steps whose speeds follow an S (Klipper runs them as small stairs)
    profile: str = "trapezoid"
    max_feed_x: float | None = None  # mm/min of the head (the X part); None = printer.feed_xy
    max_feed_y: float | None = 3000.0  # mm/min of the bed (the Y part); None = printer.feed_xy
    steps: int = 12  # s_curve: speed steps per ramp (up and down)
    min_step_mm: float = 1.0  # s_curve: steps at least this long on average (short moves get fewer)


# printer.y_motion (Y only) became printer.xy_motion: its keys under their new names
Y_MOTION_KEYS = {"accel": "accel_y", "max_feed": "max_feed_y"}


@dataclass
class Printer:
    driver: str = "moonraker"  # moonraker (Klipper) | sim (no printer: a simulated one)
    url: str = "http://localhost:7125"  # Moonraker on this Pi
    # tip X Y Z for photos and standby: bed all the way out (Y max on a bed-slinger), head out
    # of the picture; the camera calibration is made with the bed here
    photo_position: list[float] = field(default_factory=lambda: [0.0, 220.0, 60.0])
    # tip X Y Z where the head waits while the picker is put on (Setup tab, after the Machine
    # step): head high and in the middle, bed out, so the head is easy to reach
    change_position: list[float] = field(default_factory=lambda: [110.0, 220.0, 100.0])
    travel_z: float = 50.0  # tip height for every move (above the bins)
    # fixed camera: the head parks for photos at travel_z (out of the picture in X/Y only, no
    # extra rise and fall each cycle); False: it also goes to photo_position's Z. The head
    # camera always uses photo_position's Z (it sets the photo's scale)
    photo_at_travel_z: bool = True
    feed_xy: float = 6000.0
    feed_z: float = 1200.0
    limits_x: list[float] = field(default_factory=lambda: [0.0, 220.0])
    limits_y: list[float] = field(default_factory=lambda: [0.0, 220.0])
    limits_z: list[float] = field(default_factory=lambda: [0.0, 120.0])
    max_hotend_c: float = 50.0  # refuse to run while the hotend is hotter than this
    auto_home: bool = True  # home (G28) when an axis is not homed
    # homing: Z is homed over the middle of the working area (flat plate, no bins) through
    # this macro's variables z_home_x / z_home_y (klipper/sortering_pnp.cfg); None = plain G28
    home_macro: str | None = "_SORTERING_HOME"
    tool_macro: str | None = "_SORTERING_TOOL"  # its variable `tool` must be "picker"; None = skip
    # what the Setup tab's tool buttons run (klipper/sortering_pnp.cfg)
    tool_picker: str = "TOOL_PICKER"  # the picker is on the printer (heaters off)
    tool_hotend: str = "TOOL_HOTEND"  # the hotend is back on (printing allowed, sorting refused)
    timeout_s: float = 120.0
    # mm/s^2 while sorting (gentler bed moves: loose parts stay where the photo saw them);
    # None = the printer's own setting
    accel: float | None = None
    # the X/Y acceleration profile (docs/reference.md, X/Y acceleration profile)
    xy_motion: XYMotion = field(default_factory=XYMotion)


@dataclass
class Tool:
    offset: list[float] = field(default_factory=lambda: [0.0, 0.0, 0.0])  # tip - toolhead, X Y Z


@dataclass
class Picker:
    mode: str = "suction"  # servo_tweezers | suction | magnet | pneumatic_tweezers (pickers.py)
    # the Pi's pins, switched by sortering-pnp itself (pins.py), BCM numbers
    action_pin: int = 12  # header pin 32: the pump's MOSFET module, or the jaw / magnet servo
    turn_pin: int = 13  # header pin 33: the tweezers' turning servo
    pwm_chip: int | None = None  # /sys/class/pwm/pwmchipN for the servos; None = the first one
    grab_angle: float | None = None  # servo angle that holds; None = the type's (pickers.py)
    release_angle: float | None = None  # servo angle that lets go; None = the type's
    rotate_offset_deg: float = 0.0  # fine trim of the jaw angle
    # tweezers on a stepper instead of the turning servo: Klipper macros (klipper/sortering_pnp.cfg)
    rotate_macro: str | None = None  # e.g. SORTERING_ROTATE (ANGLE=<deg>); None = servo on turn_pin
    rotate_home: str | None = None  # with rotate_macro: finds 0 deg before every sort
    grip_from_head_mm: float = 1.5  # tweezers close at least this far below a screw head
    approach_mm: float = 8.0  # slow descent from this far above the part
    depth_mm: float = 0.5  # go this far below the top of the part (spring-loaded cup)
    grip_height: float = 0.5  # gripper: close at this share of the part height (0 bed, 1 top)
    clearance_mm: float = 1.0  # free space a part needs around it to be picked first
    drop_mm: float = 10.0  # release at least this far above the bin's rim
    # lower to rim + drop_mm over the bin before letting go; False: let go at the travel
    # height (never below rim + drop_mm). Setup tab, Picker step
    lower_to_drop: bool = False
    dwell_s: float = 0.3  # wait after grab / release
    feed_z_slow: float = 300.0

    @property
    def kind(self) -> PickerType:
        return picker_type(self.mode)

    def set_type(self, mode: str) -> None:
        """Use this kind of picker (old names are mapped)."""
        self.mode = picker_type(mode).key


@dataclass
class Shake:
    enabled: bool = True  # spread a clump by shaking the bed when nothing can be picked
    axis: str = "Y"
    moves: int = 6
    distance_mm: float = 4.0
    feed: float = 9000.0
    max_in_a_row: int = 3  # then pause and ask for a hand


@dataclass
class Run:
    strategy: str = "sort"  # sort | clear | kit
    min_score: float = 0.5  # below: the "unsure" bin
    kit: dict[str, int] = field(default_factory=dict)  # kit strategy: rule -> how many
    max_failed_picks: int = 3  # the same spot fails this often: leave the part, warn
    failed_radius_mm: float = 4.0  # a part still within this of a pick: the pick failed
    work_margin_mm: float = 3.0  # parts closer than this to the working-area wall are skipped
    keep_photos: int = 300  # keep this many photos in the runs folder (0 = keep all)
    scan_bins_on_start: bool = True  # find the bins with the camera when a run starts
    only_seen_bins: bool = True  # use only the bins the camera sees (covered ones are skipped)
    # the first run after sortering-pnp starts: home, resync, and look into the bins (a bin
    # with parts collects their kind, an empty one is a free wild bin): startup.py
    startup_check: bool = True
    # census: the most numerous kind first, finished before the next, and back to a kind
    # done earlier when more of it turns up | largest_group: the biggest on each photo | nearest
    order: str = "census"
    shake: Shake = field(default_factory=Shake)
    fill: Fill = field(default_factory=Fill)  # how full the bins are (estimated, see fill.py)
    # a new kind and no free wild bin: ask (a bin change, chosen by binswap.py) | overflow
    when_no_bin: str = "ask"
    # a new kind and no free wild bin, before asking: share a wild bin with the same class
    # (another length: DIN912_M3x10 in with DIN912_M3x8) | family (any size) | none
    share_wild: str = "class"
    check_emptied: bool = True  # after a bin change: parts still seen in a bin are counted


@dataclass
class Standby:
    interval_s: float = 60.0  # automatic mode: look for new parts this often
    min_parts: int = 1  # start sorting from this many parts
    # motors off while waiting: quiet, but it homes again before sorting, and homing Y stops
    # the bed sharply at its switch with the parts on it
    motors_off: bool = False
    max_errors: int = 3  # automatic mode switches itself off after this many errors in a row


@dataclass
class Models:
    classifier_conf: float = 0.6  # the classifier overrules stage 1 only when at least this sure
    use_recommended_conf: bool = True  # stage-1 confidence from the model card, when it has one
    prefer: list[str] = field(default_factory=lambda: ["ncnn", "onnx", "pt"])  # weights to use
    max_upload_mb: int = 2000


@dataclass
class Web:
    port: int = 8080
    host: str = ""  # "" = every network interface (open it from the PC)
    require_login: bool = True  # user name and password for the page (False: open to the network)
    session_days: int = 30  # stay logged in this long on a browser


@dataclass
class Bed:
    """The Gridfinity grid the bed holds. Every start on a real printer begins with this grid
    and no bins (Runner.fresh_session); Resync or the start-up check finds them."""

    cols: int = 5  # cells along X (5 x 42 mm on a 220 mm bed)
    rows: int = 5  # cells along Y


@dataclass
class Machine:
    paths: Paths = field(default_factory=Paths)
    bed: Bed = field(default_factory=Bed)
    camera: Camera = field(default_factory=Camera)
    lights: Lights = field(default_factory=Lights)
    printer: Printer = field(default_factory=Printer)
    tool: Tool = field(default_factory=Tool)
    picker: Picker = field(default_factory=Picker)
    run: Run = field(default_factory=Run)
    models: Models = field(default_factory=Models)
    standby: Standby = field(default_factory=Standby)
    web: Web = field(default_factory=Web)
    calibration: Calibration = field(default_factory=Calibration)  # Calibrate tab: the board
    base_dir: Path = field(default_factory=Path.cwd)  # folder of the config file

    def path(self, value: str | None) -> Path | None:
        """A configured path, relative ones against the config file's folder."""
        if value in (None, ""):
            return None
        p = Path(value).expanduser()
        return p if p.is_absolute() else (self.base_dir / p).resolve()

    def validate(self) -> None:
        if self.picker.mode not in PICKER_MODES:
            raise ConfigError(
                f"picker.mode must be one of {PICKER_MODES}, got {self.picker.mode!r}"
            )
        self.picker.set_type(self.picker.mode)
        if self.printer.driver not in PRINTER_DRIVERS:
            raise ConfigError(
                f"printer.driver must be one of {PRINTER_DRIVERS}, got {self.printer.driver!r}"
            )
        for name in ("photo_position", "change_position", "limits_x", "limits_y", "limits_z"):
            v = getattr(self.printer, name)
            if len(v) != (3 if name.endswith("_position") else 2):
                raise ConfigError(f"printer.{name}: wrong number of values {v}")
        if len(self.tool.offset) != 3:
            raise ConfigError("tool.offset needs X Y Z")
        from .trayview import parse_colour

        try:
            parse_colour(self.camera.mask_colour)
        except ValueError as exc:
            raise ConfigError(str(exc)) from exc
        li = self.lights
        if sorted(li.order.upper()) != ["B", "G", "R"]:
            raise ConfigError("lights.order must be RGB, GRB, ... (each letter once)")
        if not 0 <= li.brightness <= 1 or li.count < 1:
            raise ConfigError("lights: brightness 0..1, count at least 1")
        s = li.colour.strip().lstrip("#")
        if len(s) != 6 or any(c not in "0123456789abcdefABCDEF" for c in s):
            raise ConfigError(f"lights.colour must be #RRGGBB, got {li.colour!r}")
        if self.camera.source not in ("overview", "head"):
            raise ConfigError("camera.source must be overview or head")
        a = self.camera.adjust
        for key in ("focus", "white_balance", "exposure"):
            if getattr(a, key) not in ("auto", "manual"):
                raise ConfigError(f"camera.adjust.{key} must be auto or manual")
        if self.bed.cols < 1 or self.bed.rows < 1:
            raise ConfigError("bed.cols and bed.rows must be at least 1")
        if self.run.when_no_bin not in ("ask", "overflow"):
            raise ConfigError("run.when_no_bin must be ask or overflow")
        if self.run.share_wild not in ("class", "family", "none"):
            raise ConfigError("run.share_wild must be class, family or none")
        if self.run.order not in ("census", "largest_group", "nearest"):
            raise ConfigError("run.order must be census, largest_group or nearest")
        if self.run.shake.axis.upper() not in ("X", "Y"):
            raise ConfigError("run.shake.axis must be X or Y")
        xm = self.printer.xy_motion
        if xm.profile not in ("s_curve", "trapezoid"):
            raise ConfigError("printer.xy_motion.profile must be s_curve or trapezoid")
        if min(xm.accel_x, xm.accel_y) <= 0 or xm.steps < 1 or xm.min_step_mm <= 0:
            raise ConfigError(
                "printer.xy_motion: accel_x, accel_y, steps and min_step_mm must be above 0"
            )
        if not 0 < xm.carrying <= 1:
            raise ConfigError("printer.xy_motion.carrying must be above 0 and at most 1")
        for key in ("max_feed_x", "max_feed_y"):
            if getattr(xm, key) is not None and getattr(xm, key) <= 0:
                raise ConfigError(f"printer.xy_motion.{key} must be above 0 (or null)")


def _build(cls: type, data: Mapping[str, Any] | None, where: str) -> Any:
    data = dict(data or {})
    hints = typing.get_type_hints(cls)
    kwargs: dict[str, Any] = {}
    names = {f.name for f in dataclasses.fields(cls)}
    for key, value in data.items():
        if key not in names and (cls.__name__, key) in RETIRED:
            log.warning("%s: %r is no longer used and is ignored", where, key)
            continue
        if key not in names or key == "base_dir":
            raise ConfigError(f"{where}: unknown key {key!r} (known: {sorted(names)})")
        hint = hints[key]
        if dataclasses.is_dataclass(hint):
            kwargs[key] = _build(hint, value, f"{where}.{key}")
        else:
            kwargs[key] = value
    return cls(**kwargs)


def _renamed(raw: Mapping[str, Any], where: str) -> dict[str, Any]:
    """An older machine.yaml: printer.y_motion read as printer.xy_motion (its accel and
    max_feed are the bed's, i.e. accel_y and max_feed_y)."""
    raw = dict(raw)
    pr = raw.get("printer")
    if isinstance(pr, Mapping) and "y_motion" in pr:
        pr = dict(pr)
        old = dict(pr.pop("y_motion") or {})
        if "xy_motion" in pr:
            raise ConfigError(f"{where}: printer has both y_motion and xy_motion: keep xy_motion")
        pr["xy_motion"] = {Y_MOTION_KEYS.get(k, k): v for k, v in old.items()}
        log.warning("%s: printer.y_motion is now printer.xy_motion (read as such)", where)
        raw["printer"] = pr
    return raw


def load(path: str | Path | None = None) -> Machine:
    """Read machine.yaml (or defaults when `path` is None)."""
    if path is None:
        m = Machine()
    else:
        p = Path(path).expanduser().resolve()
        raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        if not isinstance(raw, Mapping):
            raise ConfigError(f"{p}: expected a mapping at the top")
        m = _build(Machine, _renamed(raw, p.name), p.name)
        m.base_dir = p.parent
    m.validate()
    return m
