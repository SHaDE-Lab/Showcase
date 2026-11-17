# Copyright 2026 The SHaDE Lab, Arizona State University
# SPDX-License-Identifier: CERN-OHL-P-2.0
"""Settings for the MaRTiny image server. Everything comes from environment variables (or a .env file next to server.py),
so no credential, address or key is ever written in the code."""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping, Optional


def _flag(value: Optional[str], default: bool) -> bool:
    if value is None or value.strip() == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _number(value: Optional[str], default: float) -> float:
    try:
        return float(value) if value not in (None, "") else default
    except ValueError:
        raise ValueError(f"expected a number, got {value!r}") from None


@dataclass(frozen=True)
class Settings:
    # database: with no MONGO_URL the server keeps data in memory (development only, lost on restart)
    mongo_url: Optional[str] = None
    mongo_db: str = "martiny-studio"
    port: int = 8080
    # people detection: "yolo" (Ultralytics, AGPL-3.0), "torchvision" (permissive alternative) or "none"
    detector: str = "yolo"
    yolo_weights: str = "yolov8x.pt"
    device: str = "cpu"
    confidence: float = 0.3
    # shadow detection: "module:callable" that returns the trained network, or "none"
    shadow_network: str = "none"
    shadow_update_interval_s: float = 60.0   # 0 = recompute the shadow map for every image
    shade_overlap_fraction: float = 0.2      # share of a person's box that must lie in shadow to count as "in shade"
    # privacy: keep the photographs themselves in the database? Off unless you turn it on.
    store_images: bool = False
    max_upload_mb: float = 10.0
    cors_origin: Optional[str] = None        # e.g. https://your-viewer.example.org ; unset = no CORS headers
    sentry_dsn: Optional[str] = None         # optional error reporting; unset = off

    @classmethod
    def from_env(cls, env: Mapping[str, str] = os.environ) -> "Settings":
        g = env.get
        return cls(
            mongo_url=g("MONGO_URL") or None,
            mongo_db=g("MONGO_DB", cls.mongo_db),
            port=int(_number(g("SERVER_PORT"), cls.port)),
            detector=(g("MARTINY_DETECTOR", cls.detector) or cls.detector).lower(),
            yolo_weights=g("YOLO_WEIGHTS", cls.yolo_weights),
            device=g("MARTINY_DEVICE", cls.device),
            confidence=_number(g("MARTINY_CONFIDENCE"), cls.confidence),
            shadow_network=g("MARTINY_SHADOW_NETWORK", cls.shadow_network) or "none",
            shadow_update_interval_s=_number(g("SHADOW_UPDATE_INTERVAL_S"), cls.shadow_update_interval_s),
            shade_overlap_fraction=_number(g("SHADE_OVERLAP_FRACTION"), cls.shade_overlap_fraction),
            store_images=_flag(g("STORE_IMAGES"), cls.store_images),
            max_upload_mb=_number(g("MAX_UPLOAD_MB"), cls.max_upload_mb),
            cors_origin=g("CORS_ORIGIN") or None,
            sentry_dsn=g("SENTRY_DSN") or None,
        )
