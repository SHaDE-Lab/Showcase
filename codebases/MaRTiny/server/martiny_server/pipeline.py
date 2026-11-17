# Copyright 2026 The SHaDE Lab, Arizona State University
# SPDX-License-Identifier: CERN-OHL-P-2.0
"""One photo in, one result out: detect people, find the shadow, count who stands in shade."""
from __future__ import annotations

import base64
import datetime
import threading
import time
from io import BytesIO
from typing import Callable, Dict

from PIL import Image

from .shade import count_in_shade


def _jpeg_b64(image: Image.Image) -> str:
    buf = BytesIO()
    image.convert("RGB" if image.mode not in ("L", "RGB") else image.mode).save(buf, format="JPEG")
    return base64.b64encode(buf.getvalue()).decode("ascii")


class _Device:
    def __init__(self): self.shadow_map = None; self.shadow_time = 0.0


class Pipeline:
    """Keeps, for each device, the latest shadow map. Shadows move slowly and finding them is the slow step, so the map is
    reused until it is `shadow_update_interval_s` old (0 = find it again for every photo). People are detected on every photo."""

    def __init__(self, detector, shadow_detector, shadow_update_interval_s: float = 60.0, overlap_fraction: float = 0.2,
                 store_images: bool = False, clock: Callable[[], float] = time.time):
        self.detector, self.shadow_detector = detector, shadow_detector
        self.interval, self.overlap, self.store_images, self.clock = shadow_update_interval_s, overlap_fraction, store_images, clock
        self._devices: Dict[str, _Device] = {}
        self._lock = threading.Lock()          # guards the table of devices
        self._model_lock = threading.Lock()    # the models run one photo at a time

    def _device(self, uuid: str) -> _Device:
        with self._lock:
            return self._devices.setdefault(uuid, _Device())

    def process(self, image: Image.Image, uuid: str) -> dict:
        dev = self._device(uuid)
        now = self.clock()
        with self._model_lock:
            if dev.shadow_map is None or now - dev.shadow_time >= self.interval:
                dev.shadow_map, dev.shadow_time = self.shadow_detector.find_shadow(image), now
            boxes, confs, clss = self.detector.detect(image)
        import numpy as np
        in_shade = count_in_shade(np.asarray(dev.shadow_map), boxes, self.overlap)
        stamp = datetime.datetime.now().astimezone()
        epoch = int(stamp.timestamp())
        doc = {
            "_id": f"{uuid}_{int(stamp.timestamp() * 1000)}",
            "mac": uuid.replace("_", ":").upper(),
            "boxes": boxes, "confs": confs, "clss": clss,
            "isInShadow": in_shade,
            "time": epoch,
            "readableTime": f"{stamp:%Y-%m-%d %H:%M:%S%z}",
        }
        if self.store_images:                  # off by default: the photographs show people
            doc["shadow"] = _jpeg_b64(dev.shadow_map)
            doc["originalImage"] = _jpeg_b64(image)
        return doc
