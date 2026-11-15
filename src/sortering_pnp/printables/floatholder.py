"""Floating tool holder: the tool rides up on a miniature linear rail when it hits the bed (or a
pile of parts), two extension springs pull it back down. Same printer interface as toolholder.py
(2 x M3, 14 mm apart, into two 4.5 mm standoffs) and the same motor seat (NEMA 8 size: M2 holes on
a 16 mm square, a Ø15 flange through the plate).

The rail: JLCMC E-BMN12H-1-L100-Z0-P-M-E12.5 (MGN12H sizes: rail 12 x 8, 100 long, M3 holes every
25 mm, 12.5 from each end; block 27 wide, 45.4 long, 13 from the rail's foot to its top, 3 from
the rail's foot to its underside, 4 x M3 on 20 x 20). Two printed parts:

- The plate, on the printer: the printer's two M3 screws sunk in it; the rail on a strip as wide
  and long as itself (so the springs fit between the plate and the block), held by 4 x M3
  self-tapping screws; a column under the block (the rest stop); the lower spring screws; and
  holes for Ø2.5 x 10 dowel pins, the top stop, pressed in where the travel should end.
- The L, on the block: its top on the block (4 x M3), the motor on its foot further down (so it
  does not cover those screws), and on top an overhang over the block's end that reaches back
  towards the printer beside the rail: each spring's hook sits in a slot there, and a screw
  from the front goes through the overhang and the hook.

The two springs (5.5 x 25.5) hang behind the block, one each side of the rail.

Built where it sits: x across, y away from the printer (the plate's back at y = 0), z up (the
block's lower end, at rest on the column, at z = 0).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from manifold3d import CrossSection, Manifold, OpType

from .meshio import Mesh
from .toolholder import SEG, _rounded_rect, _teardrop_y


@dataclass(frozen=True)
class FloatHolder:
    # the printer's interface (as toolholder.ToolHolder)
    m3_pitch: float = 14.0
    m3_d: float = 3.4
    m3_head_d: float = 6.5  # counterbore: an M3 socket head (Ø5.5) sinks in
    m3_clamp: float = 4.0  # plate under the heads: the tool holder's screws still reach
    m3_z: float = 12.0  # the printer's screws: behind the block, below the springs
    standoff_h: float = 4.5
    standoff_d: float = 6.5
    above_room: float = 7.4
    below_room: float = 15.0
    shim_h: float = 4.0
    room_play: float = 0.4
    # a pad on the back, against the printer's head higher up: the plate does not lever about
    # its two screws (mm above the plate's bottom edge: its ramp starts, its step ends)
    pad_from: float = 38.0
    pad_to: float = 45.0
    # the rail and its block (E-BMN12H = MGN12H sizes)
    rail_w: float = 12.0
    rail_h: float = 8.0
    rail_len: float = 100.0
    rail_pitch: float = 25.0
    rail_end: float = 12.5
    rail_drop: float = 1.5  # the rail's foot end sits this far down in the column
    car_w: float = 27.0
    car_l: float = 45.4
    car_h: float = 13.0
    car_gap: float = 3.0  # rail's foot to the block's underside
    car_pitch: float = 20.0
    car_thread: float = 3.5
    tap_d: float = 2.5  # pilot hole for an M3 self-tapping screw
    # the motor (as the tool holder)
    motor_w: float = 20.0
    motor_l: float = 30.0
    motor_pitch: float = 16.0
    m2_d: float = 2.4
    m2_head_d: float = 4.4
    m2_clamp: float = 2.5
    flange_d: float = 15.0
    flange_play: float = 0.5
    body_play: float = 0.6
    # the L
    leg_t: float = 4.5  # M3 x 8 into the block: 3.5 mm of thread
    m3_head: float = 5.5  # the block's screw heads stand on the leg's front
    key_room: float = 1.0  # from the motor's top to those heads: a hex key's way in
    base_t: float = 4.5
    rib_t: float = 2.5
    rib_h: float = 20.0
    lid_h: float = 7.0  # the overhang over the block's top end
    lid_play: float = 0.3  # above the block's end
    notch_play: float = 1.0  # round the rail in the overhang's notch, each side and in front
    head_sink: float = 1.0  # the upper spring screws' heads, sunk in the leg's front
    head_d: float = 6.0
    corner_r: float = 1.5
    # springs and stops
    spring_od: float = 5.5
    spring_len: float = 25.5  # over the hooks
    spring_play: float = 0.5  # round each spring
    post_short: float = 2.5  # screws this much closer than the spring's length
    slot_w: float = 2.0  # the hook's slot in the overhang
    dowel_d: float = 2.4  # Ø2.5 dowel pins, pressed
    dowel_in: float = 4.8  # hole depth: 5 mm of a 10 mm pin stands out
    travels: tuple[float, ...] = (4.0, 6.5, 9.0, 11.5, 14.0, 16.5, 19.0, 21.5, 24.0)
    strip_extra: float = 1.0  # more room round the springs than they strictly need
    column_h: float = 8.0  # under the block
    plate_edge: float = 1.5  # beyond the block's sides
    plate_t: float = 7.2  # beside the strip: the printer's screw heads sink in it

    # ---- the springs' room
    @property
    def strip_h(self) -> float:
        """The strip under the rail: what the springs lack between the plate and the block."""
        return self.spring_od + 2 * self.spring_play - self.car_gap + self.strip_extra

    @property
    def rail_y0(self) -> float:
        return self.plate_t + self.strip_h

    @property
    def rail_y1(self) -> float:
        return self.rail_y0 + self.rail_h

    @property
    def spring_x(self) -> float:
        """Half-way between the rail's side and the block's."""
        return (self.rail_w / 2 + self.car_w / 2) / 2

    @property
    def spring_y(self) -> float:
        """Half-way between the plate and the block's underside."""
        return self.plate_t + (self.strip_h + self.car_gap) / 2

    @property
    def spring_r(self) -> float:
        return self.spring_od / 2 + self.spring_play

    # ---- the rail and the block
    @property
    def rail_z0(self) -> float:
        return -self.rail_drop

    @property
    def rail_z1(self) -> float:
        return self.rail_z0 + self.rail_len

    def rail_holes(self) -> list[float]:
        n = round((self.rail_len - 2 * self.rail_end) / self.rail_pitch) + 1
        return [self.rail_z0 + self.rail_end + k * self.rail_pitch for k in range(n)]

    @property
    def car_y0(self) -> float:
        return self.rail_y0 + self.car_gap

    @property
    def leg_y0(self) -> float:
        return self.rail_y0 + self.car_h

    @property
    def leg_y1(self) -> float:
        return self.leg_y0 + self.leg_t

    def car_holes(self) -> list[tuple[float, float]]:
        h, zc = self.car_pitch / 2, self.car_l / 2
        return [(sx * h, zc + sz * h) for sx in (-1, 1) for sz in (-1, 1)]

    # ---- the L
    @property
    def lid_z0(self) -> float:
        return self.car_l + self.lid_play

    @property
    def lid_z1(self) -> float:
        return self.lid_z0 + self.lid_h

    @property
    def lid_y0(self) -> float:
        """The overhang's back, just off the plate's face."""
        return self.plate_t + 0.5

    @property
    def post_z(self) -> float:
        """The upper spring screws, through the overhang."""
        return self.lid_z0 + 3.2

    @property
    def low_post_z(self) -> float:
        return self.post_z - (self.spring_len - self.post_short)

    @property
    def base_z(self) -> float:
        """The motor's foot (its underside): the motor's top stays under the block's screws."""
        low = min(z for _, z in self.car_holes())
        return low - self.m3_head / 2 - self.key_room - self.motor_l - self.base_t

    @property
    def leg_half(self) -> float:
        return self.car_w / 2 + 0.5

    @property
    def motor_y(self) -> float:
        return self.leg_y1 + self.body_play + self.motor_w / 2

    @property
    def base_y1(self) -> float:
        return self.motor_y + self.motor_pitch / 2 + self.m2_head_d / 2 + 2.0

    def m2_spots(self) -> list[tuple[float, float]]:
        h = self.motor_pitch / 2
        return [(sx * h, self.motor_y + sy * h) for sx in (-1, 1) for sy in (-1, 1)]

    # ---- the plate
    @property
    def plate_half(self) -> float:
        return self.car_w / 2 + self.plate_edge

    @property
    def plate_z0(self) -> float:
        return -self.column_h

    @property
    def plate_z1(self) -> float:
        return self.rail_z1 + 1.5

    def dowels(self) -> list[tuple[float, float, float]]:
        """(travel, x, z) of each dowel hole (one each side at x and -x): two staggered rows,
        so 2.5 mm steps fit."""
        out = []
        for i, t in enumerate(self.travels):
            x = self.spring_x + (1.7 if i % 2 == 0 else -1.7)
            out.append((t, x, self.lid_z1 + t + self.dowel_d / 2))
        return out

    def m3_spots(self) -> list[float]:
        return [-self.m3_pitch / 2, self.m3_pitch / 2]

    def shims(self) -> list[tuple[float, float, float, float]]:
        gap = self.m3_pitch / 2 - self.standoff_d / 2 - 0.5
        z1 = self.m3_z + self.above_room - self.room_play
        top = (-gap, gap, z1 - self.shim_h, z1)
        z0 = self.m3_z - self.below_room + self.room_play
        low = (-self.plate_half + 1.0, self.plate_half - 1.0, z0, z0 + self.shim_h)
        return [top, low]

    def pads(self) -> list[tuple[float, float, float, float]]:
        """(x0, x1, z0, z1) of the pad's flat face on the back, as deep as the standoffs; its
        45 deg ramp below starts at the plate's back at pad_from."""
        hw = self.plate_half - 1.0
        z0 = self.plate_z0 + self.pad_from + self.standoff_h
        return [(-hw, hw, z0, self.plate_z0 + self.pad_to)]


def _box(x0: float, x1: float, y0: float, y1: float, z0: float, z1: float) -> Manifold:
    return Manifold.cube([x1 - x0, y1 - y0, z1 - z0]).translate([x0, y0, z0])


def _xz_plate(sec: CrossSection, y0: float, y1: float) -> Manifold:
    return sec.extrude(y1 - y0).rotate([90, 0, 0]).translate([0, y1, 0])


def _shims(p: FloatHolder) -> list[Manifold]:
    s = p.standoff_h
    out = []
    for x0, x1, z0, z1 in p.shims() + p.pads():  # a 45 deg slope under each: no support
        sec = CrossSection([[(0.01, z0 - s), (0.01, z1), (-s, z1), (-s, z0)]])  # (y, z)
        out.append(sec.extrude(x1 - x0).rotate([90, 0, 90]).translate([x0, 0, 0]))
    return out


def _teardrop_z(d: float, x: float, y: float, z0: float, z1: float) -> Manifold:
    """A hole along z with a 45 deg point towards +x (up when the L prints on its side)."""
    r = d / 2
    pts = [
        (r * math.cos(math.radians(a)), r * math.sin(math.radians(a))) for a in range(45, 316, 10)
    ]
    pts.append((r * math.sqrt(2), 0.0))
    return CrossSection([pts]).extrude(z1 - z0).translate([x, y, z0])


def build_plate(p: FloatHolder | None = None) -> Manifold:
    """The part on the printer: prints standing up, as built."""
    p = p or FloatHolder()
    hw, r = p.plate_half, p.corner_r
    w, cw = p.rail_w / 2, p.car_w / 2
    parts = [
        _xz_plate(_rounded_rect(-hw, hw, p.plate_z0, p.plate_z1, r), 0, p.plate_t),
        *_shims(p),
        _box(-w, w, p.plate_t - 0.01, p.rail_y0, p.rail_z0, p.rail_z1),  # the strip
        _box(-cw, cw, p.plate_t - 0.01, p.leg_y0 - 0.5, p.plate_z0, 0.0),  # the column
    ]
    body = Manifold.batch_boolean(parts, OpType.Add)
    rw = w + 0.15
    cuts = [_box(-rw, rw, p.rail_y0, p.rail_y1 + 0.3, p.rail_z0, 1.0)]  # the rail's foot end
    for x in p.m3_spots():  # the printer's screws, heads sunk
        cuts.append(_teardrop_y(p.m3_d, x, p.m3_z, -1, p.rail_y0 + 1))
        cuts.append(_teardrop_y(p.m3_head_d, x, p.m3_z, p.m3_clamp, p.rail_y0 + 0.01))
    for z in p.rail_holes():  # the rail's self-tapping screws, blind
        cuts.append(_teardrop_y(p.tap_d, 0.0, z, 1.0, p.rail_y0 + 0.01))
    for s in (-1, 1):
        x = s * p.spring_x
        cuts.append(_teardrop_y(p.tap_d, x, p.low_post_z, 0.5, p.plate_t + 0.01))
        for _, dx, z in p.dowels():
            cuts.append(_teardrop_y(p.dowel_d, s * dx, z, p.plate_t - p.dowel_in, p.plate_t + 0.01))
    return body - Manifold.batch_boolean(cuts, OpType.Add)


def build_l(p: FloatHolder | None = None) -> Manifold:
    """The part on the block, built where it sits (print_poses lays it on its side)."""
    p = p or FloatHolder()
    hw, r = p.leg_half, p.corner_r
    parts = [
        _xz_plate(_rounded_rect(-hw, hw, p.base_z, p.lid_z1, r), p.leg_y0, p.leg_y1),
        _box(-hw, hw, p.lid_y0, p.leg_y0 + 0.01, p.lid_z0, p.lid_z1),  # the overhang
    ]
    base = _rounded_rect(-hw, hw, p.leg_y0 - r, p.base_y1, r).extrude(p.base_t)
    base = (base ^ _box(-hw, hw, p.leg_y0, p.base_y1, 0, p.base_t)).translate([0, 0, p.base_z])
    parts.append(base)
    zb = p.base_z + p.base_t
    tri = CrossSection(
        [[(p.leg_y1 - 0.01, zb - 0.01), (p.base_y1, zb - 0.01), (p.leg_y1 - 0.01, zb + p.rib_h)]]
    )
    rib = tri.extrude(p.rib_t).rotate([90, 0, 90])
    parts += [rib.translate([hw - p.rib_t, 0, 0]), rib.translate([-hw, 0, 0])]
    body = Manifold.batch_boolean(parts, OpType.Add)
    rw = p.rail_w / 2 + p.notch_play
    cuts = [_box(-rw, rw, 0, p.rail_y1 + p.notch_play, p.lid_z0 - 1, p.lid_z1 + 1)]  # the rail
    fd = p.flange_d + p.flange_play
    cuts.append(_teardrop_z(fd, 0.0, p.motor_y, p.base_z - 1, zb + 1))
    for x, y in p.m2_spots():
        cuts.append(_teardrop_z(p.m2_d, x, y, p.base_z - 1, zb + 1))
        cuts.append(_teardrop_z(p.m2_head_d, x, y, p.base_z - 1, p.base_z + p.base_t - p.m2_clamp))
    for x, z in p.car_holes():
        cuts.append(_teardrop_y(p.m3_d, x, z, p.leg_y0 - 1, p.leg_y1 + 1))
    for s in (-1, 1):  # each spring's hook in a slot, the upper screw across it
        x0, x1 = sorted((s * (p.spring_x + p.spring_r), s * (p.rail_w / 2)))
        cuts.append(
            _box(
                x0,
                x1,
                p.spring_y - p.slot_w / 2,
                p.spring_y + p.slot_w / 2,
                p.lid_z0 - 1,
                p.post_z + 2.2,
            )
        )
        cuts.append(_teardrop_y(p.tap_d, s * p.spring_x, p.post_z, p.lid_y0 - 1, p.leg_y1 + 1))
        y = p.leg_y1 - p.head_sink  # the M3 x 20 still reaches past the hook's slot
        cuts.append(_teardrop_y(p.head_d, s * p.spring_x, p.post_z, y, p.leg_y1 + 1))
    return body - Manifold.batch_boolean(cuts, OpType.Add)


# ---- the bought parts, where they are (to check that everything clears)
def rail_box(p: FloatHolder) -> Manifold:
    return _box(-p.rail_w / 2, p.rail_w / 2, p.rail_y0, p.rail_y1, p.rail_z0, p.rail_z1)


def block_box(p: FloatHolder, rise: float = 0.0) -> Manifold:
    w = p.car_w / 2
    return _box(-w, w, p.car_y0, p.leg_y0, rise, p.car_l + rise)


def motor_box(p: FloatHolder, rise: float = 0.0) -> Manifold:
    w = p.motor_w / 2
    z = p.base_z + p.base_t + rise
    return _box(-w, w, p.motor_y - w, p.motor_y + w, z, z + p.motor_l)


def spring_body(p: FloatHolder, x: float, rise: float = 0.0) -> Manifold:
    """A spring between its screws, as a cylinder (the hooks left out)."""
    z0, z1 = p.low_post_z + 2.0, p.lid_z0 + rise - 0.5
    r = p.spring_od / 2
    return Manifold.cylinder(z1 - z0, r, r, SEG).translate([x, p.spring_y, z0])


def dowel(p: FloatHolder, x: float, z: float) -> Manifold:
    """A Ø2.5 x 10 pin pressed into its hole."""
    return (
        Manifold.cylinder(10.0, 1.25, 1.25, 24)
        .rotate([-90, 0, 0])
        .translate([x, p.plate_t - p.dowel_in, z])
    )


def print_poses(p: FloatHolder | None = None) -> dict[str, Manifold]:
    """Each part the way it prints, on z = 0, without supports: the plate standing up, the L on
    its side (its profile in every layer: strong across the bend, the overhang no overhang)."""
    p = p or FloatHolder()
    plate = build_plate(p)
    lpart = build_l(p).rotate([0, -90, 0])  # +x up: the teardrops point up
    return {
        "plate": plate.translate([0, 0, -plate.bounding_box()[2]]),
        "l": lpart.translate([0, 0, -lpart.bounding_box()[2]]),
    }


def _mesh(m: Manifold) -> Mesh:
    from .gridfinity import _to_mesh

    return _to_mesh(m)


NOTES = """Floating tool holder (sortering-pnp print catalogue)

The tool rides up a miniature linear rail when it hits the bed or a pile of parts; two
extension springs behind the block pull it back down onto a column. For a JLCMC
E-BMN12H-1-L100-Z0-P-M-E12.5 (MGN12H sizes: rail 12 x 8 x 100, M3 holes every 25 mm; block
27 x 45.4, 4 x M3 on 20 x 20) and two {od:g} x {length:g} springs. The printer's interface and the motor's
seat are the tool holder's: 2 x M3, {m3_pitch:g} mm apart, into the {standoff_h:g} mm standoffs; NEMA 8, 4 x M2
on a 16 mm square, Ø{flange_hole:g} flange hole.

Print, PETG or PLA, 0.4 mm nozzle, 0.2 mm layers, 4 walls, 40 % infill or more, no supports:
- float_plate.stl: standing up, as exported.
- float_l.stl: on its side, as exported (strong across the bend).

Screws and pins:
- 2 x M3, the printer's: the tool holder's screws ({m3_clamp:g} mm of plate under the heads).
- 4 x M3 x 10 self-tapping: the rail.
- 4 x M3 x 8: the L on the block ({car_thread:g} mm of thread in it).
- 4 x M2 x 5: the motor, as on the tool holder.
- 2 x M3 x 8 self-tapping: the lower spring screws, into the plate (about 3 mm left out).
- 2 x M3 x 20 self-tapping: the upper spring screws, from the L's front through the overhang.
- 2 x dowel pin Ø2.5 x 10: the top stop.

Fitting, in this order:
1. The plate on the printer's standoffs, its two M3 screws sunk in their counterbores. The pad on
   its back ({pads} mm above its bottom edge) rests on the head: it does not lever.
2. The rail (with its block on it) on the strip, its foot end down in the notch of the
   column. Slide the block up to reach the two lower holes; screw all four.
3. The lower spring screws, block slid up: about 3 mm of shank left out, a hook on each.
4. The L on the block: 4 x M3 x 8. Slide the block down onto the column.
5. Each spring's upper hook up into its slot in the overhang, the upper screw from the front
   through the overhang and the hook.
6. The motor on the L's foot (4 x M2 x 5 from below), then the tool.
7. The dowel pins: one each side, pressed into the pair of holes for the travel you want:
{travels}
   Each mm of travel stretches the springs by a mm: keep within what they take (a 15 mm core
   that stretches to 25 mm takes 10 mm).

The block's screws stay reachable above the motor: the L comes off the block with the motor on.
After fitting, redo Tip height and Camera to printer on the Setup tab: the tool's axis is
{dy:.1f} mm further from the head than on the tool holder and {dz:.1f} mm higher.
Size: plate {pw:g} wide x {ph:g} high, {pd:g} deep; it reaches {above:g} mm above the printer's screws.
"""


def holder_files(p: FloatHolder | None = None) -> list[tuple[str, bytes]]:
    from .meshio import stl_bytes
    from .toolholder import ToolHolder

    p = p or FloatHolder()
    t = ToolHolder()
    rows = "\n".join(
        f"   {tr:4g} mm: the holes {z - p.plate_z0:.1f} mm above the plate's bottom, {dx:.2f} mm off the middle"
        for tr, dx, z in p.dowels()
    )
    notes = NOTES.format(
        od=p.spring_od,
        length=p.spring_len,
        m3_pitch=p.m3_pitch,
        standoff_h=p.standoff_h,
        flange_hole=p.flange_d + p.flange_play,
        m3_clamp=p.m3_clamp,
        car_thread=p.car_thread,
        travels=rows,
        pads=f"ramp from {p.pad_from:g}, step at {p.pad_to:g}",
        dy=p.motor_y - t.motor_y,
        dz=(t.m3_z - 0.0) - (p.m3_z - p.base_z),
        pw=round(2 * p.plate_half, 1),
        ph=round(p.plate_z1 - p.plate_z0, 1),
        pd=round(p.leg_y0 - 0.5, 1),
        above=round(p.plate_z1 - p.m3_z, 1),
    )
    poses = print_poses(p)
    return [
        (
            "float_plate.stl",
            stl_bytes(_mesh(poses["plate"]), "sortering-pnp floating holder plate"),
        ),
        ("float_l.stl", stl_bytes(_mesh(poses["l"]), "sortering-pnp floating holder L")),
        ("FLOAT_HOLDER.txt", notes.encode()),
    ]
