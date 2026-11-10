"""Colour-threshold fractions on synthetic fisheye images with known composition."""
import numpy as np
import pytest
from PIL import Image

import webmrt as w

SKY, TREE, WALL = (90, 150, 255), (40, 120, 30), (150, 140, 130)


def fisheye(size=200, sky_frac_rows=0.5):
    """White outside the circle; inside: sky in the upper part, one tree band, grey 'building' elsewhere."""
    yy, xx = np.mgrid[:size, :size]
    c = (size - 1) / 2
    inside = (xx - c) ** 2 + (yy - c) ** 2 <= (size / 2) ** 2
    arr = np.full((size, size, 3), 255, np.uint8)
    arr[inside] = WALL
    arr[inside & (yy < size * sky_frac_rows)] = SKY
    arr[inside & (yy >= size * 0.8)] = TREE
    return Image.fromarray(arr), inside, yy


def test_fractions_match_the_painted_areas_and_sum_to_one():
    img, inside, yy = fisheye()
    n = inside.sum()
    svf, trees, buildings = w.calc_SVF(img)
    assert svf == pytest.approx((inside & (yy < 100)).sum() / n)
    assert trees == pytest.approx((inside & (yy >= 160)).sum() / n)
    assert svf + trees + buildings == pytest.approx(1.0)


def test_all_sky_and_all_wall_extremes():
    img, inside, yy = fisheye(sky_frac_rows=2.0)  # sky everywhere (tree band is overwritten last, so remove it)
    arr = np.array(img)
    arr[inside] = SKY
    svf, trees, buildings = w.calc_SVF(Image.fromarray(arr))
    assert (svf, trees, buildings) == pytest.approx((1.0, 0.0, 0.0))
    arr[inside] = WALL
    assert w.calc_SVF(Image.fromarray(arr)) == pytest.approx((0.0, 0.0, 1.0))


def test_overlay_is_a_png_data_url():
    img, *_ = fisheye(64)
    *_, overlay = w.calc_SVF(img, return_overlay=True)
    assert overlay.startswith("data:image/png;base64,")
