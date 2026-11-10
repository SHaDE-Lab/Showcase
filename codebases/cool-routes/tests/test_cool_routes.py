"""Tests of the Cool Routes method on the bundled sample data (real ASU campus MRT rasters)."""
import csv
import json
import math
import random
from pathlib import Path

import numpy as np
import pytest
import rasterio
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import dijkstra
from shapely.geometry import LineString

from coolroutes import (MrtRaster, NodeIndex, blended_weight, calculate_statistics, get_route,
                        graph_mrt_scale, make_walking_network_graph, mrt_to_rgba, to_undirected)
from coolroutes.raster import MRT_COLORS_HEX
from coolroutes.routing import find_the_used_edge

DATA = Path(__file__).resolve().parents[1] / "data"
GPKG = DATA / "walk_graph_crop.gpkg"
STAMPS = ["2024-04-26-2100", "2024-06-15-2200"]


@pytest.fixture(scope="session", params=STAMPS)
def case(request):
    s = request.param
    raster = MrtRaster.from_geotiff(DATA / f"mrt_{s}.tif")
    Gd = make_walking_network_graph(raster, GPKG)
    U = to_undirected(Gd)
    return {"stamp": s, "raster": raster, "Gd": Gd, "U": U, "index": NodeIndex(U)}


def _random_pairs(U, n, seed):
    rng, nodes, out = random.Random(seed), sorted(U.nodes), []
    while len(out) < n:
        a, b = rng.choice(nodes), rng.choice(nodes)
        if a != b:
            out.append((a, b))
    return out


def _lonlat(U, n):
    return (U.nodes[n]["lon"], U.nodes[n]["lat"])


# ---------------------------------------------------------------- edge MRT
def test_edge_mrt_matches_independent_rasterio_sampling(case):
    """Edge mean/total MRT equal a from-scratch re-computation that uses rasterio's own sampler."""
    edges = list(case["Gd"].edges(data=True))
    with rasterio.open(DATA / f"mrt_{case['stamp']}.tif") as src:
        scale = src.scales[0]
        for u, v, d in edges[:: max(1, len(edges) // 60)]:
            line = LineString(d["geometry"])
            n = max(int(line.length), 1)
            pts = [line.interpolate(i / n, normalized=True) for i in range(n + 1)]
            vals = [max(float(next(src.sample([(p.x, p.y)]))[0]) * scale, 0) for p in pts]
            assert d["cost"] == pytest.approx(sum(vals), rel=1e-9)
            assert d["mrt"] == pytest.approx(sum(vals) / (n + 1), rel=1e-9)


def test_cost_is_sum_and_mrt_is_mean(case):
    for u, v, d in case["Gd"].edges(data=True):
        n = max(int(d["geometry"].length), 1) + 1
        assert d["cost"] == pytest.approx(d["mrt"] * n, rel=1e-9)
        assert d["mrt"] >= 0


def test_consistent_with_published_graph(case):
    """Loose consistency with the lab's own pre-computed graph (reference_published_*.csv).

    The graph shipped with the live tool does not appear to come from the very same raster
    version as the shipped GeoTIFF (per-edge values differ, 17 % of edges use one or two fewer
    samples), so only structure and aggregate level are asserted here, not per-edge equality.
    """
    ref = {}
    with open(DATA / f"reference_published_{case['stamp']}.csv") as f:
        for r in csv.DictReader(f):
            ref[(int(r["u"]), int(r["v"]), round(float(r["length"]), 3))] = (float(r["mrt"]), float(r["cost"]))
    same_n, mine, theirs = 0, [], []
    for u, v, d in case["Gd"].edges(data=True):
        m, c = ref[(u, v, round(d["length"], 3))]
        same_n += abs(c / m - (max(int(d["geometry"].length), 1) + 1)) < 1e-6
        mine.append(d["mrt"])
        theirs.append(m)
    assert same_n / len(mine) > 0.75            # same sampling rule on (nearly) all edges
    assert abs(np.mean(mine) - np.mean(theirs)) < 0.5   # same overall MRT level (degC)


# ---------------------------------------------------------------- routing
def _csgraph_shortest_length(U, a, b):
    nodes = sorted(U.nodes)
    ix = {n: i for i, n in enumerate(nodes)}
    best = {}
    for u, v, d in U.edges(data=True):
        key = (ix[u], ix[v])
        best[key] = min(best.get(key, 1e18), d["length"])
    rows, cols, vals = [], [], []
    for (i, j), w in best.items():
        rows += [i, j]
        cols += [j, i]
        vals += [w, w]
    m = coo_matrix((vals, (rows, cols)), shape=(len(nodes),) * 2).tocsr()
    return dijkstra(m, indices=ix[a])[ix[b]]


def test_weight_length_reproduces_shortest_path(case):
    U, index = case["U"], case["index"]
    for a, b in _random_pairs(U, 25, seed=1):
        stats, _, _, route = get_route(U, index, _lonlat(U, a), _lonlat(U, b), "length")
        assert stats["length"] == pytest.approx(_csgraph_shortest_length(U, a, b), rel=1e-9)
        assert route[0] == a and route[-1] == b


def test_cool_route_is_never_hotter_than_shortest(case):
    U, index = case["U"], case["index"]
    n_cooler = 0
    for a, b in _random_pairs(U, 40, seed=2):
        s_ll, e_ll = _lonlat(U, a), _lonlat(U, b)
        cool, _, _, rc = get_route(U, index, s_ll, e_ll, "cost")
        short, _, _, rs = get_route(U, index, s_ll, e_ll, "length")
        # the cool route minimises total heat (cost) and the short route minimises length ...
        cost_c = sum(min(d["cost"] for d in U.get_edge_data(x, y).values()) for x, y in zip(rc[:-1], rc[1:]))
        cost_s = sum(min(d["cost"] for d in U.get_edge_data(x, y).values()) for x, y in zip(rs[:-1], rs[1:]))
        assert cost_c <= cost_s + 1e-9
        assert cool["length"] >= short["length"] - 1e-9
        # ... which implies a lower (published) average MRT
        assert cool["average_mrt"] <= short["average_mrt"] + 1e-9
        n_cooler += cool["average_mrt"] < short["average_mrt"] - 0.01
    assert n_cooler > 10      # the method actually finds cooler alternatives on this campus


def test_route_lengths_consistent(case):
    U, index = case["U"], case["index"]
    for a, b in _random_pairs(U, 15, seed=3):
        for w in ("length", "cost"):
            stats, gj, mrt_hops, route = get_route(U, index, _lonlat(U, a), _lonlat(U, b), w)
            hop_len = sum(min(d["length"] for d in U.get_edge_data(x, y).values()) for x, y in zip(route[:-1], route[1:])) \
                if w == "length" else stats["length"]
            assert stats["length"] == pytest.approx(hop_len, rel=1e-9)
            (lo1, la1), (lo2, la2) = gj["coordinates"][0], gj["coordinates"][-1]
            straight = math.hypot((lo2 - lo1) * 111320 * math.cos(math.radians(la1)), (la2 - la1) * 110574)
            assert stats["length"] >= 0.98 * straight       # a path is never shorter than the straight line
            assert len(mrt_hops) == len(route) - 1


def test_blend_endpoints_match_published_routes(case):
    U, index = case["U"], case["index"]
    scale = graph_mrt_scale(U)
    for a, b in _random_pairs(U, 15, seed=4):
        s_ll, e_ll = _lonlat(U, a), _lonlat(U, b)
        short, _, _, _ = get_route(U, index, s_ll, e_ll, "length")
        cool, _, _, r_cool = get_route(U, index, s_ll, e_ll, "cost")
        b0, _, _, _ = get_route(U, index, s_ll, e_ll, blended_weight(scale, 0.0))
        b1, _, _, r1 = get_route(U, index, s_ll, e_ll, blended_weight(scale, 1.0))
        assert b0["length"] == pytest.approx(short["length"], rel=1e-9)
        assert b1["average_mrt"] == pytest.approx(cool["average_mrt"], rel=1e-9)
        mid, *_ = get_route(U, index, s_ll, e_ll, blended_weight(scale, 0.5))
        assert short["length"] - 1e-9 <= mid["length"] <= cool["length"] + 1e-9


def test_nearest_node_matches_brute_force(case):
    U, index = case["U"], case["index"]
    rng = random.Random(5)
    nodes = sorted(U.nodes)
    for _ in range(40):
        n = rng.choice(nodes)
        lon, lat = _lonlat(U, n)
        lon += rng.uniform(-4e-4, 4e-4)
        lat += rng.uniform(-4e-4, 4e-4)
        x, y = index.transformer.transform(lon, lat)
        brute = min(nodes, key=lambda m: (U.nodes[m]["x"] - x) ** 2 + (U.nodes[m]["y"] - y) ** 2)
        assert index.nearest(lon, lat) == brute


def test_deterministic(case):
    raster = case["raster"]
    G2 = make_walking_network_graph(raster, GPKG)
    a = sorted((u, v, k, d["cost"], d["mrt"]) for u, v, k, d in case["Gd"].edges(keys=True, data=True))
    b = sorted((u, v, k, d["cost"], d["mrt"]) for u, v, k, d in G2.edges(keys=True, data=True))
    assert a == b
    U2, idx2 = to_undirected(G2), NodeIndex(to_undirected(G2))
    for x, y in _random_pairs(U2, 5, seed=6):
        r1 = get_route(case["U"], case["index"], _lonlat(U2, x), _lonlat(U2, y), "cost")[3]
        r2 = get_route(U2, idx2, _lonlat(U2, x), _lonlat(U2, y), "cost")[3]
        assert r1 == r2


def test_golden_routes_reproduced():
    """Regression: the committed golden routes (also the target of the website's JS router) are reproduced."""
    golden = json.loads((DATA / "golden_routes.json").read_text())
    built = {}
    for s in STAMPS:
        raster = MrtRaster.from_geotiff(DATA / f"mrt_{s}.tif")
        U = to_undirected(make_walking_network_graph(raster, GPKG))
        built[s] = (U, NodeIndex(U))
        assert graph_mrt_scale(U) == pytest.approx(golden["scale"][s], rel=1e-12)
    for pair in golden["pairs"]:
        for s, per in pair["stamps"].items():
            U, index = built[s]
            weights = {"length": "length", "cost": "cost", "blend": blended_weight(golden["scale"][s], golden["blend_w"])}
            for name, w in weights.items():
                stats, _, _, route = get_route(U, index, pair["start"], pair["end"], w)
                assert route == per[name]["route"]
                assert stats["length"] == pytest.approx(per[name]["length"], rel=1e-9)
                assert stats["average_mrt"] == pytest.approx(per[name]["average_mrt"], rel=1e-9)


# ---------------------------------------------------------------- raster
def test_loader_applies_scale():
    with rasterio.open(DATA / f"mrt_{STAMPS[0]}.tif") as src:
        raw = src.read(1)
    r = MrtRaster.from_geotiff(DATA / f"mrt_{STAMPS[0]}.tif")
    assert np.allclose(r.data, raw * 0.01)
    assert 10 < r.data.mean() < 80


def test_colour_ramp_matches_legend():
    stops = np.array([[25, 30, 35, 40, 45, 50, 55, 60, 65, 70, 75, 80]], dtype=float)
    rgba = mrt_to_rgba(stops)[0]
    for i, hexcol in enumerate(MRT_COLORS_HEX):
        assert tuple(rgba[i, :3]) == tuple(int(hexcol[j:j + 2], 16) for j in (1, 3, 5))
        assert rgba[i, 3] == 255
    edge = mrt_to_rgba(np.array([[0.0, -5.0, np.nan, 10.0, 200.0]]))[0]
    assert list(edge[:3, 3]) == [0, 0, 0]                       # non-positive / NaN -> transparent
    assert tuple(edge[3, :3]) == tuple(rgba[0, :3])             # clipped to the 25 degC colour
    assert tuple(edge[4, :3]) == tuple(rgba[-1, :3])            # clipped to the 80 degC colour
