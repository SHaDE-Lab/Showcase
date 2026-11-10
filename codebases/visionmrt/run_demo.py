#!/usr/bin/env python
"""
Regenerate the VisionMRT demo from the released code.

Runs the full pipeline (segmentation + depth -> SVF -> 3D shadows -> weather -> energy balance -> MRT/UTCI/PET)
on both example sites for one day, then writes:

  * data/expected/<site>.json     expected hourly outputs the tests compare against (with tolerances in the tests)
  * <out>/data.json + images      assets for the portfolio website's interactive widget (default: ../../demos/visionmrt)

    python run_demo.py                  # both sites, writes everything (about 2 minutes)
    python run_demo.py --no-web         # only refresh data/expected
    python run_demo.py --date 2018-06-09 --weather data/weather/tempe_2018-06-09.json
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "src"))
import pipeline as P  # noqa: E402

SITES = {
    "site_a_open": "Site A · more open sky",
    "site_b_enclosed": "Site B · more enclosed",
}
FACE_PX = 128                                        # size of one cube face in the preview nets
BASE_RGB = np.array([[255, 255, 255], [96, 165, 250], [52, 160, 90], [150, 156, 168],
                     [92, 98, 110], [214, 190, 120], [224, 90, 200], [60, 210, 230]], dtype=np.uint8)
NET = {"Up": (0, 1), "West": (1, 0), "North": (1, 1), "East": (1, 2), "South": (1, 3), "Down": (2, 1)}   # (row, col)


def _labels(path):
    arr = np.array(Image.open(path).convert("RGB"))
    lab = np.zeros(arr.shape[:2], dtype=np.uint8)
    for i, c in enumerate(P.SEG_COLORS):
        lab[np.all(arr == c, axis=-1)] = i
    return lab


def _face_label(site_dir, face):
    f = sorted(Path(site_dir, "color_depth_seg", "seg").glob(f"*_{P.FACE_SUFFIX[face]}_seg.png"))[0]
    return _labels(f)


def _resize_nearest(a, n):
    s = a.shape[0] // n
    return a[::s, ::s][:n, :n]


def render_net(site_dir, shadow_imgs=None):
    """Cube-cross preview: segmentation classes, darkened where a shadow map says the surface is shaded."""
    canvas = np.zeros((3 * FACE_PX, 4 * FACE_PX, 4), dtype=np.uint8)           # transparent background
    for face, (r, c) in NET.items():
        lab = _resize_nearest(_face_label(site_dir, face), FACE_PX)
        rgb = BASE_RGB[np.clip(lab, 0, len(BASE_RGB) - 1)].astype(np.float32)
        if shadow_imgs is not None:
            code = _resize_nearest(P.decode_shadow(shadow_imgs[face]), FACE_PX)
            shade = (code != 1) & (lab != 1)                                   # sky is never "in shadow"
            rgb[shade] = rgb[shade] * 0.38 + np.array([20, 24, 48]) * 0.62
            lit = (code == 1) & (lab != 1)
            rgb[lit] = np.minimum(255, rgb[lit] * 1.12 + 12)
        canvas[r * FACE_PX:(r + 1) * FACE_PX, c * FACE_PX:(c + 1) * FACE_PX, :3] = rgb.astype(np.uint8)
        canvas[r * FACE_PX:(r + 1) * FACE_PX, c * FACE_PX:(c + 1) * FACE_PX, 3] = 255
    return Image.fromarray(canvas, "RGBA")


def fisheye_preview(path, size=360):
    arr = np.array(Image.open(path).convert("RGB"))
    lab = np.zeros(arr.shape[:2], dtype=np.uint8)
    for i, c in enumerate(P.SEG_COLORS):
        lab[np.all(arr == c, axis=-1)] = i
    h, w = lab.shape
    yy, xx = np.indices(lab.shape)
    disc = np.hypot(xx - (w - 1) / 2, yy - (h - 1) / 2) <= min(h, w) / 2
    rgba = np.zeros((h, w, 4), dtype=np.uint8)
    rgba[..., :3] = BASE_RGB[np.clip(lab, 0, len(BASE_RGB) - 1)]
    rgba[..., 3] = np.where(disc, 255, 0)
    return Image.fromarray(rgba, "RGBA").resize((size, size), Image.NEAREST)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default="2018-06-09")
    ap.add_argument("--weather", default=str(HERE / "data" / "weather" / "tempe_2018-06-09.json"))
    ap.add_argument("--out", default=str(HERE.parent.parent / "demos" / "visionmrt"))
    ap.add_argument("--no-web", action="store_true", help="only write data/expected")
    a = ap.parse_args()

    weather = P.load_weather(a.weather)
    out = Path(a.out)
    exp_dir = HERE / "data" / "expected"
    exp_dir.mkdir(parents=True, exist_ok=True)
    web = {"date": a.date, "timezone": "America/Phoenix", "hours": P.SHADOW_HOURS,
           "weather": {k: [weather[h][k] for h in P.SHADOW_HOURS]
                       for k in ("air_temperature", "relative_humidity", "wind_velocity_10m", "cloud_cover")},
           "classes": [{"name": n, "rgb": BASE_RGB[i].tolist()} for i, n in enumerate(P.SEG_CLASS_NAMES) if i in (1, 2, 3, 4, 5)],
           "sites": {}}

    for sid, label in SITES.items():
        print(f"== {sid}")
        site_dir = HERE / "data" / "sites" / sid
        res = P.run_site(site_dir, HERE / "build" / sid, a.date, weather)
        df = res["results"]
        comp = P.radiation_components(df)
        sun = df["SunVisible"].astype(bool).tolist()

        expected = {"site": sid, "date": a.date, "lat": res["lat"], "lon": res["lon"], "svf": round(res["svf"], 4),
                    "hours": P.SHADOW_HOURS,
                    "mrt": df["MRT_CalcSW_CalcLW"].round(2).tolist(), "utci": df["UTCI"].round(2).tolist(),
                    "pet": df["PET"].round(2).tolist(), "sun_visible": sun,
                    "sw_absorbed": comp["SW_absorbed"].round(1).tolist(), "lw_absorbed": comp["LW_absorbed"].round(1).tolist()}
        (exp_dir / f"{sid}.json").write_text(json.dumps(expected, indent=1), encoding="utf-8")

        if a.no_web:
            continue
        img_dir = out / "img" / sid
        img_dir.mkdir(parents=True, exist_ok=True)
        render_net(site_dir).save(img_dir / "seg_net.png", optimize=True)
        fisheye_preview(res["fisheye_up"]).save(img_dir / "fisheye.png", optimize=True)
        for h in P.SHADOW_HOURS:
            render_net(site_dir, res["shadow"][h]).quantize(colors=48, method=Image.FASTOCTREE).save(
                img_dir / f"shadow_{h:02d}.png", optimize=True)
        lit = {}
        for h in P.SHADOW_HOURS:       # share of each face's non-sky pixels that is sunlit, per hour
            lit[h] = {f: round(float((P.decode_shadow(res["shadow"][h][f]) == 1).mean()), 3) for f in NET}
        web["sites"][sid] = {
            "label": label, "lat": res["lat"], "lon": res["lon"], "svf": expected["svf"],
            "mrt": expected["mrt"], "utci": expected["utci"], "pet": expected["pet"], "sun_visible": sun,
            "sw_absorbed": expected["sw_absorbed"], "lw_absorbed": expected["lw_absorbed"],
            "sunlit_share": lit,
        }

    if not a.no_web:
        out.mkdir(parents=True, exist_ok=True)
        (out / "data.json").write_text(json.dumps(web, separators=(",", ":")), encoding="utf-8")
        print("demo assets ->", out)


if __name__ == "__main__":
    main()
