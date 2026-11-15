"""The classifier's crops follow its model card (classifier_crop), and a classifier that cannot
judge sizes may change a part's type only; a shank clearly of another size goes to unsure."""

from __future__ import annotations

import numpy as np
import pytest

from sortering_pnp.layout import Layout
from sortering_pnp.measure.classcrop import (
    CropSpec,
    corrected_class,
    legacy_crop,
    size_fit,
    split_size,
    with_size,
    with_type,
)
from sortering_pnp.naming import UNKNOWN
from sortering_pnp.parts import Part
from sortering_pnp.rules import destination

CARD = {
    "classifier_crop": {
        "version": 1,
        "mode": "fixed",
        "longest_side_px": 1024,
        "size_px": 256,
        "pad": [114, 114, 114],
        "interpolation": "area",
        "centre": "box",
        "labels": "class",
    }
}


def test_the_crop_block_is_read_and_checked():
    spec = CropSpec.from_card(CARD)
    assert spec == CropSpec(1024, 256, (114, 114, 114), "area", "class")
    assert CropSpec.from_card({}) is None and CropSpec.from_card(None) is None
    for bad in ({"version": 2}, {"mode": "scaled"}, {"labels": "size"}, {"interpolation": "x"}):
        with pytest.raises(ValueError):
            CropSpec.from_card({"classifier_crop": {**CARD["classifier_crop"], **bad}})


def _photo_with(boxes, shape=(1500, 2000)):
    img = np.zeros((*shape, 3), np.uint8)
    for x0, y0, x1, y1 in boxes:
        img[y0:y1, x0:x1] = 255
    return img


def test_crops_have_one_size_and_keep_the_parts_sizes():
    """Every crop is size_px square, and a part twice as wide is twice as wide in its crop:
    the scale is the photo's, never the part's."""
    spec = CropSpec.from_card(CARD)
    small_box, big_box = (400, 400, 440, 520), (1200, 600, 1280, 840)
    img = _photo_with([small_box, big_box])
    shrunk, s = spec.shrink(img)
    assert max(shrunk.shape[:2]) == 1024
    widths = []
    for box in (small_box, big_box):
        crop = spec.crop(shrunk, s, box)
        assert crop.shape == (256, 256, 3)
        cols = np.nonzero(crop[128, :, 0] > 127)[0]
        widths.append(len(cols))
    assert widths[1] == pytest.approx(2 * widths[0], abs=1)
    assert widths[0] == pytest.approx(40 * s, abs=1)  # at the stage-1 scale, not enlarged


def test_a_part_at_the_edge_is_padded_grey():
    spec = CropSpec.from_card(CARD)
    img = _photo_with([(0, 0, 30, 30)])
    shrunk, s = spec.shrink(img)
    crop = spec.crop(shrunk, s, (0, 0, 30, 30))
    assert crop.shape == (256, 256, 3)
    assert (crop[0, 0] == 114).all() and (crop[-1, -1] == 0).all()


def test_the_old_crop_without_a_block():
    img = _photo_with([(100, 100, 140, 200)], shape=(400, 400))
    crop = legacy_crop(img, (100, 100, 140, 200))
    assert crop.shape[0] > 100 and crop.shape[1] > 40  # the box and a margin, not resized


def test_type_and_size_of_a_class():
    assert split_size("DIN912_M4") == ("DIN912", "M4")
    assert split_size("DIN125A_M2.5") == ("DIN125A", "M2.5")
    assert split_size("TNUT_DROP_S6_M4") == ("TNUT_DROP_S6", "M4")
    assert split_size("BRACKET_2020") == ("BRACKET", "2020")
    assert split_size(UNKNOWN) == (UNKNOWN, None)
    assert with_type("DIN912_M4", "DIN7984") == "DIN7984_M4"
    assert with_type(UNKNOWN, "DIN912") is None


KNOWN = {"DIN912_M3", "DIN912_M4", "DIN7984_M4", "DIN7984_M3", UNKNOWN}
CLASS_SPEC = CropSpec.from_card(CARD)
TYPE_SPEC = CropSpec(labels="type")


@pytest.mark.parametrize(
    ("said", "spec", "expected"),
    [
        ("DIN912_M3", CLASS_SPEC, "DIN912_M3"),  # trained on fixed crops: it may change the size
        ("DIN912_M3", None, "DIN912_M4"),  # no crop block: the size stays stage 1's
        ("DIN7984_M3", None, "DIN7984_M4"),  # ...but the type may change
        ("DIN7984", TYPE_SPEC, "DIN7984_M4"),  # labels "type": a type with stage 1's size
        ("DIN933_M4", None, "DIN912_M4"),  # a class stage 1 does not know: kept
        (UNKNOWN, None, UNKNOWN),  # unknown is unknown, whatever the size
    ],
)
def test_what_the_classifier_may_change(said, spec, expected):
    new, why = corrected_class("DIN912_M4", said, spec, KNOWN, UNKNOWN)
    assert new == expected, why


def _part(**kw) -> Part:
    d = dict(
        id=1,
        cls="DIN912_M3",
        score=0.9,
        plate_xy=(0.0, 0.0),
        plate_angle=0.0,
        polygon=np.zeros((0, 2)),
        top_mm=3.0,
        length_mm=10.0,
        measurable=True,
        has_length=True,
    )
    d.update(kw)
    return Part(**d)


def test_a_shank_of_another_size_goes_to_the_unsure_bin():
    lay = Layout.default()
    unsure = next(b for b in lay.bins if b.role == "unsure")
    dec = destination(_part(size_seen="M4"), lay, 0.5)
    assert dec.bin is unsure and "looks M4" in dec.reason
    assert destination(_part(), lay, 0.5).bin is not unsure


def test_best_fit_takes_the_measured_size_when_the_model_knows_it():
    known = {"DIN912_M3", "DIN912_M4"}
    o = {"class": "DIN912_M3", "size": "M3", "size_mismatch": "M4"}
    size_fit(o, "best_fit", known)
    assert o["class"] == "DIN912_M4" and o["size"] == "M4" and "size_mismatch" not in o
    o = {"class": "DIN912_M3", "size": "M3", "size_mismatch": "M5"}  # no DIN912_M5: unsure
    size_fit(o, "best_fit", known)
    assert o["class"] == "DIN912_M3" and o["size_mismatch"] == "M5"
    o = {"class": "DIN912_M3", "size": "M3", "size_mismatch": "M4"}
    size_fit(o, "unsure", known)  # the Unsure Bin option: left for the unsure bin
    assert o["class"] == "DIN912_M3" and o["size_mismatch"] == "M4"
    assert with_size("TNUT_DROP_S6_M4", "M5") == "TNUT_DROP_S6_M5"


def test_the_choice_is_made_in_setup_and_kept(machine):
    import copy

    from sortering_pnp.printer.sim import SimPrinter, SimVision, SimWorld
    from sortering_pnp.runner import Runner
    from sortering_pnp.transform import Transform2D

    assert machine.run.size_check == "best_fit"  # the default
    lay = Layout.default()
    lay.save(machine.path(machine.paths.layout))
    vision = SimVision(SimWorld(), lambda: lay, Transform2D.identity)
    runner = Runner(machine, SimPrinter(machine, SimWorld()), vision)
    with pytest.raises(ValueError):
        runner.setup_size_check("report")
    assert runner.setup_size_check("unsure")["size_check"] == "unsure"
    fresh = copy.deepcopy(machine)  # after a restart
    fresh.run.size_check = "best_fit"
    again = Runner(fresh, SimPrinter(fresh, SimWorld()), vision)
    assert again.m.run.size_check == "unsure"


@pytest.mark.parametrize(
    ("shank_mm", "measurable", "mismatch"),
    [
        (2.95, True, None),  # an M3: ok
        (3.6, True, None),  # nearer M4, not clearly: said, not acted on
        (3.85, True, "M4"),  # clearly an M4
        (3.85, False, None),  # tilted or cut by the border: never acted on
    ],
)
def test_the_size_check_acts_only_when_clear(monkeypatch, shank_mm, measurable, mismatch):
    from types import SimpleNamespace

    from sortering_pnp.calib.geometry import nominal_camera
    from sortering_pnp.measure import infer
    from sortering_pnp.measure.geometry import ClassGeometry

    cam = nominal_camera()
    geo = ClassGeometry("DIN912_M3", "DIN912", "M3", "bearing_to_tip", [10.0], 3.0, 2.75)
    h = geo.heights(10.0)["tip"]
    c = cam.project(np.array([[110.0, 110.0, h]]))[0]
    px_per_mm = 1 / infer.thread_diameter_mm([1.0], cam, c, h)
    monkeypatch.setattr(infer, "edge_widths", lambda g, ek: [shank_mm * px_per_mm] * 5)
    ek = SimpleNamespace(keypoints={"bearing": c, "tip": c}, shank_widths_px=[1.0])
    scene = SimpleNamespace(cam=cam)
    out = infer._size_check(scene, None, geo, infer.Settings(), ek, None, (0, 0), measurable)  # noqa: SLF001
    assert out["thread_diameter_mm"] == pytest.approx(shank_mm, abs=0.01)
    assert out.get("size_mismatch") == mismatch
    assert (out["size_check"] == "ok") == (shank_mm < 3.5)
