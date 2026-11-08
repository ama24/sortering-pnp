"""Suction cups in TPU 95A for the suction picker: one straight body, five tips, each with and
without a sieve.

The body: a Ø7 shank that goes 7 mm into the picker's socket, held by 3 M3 screws at 120 deg
that press into blind holes (blind: a hole through to the bore would leak), then a straight Ø7
neck of 20 mm with the Ø4.3 bore of the pump's tube. No channel is wider than 4.3 mm: the folds
of the bellows go inwards (the passage narrows to about Ø2 there, still wider than the tip's hole).

The tips (screws lie on the plate; every hole is smaller than an M2's core, Ø1.57, so no screw
goes in):
- A: two stiff folds and a cone lip: flat faces (pan, button, cheese and hex heads, nuts).
- D: four soft folds and a thin skirt (0.45 mm at its edge): takes up a few mm of height and
  follows curved or tilted faces.
S, M and L are the lip's size (S for M2-M3 heads, M for M4-M5, L for M6, M8 at a pinch).
`sieve`: instead of one hole, a dome with many small ones; the part rests on the dome's flat top,
0.4 mm below the lip (the lip seals first), so the holes on its sides stay open: the part can't
plug the cup, more air flows, and it lets go at once.

Printed standing on the shank's end, tip up, no supports: every overhang is 45 deg or steeper
(the dome and the floors are cones). TPU 95A, 0.4 mm nozzle, 3 walls, slow (20-25 mm/s).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from manifold3d import CrossSection, Manifold

from .meshio import Mesh

SEG = 72  # facets round the axis


@dataclass(frozen=True)
class Tip:
    name: str  # AS, AM, DS, DM, DL
    style: str  # "A" cone lip | "D" thin skirt
    lip_d: float  # outside Ø of the lip
    rim_t: float  # lip wall at the rim (D: the skirt's edge)
    depth: float  # floor (or the dome's top) to the rim
    folds: int  # bellows folds
    pitch: float  # mm per fold
    amp: float  # how far a fold goes in
    fold_t: float  # wall of the folds (measured across, horizontally)
    hole_d: float  # the single hole (without sieve)
    sieve_d: float  # each hole of the sieve
    use: str


TIPS: dict[str, Tip] = {
    t.name: t
    for t in (
        Tip("AS", "A", 4.4, 0.7, 1.8, 2, 3.0, 1.0, 1.0, 1.0, 0.7, "M2-M3 heads, flat faces"),
        Tip("AM", "A", 6.2, 0.8, 2.2, 2, 3.0, 1.0, 1.0, 1.4, 0.9, "M4-M5 heads, flat faces"),
        Tip("DS", "D", 5.2, 0.45, 2.6, 4, 2.4, 1.1, 0.9, 1.0, 0.7, "M2-M3, curved or tilted"),
        Tip("DM", "D", 7.6, 0.45, 3.2, 4, 2.4, 1.1, 0.9, 1.4, 0.9, "M3-M5, curved or tilted"),
        Tip("DL", "D", 10.6, 0.45, 3.8, 4, 2.4, 1.1, 0.9, 1.4, 0.9, "M5-M6 (M8), curved"),
    )
}


@dataclass(frozen=True)
class Cup:
    tip: Tip
    sieve: bool = False
    body_d: float = 7.0  # shank and neck: straight
    shank_l: float = 7.0  # into the picker's 7 mm socket
    neck_l: float = 20.0  # below the socket, at least (longer to make every cup `length` long)
    length: float = (
        47.0  # shank's end to the lip, the same for every cup: swap without recalibrating
    )
    bore_d: float = 4.3  # the pump tube's inside: no channel wider
    shank_bore_d: float = 3.2  # narrower in the shank: wall left behind the screws' holes
    fix_z: float = 3.5  # the M3 screws' axis, from the shank's end (the socket's bottom)
    fix_d: float = 2.6  # blind hole for an M3 screw's point (the thread bites around it)
    fix_depth: float = 1.0
    floor_t: float = 0.8  # the plate the hole goes through, the dome
    recess: float = 0.4  # the dome's top below the rim: the lip seals first
    plateau_r: float = 0.3  # the dome's top, where the part rests: no hole there
    web: float = 0.45  # TPU between two sieve holes
    holes: list[tuple[float, float]] = field(default_factory=list, compare=False)

    @property
    def name(self) -> str:
        return f"cup_{self.tip.name}" + ("_sieve" if self.sieve else "")


def _inside(c: Cup) -> tuple[float, float, float]:
    """(the cup's inside radius at its floor, its wall there, at the rim)."""
    t = c.tip
    rim_in = t.lip_d / 2 - t.rim_t
    if t.style == "A":  # a short cup, its inside a little conical (straight with the sieve)
        ci, wall = (rim_in if c.sieve else rim_in - 0.4), 1.0
    else:  # the skirt: its inside flares 0.6 mm more, 0.9 mm thick at the base
        ci, wall = rim_in - 0.6, 0.9
    return ci, wall, rim_in


def _profile(c: Cup) -> tuple[list[tuple[float, float]], dict[str, float]]:
    """The half section, its neck made longer so the lip is at `length` (the same for every cup:
    the tip height stays when the cup is swapped)."""
    _, marks = _profile_at(c, c.neck_l)
    extra = c.length - marks["rim"]
    if extra < -1e-9:
        raise ValueError(
            f"{c.name}: {marks['rim']:.2f} mm long with the shortest neck, over {c.length:g}"
        )
    return _profile_at(c, c.neck_l + extra)


def _profile_at(c: Cup, neck_l: float) -> tuple[list[tuple[float, float]], dict[str, float]]:
    """The half section (r, z) to revolve, from the shank's end (z = 0) up to the lip, and the
    heights that matter: the outside up, the inside back down, one simple polygon. Every slope
    is 45 deg or steeper: it prints standing on the shank with no supports."""
    t = c.tip
    R, rb, rs = c.body_d / 2, c.bore_d / 2, c.shank_bore_d / 2
    z_neck = c.shank_l + neck_l
    r_fold = rb + t.fold_t  # the folds' outside, before folding in
    outer = [(R, 0.0), (R, z_neck), (r_fold, z_neck + (R - r_fold))]
    z = z_neck + (R - r_fold)
    inner = [(rs, 0.0), (rs, c.shank_l), (rb, c.shank_l + rb - rs), (rb, z)]
    for _ in range(t.folds):  # each fold in, then out: 45 deg at most (amp <= pitch / 2)
        h = t.pitch / 2
        outer += [(r_fold - t.amp, z + h), (r_fold, z + 2 * h)]
        inner += [(rb - t.amp, z + h), (rb, z + 2 * h)]
        z += 2 * h
    z_b = z
    ci, wall, rim_in = _inside(c)
    marks = {"neck_top": z_neck, "folds_top": z_b}
    if c.sieve:  # out to the cup's inside, then a dome (45 deg) up to its flat top
        q = z_b + abs(ci - rb)
        under = q + (ci - c.plateau_r)
        top = under + c.floor_t
        floor = q + c.floor_t  # where the dome meets the wall
        rim = top + c.recess
        inner += [(ci, q), (c.plateau_r, under), (0.0, under), (0.0, top), (c.plateau_r, top)]
        marks |= {"dome_under": under, "dome_top": top}
    else:  # in to the hole (a cone), through the plate, a funnel out to the cup's wall
        r0 = t.hole_d / 2
        p2 = z_b + (rb - r0)
        p3 = p2 + c.floor_t
        floor = p3 + (ci - r0)
        rim = floor + t.depth
        inner += [(r0, p2), (r0, p3)]
        marks |= {"hole_top": p3}
    inner.append((ci, floor))
    base_r = ci + wall
    rise = abs(base_r - r_fold)  # out (or in) to the cup at 45 deg, along the floor below it
    z1 = max(z_b, floor - rise)
    outer += [(r_fold, z1), (base_r, z1 + rise)]
    if floor > z1 + rise + 1e-9:
        outer.append((base_r, floor))
    n = 1 if t.style == "A" else 8
    for k in range(1, n + 1):  # A: one straight cone; D: a skirt flaring and thinning
        u = k / n
        zz = floor + (rim - floor) * u
        ro = base_r + (t.lip_d / 2 - base_r) * (u if t.style == "A" else u**1.6)
        th = wall + (t.rim_t - wall) * u
        outer.append((ro, zz))
        inner.append((ro - th, zz))
    marks |= {"floor": floor, "rim": rim, "transition": z1 + rise}
    return outer + list(reversed(inner)), marks


def holes(c: Cup) -> list[tuple[float, float]]:
    """(x, y) of the sieve's holes: rings on the dome's sides, none on its top (the part rests
    there, so it can't cover them). At least 3."""
    d = c.tip.sieve_d
    ci = _inside(c)[0]
    lo, hi = c.plateau_r + d / 2 + 0.15, ci - d / 2 - 0.25
    if hi < lo - 1e-9:
        raise ValueError(f"{c.tip.name}: no room for a sieve hole of Ø{d:g}")
    out: list[tuple[float, float]] = []
    step = d + c.web
    rho, k = lo, 0
    while rho <= hi + 1e-9:
        n = max(3, int(2 * math.pi * rho / step))
        for j in range(n):
            a = 2 * math.pi * j / n + (k % 2) * math.pi / n
            out.append((rho * math.cos(a), rho * math.sin(a)))
        rho += step
        k += 1
    return out


def build(c: Cup) -> Manifold:
    poly, marks = _profile(c)
    body = CrossSection([poly]).revolve(SEG)
    # the three M3 screws: blind holes into the shank, 120 deg apart
    R = c.body_d / 2
    for k in range(3):
        a = 90.0 + 120.0 * k
        pin = (
            Manifold.cylinder(c.fix_depth + 1.0, c.fix_d / 2, c.fix_d / 2, 24)
            .rotate([0, 90, 0])
            .translate([R - c.fix_depth, 0, c.fix_z])
            .rotate([0, 0, a])
        )
        body = body - pin
    if c.sieve:  # vertical holes through the dome
        under, top, pl = marks["dome_under"], marks["dome_top"], c.plateau_r
        for x, y in holes(c):
            rho = math.hypot(x, y)
            z0 = under + min(0.0, pl - rho) - 0.2  # the dome's underside there (45 deg)
            z1 = top + min(0.0, pl - rho) + 0.2
            h = Manifold.cylinder(z1 - z0, c.tip.sieve_d / 2, c.tip.sieve_d / 2, 16)
            body = body - h.translate([x, y, z0])
    return body


def cup_mesh(c: Cup) -> Mesh:
    from .gridfinity import _to_mesh

    return _to_mesh(build(c))


def all_cups() -> list[Cup]:
    return [Cup(t, sieve) for t in TIPS.values() for sieve in (False, True)]


CUP_NOTES = """Suction cups for the suction picker (sortering-pnp print catalogue: prints/cups/)

Material: TPU 95A. 0.4 mm nozzle, 0.2 mm layers, 3 walls (or more: the folds are walls only),
100 % infill, 20-25 mm/s, no supports. Stand it on the shank's end (as exported), tip up.

Fit: the Ø7 shank goes 7 mm into the picker's socket; 3 M3 screws, 120 deg apart, {fix_z:g} mm from
the socket's bottom, press into its blind holes (Ø{fix_d:g}, {fix_depth:g} mm deep: they don't reach
the bore, nothing leaks). Snug them, don't crush the TPU.

Length: every cup is {length:g} mm from the shank's end to the lip (the neck makes up the
difference, {neck:g} mm or more below the socket): swap cups without measuring the tip height again.

Body: straight Ø7, bore Ø4.3 (the pump's tube; Ø3.2 in the shank,
behind the screws). The folds go inwards: no channel is wider than 4.3 mm.

Tips (every hole smaller than an M2's core, Ø1.57: no screw goes in):
{table}
A: two stiff folds and a cone lip, for flat faces (pan, button, cheese and hex heads, nuts).
D: four soft folds and a thin skirt (0.45 mm at the edge): a few mm of give, follows curved and
   tilted faces (the side of a head, countersunk heads).
_sieve: a dome with many small holes instead of one. The part rests on the dome's flat top,
   0.4 mm below the lip, so the holes on its sides stay open: it can't plug the cup, more air
   flows, and it lets go at once. Holding force is the same (vacuum x the lip's area).
"""


def cup_files() -> list[tuple[str, bytes]]:
    from .meshio import stl_bytes

    out = []
    rows = []
    for c in all_cups():
        out.append((f"{c.name}.stl", stl_bytes(cup_mesh(c), c.name)))
        if not c.sieve:
            t = c.tip
            n = len(holes(Cup(t, True)))
            _, marks = _profile(c)
            rows.append(
                f"  {t.name}  lip Ø{t.lip_d:g}, {t.folds} folds, hole Ø{t.hole_d:g} "
                f"(sieve: {n} x Ø{t.sieve_d:g}), neck {marks['neck_top'] - c.shank_l:.1f} mm: {t.use}"
            )
    c0 = Cup(TIPS["AS"])
    notes = CUP_NOTES.format(
        fix_z=c0.fix_z,
        fix_d=c0.fix_d,
        fix_depth=c0.fix_depth,
        neck=c0.neck_l,
        length=c0.length,
        table="\n".join(rows),
    )
    out.append(("CUPS.txt", notes.encode()))
    return out
