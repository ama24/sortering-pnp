"""Run the chosen models on a photo: stage 1 (segment / obb / detect), the optional classifier on
close-up crops, then the length measurement (measure/) (stage 2 keypoints and/or classical edges).

Segmentation models give the full result. Box models (detect, obb) give class and position: their
outline is the (rotated) box, and lengths are not measured. Needs ultralytics.
"""

from __future__ import annotations

import dataclasses
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

log = logging.getLogger("sortering_pnp.analysis")

STAGE1_TASKS = ("segment", "obb", "detect")


@dataclass
class ModelChoice:
    stage1: Path
    stage2: Path | None = None
    classifier: Path | None = None
    imgsz: int | None = None  # stage 1 image size (from the model card); None = vision.yaml
    conf: float | None = None  # stage 1 confidence; None = vision.yaml
    label: str = ""


def run_boxes(model: Any, scene: Any, names: Mapping[int, str], st: Any, task: str) -> list[Any]:
    """Stage 1 with a detect or OBB model: Detections whose outline is the (rotated) box."""
    import cv2

    from sortering_pnp.measure.infer import Detection

    h, w = scene.image.shape[:2]
    s = st.stage1_imgsz / max(h, w)
    small = cv2.resize(scene.image, (round(w * s), round(h * s)), interpolation=cv2.INTER_AREA)
    res = model.predict(
        small, imgsz=st.stage1_imgsz, conf=st.conf, iou=st.iou, max_det=st.max_det, verbose=False
    )[0]
    if task == "obb":
        if res.obb is None:
            return []
        polys = res.obb.xyxyxyxy.cpu().numpy()
        cls, conf = res.obb.cls.cpu().numpy(), res.obb.conf.cpu().numpy()
    else:
        if res.boxes is None:
            return []
        b = res.boxes.xyxy.cpu().numpy()
        polys = np.stack(
            [
                np.c_[b[:, 0], b[:, 1]],
                np.c_[b[:, 2], b[:, 1]],
                np.c_[b[:, 2], b[:, 3]],
                np.c_[b[:, 0], b[:, 3]],
            ],
            axis=1,
        )
        cls, conf = res.boxes.cls.cpu().numpy(), res.boxes.conf.cpu().numpy()
    out = []
    for poly, c, sc in zip(polys, cls, conf, strict=True):
        full = (np.asarray(poly, float) + 0.5) / s - 0.5
        box = (*full.min(axis=0).tolist(), *full.max(axis=0).tolist())
        cid = int(c)
        out.append(Detection(cid, names.get(cid, str(cid)), float(sc), full, box))
    return out


class Analyzer:
    """Loaded models; `analyse(scene)` gives measure/infer.py style results."""

    def __init__(
        self,
        choice: ModelChoice,
        geometry: Any,
        settings: Any,
        classes_yaml: Path | None = None,
        classifier_conf: float = 0.6,
    ) -> None:
        from sortering_pnp.measure.modelcard import check_classes
        from sortering_pnp.yolo import YOLO

        self.choice = choice
        self.stage1 = YOLO(str(choice.stage1))
        self.task = str(self.stage1.task)
        if self.task not in STAGE1_TASKS:
            raise ValueError(f"{choice.stage1}: a {self.task} model cannot find parts (stage 1)")
        self.names = {int(k): v for k, v in self.stage1.names.items()}
        errors, self.warnings = check_classes(choice.stage1, self.names, classes_yaml)
        if errors:
            raise ValueError("; ".join(errors))
        self.stage2 = YOLO(str(choice.stage2)) if choice.stage2 else None
        if self.stage2 is not None and self.stage2.task != "pose":
            raise ValueError(f"{choice.stage2}: stage 2 must be a pose (keypoint) model")
        self.classifier = YOLO(str(choice.classifier)) if choice.classifier else None
        if self.classifier is not None and self.classifier.task != "classify":
            raise ValueError(f"{choice.classifier}: the classifier must be a classify model")
        self.classifier_conf = classifier_conf
        self.crop_spec = None  # the classifier's crops (model card), None: the old crop
        if self.classifier is not None:
            from sortering_pnp.io import read_json
            from sortering_pnp.measure.classcrop import CropSpec
            from sortering_pnp.measure.modelcard import find_card

            card_path = find_card(choice.classifier)
            self.crop_spec = CropSpec.from_card(read_json(card_path) if card_path else None)
            if self.crop_spec is None:
                self.warnings.append(
                    "the classifier's model card has no classifier_crop: it cannot judge sizes, "
                    "so it may change a part's type only"
                )
        self.geo = geometry
        changes: dict[str, Any] = {}
        if choice.imgsz:
            changes["stage1_imgsz"] = int(choice.imgsz)
        if choice.conf:
            changes["conf"] = float(choice.conf)
        self.st = dataclasses.replace(settings, **changes)
        if self.crop_spec is not None and self.crop_spec.longest_side_px != self.st.stage1_imgsz:
            self.warnings.append(
                f"the classifier was trained at {self.crop_spec.longest_side_px} px, stage 1 runs "
                f"at {self.st.stage1_imgsz} px: its crops follow the classifier"
            )

    def describe(self) -> dict[str, Any]:
        return {
            "label": self.choice.label,
            "task": self.task,
            "classes": len(self.names),
            "stage2": bool(self.stage2),
            "classifier": bool(self.classifier),
            "classifier_sizes": bool(self.crop_spec and self.crop_spec.labels == "class"),
            "imgsz": self.st.stage1_imgsz,
            "conf": self.st.conf,
            "warnings": list(self.warnings),
        }

    def _classify(self, scene: Any, det: Any, small: tuple[Any, float] | None) -> tuple[str, float]:
        """The classifier on the part's crop, cut as its model card says (`small`: the photo
        shrunk to the card's scale, once per photo)."""
        from sortering_pnp.measure.classcrop import legacy_crop

        if self.crop_spec is not None and small is not None:
            crop = self.crop_spec.crop(small[0], small[1], det.box)
            r = self.classifier.predict(crop, imgsz=self.crop_spec.size_px, verbose=False)[0]
        else:
            r = self.classifier.predict(legacy_crop(scene.image, det.box), verbose=False)[0]
        top = int(r.probs.top1)
        return str(self.classifier.names[top]), float(r.probs.top1conf)

    def analyse(self, scene: Any, name: str = "") -> dict[str, Any]:
        import time

        from sortering_pnp.measure.infer import measure_screw, plate_pose, run_pose, run_stage1
        from sortering_pnp.naming import UNKNOWN

        t0 = time.perf_counter()
        if self.task == "segment":
            dets = run_stage1(self.stage1, scene, self.names, self.st)
        else:
            dets = run_boxes(self.stage1, scene, self.names, self.st, self.task)
        objects = []
        small = None
        if self.classifier is not None and self.crop_spec is not None and dets:
            small = self.crop_spec.shrink(scene.image)
        ids = {v: k for k, v in self.names.items()}
        for i, det in enumerate(dets, start=1):
            obj: dict[str, Any] = {"id": i}
            if self.classifier is not None:
                from sortering_pnp.measure.classcrop import corrected_class

                cname, cconf = self._classify(scene, det, small)
                obj["stage1_class"] = det.class_name
                obj["classifier"] = {"class": cname, "conf": round(cconf, 3)}
                if cconf >= self.classifier_conf and cname != det.class_name:
                    new, why = corrected_class(det.class_name, cname, self.crop_spec, ids, UNKNOWN)
                    obj["classifier"]["result"] = why
                    if new != det.class_name:
                        det.class_name = new
                        det.class_id = ids.get(new, det.class_id)
            obj.update(
                {
                    "class": det.class_name,
                    "class_id": det.class_id,
                    "unknown": det.class_name == UNKNOWN,
                    "score": round(det.score, 3),
                    "box": [round(v, 1) for v in det.box],
                    "polygon": np.round(det.polygon, 1).tolist(),
                }
            )
            geo = self.geo.classes.get(det.class_name)
            height = 1.5
            if geo is not None:
                obj["size"] = geo.size
                height = geo.d / 2
                if self.task == "segment":
                    pose = run_pose(self.stage2, scene, det, self.st) if self.stage2 else None
                    obj.update(measure_screw(scene, det, geo, self.st, pose))
                else:
                    obj["measurable"] = False
            obj["position_mm"], obj["orientation_deg"] = plate_pose(scene, det, height)
            objects.append(obj)
        return {
            "image": name,
            "camera": scene.camera_source,
            "roi": scene.roi,
            "model": self.choice.label,
            "task": self.task,
            "objects": objects,
            "timing_s": {"total": round(time.perf_counter() - t0, 3)},
        }
