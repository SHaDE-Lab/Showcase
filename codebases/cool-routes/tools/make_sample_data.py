"""Maintainer tool: cut the small public sample dataset out of the full Cool Routes server data.

Not needed to run the demo or the tests (the output is committed in ``data/``).
It documents exactly how ``data/`` was produced.

    python tools/make_sample_data.py --server-dir /path/to/Cool-Routes-Server/server

Inputs  (SHaDE Lab Cool Routes server, ``server/``):
    output/<stamp>_mrt.tif                 hourly SOLWEIG MRT rasters (EPSG:3857, 1 m, float64)
    output/<stamp>_graph_networked.graphml the live tool's pre-computed MRT graph for that stamp
    Maps/walkOnlyGraph.gpkg                pedestrian network of the ASU Tempe campus (OpenStreetMap)

Outputs (``data/``):
    mrt_<stamp>.tif                  1000 x 1000 m window, int16 x 0.01 degC, deflate-compressed
    walk_graph_crop.gpkg             sub-network fully inside the window (largest connected part)
    reference_published_<stamp>.csv  per-edge ``mrt`` / ``cost`` from the live tool's own graphml,
                                     used by the tests as an independent check
Raster stamps are the *UTC* hour (see solweig_run.py: ``time_to_run.tz_convert(None)``).
"""
from __future__ import annotations

import argparse
import csv
from pathlib import Path

import geopandas as gpd
import networkx as nx
import numpy as np
import rasterio
from pyproj import Transformer
from rasterio.windows import Window
from shapely.geometry import box
from shapely.ops import transform as shp_transform

STAMPS = ["2024-04-26-2100", "2024-06-15-2200"]
CENTER_3857 = (-12460750.0, 3951550.0)   # core of the ASU Tempe campus (around the Brickyard)
HALF = 500                                # pixels (1 pixel = 1 EPSG:3857 unit)
MARGIN = 5.0                              # edges must lie this far inside the window


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--server-dir", required=True, type=Path)
    ap.add_argument("--out", type=Path, default=Path(__file__).resolve().parents[1] / "data")
    a = ap.parse_args()
    a.out.mkdir(exist_ok=True)

    bounds = None
    for stamp in STAMPS:
        with rasterio.open(a.server_dir / "output" / f"{stamp}_mrt.tif") as src:
            r, c = src.index(*CENTER_3857)
            win = Window(c - HALF, r - HALF, 2 * HALF, 2 * HALF)
            data = src.read(1, window=win)
            tr = src.window_transform(win)
            crs = src.crs
        q = np.clip(np.rint(data * 100.0), -32768, 32767).astype("int16")
        prof = dict(driver="GTiff", dtype="int16", count=1, height=q.shape[0], width=q.shape[1],
                    crs=crs, transform=tr, compress="deflate", predictor=2, nodata=None)
        with rasterio.open(a.out / f"mrt_{stamp}.tif", "w", **prof) as dst:
            dst.write(q, 1)
            dst.scales = (0.01,)
            dst.offsets = (0.0,)
            dst.update_tags(SOURCE="SHaDE Lab Cool Routes SOLWEIG MRT raster", STAMP_UTC=stamp,
                            UNITS="degC", QUANTISATION="int16 x 0.01")
        bounds = (tr.c, tr.f + tr.e * q.shape[0], tr.c + tr.a * q.shape[1], tr.f)
        print(stamp, "window", bounds, "MRT %.1f..%.1f" % (data.min(), data.max()))

    # ---- sub-network fully inside the window
    gpkg = a.server_dir / "Maps" / "walkOnlyGraph.gpkg"
    nodes = gpd.read_file(gpkg, layer="nodes")
    edges = gpd.read_file(gpkg, layer="edges")
    tr = Transformer.from_crs("EPSG:4326", "EPSG:3857", always_xy=True)
    inner = box(bounds[0] + MARGIN, bounds[1] + MARGIN, bounds[2] - MARGIN, bounds[3] - MARGIN)
    inside = np.array([inner.contains(shp_transform(tr.transform, g)) for g in edges.geometry])
    sub = edges[inside]
    G = nx.Graph()
    G.add_edges_from(zip(sub["u"], sub["v"]))
    keep = max(nx.connected_components(G), key=len)
    sub = sub[sub["u"].isin(keep) & sub["v"].isin(keep)]
    used = set(sub["u"]) | set(sub["v"])
    nsub = nodes[nodes["osmid"].isin(used)]
    sub = sub[["u", "v", "key_", "osmid", "oneway", "highway", "length", "geometry"]].copy()
    for col in ("osmid", "oneway", "highway"):
        sub[col] = sub[col].astype(str)
    nsub = nsub[["osmid", "y", "x", "street_count", "highway", "geometry"]].copy()
    nsub["highway"] = nsub["highway"].astype(str)
    out_gpkg = a.out / "walk_graph_crop.gpkg"
    out_gpkg.unlink(missing_ok=True)
    nsub.to_file(out_gpkg, layer="nodes", driver="GPKG")
    sub.to_file(out_gpkg, layer="edges", driver="GPKG")
    print("sub-network:", len(nsub), "nodes,", len(sub), "directed edges")

    # ---- reference values from the live tool's own pre-computed graphs
    wanted = {(int(u), int(v), round(float(l), 3)) for u, v, l in zip(sub["u"], sub["v"], sub["length"])}
    for stamp in STAMPS:
        Gref = nx.read_graphml(a.server_dir / "output" / f"{stamp}_graph_networked.graphml")
        with open(a.out / f"reference_published_{stamp}.csv", "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["u", "v", "length", "mrt", "cost"])
            n = 0
            for u, v, d in Gref.edges(data=True):
                sig = (int(u), int(v), round(float(d["length"]), 3))
                if sig in wanted:
                    w.writerow([u, v, d["length"], d["mrt"], d["cost"]])
                    n += 1
        print(stamp, "reference rows:", n)


if __name__ == "__main__":
    main()
