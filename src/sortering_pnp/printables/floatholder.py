"""Floating tool holder: the tool rides up on a miniature linear rail when it hits the bed, two
extension springs pull it back down (like a pick-and-place head). Same printer interface as
toolholder.py (2 x M3, 14 mm apart, into two 4.5 mm standoffs) and the same motor seat (NEMA 8
size: M2 holes on a 16 mm square, a Ø15 flange through the plate).

The rail: JLCMC E-BMN12H-1-L100-Z0-P-M-E12.5 (MGN12H sizes: rail 12 x 8, 100 long, M3 holes every
25 mm, 12.5 from each end; block 27 wide, 45.4 long, 13 from the rail's foot to its top, 4 x M3
on 20 x 20). Three printed parts:

- The plate, on the printer. Its two M3 screws sit in counterbores, the heads under the rail.
  The rail lies in a shallow groove (straight), its foot end in a notch of the ledge at the
  bottom; M3 self-tapping screws hold it. The ledge is the rest stop: the 90° piece sits on it.
  Two shims on the back, as on the tool holder, rest on the head.
- The 90° piece, on the carriage (4 x M3 into the block). The motor stands on its foot as on
  the tool holder. Its ears at the top carry the moving spring posts.
- The stop block, on the rail's two top holes: the 90° piece hits it after `travel`, so the
  carriage never leaves the rail and the springs are never over-stretched.

Two extension springs, one each side of the carriage, hang from M3 screws: in the ears (the
moving posts) and in the plate (one hole per spring length in SPRINGS: use the one that fits).

Built where it sits: x across, y away from the printer (the plate's back at y = 0), z up (the
90° piece's foot, at rest, at z = 0).
"""

from __future__ import annotations

from dataclasses import dataclass

from manifold3d import CrossSection, Manifold, OpType

from .meshio import Mesh
from .toolholder import SEG, _rounded_rect, _teardrop_y

# the extension springs it takes: (outside Ø, length over the hooks), mm
SPRINGS: tuple[tuple[float, float], ...] = ((5.0, 20.5), (5.5, 25.5), (7.0, 38.0), (7.0, 51.0))


@dataclass(frozen=True)
class FloatHolder:
    # the printer's interface (as toolholder.ToolHolder)
    m3_pitch: float = 14.0  # the two M3 screws, centre to centre
    m3_d: float = 3.4  # clearance for M3
    m3_head_d: float = 6.5  # counterbore: an M3 socket head (Ø5.5) sinks in
    m3_clamp: float = 4.0  # plate left under the heads: the same screws as the tool holder's
    m3_z: float = 60.0  # the printer's screws, above the 90° piece's foot
    standoff_h: float = 4.5
    standoff_d: float = 6.5
    above_room: float = 7.4  # the head's face above the screws
    below_room: float = 15.0  # and below them
    shim_h: float = 4.0
    room_play: float = 0.4
    # the rail and its block (E-BMN12H = MGN12H sizes)
    rail_w: float = 12.0
    rail_h: float = 8.0
    rail_len: float = 100.0
    rail_pitch: float = 25.0  # M3 holes
    rail_end: float = 12.5  # first hole from each end (E12.5)
    rail_drop: float = 1.5  # the rail's foot end below the rest: the block stops before it
    groove: float = 0.6  # the rail lies this deep in the plate
    groove_play: float = 0.3  # on the width
    car_w: float = 27.0
    car_l: float = 45.4
    car_h: float = 13.0  # rail's foot to the block's top
    car_gap: float = 3.0  # rail's foot to the block's underside
    car_pitch: float = 20.0  # 4 x M3 on this square
    car_thread: float = 3.5  # thread depth in the block
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
    # the 90° piece
    leg_t: float = 6.0  # on the block
    car_head_d: float = 6.2  # counterbores for the block's M3 heads
    car_clamp: float = 2.8  # leg left under them: M3 x 6 reaches 3.2 mm into the block
    base_t: float = 4.5  # the motor's foot
    rib_t: float = 2.5
    rib_h: float = 20.0
    ear_h: float = 8.0
    edge: float = 2.5
    corner_r: float = 2.0
    # springs and stops
    travel: float = 8.0  # how far the tool can rise
    spring_y: float = 12.0  # the springs' axis, from the plate's back
    spring_play: float = 1.0  # from the block's side to the widest spring
    post_short: float = (
        2.5  # posts this much closer than the spring's length: a little stretch at rest
    )
    ledge_play: float = 0.5  # the block stays this far above the ledge (the 90° piece rests on it)
    plate_t: float = 8.0
    stop_t: float = 10.0  # the stop block, on the rail's top
    stop_w: float = 20.0
    stop_clamp: float = 3.0  # block left under its screws' heads

    # ---- where things are
    @property
    def rail_y0(self) -> float:
        return self.plate_t - self.groove

    @property
    def rail_y1(self) -> float:
        return self.rail_y0 + self.rail_h

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
        """The 90° piece's back: on the block's top."""
        return self.rail_y0 + self.car_h

    @property
    def leg_y1(self) -> float:
        return self.leg_y0 + self.leg_t

    @property
    def motor_y(self) -> float:
        return self.leg_y1 + self.body_play + self.motor_w / 2

    @property
    def base_y1(self) -> float:
        return self.motor_y + self.motor_pitch / 2 + self.m2_head_d / 2 + self.edge

    @property
    def leg_half(self) -> float:
        """Half the 90° piece's width: the block's screw heads, then a rib each side."""
        return self.car_pitch / 2 + self.car_head_d / 2 + 1.0 + self.rib_t

    @property
    def spring_x(self) -> float:
        return self.car_w / 2 + self.spring_play + max(od for od, _ in SPRINGS) / 2

    @property
    def ear_half(self) -> float:
        return self.spring_x + self.tap_d / 2 + 3.0

    @property
    def post_z(self) -> float:
        """The moving posts (in the ears), at rest."""
        return self.car_l - self.ear_h / 2

    def plate_post_z(self, length: float) -> float:
        return self.post_z - (length - self.post_short)

    @property
    def plate_z0(self) -> float:
        return min(self.plate_post_z(n) for _, n in SPRINGS) - 4.0

    @property
    def plate_z1(self) -> float:
        return self.rail_z1 + 1.5

    @property
    def plate_half(self) -> float:
        return self.ear_half + 2.0

    @property
    def ledge_half(self) -> float:
        return self.car_w / 2 + 0.3

    @property
    def stop_z0(self) -> float:
        return self.car_l + self.travel

    @property
    def stop_z1(self) -> float:
        return self.rail_holes()[-1] + 6.0

    def car_holes(self) -> list[tuple[float, float]]:
        h, zc = self.car_pitch / 2, self.car_l / 2
        return [(sx * h, zc + sz * h) for sx in (-1, 1) for sz in (-1, 1)]

    def m2_spots(self) -> list[tuple[float, float]]:
        h = self.motor_pitch / 2
        return [(sx * h, self.motor_y + sy * h) for sx in (-1, 1) for sy in (-1, 1)]

    def m3_spots(self) -> list[float]:
        return [-self.m3_pitch / 2, self.m3_pitch / 2]

    def shims(self) -> list[tuple[float, float, float, float]]:
        gap = self.m3_pitch / 2 - self.standoff_d / 2 - 0.5
        z1 = self.m3_z + self.above_room - self.room_play
        top = (-gap, gap, z1 - self.shim_h, z1)
        z0 = self.m3_z - self.below_room + self.room_play
        low = (-self.plate_half + 1.0, self.plate_half - 1.0, z0, z0 + self.shim_h)
        return [top, low]


def _box(x0: float, x1: float, y0: float, y1: float, z0: float, z1: float) -> Manifold:
    return Manifold.cube([x1 - x0, y1 - y0, z1 - z0]).translate([x0, y0, z0])


def _xz_plate(sec: CrossSection, y0: float, y1: float) -> Manifold:
    """A section in (x, z) made thick from y0 to y1."""
    return sec.extrude(y1 - y0).rotate([90, 0, 0]).translate([0, y1, 0])


def _shims(p: FloatHolder) -> list[Manifold]:
    s = p.standoff_h
    out = []
    for x0, x1, z0, z1 in p.shims():
        sec = CrossSection([[(0.01, z0 - s), (0.01, z1), (-s, z1), (-s, z0)]])  # (y, z)
        out.append(sec.extrude(x1 - x0).rotate([90, 0, 90]).translate([x0, 0, 0]))
    return out


def build_plate(p: FloatHolder | None = None) -> Manifold:
    """The part on the printer: the rail, the ledge (rest stop), the plate's spring posts."""
    p = p or FloatHolder()
    hw = p.plate_half
    plate = _xz_plate(_rounded_rect(-hw, hw, p.plate_z0, p.plate_z1, p.corner_r), 0, p.plate_t)
    ledge = _box(-p.ledge_half, p.ledge_half, p.plate_t - 0.01, p.leg_y1 - 1.0, p.plate_z0, 0.0)
    body = Manifold.batch_boolean([plate, ledge, *_shims(p)], OpType.Add)
    gw = p.rail_w / 2 + p.groove_play / 2
    cuts = [
        _box(-gw, gw, p.rail_y0, p.plate_t + 1, p.rail_z0, p.plate_z1 + 1),  # the groove
        _box(-gw, gw, p.rail_y0, p.rail_y1 + 0.3, p.rail_z0, 1.0),  # the rail's notch in the ledge
        # the block's place: the 90° piece's leg rests on the ledge, the block does not
        _box(-p.ledge_half - 1, p.ledge_half + 1, p.plate_t - 0.5, p.leg_y0, -p.ledge_play, 1.0),
    ]
    for x in p.m3_spots():  # the printer's screws, their heads sunk under the rail
        cuts.append(_teardrop_y(p.m3_d, x, p.m3_z, -1, p.plate_t + 1))
        cuts.append(_teardrop_y(p.m3_head_d, x, p.m3_z, p.m3_clamp, p.plate_t + 1))
    for z in p.rail_holes():  # self-tapping screws from the rail (blind: they end in the plate)
        cuts.append(_teardrop_y(p.tap_d, 0.0, z, 1.0, p.plate_t + 1))
    for _, length in SPRINGS:  # the plate's spring posts
        for x in (-p.spring_x, p.spring_x):
            cuts.append(_teardrop_y(p.tap_d, x, p.plate_post_z(length), -1, p.plate_t + 1))
    return body - Manifold.batch_boolean(cuts, OpType.Add)


def build_carriage(p: FloatHolder | None = None) -> Manifold:
    """The 90° piece: its leg on the block, the motor on its foot, the moving posts in its ears."""
    p = p or FloatHolder()
    hw, r = p.leg_half, p.corner_r
    leg = _xz_plate(_rounded_rect(-hw, hw, -r, p.car_l, r), p.leg_y0, p.leg_y1)
    leg = leg ^ _box(-hw, hw, p.leg_y0, p.leg_y1, 0, p.car_l)
    ez0, w = p.car_l - p.ear_h, p.ear_half - hw
    ears = []
    for s in (-1, 1):  # 45 deg underneath: prints standing on the foot
        pts = [(hw - 0.01, ez0 - w), (p.ear_half, ez0), (p.ear_half, p.car_l), (hw - 0.01, p.car_l)]
        pts = [(s * x, z) for x, z in pts]
        if s < 0:
            pts.reverse()
        ears.append(_xz_plate(CrossSection([pts]), p.leg_y0, p.leg_y1))
    base = _rounded_rect(-hw, hw, p.leg_y0 - r, p.base_y1, r).extrude(p.base_t)
    base = base ^ _box(-hw, hw, p.leg_y0, p.base_y1, 0, p.base_t)
    tri = CrossSection(
        [
            [
                (p.leg_y1 - 0.01, p.base_t - 0.01),
                (p.base_y1, p.base_t - 0.01),
                (p.leg_y1 - 0.01, p.base_t + p.rib_h),
            ]
        ]
    )
    rib = tri.extrude(p.rib_t).rotate([90, 0, 90])
    ribs = [rib.translate([hw - p.rib_t, 0, 0]), rib.translate([-hw, 0, 0])]
    body = Manifold.batch_boolean([leg, *ears, base, *ribs], OpType.Add)
    fd = (p.flange_d + p.flange_play) / 2
    cuts = [Manifold.cylinder(p.base_t + 2, fd, fd, SEG).translate([0, p.motor_y, -1])]
    cb = p.base_t - p.m2_clamp
    for x, y in p.m2_spots():
        cuts.append(
            Manifold.cylinder(p.base_t + 2, p.m2_d / 2, p.m2_d / 2, 24).translate([x, y, -1])
        )
        cuts.append(
            Manifold.cylinder(cb + 1, p.m2_head_d / 2, p.m2_head_d / 2, 24).translate([x, y, -1])
        )
    for x, z in p.car_holes():  # 4 x M3 into the block, heads sunk in the leg's front
        cuts.append(_teardrop_y(p.m3_d, x, z, p.leg_y0 - 1, p.leg_y1 + 1))
        cuts.append(_teardrop_y(p.car_head_d, x, z, p.leg_y0 + p.car_clamp, p.leg_y1 + 1))
    for x in (-p.spring_x, p.spring_x):  # the moving posts
        cuts.append(_teardrop_y(p.tap_d, x, p.post_z, p.leg_y0 - 1, p.leg_y1 + 1))
    return body - Manifold.batch_boolean(cuts, OpType.Add)


def _hole_y(d: float, x: float, z: float, y0: float, y1: float) -> Manifold:
    return Manifold.cylinder(y1 - y0, d / 2, d / 2, 24).rotate([-90, 0, 0]).translate([x, y0, z])


def build_stop(p: FloatHolder | None = None) -> Manifold:
    """The stop block on the rail's top two holes (screws through it and the rail into the plate)."""
    p = p or FloatHolder()
    h = p.stop_w / 2
    y0, y1 = p.rail_y1, p.rail_y1 + p.stop_t
    body = _box(-h, h, y0, y1, p.stop_z0, p.stop_z1)
    cuts = []
    for z in p.rail_holes()[-2:]:
        cuts.append(_hole_y(p.m3_d, 0.0, z, y0 - 1, y1 + 1))
        cuts.append(_hole_y(p.m3_head_d, 0.0, z, y0 + p.stop_clamp, y1 + 1))
    return body - Manifold.batch_boolean(cuts, OpType.Add)


# ---- the bought parts, where they are (to check that everything clears)
def rail_box(p: FloatHolder) -> Manifold:
    return _box(-p.rail_w / 2, p.rail_w / 2, p.rail_y0, p.rail_y1, p.rail_z0, p.rail_z1)


def block_box(p: FloatHolder, rise: float = 0.0) -> Manifold:
    w = p.car_w / 2
    return _box(-w, w, p.car_y0, p.leg_y0, rise, p.car_l + rise)


def motor_box(p: FloatHolder, rise: float = 0.0) -> Manifold:
    w = p.motor_w / 2
    y = p.motor_y
    return _box(-w, w, y - w, y + w, p.base_t + rise, p.base_t + p.motor_l + rise)


def spring_body(p: FloatHolder, od: float, length: float, x: float, rise: float = 0.0) -> Manifold:
    """A spring between its posts, as a cylinder (the hooks left out)."""
    z0, z1 = p.plate_post_z(length) + 3.0, p.post_z + rise - 3.0
    return Manifold.cylinder(z1 - z0, od / 2, od / 2, SEG).translate([x, p.spring_y, z0])


def _mesh(m: Manifold) -> Mesh:
    from .gridfinity import _to_mesh

    return _to_mesh(m)


def print_poses(p: FloatHolder | None = None) -> dict[str, Manifold]:
    """Each part the way it prints, on z = 0, without supports."""
    p = p or FloatHolder()
    plate = build_plate(p)
    stop = build_stop(p).rotate([90, 0, 0])  # on its back: the screw holes vertical
    return {
        "plate": plate.translate([0, 0, -plate.bounding_box()[2]]),
        "carriage": build_carriage(p),
        "stop": stop.translate([0, 0, -stop.bounding_box()[2]]),
    }


NOTES = """Floating tool holder (sortering-pnp print catalogue)

The tool rides up a miniature linear rail when it hits the bed; two extension springs pull it
back down onto a rest stop. For a JLCMC E-BMN12H-1-L100-Z0-P-M-E12.5 (MGN12H sizes: rail 12 x 8 x
100, M3 holes every 25 mm; block 27 x 45.4, 4 x M3 on 20 x 20). The printer's interface and the
motor's seat are the tool holder's: 2 x M3, {m3_pitch:g} mm apart, into the {standoff_h:g} mm standoffs; NEMA 8,
4 x M2 on a 16 mm square, Ø{flange_hole:g} flange hole.

Print, PETG or PLA, 0.4 mm nozzle, 0.2 mm layers, 4 walls, 40 % infill or more, no supports:
- float_plate.stl: standing up as exported.
- float_carriage.stl: standing on the motor's foot.
- float_stop.stl: lying on its back.

Screws: 2 x M3 (the printer's, as the tool holder: {m3_clamp:g} mm of plate under the heads), 2 x M3 x 10
self-tapping (rail, bottom holes), 2 x M3 x 16 self-tapping (stop block and rail, top holes),
4 x M3 x 6 (90° piece to the block: 3.2 mm in its {car_thread:g} mm threads), 4 x M2 x 5 (motor),
4 x M3 self-tapping as spring posts: 2 x M3 x 18 in the ears, 2 x M3 x 12 in the plate.

Fitting, in this order:
1. The plate on the printer's standoffs, its two M3 screws in their counterbores (the heads
   end under the rail). Two shims on the back rest on the head, as on the tool holder.
2. The rail (with its block on it) in the groove, its foot end down in the notch of the ledge.
   Slide the block up and screw the two bottom holes (M3 x 10 into the plate); slide it back
   down onto the ledge.
3. The stop block on the rail's two top holes: 2 x M3 x 16 through the block and the rail
   into the plate. The block can now move {travel:g} mm and no further.
4. The 90° piece on the block: 4 x M3 x 6, heads in the counterbores (do it before the motor:
   the motor covers them). It rests on the ledge.
5. The motor on its foot as on the tool holder (4 x M2 x 5 from below), then the tool.
6. The spring posts: M3 x 18 from the front into each ear (the tip ends just short of the
   plate, so a hook can not slip off), M3 x 12 into the plate's hole for your springs, heads
   about 6 mm proud. One spring each side, hooks on the screws' shanks.

The plate's holes for each spring (Ø x length over the hooks), {post_short:g} mm closer than its length:
{springs}
The springs together must hold the moving part (90° piece, block, motor, tool: about 140 g)
on the ledge: lift the tool by hand, it should snap back and not sag when the head moves fast.

After fitting, redo Tip height and Camera to printer on the Setup tab: the tool's axis is
{dy:.1f} mm further from the head than on the tool holder and {dz:.1f} mm lower.
Size: plate {pw:g} wide x {ph:g} high; it reaches {above:g} mm above the printer's screws.
"""


def holder_files(p: FloatHolder | None = None) -> list[tuple[str, bytes]]:
    from .meshio import stl_bytes
    from .toolholder import ToolHolder

    p = p or FloatHolder()
    t = ToolHolder()
    springs = "\n".join(
        f"  {od:g} x {n:g}: {p.plate_post_z(n) - p.plate_z0:.1f} mm above the plate's bottom"
        for od, n in SPRINGS
    )
    notes = NOTES.format(
        m3_pitch=p.m3_pitch,
        standoff_h=p.standoff_h,
        flange_hole=p.flange_d + p.flange_play,
        m3_clamp=p.m3_clamp,
        car_thread=p.car_thread,
        travel=p.travel,
        post_short=p.post_short,
        springs=springs,
        dy=p.motor_y - t.motor_y,
        dz=p.m3_z - t.m3_z,
        pw=round(2 * p.plate_half, 1),
        ph=round(p.plate_z1 - p.plate_z0, 1),
        above=round(p.plate_z1 - p.m3_z, 1),
    )
    poses = print_poses(p)
    return [
        (
            "float_plate.stl",
            stl_bytes(_mesh(poses["plate"]), "sortering-pnp floating holder plate"),
        ),
        (
            "float_carriage.stl",
            stl_bytes(_mesh(poses["carriage"]), "sortering-pnp floating holder 90 deg piece"),
        ),
        ("float_stop.stl", stl_bytes(_mesh(poses["stop"]), "sortering-pnp floating holder stop")),
        ("FLOAT_HOLDER.txt", notes.encode()),
    ]
