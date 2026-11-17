# Copyright 2026 The SHaDE Lab, Arizona State University
# SPDX-License-Identifier: CERN-OHL-P-2.0
"""People detectors. Every detector has detect(image) -> (boxes, confidences, classes), in COCO-80 class numbers
(0 person, 1 bicycle, 15 cat, 16 dog, 25 umbrella), with boxes as [x1, y1, x2, y2] pixels.

LICENSE NOTE: YoloDetector uses the Ultralytics package and the YOLOv8 weights, which are licensed AGPL-3.0, not
CERN-OHL-P. Nothing from Ultralytics is included in this repository; it is imported only if you choose it. If AGPL does not
suit your use, choose the torchvision detector instead (MARTINY_DETECTOR=torchvision)."""
from __future__ import annotations

from typing import List, Sequence, Tuple

ALLOWED_CLASSES = (0, 1, 15, 16, 25)          # person, bicycle, cat, dog, umbrella
Detections = Tuple[List[List[int]], List[float], List[int]]


class NullDetector:
    """Finds nothing. Lets the server run, and be tested, without any model."""
    def detect(self, image) -> Detections:
        return [], [], []


class YoloDetector:
    def __init__(self, weights: str = "yolov8x.pt", device: str = "cpu", imgsz=(640, 480), confidence: float = 0.3,
                 allowed: Sequence[int] = ALLOWED_CLASSES, model=None):
        if model is None:
            try:
                from ultralytics import YOLO          # AGPL-3.0: see the licence note above
            except ImportError as exc:
                raise RuntimeError("MARTINY_DETECTOR=yolo needs the ultralytics package (pip install ultralytics); "
                                   "or use MARTINY_DETECTOR=torchvision or none") from exc
            model = YOLO(weights)                      # downloads the weights on first use if the file is missing
        self.model, self.device, self.imgsz = model, device, imgsz
        self.confidence, self.allowed = confidence, set(allowed)

    def detect(self, image) -> Detections:
        result = self.model(image, imgsz=self.imgsz, verbose=False, device=self.device)[0].numpy()
        boxes, confs, clss = [], [], []
        for box, conf, cls in zip(result.boxes.xyxy, result.boxes.conf, result.boxes.cls):
            if conf > self.confidence and int(cls) in self.allowed:
                boxes.append([round(float(v)) for v in box])
                confs.append(float(conf))
                clss.append(int(cls))
        return boxes, confs, clss


# torchvision numbers its COCO classes 1 to 91; the lab's data uses the 80-class numbers of YOLO.
TORCHVISION_TO_COCO80 = {1: 0, 2: 1, 17: 15, 18: 16, 28: 25}


class TorchvisionDetector:
    """Permissive alternative: a torchvision Faster R-CNN (BSD-3-Clause code), reporting classes in YOLO numbering."""
    def __init__(self, device: str = "cpu", confidence: float = 0.3, allowed: Sequence[int] = ALLOWED_CLASSES,
                 model=None, weights="DEFAULT"):
        import torch
        if model is None:
            from torchvision.models.detection import fasterrcnn_mobilenet_v3_large_320_fpn
            model = fasterrcnn_mobilenet_v3_large_320_fpn(weights=weights, weights_backbone=None)   # weights=None: random start, nothing downloaded
        self._torch = torch
        self.model = model.to(device).eval()
        self.device, self.confidence, self.allowed = device, confidence, set(allowed)

    def detect(self, image) -> Detections:
        from torchvision.transforms.functional import to_tensor
        with self._torch.no_grad():
            out = self.model([to_tensor(image.convert("RGB")).to(self.device)])[0]
        boxes, confs, clss = [], [], []
        for box, score, label in zip(out["boxes"].cpu().tolist(), out["scores"].cpu().tolist(), out["labels"].cpu().tolist()):
            cls = TORCHVISION_TO_COCO80.get(int(label))
            if cls is None or cls not in self.allowed or score <= self.confidence:
                continue
            boxes.append([round(v) for v in box])
            confs.append(float(score))
            clss.append(cls)
        return boxes, confs, clss
