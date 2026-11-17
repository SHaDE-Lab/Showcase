"""Shared fixtures: synthetic thermal panoramas (no real imagery is shipped with this folder)."""
import os
import sys

import cv2
import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

SKY, WALL, GROUND = 0, 38, 44          # grey values are surface temperatures in degrees C; the code treats < 4 as sky


def make_panorama(path, kind, h=256, w=512):
    """Equirectangular thermal panorama. 'open': sky above the horizon, warm ground below.
    'enclosed': the same, but buildings fill the horizon band and part of the sky."""
    img = np.full((h, w), GROUND, np.uint8)
    img[: h // 2, :] = SKY
    if kind == "enclosed":
        img[h // 2 - h // 3: h // 2, :] = WALL           # a ring of buildings 60 degrees high
        img[: h // 6, : w // 2] = WALL                   # and overhanging cover on one side
    cv2.imwrite(path, cv2.merge([img, img, img]))
    return path


@pytest.fixture(scope="session")
def panos(tmp_path_factory):
    root = tmp_path_factory.mktemp("panos")
    out = {}
    for kind in ("open", "enclosed"):
        folder = root / kind / "20200621_10012"          # <date>_<site><hour>, as the code expects
        folder.mkdir(parents=True)
        make_panorama(str(folder / "pano.jpg"), kind)
        out[kind] = str(root / kind)
    return out
