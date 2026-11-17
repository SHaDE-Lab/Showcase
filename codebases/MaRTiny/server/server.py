# Copyright 2026 The SHaDE Lab, Arizona State University
# SPDX-License-Identifier: CERN-OHL-P-2.0
"""Starts the MaRTiny image server:  python server.py   (settings come from the environment or a .env file, see .env.example)"""
import os

from martiny_server.api import create_app
from martiny_server.config import Settings
from martiny_server.detectors import load_detector, load_shadow_detector
from martiny_server.pipeline import Pipeline
from martiny_server.store import connect


def build_app(settings: Settings):
    if settings.sentry_dsn:                       # optional error reporting; the DSN is never in the code
        import sentry_sdk
        sentry_sdk.init(dsn=settings.sentry_dsn, traces_sample_rate=0.1)
    store = connect(settings)
    store.ensure_indexes()
    pipeline = Pipeline(load_detector(settings), load_shadow_detector(settings.shadow_network, settings.device),
                        settings.shadow_update_interval_s, settings.shade_overlap_fraction, settings.store_images)
    return create_app(pipeline, store, settings)


if __name__ == "__main__":
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass
    cfg = Settings.from_env(os.environ)
    if not cfg.mongo_url:
        print("MONGO_URL is not set: keeping data in memory only (it is lost when the server stops).")
    build_app(cfg).run("0.0.0.0", cfg.port, threaded=True)
