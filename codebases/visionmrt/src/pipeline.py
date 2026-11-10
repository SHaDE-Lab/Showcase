"""
VisionMRT example pipeline (public release)
===========================================
Runs the same compute flow as the VisionMRT web tool's "Compute All Day" button, without the web layer:

    cube-face segmentation + depth  ->  fisheye (sky-up) view  ->  sky view factor
        -> 3D scene + hourly shadow casting  ->  weather  ->  surface energy balance
        -> mean radiant temperature (MRT), UTCI, PET for every hour of the day

The step order, defaults (hours 07..19, 1 h steps, altitude 340 m, log-law wind at 1.1 m, label colours, face
suffixes) are taken from the web tool's compute task; the physics lives in the unchanged modules
SurfaceTemperature.py, PyShadowComputation.py, FisheyeProjection.py and svf.py.

Weather is read from a JSON file instead of being downloaded, so a run is fully offline and repeatable.

Authors: SHaDE Lab, Arizona State University.
"""
from __future__ import annotations

import contextlib
import datetime as _dt
import json
import math
import os
import shutil
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
import pytz
from PIL import Image

# the physics modules print arrows / degree signs; a redirected Windows stdout would raise on them
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

SRC_DIR = Path(__file__).resolve().parent
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

# --- constants shared with the web tool ------------------------------------------------------------------------------
DAY_START_HOUR, DAY_END_HOUR = 7, 19
SHADOW_HOURS = list(range(DAY_START_HOUR, DAY_END_HOUR + 1))
DEFAULT_ALTITUDE_M = 340.0
SHADOW_DOWNSAMPLE = 2           # the web tool builds the shadow scene at half resolution (256 x 256 per face)

FACE_SUFFIX = {"North": "0_0", "South": "180_0", "East": "90_0", "West": "270_0", "Up": "0_90", "Down": "0_270"}
DIR_MAP = {"front": "North", "right": "East", "back": "South", "left": "West", "top": "Up", "bottom": "Down"}
SEG_COLORS = [[255, 255, 255], [0, 0, 255], [0, 255, 0], [192, 192, 192],
              [128, 128, 128], [255, 255, 0], [255, 0, 255], [0, 255, 255]]
SEG_CLASS_NAMES = ["Background", "Sky", "Trees/Plants", "Buildings", "Impervious Surfaces",
                   "Pervious Surfaces", "Non-permanent Objects", "ShadeSail"]


# --- small helpers -----------------------------------------------------------------------------------------------------
@contextlib.contextmanager
def _cwd(path):
    """The physics modules read and write output/<site>/... relative to the working directory."""
    old = os.getcwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(old)


def site_location(site_dir) -> tuple[float, float]:
    """Latitude/longitude, taken from the cube-face file names '<lat>_<lon>_<heading>_<pitch>_seg.png'."""
    f = sorted(Path(site_dir, "color_depth_seg", "seg").glob("*_seg.png"))[0].name
    lat, lon = f.split("_")[:2]
    return float(lat), float(lon)


def load_weather(path) -> dict:
    """{local hour: {air_temperature, relative_humidity, wind_velocity (1.1 m), wind_velocity_10m, cloud_cover 0..1}}"""
    raw = json.loads(Path(path).read_text(encoding="utf-8"))["hourly"]
    return {int(h): v for h, v in raw.items()}


def wind_at_height(u10: float, target_z: float = 1.1, z0: float = 0.03) -> float:
    """Log-law reduction of the 10 m wind speed to pedestrian level (same as the web tool)."""
    if u10 <= 0:
        return 0.0
    z0 = max(z0, 1e-4)
    return u10 * math.log(target_z / z0) / math.log(10.0 / z0)


def load_seg_labels(seg_dir) -> dict:
    """Segmentation of the six faces as integer label arrays, keyed front/right/back/left/top/bottom."""
    seg = {}
    for st_dir, face in DIR_MAP.items():
        matches = sorted(Path(seg_dir).glob(f"*_{FACE_SUFFIX[face]}_seg.png"))
        if not matches:
            seg[st_dir] = np.ones((512, 512), dtype=np.uint8)
            continue
        img = np.array(Image.open(matches[0]).convert("RGB"))
        # A grayscale label map has R == G == B. (The web tool's loader tests only R == G, which misreads a face
        # that is entirely sky, RGB (0,0,255), as an all-zero label map; svf.py always tested all three channels.)
        if (img[:, :, 0] == img[:, :, 1]).all() and (img[:, :, 1] == img[:, :, 2]).all() and img.max() < 8:
            seg[st_dir] = img[:, :, 0].astype(np.uint8)
        else:
            lab = np.zeros(img.shape[:2], dtype=np.uint8)
            for label, color in enumerate(SEG_COLORS):
                lab[np.all(img == color, axis=-1)] = label
            seg[st_dir] = lab
    return seg


def decode_shadow(img_rgb: np.ndarray) -> np.ndarray:
    """Shadow-map picture -> code: 0 shadow, 1 sunlit, 2 tree shadow, 3 shade-sail shadow."""
    s = np.ones(img_rgb.shape[:2], dtype=np.uint8)
    s[np.all(img_rgb == [0, 0, 0], axis=-1)] = 0
    s[np.all(img_rgb == [20, 80, 20], axis=-1)] = 2
    s[np.all(img_rgb == [0, 0, 100], axis=-1)] = 3
    return s


# --- the steps ---------------------------------------------------------------------------------------------------------
def compute_svf(site_dir) -> dict:
    """Sky view factor of a site from its six segmentation faces (see svf.py)."""
    import svf
    return svf.compute_site_svf(site_dir)


def cast_shadows(site_id: str, lat: float, lon: float, date_str: str, tz_name: str, downsample=SHADOW_DOWNSAMPLE):
    """3D scene from depth+segmentation, then one shadow map per face per local hour.
    Expects output/<site_id>/color_depth_seg/ under the current working directory.
    Returns {hour: {face_name: RGB uint8 image}}."""
    import PyShadowComputation as sc
    pairs = sc.generate_image_pairs(site_id)
    scene, _meshes, _, face_data, vcounts, all_verts, tree_ids, sail_ids = sc.build_shadow_scene_once(
        pairs, downsample=downsample)
    year, month, day = [int(x) for x in date_str.split("-")]
    tz = pytz.timezone(tz_name)
    stamps = [tz.localize(_dt.datetime(year, month, day, h, 0, 0)) for h in SHADOW_HOURS]
    results = sc.execute_timestep(scene, face_data, vcounts, all_verts, lat, lon, stamps,
                                  tree_geom_ids=tree_ids, sail_geom_ids=sail_ids)
    return {h: imgs for h, (_ts, imgs) in zip(SHADOW_HOURS, results)}


def run_site(site_dir, out_dir, date_str: str, weather: dict, tz_name: str = "America/Phoenix",
             lat: float | None = None, lon: float | None = None, altitude: float = DEFAULT_ALTITUDE_M,
             keep_workdir: bool = False, verbose: bool = False) -> dict:
    """Compute MRT / UTCI / PET for every hour (07..19) of `date_str` at one site.

    site_dir : folder holding color_depth_seg/seg/*_seg.png and color_depth_seg/depth/*_depth.png (colour optional)
    out_dir  : where results.csv, svf.json, fisheye_up_seg.png and the shadow maps are written
    Returns  : {"svf", "results" (DataFrame, one row per hour), "shadow" ({hour: {face: img}}), "fisheye_up" (path)}
    """
    site_dir, out_dir = Path(site_dir).resolve(), Path(out_dir).resolve()
    site_id = site_dir.name
    if lat is None or lon is None:
        lat, lon = site_location(site_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    work = Path(tempfile.mkdtemp(prefix="visionmrt_"))
    try:
        dst = work / "output" / site_id
        shutil.copytree(site_dir / "color_depth_seg", dst / "color_depth_seg")
        with contextlib.ExitStack() as stack:
            stack.enter_context(_cwd(work))
            if not verbose:
                stack.enter_context(contextlib.redirect_stdout(stack.enter_context(open(os.devnull, "w", encoding="utf-8"))))
            import FisheyeProjection
            from SurfaceTemperature import SurfaceTemperature
            import svf as svf_mod

            # 0. fisheye (sky-up) segmentation view - the input the fisheye SVF method reads
            FisheyeProjection.fisheye_projection_type(site_id, image_type="seg", directions=["up"])
            fisheye_png = dst / "fisheye" / "seg" / "fisheye_photo_up_0_90.png"

            # SVF: cosine-weighted sky solid angle of the six faces
            info = svf_mod.ensure_site_svf(dst, source="release")

            # 1. shadows for every hour
            shadow = cast_shadows(site_id, lat, lon, date_str, tz_name)

            # 2-3. weather -> per-hour inputs
            hours = SHADOW_HOURS
            n = len(hours)
            g = lambda key, d: [weather.get(h, {}).get(key, d) for h in hours]       # noqa: E731
            air, rh, wind = g("air_temperature", 38.0), g("relative_humidity", 20.0), g("wind_velocity", 1.25)
            wind10, cloud = g("wind_velocity_10m", 2.5), g("cloud_cover", 0.0)
            st = SurfaceTemperature()
            lw = {d: [st.get_atmospheric_radiation(air[i], st.get_vapor_pressure(rh[i], air[i]), cloud[i])
                      for i in range(n)] for d in DIR_MAP}
            measurements = {
                "single_mode": False, "air_temperature": air, "relative_humidity": rh,
                "wind_velocity": wind, "wind_velocity_10m": wind10, "cloud_cover": cloud,
                "mrt_gt": [0.0] * n, "shaded_at_measurement": [0] * n, "sky_view_factor": [0.6] * n,
                "shortwave_radiation": {d: [0.0] * n for d in DIR_MAP}, "longwave_radiation": lw,
            }

            # 4. shadow codes + fisheye geometry for the physics
            shadow_data = {d: [decode_shadow(shadow[h][face]) for h in hours] for d, face in DIR_MAP.items()}
            size = 512
            yy, xx = np.indices((size, size))
            r = np.clip(np.sqrt((xx - size // 2) ** 2 + (yy - size // 2) ** 2) / (size // 2), 0, 1)
            r = r.astype(np.float32).flatten()
            frac = np.cos(r * (np.pi / 2.0)).astype(np.float32)
            radii = {d: r.copy() for d in DIR_MAP}
            fracs = {d: frac.copy() for d in DIR_MAP}
            surface_temp = {d: [np.full((512, 512), np.nan, dtype=np.float32) for _ in range(n)] for d in DIR_MAP}

            year, month, day = [int(x) for x in date_str.split("-")]
            tz = pytz.timezone(tz_name)
            local_times = [tz.localize(_dt.datetime(year, month, day, h)).strftime("%Y-%m-%d %H:%M:%S") for h in hours]
            csv_path = os.path.join("output", site_id, "toolkit_mrt_results.csv")

            # 5. surface energy balance -> MRT, UTCI, PET
            st.execute(
                segmentation_data=load_seg_labels(dst / "color_depth_seg" / "seg"),
                local_times=local_times, shadow_data=shadow_data,
                location={"latitude": lat, "longitude": lon, "altitude": float(altitude)},
                measurements=measurements, minute_delta=60,
                radii_by_fisheye_subset=radii, fractions_by_fisheye_subset=fracs,
                csv_path=csv_path, surface_temperature_data=surface_temp,
                folder_id=site_id, timezone=tz_name)

        results = pd.read_csv(work / "output" / site_id / "toolkit_mrt_results.csv")
        results = results.drop_duplicates(subset="DateTime", keep="last").reset_index(drop=True)
        results.insert(0, "Hour", hours[: len(results)])
        results.to_csv(out_dir / "results.csv", index=False)
        shutil.copy(fisheye_png, out_dir / "fisheye_up_seg.png")
        (out_dir / "svf.json").write_text(json.dumps(info, indent=1), encoding="utf-8")
        return {"svf": info["svf"], "results": results, "shadow": shadow,
                "fisheye_up": out_dir / "fisheye_up_seg.png", "lat": lat, "lon": lon}
    finally:
        if keep_workdir:
            print("work dir kept:", work)
        else:
            shutil.rmtree(work, ignore_errors=True)


# --- derived quantities ------------------------------------------------------------------------------------------------
SIX_DIR_WEIGHTS = [0.22, 0.22, 0.22, 0.22, 0.06, 0.06]      # Left, Right, Front, Back, Up, Down (SurfaceTemperature)
BODY_ABSORPTION, BODY_EMISSION, SIGMA = 0.7, 0.97, 5.670367e-8
_DIRS = ["Left", "Right", "Front", "Back", "Up", "Down"]


def radiation_components(results: pd.DataFrame) -> pd.DataFrame:
    """Absorbed shortwave and longwave flux density (W/m2) of a standing person, from the six-direction fluxes the model
    wrote (Calc_SW_*/Calc_LW_*), weighted exactly as SurfaceTemperature.compute_mean_radiant_flux_density does, and the
    MRT those two numbers imply. `MRT_from_components` must equal the model's own MRT_CalcSW_CalcLW column."""
    sw = sum(w * BODY_ABSORPTION * results[f"Calc_SW_{d}"] for w, d in zip(SIX_DIR_WEIGHTS, _DIRS))
    lw = sum(w * BODY_EMISSION * results[f"Calc_LW_{d}"] for w, d in zip(SIX_DIR_WEIGHTS, _DIRS))
    mrt = ((sw + lw) / (BODY_EMISSION * SIGMA)) ** 0.25 - 273.15
    return pd.DataFrame({"Hour": results["Hour"], "SW_absorbed": sw, "LW_absorbed": lw, "MRT_from_components": mrt})
