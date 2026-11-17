import os

import cv2
import numpy as np
import pytest

from panomrt.utils import definitions as d
from panomrt.utils.calculate import calc
from panomrt.utils.image.fisheyeProjection import fisheyeProjection
from panomrt.utils.image.imageReader import ImageReader
from panomrt.utils.image.pano2cube import panorama_to_cubemap

FACES = ["0_0", "90_0", "180_0", "270_0", "0_90", "0_270"]       # front, right, back, left, top, bottom


@pytest.fixture(scope="module")
def fp():
    return fisheyeProjection(512, 512, 6)


def rings(fp):
    r = np.zeros((5, 512 * 512))
    for i in range(5):
        r[i] = np.where(fp.radiusPerImage[i] >= 0, (fp.radiusPerImage[i] * d.N_RINGS).astype(int), 0)
    return r


def svf(fp, seg):
    r = rings(fp)
    return calc.computeSkyViewFactor(seg, fp.fractionPerImage[2], fp.fractionPerImage[4], r[2], r[4])


def test_fisheye_geometry_five_views_cover_the_upper_hemisphere(fp):
    assert fp.pointCoords.shape == (5, 512 * 512 * 3)
    assert (fp.radiusPerImage[4] >= 0).all()                           # the centre face looks entirely above the horizon
    for i in range(4):
        assert (fp.radiusPerImage[i] >= 0).sum() == 512 * 512 // 2     # side faces: only the half above the horizon counts
    assert fp.radiusPerImage.max() <= 1.0 + 1e-9


def test_fisheye_fractions_are_equal_area_weights(fp):
    for i in range(5):
        f = fp.fractionPerImage[i]
        assert (f[fp.radiusPerImage[i] >= 0] > 0).all()
        assert (f[fp.radiusPerImage[i] < 0] == -1).all()


def test_sky_view_factor_of_open_sky_and_of_no_sky(fp):
    assert svf(fp, np.ones((6, 512, 512), bool)) == pytest.approx(1.0, abs=0.01)
    assert svf(fp, np.zeros((6, 512, 512), bool)) == 0.0


def test_sky_view_factor_of_a_cone_of_sky_matches_sin_squared(fp):
    # sky wherever the fisheye zenith angle is under 45 degrees: Steyn's cosine-weighted SVF is sin^2(45) = 0.5
    seg = np.zeros((6, 512, 512), bool)
    seg[4] = (fp.radiusPerImage[4].reshape(512, 512) < 0.5)
    assert svf(fp, seg) == pytest.approx(0.5, abs=0.04)


def test_pano2cube_writes_six_correctly_named_faces(tmp_path):
    src = tmp_path / "pano.png"
    pano = np.zeros((128, 256, 3), np.uint8)
    pano[:64] = 10                                                     # upper half: "sky"
    pano[64:] = 200                                                    # lower half: ground
    cv2.imwrite(str(src), pano)
    out = tmp_path / "faces"
    panorama_to_cubemap(str(src), str(out), cube_size=64)
    names = sorted(os.listdir(out))
    assert names == sorted(f"pano_{f}.jpg" for f in FACES)
    top = cv2.imread(str(out / "pano_0_90.jpg"))
    bottom = cv2.imread(str(out / "pano_0_270.jpg"))
    assert top.shape == (64, 64, 3)
    assert top.mean() < 40 and bottom.mean() > 160                     # the top face sees sky, the bottom face sees ground
    for f in ("0_0", "90_0", "180_0", "270_0"):
        face = cv2.imread(str(out / f"pano_{f}.jpg"))
        assert face[:20].mean() < 60 < 150 < face[-20:].mean()         # side faces: sky above, ground below


def test_pano2cube_reports_a_missing_file_instead_of_crashing(tmp_path, capsys):
    panorama_to_cubemap(str(tmp_path / "nope.png"), str(tmp_path / "o"), cube_size=8)
    assert "Failed to load" in capsys.readouterr().out


def test_image_reader_orders_faces_and_marks_sky(tmp_path):
    values = {"0_0": 40, "90_0": 40, "180_0": 40, "270_0": 40, "0_90": 0, "0_270": 40}      # only the top face is sky
    for name, v in values.items():
        cv2.imwrite(str(tmp_path / f"loc_{name}.jpg"), np.full((512, 512, 3), v, np.uint8))
    ir = ImageReader(str(tmp_path))
    assert ir.files.shape == (6, 512, 512)
    assert [os.path.basename(f) for f in ir.fileNames] == [f"loc_{n}.jpg" for n in ("0_0", "90_0", "180_0", "270_0", "0_90", "0_270")]
    assert ir.segmentationData[4].all() and not ir.segmentationData[:4].any() and not ir.segmentationData[5].any()
    assert ir.imageFilesExist() == 1
