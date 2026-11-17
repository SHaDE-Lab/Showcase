# Copyright 2026 The SHaDE Lab, Arizona State University
# SPDX-License-Identifier: CERN-OHL-P-2.0
"""The image server's web API. The ESP32-CAM posts a photo; the server analyses it and stores the result.

  POST /api/v1/                 multipart form: uuid (device id) and image (a file, or base64 text) -> "Success"
  POST /api/v1/getAllResults    same, and the stored result is returned as JSON
  GET  /healthz                 liveness check"""
from __future__ import annotations

import base64
import binascii
from io import BytesIO

from flask import Flask, jsonify, request
from PIL import Image, UnidentifiedImageError

from .store import ValidationError, normalise_mac


def create_app(pipeline, store, settings) -> Flask:
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = int(settings.max_upload_mb * 1024 * 1024)

    @app.after_request
    def cors(response):
        if settings.cors_origin:
            response.headers["Access-Control-Allow-Origin"] = settings.cors_origin
        return response

    @app.get("/healthz")
    def healthz():
        return jsonify(status="ok")

    @app.route("/api/v1/", methods=["POST", "GET"])
    @app.route("/api/v1/<verb>", methods=["POST", "GET"])
    def image(verb: str = "none"):
        upload = request.files.get("image")
        encoded = request.form.get("image")
        if upload is None and not encoded:
            return "Image must be attached in request", 400
        if "uuid" not in request.form:
            return "UUID must be attached in request", 400
        try:
            uuid = normalise_mac(request.form["uuid"]).replace(":", "_")
        except ValidationError:
            return "UUID must be a MAC address such as 24_6F_28_AA_BB_CC", 400

        try:
            raw = upload.stream if upload is not None else BytesIO(base64.b64decode(encoded, validate=True))
            with Image.open(raw) as opened:
                photo = opened.copy()
        except (UnidentifiedImageError, binascii.Error, ValueError, OSError):
            return "Invalid image", 400

        doc = pipeline.process(photo, uuid)
        store.insert_result(doc)

        if verb.lower() == "getallresults":
            return jsonify({k: v for k, v in doc.items()})
        if verb.lower() == "none":
            return "Success", 200
        return "API endpoint not found. Try /api/v1/getAllResults", 200

    return app
