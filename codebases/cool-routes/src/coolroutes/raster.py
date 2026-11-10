"""MRT raster access and colourisation.

Curated from the SHaDE Lab Cool Routes server (``server/raster.py`` and the
raster-sampling helper in ``solweig_server/form_graphml.py``).

* ``MrtRaster.sample`` reproduces ``rasterio.DatasetReader.sample`` semantics
  (nearest pixel = floor of the pixel coordinate, 0 outside the raster) so edge
  statistics equal those of the published pipeline.
* ``mrt_to_rgba`` is the colour ramp of the live tool's MRT overlay (fixed
  25-80 degC range, the same 12 stops as the web legend).
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import rasterio
from rasterio.transform import Affine
from rasterio.warp import transform_bounds


@dataclass
class MrtRaster:
    """A single-band mean radiant temperature raster held in memory (degC)."""

    data: np.ndarray          # 2-D float64, degC
    transform: Affine
    crs: "rasterio.crs.CRS"

    # ------------------------------------------------------------------ io
    @classmethod
    def from_geotiff(cls, path) -> "MrtRaster":
        """Read a GeoTIFF; honours the band's scale/offset (sample data are int16 x 0.01)."""
        with rasterio.open(path) as src:
            data = src.read(1).astype("float64")
            scale = src.scales[0] if src.scales else 1.0
            offset = src.offsets[0] if src.offsets else 0.0
            data = data * scale + offset
            return cls(data=data, transform=src.transform, crs=src.crs)

    @property
    def height(self) -> int:
        return self.data.shape[0]

    @property
    def width(self) -> int:
        return self.data.shape[1]

    @property
    def bounds(self):
        """(left, bottom, right, top) in raster CRS units."""
        t = self.transform
        return (t.c, t.f + t.e * self.height, t.c + t.a * self.width, t.f)

    # ------------------------------------------------------------ sampling
    def sample(self, x: float, y: float) -> float:
        """MRT at one point given in the raster CRS (nearest pixel, 0 outside)."""
        col, row = (~self.transform) * (x, y)
        col, row = math.floor(col), math.floor(row)
        if 0 <= row < self.height and 0 <= col < self.width:
            return float(self.data[row, col])
        return 0.0

    def projection_info(self) -> dict:
        """Equivalent of the tool's ``get_raster_projection_info`` (WGS84 extent + MRT range)."""
        valid = np.isfinite(self.data) & (self.data > 0)
        if not valid.any():
            raise ValueError("Raster does not contain any positive non-zero MRT values.")
        l, b, r, t = self.bounds
        west, south, east, north = transform_bounds(self.crs, "EPSG:4326", l, b, r, t, densify_pts=21)
        return {
            "width": self.width,
            "height": self.height,
            "mrtRange": {"min": float(self.data[valid].min()), "max": float(self.data[valid].max())},
            "extent": {"xmin": west, "ymin": south, "xmax": east, "ymax": north,
                       "spatialReference": {"wkid": 4326}},
        }


# ------------------------------------------------------------------ colours
FIXED_MIN_MRT = 25.0
FIXED_MAX_MRT = 80.0
MRT_STOP_VALUES = np.array([25, 30, 35, 40, 45, 50, 55, 60, 65, 70, 75, 80], dtype=np.float32)
MRT_COLORS_HEX = ["#08306b", "#08519c", "#2171b5", "#6baed6", "#c6dbef", "#ffffcc",
                  "#ffeda0", "#fed976", "#feb24c", "#fd8d3c", "#fc4e2a", "#800026"]


def _hex_to_rgb(h: str):
    h = h.lstrip("#")
    return [int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)]


def mrt_to_rgba(data: np.ndarray) -> np.ndarray:
    """Colourise an MRT array exactly like ``convert_mrt_tiff_to_png``.

    Pixels that are NaN or <= 0 degC are transparent (buildings / no data).
    Returns a (H, W, 4) uint8 array.
    """
    data = np.asarray(data, dtype="float32")
    valid = np.isfinite(data) & (data > 0)
    colors = np.array([_hex_to_rgb(c) for c in MRT_COLORS_HEX], dtype=np.float32)
    normalized = np.clip((np.nan_to_num(data, nan=0.0) - FIXED_MIN_MRT) / (FIXED_MAX_MRT - FIXED_MIN_MRT), 0.0, 1.0)
    positions = (MRT_STOP_VALUES - FIXED_MIN_MRT) / (FIXED_MAX_MRT - FIXED_MIN_MRT)
    chans = [np.interp(normalized, positions, colors[:, k]) for k in range(3)]
    alpha = np.full(data.shape, 255, dtype=np.uint8)
    for c in chans:
        c[~valid] = 0
    alpha[~valid] = 0
    return np.stack([c.astype(np.uint8) for c in chans] + [alpha], axis=-1)
