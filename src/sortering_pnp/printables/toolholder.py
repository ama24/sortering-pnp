"""Tool holder: an L bracket that holds the turning stepper of the pneumatic tweezers (a NEMA 8
size motor, 20 x 20 x 30 mm, M2 holes on a 16 mm square, a Ø15 flange) on the printer's tool
interface (2 x M3, 14 mm apart, into two 4.5 mm standoffs on the printer's head).

- The printer plate sits on the two standoffs; its two M3 screws go through it from the front,
  side by side, into them. Two shims on its back, 4.5 mm like the standoffs, rest on the head:
  one at the top (between the standoffs, in the 7.4 mm there is above the screws), one low down
  (in the 15 mm below them). A push on the tool turns the plate about one shim and the screws
  hold it back: a lever, instead of everything hanging on the standoffs.
- The motor plate sticks out from the printer plate's foot at 90 deg. The motor stands on it
  inside the L, its body up along the printer plate; its flange goes down through the plate,
  so the shaft (and the tweezers' air) points at the bed. Four M2 x 5 screws from below, in
  counterbores: 2.5 mm of plate under the heads, so 2.5 mm of thread reaches into the motor.
- The motor is 30 mm long, so the printer's screws sit above its top, with room for a hex key
  over it.
- Two ribs, one each side of the motor, tie the plates together: the tool hangs from the
  printer plate and the ribs carry the bend.

Built where it sits: x across (the M3 pair along x), y away from the printer (the printer plate's
back at y = 0), z up (the motor plate's underside at z = 0). It prints the same way up: standing
on the motor plate, every hole of the motor vertical, no supports (the M3 holes are teardrops,
the shims' undersides 45 deg).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from manifold3d import CrossSection, Manifold, OpType

from .meshio import Mesh

SEG = 48


@dataclass(frozen=True)
class ToolHolder:
    # the printer's interface
    m3_pitch: float = 14.0  # the two M3 screws, centre to centre
    m3_d: float = 3.4  # clearance for M3
    m3_head_d: float = 5.5  # an M3 socket head: room for it beside the ribs
    standoff_h: float = 4.5  # the printer's standoffs: the plate's back is this far off the head
    standoff_d: float = 6.5  # their size across (room for them beside the top shim)
    above_room: float = 7.4  # the head's face above the screws' axis: the plate ends below it
    below_room: float = 15.0  # the head's face below the screws' axis: the low shim stays on it
    shim_h: float = 4.0  # each shim's face on the head, top to bottom
    room_play: float = 0.4  # kept off the limits above
    # the motor (NEMA 8 size)
    motor_w: float = 20.0  # square body
    motor_l: float = 30.0  # body length, flange face to back
    motor_pitch: float = 16.0  # M2 holes on this square
    m2_d: float = 2.4  # clearance for M2
    m2_head_d: float = 4.4  # counterbore for an M2 socket (Ø3.8) or pan head (Ø4)
    m2_screw_l: float = 5.0  # the M2 screws there are (M2 x 5)
    m2_clamp: float = 2.5  # plate left under the heads: the rest of the screw is in the motor
    flange_d: float = 15.0  # passes through the motor plate
    flange_play: float = 0.5  # on the diameter
    body_play: float = 0.6  # from the motor's body to the printer plate and the ribs
    # the bracket
    plate_t: float = 4.0  # printer plate
    base_t: float = 4.5  # motor plate (the M2 heads sit flush in their counterbores)
    rib_t: float = 2.5  # each rib, beside the motor
    rib_h: float = 20.0  # how far up the printer plate the ribs reach (the motor's top stays free)
    key_room: float = 4.0  # from the motor's top to the M3 heads' lower edge: a hex key's way in
    edge: float = 2.5  # material round the holes, to the plates' edges
    corner_r: float = 2.0  # rounded outer corners

    # ---- where things are
    @property
    def half_w(self) -> float:
        """Half the bracket's width: the motor, its play, and a rib each side."""
        return self.motor_w / 2 + self.body_play + self.rib_t

    @property
    def motor_y(self) -> float:
        """The motor's axis, from the printer plate's back."""
        return self.plate_t + self.body_play + self.motor_w / 2

    @property
    def base_d(self) -> float:
        """The motor plate's depth (y), past the motor's front screws."""
        return self.motor_y + self.motor_pitch / 2 + self.m2_head_d / 2 + self.edge

    @property
    def motor_top(self) -> float:
        return self.base_t + self.motor_l

    @property
    def m3_z(self) -> float:
        """The M3 screws' height: above the motor's top, the head and a hex key clear of it."""
        return self.motor_top + self.key_room + self.m3_head_d / 2

    @property
    def height(self) -> float:
        """Up to the head's face above the screws, less a little play."""
        return self.m3_z + self.above_room - self.room_play

    @property
    def m2_thread(self) -> float:
        """How far each M2 screw reaches into the motor."""
        return self.m2_screw_l - self.m2_clamp

    def shims(self) -> list[tuple[float, float, float, float]]:
        """(x0, x1, z0, z1) of each shim's face on the head (at y = -standoff_h): the top one
        between the standoffs, up to the plate's top; the low one across the plate, at the
        bottom of the head's face."""
        gap = self.m3_pitch / 2 - self.standoff_d / 2 - 0.5
        top = (-gap, gap, self.height - self.shim_h, self.height)
        z0 = self.m3_z - self.below_room + self.room_play
        low = (-self.half_w + 1.0, self.half_w - 1.0, z0, z0 + self.shim_h)
        return [top, low]

    def m3_spots(self) -> list[float]:
        return [-self.m3_pitch / 2, self.m3_pitch / 2]

    def m2_spots(self) -> list[tuple[float, float]]:
        h = self.motor_pitch / 2
        return [(sx * h, self.motor_y + sy * h) for sx in (-1, 1) for sy in (-1, 1)]


def _rounded_rect(x0: float, x1: float, y0: float, y1: float, r: float) -> CrossSection:
    r = min(r, (x1 - x0) / 2, (y1 - y0) / 2)
    pts = []
    for cx, cy, a0 in (
        (x1 - r, y1 - r, 0),
        (x0 + r, y1 - r, 90),
        (x0 + r, y0 + r, 180),
        (x1 - r, y0 + r, 270),
    ):
        for k in range(7):
            a = math.radians(a0 + 15 * k)
            pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    return CrossSection([pts])


def _teardrop_y(d: float, x: float, z: float, y0: float, y1: float) -> Manifold:
    """A hole along y with a 45 deg point on top: prints upright without support."""
    r = d / 2
    pts = [
        (r * math.cos(math.radians(a)), r * math.sin(math.radians(a))) for a in range(-225, 46, 15)
    ]
    pts.append((0.0, r * math.sqrt(2)))
    sec = CrossSection([pts])  # in (x, z)
    return sec.extrude(y1 - y0).rotate([90, 0, 0]).translate([x, y1, z])


def build(p: ToolHolder | None = None) -> Manifold:
    p = p or ToolHolder()
    hw = p.half_w
    # printer plate: x across, z up, y = 0..plate_t (rounded at the top)
    plate = (
        _rounded_rect(-hw, hw, -p.corner_r, p.height, p.corner_r)
        .extrude(p.plate_t)
        .rotate([90, 0, 0])
        .translate([0, p.plate_t, 0])
    )
    plate = plate ^ Manifold.cube([2 * hw, p.plate_t, p.height]).translate([-hw, 0, 0])
    # motor plate: x across, y out, z = 0..base_t (rounded at the front)
    base = _rounded_rect(-hw, hw, -p.corner_r, p.base_d, p.corner_r).extrude(p.base_t)
    base = base ^ Manifold.cube([2 * hw, p.base_d, p.base_t]).translate([-hw, 0, 0])
    # the ribs: triangles in (y, z), from the motor plate's front edge up the printer plate
    tri = CrossSection(
        [
            [
                (p.plate_t - 0.01, p.base_t - 0.01),
                (p.base_d, p.base_t - 0.01),
                (p.plate_t - 0.01, p.base_t + p.rib_h),
            ]
        ]
    )
    rib = tri.extrude(p.rib_t).rotate([90, 0, 90])  # (y, z) section, thickness along x
    ribs = [rib.translate([hw - p.rib_t, 0, 0]), rib.translate([-hw, 0, 0])]
    # the shims on the plate's back: a face on the head, a 45 deg underside (prints upright)
    s = p.standoff_h
    shims = []
    for x0, x1, z0, z1 in p.shims():
        sec = CrossSection([[(0.01, z0 - s), (0.01, z1), (-s, z1), (-s, z0)]])  # (y, z)
        shims.append(sec.extrude(x1 - x0).rotate([90, 0, 90]).translate([x0, 0, 0]))
    body = Manifold.batch_boolean([plate, base, *ribs, *shims], OpType.Add)
    # holes: the flange, the motor's screws, the printer's screws
    flange = Manifold.cylinder(
        p.base_t + 2, (p.flange_d + p.flange_play) / 2, (p.flange_d + p.flange_play) / 2, SEG
    )
    cuts = [flange.translate([0, p.motor_y, -1])]
    cb = p.base_t - p.m2_clamp  # counterbores from below, for the heads
    for x, y in p.m2_spots():
        cuts.append(
            Manifold.cylinder(p.base_t + 2, p.m2_d / 2, p.m2_d / 2, 24).translate([x, y, -1])
        )
        cuts.append(
            Manifold.cylinder(cb + 1, p.m2_head_d / 2, p.m2_head_d / 2, 24).translate([x, y, -1])
        )
    for x in p.m3_spots():
        cuts.append(_teardrop_y(p.m3_d, x, p.m3_z, -1, p.plate_t + 1))
    return body - Manifold.batch_boolean(cuts, OpType.Add)


def motor_box(p: ToolHolder | None = None) -> Manifold:
    """Where the motor's body is (to check it clears the holder)."""
    p = p or ToolHolder()
    w = p.motor_w
    return Manifold.cube([w, w, p.motor_l]).translate([-w / 2, p.motor_y - w / 2, p.base_t])


def holder_mesh(p: ToolHolder | None = None) -> Mesh:
    from .gridfinity import _to_mesh

    return _to_mesh(build(p))


NOTES = """Tool holder for the pneumatic tweezers' turning stepper (sortering-pnp print catalogue)

The motor: NEMA 8 size, {motor_w:g} x {motor_w:g} x {motor_l:g} mm, M2 holes on a {motor_pitch:g} mm square, Ø{flange_d:g}
flange. The printer's interface: 2 x M3, {m3_pitch:g} mm apart, into two {standoff_h:g} mm standoffs.

Print as exported, standing on the motor plate (no supports), PETG or PLA, 0.4 mm nozzle,
0.2 mm layers, 4 walls, 40 % infill or more.

Fitting:
- The motor stands on the motor plate inside the L, between the ribs; its flange goes down
  through the Ø{flange_hole:g} hole. 4 x M2 x {m2_screw_l:g} from below, their heads flush in counterbores:
  {m2_clamp:g} mm of plate under each head, {m2_thread:g} mm of thread in the motor.
- The printer plate sits on the printer's two {standoff_h:g} mm standoffs: 2 x M3 from the front
  through the plate ({plate_t:g} mm) into them, {m3_z:g} mm above the motor plate's underside, so a
  hex key reaches them over the motor's top ({key_room:g} mm of room).
- Two shims on the plate's back, {standoff_h:g} mm like the standoffs, rest on the head: one at the
  top between the standoffs (the plate ends {above:g} mm above the screws), one {low:g} mm below
  the screws. A push on the tool turns the plate about a shim and the screws hold it back.
  If a shim keeps the plate off a standoff, sand the shim (or add a washer on the standoff).
- Size: {width:g} wide, {depth:g} deep, {height:g} high.
"""


def holder_files(p: ToolHolder | None = None) -> list[tuple[str, bytes]]:
    from .meshio import stl_bytes

    p = p or ToolHolder()
    notes = NOTES.format(
        motor_w=p.motor_w,
        motor_l=p.motor_l,
        motor_pitch=p.motor_pitch,
        flange_d=p.flange_d,
        m3_pitch=p.m3_pitch,
        flange_hole=p.flange_d + p.flange_play,
        m2_screw_l=p.m2_screw_l,
        m2_clamp=p.m2_clamp,
        m2_thread=p.m2_thread,
        standoff_h=p.standoff_h,
        above=round(p.height - p.m3_z, 2),
        low=round(p.m3_z - p.shims()[1][2], 2),
        m3_z=round(p.m3_z, 2),
        key_room=p.key_room,
        plate_t=p.plate_t,
        width=round(2 * p.half_w, 1),
        depth=round(p.base_d, 1),
        height=round(p.height, 1),
    )
    return [
        ("tool_holder.stl", stl_bytes(holder_mesh(p), "sortering-pnp tool holder")),
        ("TOOL_HOLDER.txt", notes.encode()),
    ]
