"""Colour-threshold sky / tree / building fractions from a segmented fisheye image (the fallback method).

Extracted unchanged from SVFCalculator.calc_SVF (WebMRT, SHaDE Lab). Works on whole arrays and writes nothing to disk.
Input convention: a square RGB(A) image of the upward fisheye in which pixels outside the fisheye circle are pure white.
"""
import base64
from io import BytesIO

import numpy as np
from PIL import Image


def calc_SVF(img, return_overlay=False):
    """Returns (sky_view_factor, tree_share, building_share), each as a fraction of the pixels inside the fisheye.
    With return_overlay a 4th value is a PNG data URL (blue sky, green trees, white the rest)."""
    img_array = np.array(img.convert("RGBA"))
    r, g, b = img_array[..., 0], img_array[..., 1], img_array[..., 2]

    white = (r == 255) & (g == 255) & (b == 255)
    sky = ~white & (r < 200) & (g > 120) & (b > 200)
    trees = ~white & ~sky & (r < 120) & (g > 35) & (b < 90)

    output_array = np.full_like(img_array, 255)  # white for everything else
    output_array[sky] = (0, 0, 255, 255)
    output_array[trees] = (0, 255, 0, 255)

    fisheye_pixels = img_array.shape[0] * img_array.shape[1] - int(white.sum())
    sky_pixel_count, tree_pixel_count = int(sky.sum()), int(trees.sum())
    svf = sky_pixel_count / fisheye_pixels
    buildings = (fisheye_pixels - (tree_pixel_count + sky_pixel_count)) / fisheye_pixels
    tree_share = tree_pixel_count / fisheye_pixels

    if return_overlay:
        buffer = BytesIO()
        Image.fromarray(output_array).save(buffer, format="PNG")
        return svf, tree_share, buildings, "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")
    return svf, tree_share, buildings
