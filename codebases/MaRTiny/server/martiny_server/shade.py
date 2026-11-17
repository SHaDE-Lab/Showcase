# Copyright 2026 The SHaDE Lab, Arizona State University
# SPDX-License-Identifier: CERN-OHL-P-2.0
"""Decides whether a detected person stands in shade, from a shadow map."""
from __future__ import annotations

from typing import Sequence

import numpy as np

SHADOW_THRESHOLD = 10   # shadow-map pixels above this value count as shadow (the map is 0 to 255)


def is_in_shade(shadow_map: np.ndarray, box: Sequence[int], overlap_fraction: float = 0.2,
                threshold: int = SHADOW_THRESHOLD) -> bool:
    """True when at least `overlap_fraction` of the person's bounding box lies in shadow.

    box is (x1, y1, x2, y2) in pixels, both corners included. The area is that of the whole box even where it
    leaves the image, so a person half out of frame needs more of the visible part in shadow. This matches the
    lab's working server."""
    x1, y1, x2, y2 = (int(v) for v in box)
    h, w = shadow_map.shape[:2]
    area = (x2 - x1 + 1) * (y2 - y1 + 1)
    cx1, cy1, cx2, cy2 = max(x1, 0), max(y1, 0), min(x2, w - 1), min(y2, h - 1)
    if area <= 0 or cx2 < cx1 or cy2 < cy1:
        return False
    in_shadow = int(np.count_nonzero(shadow_map[cy1:cy2 + 1, cx1:cx2 + 1] > threshold))
    return in_shadow >= area * overlap_fraction


def count_in_shade(shadow_map: np.ndarray, boxes: Sequence[Sequence[int]], overlap_fraction: float = 0.2) -> list:
    """1 for each box that is in shade, else 0 (the format the viewer expects)."""
    return [int(is_in_shade(shadow_map, b, overlap_fraction)) for b in boxes]
