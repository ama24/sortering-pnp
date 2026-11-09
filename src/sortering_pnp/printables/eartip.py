"""A PLA tip for the suction picker that carries an earphone's silicone ear tip as its cup.

The same Ø7 shank as the TPU cups (7 mm into the picker's socket, 3 M3 screws at 120 deg into
blind holes), a Ø4.2 bore all the way, and at the end a barb for the ear tip: a groove Ø5.5,
2 mm long, between the body's shoulder (Ø7) and a collar Ø7.5. The ear tip's sleeve slides over
the collar's 45 deg lead-in and its inner lip snaps into the groove; the collar's flat underside
keeps it there. The silicone does the sealing and the give, so the body is PLA (stiff, exact).

Printed standing on the shank's end, collar up, no supports: the only overhang is the collar's
flat underside, a 1 mm ring that PLA bridges cleanly with the fan on.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from manifold3d import CrossSection, Manifold

from .meshio import Mesh

SEG = 96  # facets round the axis


@dataclass(frozen=True)
class EarTip:
    bore_d: float = 4.2  # the air channel, all the way through
    body_d: float = 7.0  # shank and neck, as the cups
    shank_l: float = 7.0  # into the picker's 7 mm socket
    groove_d: float = 5.5  # where the ear tip's inner lip sits
    groove_l: float = 2.0  # room for that lip (the clearance that traps it)
    collar_d: float = 7.5  # holds the lip in the groove
    collar_l: float = 1.0  # straight part of the collar
    lead_l: float = 1.0  # 45 deg lead-in above it: the sleeve slides on
    length: float = 30.0  # shank's end to the collar's top (the ear tip sticks out ~6-8 mm more)
    fix_z: float = 3.5  # the M3 screws' axis, from the shank's end (as the cups)
    fix_d: float = 2.6  # blind hole for an M3 screw's point
    fix_depth: float = 0.6  # shallower than the cups': the Ø4.2 bore is closer to the outside

    @property
    def name(self) -> str:
        return "tip_eartip_pla"

    def marks(self) -> dict[str, float]:
        """The heights that matter, from the shank's end (z = 0)."""
        top = self.length
        lead = top - self.lead_l
        collar = lead - self.collar_l
        groove = collar - self.groove_l
        return {"shoulder": groove, "collar": collar, "lead": lead, "top": top}

    def check(self) -> None:
        if self.groove_d - self.bore_d < 2 * 0.6 - 1e-9:
            raise ValueError("the groove's wall is under 0.6 mm: a 0.4 nozzle can't print it")
        if not self.groove_d < self.body_d < self.collar_d + 1.0:
            raise ValueError("the groove must be the narrowest part of the outside")
        if self.body_d / 2 - self.fix_depth - self.bore_d / 2 < 0.6:
            raise ValueError("the screws' holes come too close to the bore: it would leak")
        if self.marks()["shoulder"] < self.shank_l + 3.0:
            raise ValueError("too short: no neck left between the socket and the groove")


def profile(t: EarTip) -> list[tuple[float, float]]:
    """The half section (r, z) to revolve: up the outside, back down the bore."""
    t.check()
    m = t.marks()
    R, rb, rg, rc = t.body_d / 2, t.bore_d / 2, t.groove_d / 2, t.collar_d / 2
    lead_r = max(rg, rc - t.lead_l)  # 45 deg: in by as much as it rises
    return [
        (rb, 0.0),
        (R, 0.0),
        (R, m["shoulder"]),
        (rg, m["shoulder"]),
        (rg, m["collar"]),
        (rc, m["collar"]),
        (rc, m["lead"]),
        (lead_r, m["top"]),
        (rb, m["top"]),
    ]


def build(t: EarTip) -> Manifold:
    body = CrossSection([profile(t)]).revolve(SEG)
    R = t.body_d / 2
    for k in range(3):  # the three M3 screws, as the cups: blind holes, 120 deg apart
        pin = (
            Manifold.cylinder(t.fix_depth + 1.0, t.fix_d / 2, t.fix_d / 2, 24)
            .rotate([0, 90, 0])
            .translate([R - t.fix_depth, 0, t.fix_z])
            .rotate([0, 0, 90.0 + 120.0 * k])
        )
        body = body - pin
    return body


def eartip_mesh(t: EarTip) -> Mesh:
    from .gridfinity import _to_mesh

    return _to_mesh(build(t))


EARTIP_NOTES = """Ear-tip holder for the suction picker (sortering-pnp print catalogue: prints/cups/)

{name}.stl carries an earphone's silicone ear tip as the suction cup.

Material: PLA. 0.4 mm nozzle, 0.2 mm layers (0.12 for a cleaner barb), 3 walls, 100 % infill,
no supports, fan on. Stand it on the shank's end (as exported), collar up.

Fit: the Ø{body_d:g} shank goes {shank_l:g} mm into the picker's socket like the TPU cups; the 3 M3
screws, {fix_z:g} mm from the socket's bottom, press into its blind holes (Ø{fix_d:g}, {fix_depth:g} mm
deep). Snug, not tight: PLA cracks.

Bore: Ø{bore_d:g} all the way. The barb at the end: groove Ø{groove_d:g}, {groove_l:g} mm long, between the
body's shoulder (Ø{body_d:g}) and a collar Ø{collar_d:g} ({collar_l:g} mm straight, then a 45 deg lead-in).
Push the ear tip's sleeve over the collar until its inner lip clicks into the groove. The
groove's wall is {wall:.2f} mm: let the slicer print it as one wide line (Arachne).

Length: {length:g} mm to the collar's top, the ear tip adds its own (often 6-8 mm). Different
from the cups' 37 mm: after fitting it, do Setup's tip step again (tip height).
"""


def eartip_files() -> list[tuple[str, bytes]]:
    from .meshio import stl_bytes

    t = EarTip()
    notes = EARTIP_NOTES.format(
        name=t.name,
        body_d=t.body_d,
        shank_l=t.shank_l,
        fix_z=t.fix_z,
        fix_d=t.fix_d,
        fix_depth=t.fix_depth,
        bore_d=t.bore_d,
        groove_d=t.groove_d,
        groove_l=t.groove_l,
        collar_d=t.collar_d,
        collar_l=t.collar_l,
        wall=(t.groove_d - t.bore_d) / 2,
        length=t.length,
    )
    return [(f"{t.name}.stl", stl_bytes(eartip_mesh(t), t.name)), ("EARTIP.txt", notes.encode())]


def volume_mm3(t: EarTip) -> float:
    """Solid volume (for a quick check against the section)."""
    p = profile(t)
    v = 0.0
    for (r0, z0), (r1, z1) in zip(p, p[1:] + p[:1], strict=True):
        v += math.pi * (r0 * r0 + r0 * r1 + r1 * r1) * (z1 - z0) / 3
    return abs(v)
