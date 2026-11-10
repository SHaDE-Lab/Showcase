"""The fisheye (sky-up) projection and the six-face cube SVF are two routes to the same number."""
import shutil
from pathlib import Path

import pytest

import pipeline as P
import svf as S

DATA = Path(__file__).resolve().parents[1] / "data" / "sites"


@pytest.mark.parametrize("site", ["site_a_open", "site_b_enclosed"])
def test_fisheye_svf_agrees_with_cube_face_svf(tmp_path, site):
    import FisheyeProjection
    shutil.copytree(DATA / site / "color_depth_seg", tmp_path / "output" / site / "color_depth_seg")
    with P._cwd(tmp_path):
        FisheyeProjection.fisheye_projection_type(site, image_type="seg", directions=["up"])
    png = tmp_path / "output" / site / "fisheye" / "seg" / "fisheye_photo_up_0_90.png"
    assert png.exists()
    from_fisheye = S.svf_from_fisheye(S.sky_mask_from_png(png))
    from_faces = S.compute_site_svf(DATA / site)["svf"]
    assert from_fisheye == pytest.approx(from_faces, abs=0.02)


def test_enclosed_site_sees_less_sky_than_open_site():
    a = S.compute_site_svf(DATA / "site_a_open")["svf"]
    b = S.compute_site_svf(DATA / "site_b_enclosed")["svf"]
    assert 0 < b < a < 1
