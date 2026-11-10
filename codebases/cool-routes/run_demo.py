"""Run the released Cool Routes method on the sample data and regenerate the website demo assets.

    python run_demo.py                 # print a cool-vs-shortest comparison, write demo assets + golden routes
    python run_demo.py --no-assets     # only print the comparison

What it does, for each sample MRT raster (see data/README in the top-level README):
  1. build the MRT-annotated walking network (src/coolroutes/graph.py),
  2. route between a few origin/destination pairs with the published cost functions
     (cool = ``cost``, shortest = ``length``),
  3. write the compact assets used by the interactive demo in ``demos/coolroutes/data``
     (graph.json, one colourised overlay per raster, meta.json) and the regression
     reference ``data/golden_routes.json`` (also copied next to the demo for the JS parity test).
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from coolroutes import (MrtRaster, NodeIndex, blended_weight, calculate_statistics,  # noqa: E402
                        get_route, graph_mrt_scale, make_walking_network_graph, mrt_to_rgba, to_undirected)

DATA = ROOT / "data"
GPKG = DATA / "walk_graph_crop.gpkg"
# raster stamp (UTC hour, as named by the live tool) -> local label (America/Phoenix = UTC-7, no DST)
STAMPS = {
    "2024-04-26-2100": "26 Apr 2024, 2 PM",
    "2024-06-15-2200": "15 Jun 2024, 3 PM",
}
BLEND_W = 0.5          # intermediate trade-off used in the golden file (demo extension)
N_PAIRS = 12
LON_OFF, LAT_OFF = 3e-5, -2e-5   # golden query points sit ~3 m off the node, so the snap is exercised


def build(stamp):
    raster = MrtRaster.from_geotiff(DATA / f"mrt_{stamp}.tif")
    Gd = make_walking_network_graph(raster, GPKG)
    return raster, Gd, to_undirected(Gd)


def pick_pairs(U, index, n=N_PAIRS, seed=42):
    """Deterministic origin/destination pairs 350-900 m apart (projected distance) that snap back to themselves."""
    rng = random.Random(seed)
    nodes = sorted(U.nodes)
    pairs = []
    while len(pairs) < n:
        a, b = rng.choice(nodes), rng.choice(nodes)
        if a == b:
            continue
        d = ((U.nodes[a]["x"] - U.nodes[b]["x"]) ** 2 + (U.nodes[a]["y"] - U.nodes[b]["y"]) ** 2) ** 0.5
        pa = (U.nodes[a]["lon"] + LON_OFF, U.nodes[a]["lat"] + LAT_OFF)
        pb = (U.nodes[b]["lon"] + LON_OFF, U.nodes[b]["lat"] + LAT_OFF)
        if 350 <= d <= 900 and index.nearest(*pa) == a and index.nearest(*pb) == b:
            import networkx as nx
            if nx.has_path(U, a, b):
                pairs.append((a, b, pa, pb))
    return pairs


def route_record(U, index, start, stop, weight):
    stats, _, _, route = get_route(U, index, start, stop, weight)
    return {"route": [int(n) for n in route], **{k: float(v) for k, v in stats.items()}}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-assets", action="store_true")
    ap.add_argument("--demo-dir", type=Path, default=ROOT.parents[1] / "demos" / "coolroutes" / "data")
    a = ap.parse_args()

    built = {s: build(s) for s in STAMPS}
    stamp0 = next(iter(STAMPS))
    U0 = built[stamp0][2]
    index = NodeIndex(U0)
    pairs = pick_pairs(U0, index)

    # ---------------------------------------------------------------- console summary
    print(f"{'stamp':17} {'pair':>4} {'short m':>8} {'cool m':>7} {'short MRT':>10} {'cool MRT':>9}")
    golden = {"blend_w": BLEND_W, "scale": {}, "pairs": []}
    for s, (raster, Gd, U) in built.items():
        golden["scale"][s] = graph_mrt_scale(U)
    for i, (na, nb, pa, pb) in enumerate(pairs):
        rec = {"start_node": int(na), "end_node": int(nb), "start": list(pa), "end": list(pb), "stamps": {}}
        for s, (raster, Gd, U) in built.items():
            short = route_record(U, index, pa, pb, "length")
            cool = route_record(U, index, pa, pb, "cost")
            blend = route_record(U, index, pa, pb, blended_weight(golden["scale"][s], BLEND_W))
            rec["stamps"][s] = {"length": short, "cost": cool, "blend": blend}
            print(f"{s:17} {i:>4} {short['length']:8.0f} {cool['length']:7.0f} "
                  f"{short['corrected_mean_mrt']:10.2f} {cool['corrected_mean_mrt']:9.2f}")
        golden["pairs"].append(rec)

    if a.no_assets:
        return
    (DATA / "golden_routes.json").write_text(json.dumps(golden, indent=1))

    # ---------------------------------------------------------------- demo assets
    a.demo_dir.mkdir(parents=True, exist_ok=True)
    stamps = list(STAMPS)
    node_ids = sorted(U0.nodes)
    nidx = {n: i for i, n in enumerate(node_ids)}
    nodes = [[int(n), round(U0.nodes[n]["lon"], 7), round(U0.nodes[n]["lat"], 7)] for n in node_ids]
    # edge i is identical across stamps; per stamp (cost, mrt) in the same order
    edges = []
    per = {s: {} for s in stamps}
    for s in stamps:
        for u, v, k, d in built[s][2].edges(keys=True, data=True):
            per[s][(u, v, k)] = (d["cost"], d["mrt"])
    for u, v, k, d in U0.edges(keys=True, data=True):
        geom = d["geometry"]
        # geometry is stored projected; recover lon/lat from the WGS84 network instead
        edges.append([nidx[u], nidx[v], round(float(d["length"]), 3), None] + [x for s in stamps for x in per[s][(u, v, k)]])
    # lon/lat geometry (interior vertices) from the unprojected network
    from coolroutes.graph import read_walk_graph
    W = read_walk_graph(GPKG)
    lonlat = {}
    for u, v, k, d in W.edges(keys=True, data=True):
        lonlat[(u, v, round(float(d["length"]), 3))] = [round(c, 6) for xy in list(d["geometry"].coords)[1:-1] for c in xy]
    for e, (u, v, k, d) in zip(edges, U0.edges(keys=True, data=True)):
        e[3] = lonlat.get((u, v, round(float(d["length"]), 3)), lonlat.get((v, u, round(float(d["length"]), 3)), []))
        # geometry is stored u -> v; if only the reverse edge exists in the source, reverse the vertices
        if (u, v, round(float(d["length"]), 3)) not in lonlat:
            pts = e[3]
            e[3] = [c for i in range(len(pts) // 2 - 1, -1, -1) for c in pts[2 * i:2 * i + 2]]
    graph = {"stamps": stamps, "scale": {s: golden["scale"][s] for s in stamps}, "nodes": nodes, "edges": edges}
    (a.demo_dir / "graph.json").write_text(json.dumps(graph, separators=(",", ":")))

    meta = {"stamps": [{"id": s, "label": STAMPS[s], "stampUtc": s,
                        "meanMrt": float(built[s][0].data[built[s][0].data > 0].mean())} for s in stamps],
            "blendW": BLEND_W}
    for s in stamps:
        raster = built[s][0]
        l, b, r, t = raster.bounds
        img = Image.fromarray(mrt_to_rgba(raster.data), "RGBA")
        img.save(a.demo_dir / f"mrt_{s}.webp", "WEBP", quality=88, method=6)
        info = raster.projection_info()
        meta["bounds3857"] = [l, b, r, t]
        meta["extent4326"] = info["extent"]
    meta["legend"] = {"min": 25, "max": 80}
    # default trip shown when the demo opens: the sample pair with the largest heat saving on the first raster
    best = max(golden["pairs"], key=lambda p: p["stamps"][stamp0]["length"]["corrected_mean_mrt"] - p["stamps"][stamp0]["cost"]["corrected_mean_mrt"])
    meta["defaults"] = {"start": [U0.nodes[best["start_node"]]["lon"], U0.nodes[best["start_node"]]["lat"]],
                        "end": [U0.nodes[best["end_node"]]["lon"], U0.nodes[best["end_node"]]["lat"]]}
    (a.demo_dir / "meta.json").write_text(json.dumps(meta, indent=1))
    (a.demo_dir / "golden.json").write_text(json.dumps(golden, separators=(",", ":")))
    total = sum(p.stat().st_size for p in a.demo_dir.iterdir())
    print(f"\ndemo assets written to {a.demo_dir} ({total / 1e6:.2f} MB)")


if __name__ == "__main__":
    main()
