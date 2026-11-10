"""Input handling that every run depends on."""
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

import pipeline as P

DATA = Path(__file__).resolve().parents[1] / "data"


def test_wind_log_law():
    assert P.wind_at_height(0) == 0
    u = P.wind_at_height(4.0)
    assert 0 < u < 4.0                                           # slower near the ground
    assert P.wind_at_height(8.0) == pytest.approx(2 * u)                      # linear in the 10 m speed


def test_weather_file(weather):
    assert len(weather) == 24
    assert weather[14]["air_temperature"] > weather[6]["air_temperature"]      # a Tempe June day warms up
    for h in P.SHADOW_HOURS:
        assert 0 <= weather[h]["cloud_cover"] <= 1 and 0 <= weather[h]["relative_humidity"] <= 100


def test_sites_ship_segmentation_and_depth_only():
    for site in (DATA / "sites").iterdir():
        kinds = sorted(p.name for p in (site / "color_depth_seg").iterdir())
        assert kinds == ["depth", "seg"], "no colour photographs may be shipped in the public example data"
        assert len(list((site / "color_depth_seg" / "seg").glob("*_seg.png"))) == 6
        assert len(list((site / "color_depth_seg" / "depth").glob("*_depth.png"))) == 6


def test_all_sky_face_loads_as_sky(tmp_path):
    """Regression: a face that is entirely sky must load as label 1, not as an all-zero label map."""
    seg = tmp_path / "seg"
    seg.mkdir()
    sky = np.zeros((512, 512, 3), np.uint8)
    sky[..., 2] = 255
    for sfx in P.FACE_SUFFIX.values():
        Image.fromarray(sky).save(seg / f"1.0_2.0_{sfx}_seg.png")
    labels = P.load_seg_labels(seg)
    assert all((v == 1).all() for v in labels.values())


def test_gray_label_maps_still_load(tmp_path):
    seg = tmp_path / "seg"
    seg.mkdir()
    lab = np.full((512, 512), 3, np.uint8)                       # grayscale label map: every pixel "building"
    for sfx in P.FACE_SUFFIX.values():
        Image.fromarray(lab).save(seg / f"1.0_2.0_{sfx}_seg.png")
    assert all((v == 3).all() for v in P.load_seg_labels(seg).values())


def test_site_location_from_filenames():
    lat, lon = P.site_location(DATA / "sites" / "site_a_open")
    assert 33.3 < lat < 33.5 and -112.0 < lon < -111.8           # Tempe, Arizona
