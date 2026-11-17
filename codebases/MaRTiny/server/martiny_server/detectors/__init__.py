# Copyright 2026 The SHaDE Lab, Arizona State University
# SPDX-License-Identifier: CERN-OHL-P-2.0
from .objects import ALLOWED_CLASSES, NullDetector, TorchvisionDetector, YoloDetector
from .shadow import NullShadowDetector, ShadowDetector, load_shadow_detector


def load_detector(settings):
    """Builds the people detector chosen in the settings."""
    kind = settings.detector
    if kind == "none":
        return NullDetector()
    if kind == "yolo":
        return YoloDetector(settings.yolo_weights, settings.device, confidence=settings.confidence)
    if kind == "torchvision":
        return TorchvisionDetector(settings.device, settings.confidence)
    raise ValueError(f"unknown MARTINY_DETECTOR {kind!r}: use yolo, torchvision or none")
