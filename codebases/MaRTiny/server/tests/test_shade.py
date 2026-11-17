import numpy as np

from martiny_server.shade import count_in_shade, is_in_shade


def shadow(h=60, w=100, value=255):
    return np.full((h, w), value, dtype=np.uint8)


def test_box_fully_in_shadow_and_fully_in_sun():
    assert is_in_shade(shadow(value=255), (10, 10, 30, 40))
    assert not is_in_shade(shadow(value=0), (10, 10, 30, 40))


def test_threshold_ten_is_not_shadow_eleven_is():
    assert not is_in_shade(shadow(value=10), (10, 10, 30, 40))
    assert is_in_shade(shadow(value=11), (10, 10, 30, 40))


def test_overlap_fraction_boundary_is_inclusive():
    m = shadow(value=0)
    m[0:10, 0:2] = 255                       # 20 shadow pixels
    box = (0, 0, 9, 9)                       # 10 x 10 = 100 pixels, both corners included
    assert is_in_shade(m, box, 0.2)          # exactly 20 %
    m[0, 0] = 0                              # 19 pixels
    assert not is_in_shade(m, box, 0.2)


def test_box_area_counts_both_corners():
    m = shadow(value=0)
    m[5, 5] = 255
    assert is_in_shade(m, (5, 5, 5, 5), 1.0)           # a one-pixel box has area 1


def test_box_leaving_the_image_keeps_its_full_area():
    m = shadow(h=10, w=10, value=255)
    # box 10 wide by 10 tall, but only a 5 x 10 part is inside the image: 50 shadow pixels of area 100
    assert is_in_shade(m, (5, 0, 14, 9), 0.5)
    assert not is_in_shade(m, (5, 0, 14, 9), 0.51)


def test_box_completely_outside_is_not_in_shade():
    assert not is_in_shade(shadow(), (500, 500, 520, 540))
    assert not is_in_shade(shadow(), (-50, -50, -10, -10))


def test_degenerate_box_is_not_in_shade():
    assert not is_in_shade(shadow(), (30, 30, 10, 10))


def test_count_in_shade_gives_integers_per_box():
    m = shadow(value=0)
    m[:, :50] = 255
    out = count_in_shade(m, [(0, 0, 20, 20), (60, 0, 90, 20), (40, 0, 60, 20)])
    assert out == [1, 0, 1] and all(type(v) is int for v in out)
