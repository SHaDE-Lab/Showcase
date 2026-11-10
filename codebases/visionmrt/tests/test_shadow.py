"""Shadow casting on synthetic scenes where the right answer is known, and on the two example sites."""
import numpy as np
import pytest
from PIL import Image

import pipeline as P

LAT, LON, DATE, TZ = 33.42, -111.93, "2018-06-09", "America/Phoenix"
SKY, BUILDING, ROAD = (0, 0, 255), (192, 192, 192), (128, 128, 128)


def _site(root, up_color, name="synth"):
    """Six cube faces: open sky on the four sides, `up_color` overhead, road underfoot."""
    seg = root / "output" / name / "color_depth_seg" / "seg"
    dep = root / "output" / name / "color_depth_seg" / "depth"
    seg.mkdir(parents=True)
    dep.mkdir(parents=True)
    colors = {"North": SKY, "South": SKY, "East": SKY, "West": SKY, "Up": up_color, "Down": ROAD}
    for face, sfx in P.FACE_SUFFIX.items():
        img = np.zeros((512, 512, 3), np.uint8)
        img[:] = colors[face]
        Image.fromarray(img).save(seg / f"{LAT}_{LON}_{sfx}_seg.png")
        Image.fromarray(np.full((512, 512), 128, np.uint8)).save(dep / f"{LAT}_{LON}_{sfx}_depth.png")
    return name


def _ground_lit(shadow, hour):
    return float((P.decode_shadow(shadow[hour]["Down"]) == 1).mean())


def test_open_sky_leaves_the_ground_fully_sunlit(tmp_path):
    name = _site(tmp_path, up_color=SKY)
    with P._cwd(tmp_path):
        sh = P.cast_shadows(name, LAT, LON, DATE, TZ)
    for h in (8, 12, 17):
        assert _ground_lit(sh, h) > 0.99


def test_a_roof_overhead_shades_the_ground_at_midday(tmp_path):
    name = _site(tmp_path, up_color=BUILDING)
    with P._cwd(tmp_path):
        sh = P.cast_shadows(name, LAT, LON, DATE, TZ)
    assert _ground_lit(sh, 12) < 0.1


def test_open_ground_is_lit_more_than_roofed_ground_all_day(tmp_path_factory):
    res = {}
    open_dir = tmp_path_factory.mktemp("open")      # each scene is built from its own working directory
    roof_dir = tmp_path_factory.mktemp("roof")
    n1, n2 = _site(open_dir, SKY), _site(roof_dir, BUILDING)
    with P._cwd(open_dir):
        res["open"] = P.cast_shadows(n1, LAT, LON, DATE, TZ)
    with P._cwd(roof_dir):
        res["roof"] = P.cast_shadows(n2, LAT, LON, DATE, TZ)
    for h in P.SHADOW_HOURS:
        assert _ground_lit(res["open"], h) >= _ground_lit(res["roof"], h)


@pytest.mark.slow
def test_example_sites_ground_sun_exposure_follows_the_sun(runs):
    """Low morning/evening sun is blocked by the surroundings far more than the near-vertical midday sun."""
    for site, r in runs.items():
        lit = {h: _ground_lit(r["shadow"], h) for h in P.SHADOW_HOURS}
        noon = max(lit[11], lit[12], lit[13])
        assert noon > lit[7] and noon > lit[19], site
        assert noon > 0.4, site                      # open ground around solar noon
        assert all(0.0 <= v <= 1.0 for v in lit.values())


@pytest.mark.slow
def test_shadow_maps_use_only_the_four_documented_codes(runs):
    for r in runs.values():
        for face_imgs in r["shadow"].values():
            for img in face_imgs.values():
                code = P.decode_shadow(img)
                assert set(np.unique(code)) <= {0, 1, 2, 3}
                assert img.shape == (512, 512, 3)           # one pixel per segmentation pixel of the face
