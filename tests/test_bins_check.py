"""The bins check (binscheck.py): Resync and the start-up check run the model on the whole board,
give each detection to its bin, drop those on the codes and set what each bin collects."""

from __future__ import annotations

import numpy as np

from sortering_pnp import binscheck
from sortering_pnp.layout import Layout
from sortering_pnp.markers import MarkerPose
from sortering_pnp.parts import Part
from sortering_pnp.printer.sim import SimPart, SimPrinter, SimVision, SimWorld
from sortering_pnp.runner import Runner
from sortering_pnp.transform import Transform2D
from sortering_pnp.vision import Shot


def _lay() -> Layout:
    lay = Layout.default()
    lay.bins = [b for b in lay.bins if b.marker in (103, 104, 105)] + [lay.work_bin()]
    for b in lay.bins:
        if b.role != "work":
            b.role = "wild"
    return lay


def _screw(cls: str, x: float, y: float) -> SimPart:
    return SimPart(cls, x, y, 0.0, None, (7.0, 7.0), 3.2)


def _runner(machine, lay, world, out=None):  # noqa: ANN001, ANN202
    lay.save(machine.path(machine.paths.layout))
    vision = SimVision(world, lambda: lay, Transform2D.identity, out)
    runner = Runner(machine, SimPrinter(machine, world), vision)
    runner.setup_home()
    return runner, vision


def _world_104_and_a_code(lay: Layout) -> SimWorld:
    world = SimWorld(seed=1)
    cx, cy = lay.bin_centre(lay.bin_by_marker(104))
    world.parts += [_screw("DIN912_M3", cx - 6, cy - 6), _screw("DIN912_M3", cx + 6, cy - 6)]
    mx, my = lay.marker_centre(lay.bin_by_marker(103))
    world.parts.append(_screw("DIN933_M5", mx, my))  # the code itself, seen as a part
    return world


def test_resync_looks_into_each_bin_on_its_own(machine, tmp_path):
    """One photo, no pass on the whole board; then the model once per storage bin, the rest
    painted over as the tray is for sorting. The code's shelf is painted too: not seen."""
    lay = _lay()
    runner, vision = _runner(machine, lay, _world_104_and_a_code(lay), tmp_path / "runs")
    runner.claims[105] = "ISO7380_M4x8"  # from an earlier session: empty now
    res = runner.scan_bins()
    assert vision.painted == [False]  # the photo: codes only, no model on the whole board
    assert len(vision.areas) == 3  # one per storage bin
    T = runner.transform()
    for area, mk in zip(vision.areas, (103, 104, 105), strict=True):
        b = lay.bin_by_marker(mk)
        assert area.contains(tuple(T.inverse().apply(lay.bin_centre(b))))
        assert not area.contains(tuple(T.inverse().apply(lay.marker_centre(b))))  # shelf
    assert runner.claims == {104: "DIN912_M3"} and runner.bin_counts[104] == 2
    assert "1 with parts" in res["bins_check"] and "2 empty" in res["bins_check"]
    assert "on codes" not in res["bins_check"]
    snap = runner.snapshot()
    bc = snap["bins_check"]  # the results stay over the photo until the next one
    assert bc["finished"] and bc["done"] == 3 and bc["current"] is None
    assert not snap["view"].endswith("_bins.jpg")  # the page draws them on the plain photo
    assert list((tmp_path / "runs").glob("*_bins.jpg"))  # the drawn picture, kept as a record
    runner.take_shot(runner.layout(), runner.transform())  # the next photo clears them
    assert runner.snapshot()["bins_check"] is None


def test_the_page_sees_each_bin_as_it_is_done(machine, tmp_path):
    lay = _lay()
    runner, vision = _runner(machine, lay, _world_104_and_a_code(lay), tmp_path / "runs")
    seen: list[dict] = []
    look = vision.analyse_area

    def watched(*a, **k):  # noqa: ANN002, ANN003, ANN202
        seen.append(runner.snapshot()["bins_check"])
        return look(*a, **k)

    vision.analyse_area = watched
    runner.scan_bins()
    assert [s["current"] for s in seen] == [103, 104, 105]
    assert [s["done"] for s in seen] == [0, 1, 2] and all(s["total"] == 3 for s in seen)
    states = [[b["state"] for b in s["bins"]] for s in seen]
    assert states == [
        ["running", "pending", "pending"],
        ["done", "running", "pending"],
        ["done", "done", "running"],
    ]
    b104 = next(b for b in seen[2]["bins"] if b["marker"] == 104)
    assert b104["result"] == "DIN912_M3 (2)" and b104["full"] and len(b104["parts"]) == 2
    assert all(len(p["poly"]) >= 3 for p in b104["parts"]) and len(b104["floor"]) == 4
    # the claim is there while the next bins are still looked into
    assert runner.claims.get(104) == "DIN912_M3"


class _WholeBoard(SimVision):
    """A vision that cannot look into one area (e.g. a head camera's tiles)."""

    @property
    def analyse_area(self):  # noqa: ANN201
        raise AttributeError("analyse_area")


def test_without_bin_by_bin_one_pass_on_the_whole_board(machine, tmp_path):
    lay = _lay()
    lay.save(machine.path(machine.paths.layout))
    vision = _WholeBoard(_world_104_and_a_code(lay), lambda: lay, Transform2D.identity)
    runner = Runner(machine, SimPrinter(machine, vision.world), vision)
    runner.setup_home()
    res = runner.scan_bins()
    assert vision.painted[-1] is False and vision.areas == []
    assert runner.claims == {104: "DIN912_M3"}
    assert "1 on codes" in res["bins_check"]  # the code, seen on the whole board, dropped


def test_sorting_photos_stay_painted(machine):
    lay = _lay()
    runner, vision = _runner(machine, lay, SimWorld(seed=1))
    runner.take_shot(runner.layout(), runner.transform())
    assert vision.painted[-1] is True


def test_a_bin_with_rules_keeps_them(machine):
    lay = _lay()
    b = lay.bin_by_marker(104)
    b.role, b.holds = "sort", ["DIN934*"]
    world = SimWorld(seed=1)
    cx, cy = lay.bin_centre(b)
    world.parts.append(_screw("DIN912_M3", cx, cy - 6))
    runner, _ = _runner(machine, lay, world)
    runner.scan_bins()
    assert 104 not in runner.claims and runner.layout().bin_by_marker(104).holds == ["DIN934*"]
    assert any("its rules take DIN934*" in line for line in runner.console)


def _part(cls: str, xy: tuple[float, float]) -> Part:
    p = Part(1, cls, 0.9, xy, 0.0, np.zeros((0, 2)), 4.0, None, True, False, False)
    p.bed_xy = xy
    return p


def test_the_code_is_kept_out_where_the_photo_shows_it():
    """A code stands on the rim: seen from above it appears shifted outwards on the floor plane
    the parts are measured on. What the model finds there is not counted either."""
    lay = _lay()
    b = lay.bin_by_marker(104)
    mx, my = lay.marker_centre(b)
    cx, cy = lay.bin_centre(b)
    seen_at = (mx - 13.0, my - 13.0)  # where the photo shows the code (parallax)
    k = 4.0  # view pixels per mm, plate = bed
    H = [[k, 0.0, 0.0], [0.0, k, 0.0], [0.0, 0.0, 1.0]]
    mk = MarkerPose(104, (mx, my), 90.0, view_px=(seen_at[0] * k, seen_at[1] * k))
    shot = Shot("x", [], [mk], view_h=H)
    spots = binscheck.code_spots(shot, Transform2D.identity())
    assert np.allclose(spots[104], seen_at)
    ghost, real = _part("UNKNOWN", seen_at), _part("DIN912_M3", (cx + 8, cy - 8))
    per_bin, dropped = binscheck.sort_out(lay, [ghost, real], 0.5, spots)
    assert per_bin[104] == [real] and dropped == [ghost]


def test_code_labels_sit_on_the_codes(machine, tmp_path):
    """The page draws each code's label at its centre in the photo (view_px), not at its plate
    X/Y through the floor-plane homography (that lands beside a code on a rim)."""
    lay = _lay()
    runner, _ = _runner(machine, lay, SimWorld(seed=1), tmp_path / "runs")
    runner.take_shot(runner.layout(), runner.transform(), paint=False)
    snap = runner.snapshot()
    H = np.asarray(snap["view_h"])
    for mk in snap["markers"]:
        b = lay.bin_by_marker(mk["marker"])
        x, y = lay.marker_centre(b)
        u, v, w = H @ np.array([x, y, 1.0])
        assert np.allclose(mk["view_px"], (u / w, v / w), atol=0.2)
