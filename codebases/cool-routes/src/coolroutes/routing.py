"""Cool-vs-shortest routing on the MRT-annotated walking network.

Curated from the SHaDE Lab Cool Routes server (``server/routing.py`` and the
``/api/route`` handler in ``server/server.py``).  Behaviour is unchanged:

* the network is made undirected (parallel edges are kept, the cheapest one is used),
* origin / destination are snapped to the nearest network node (in the projected CRS),
* the **cool route** is Dijkstra on edge attribute ``cost`` (sum of MRT samples
  along the edge), the **shortest route** is Dijkstra on ``length``,
* statistics are accumulated over the cheapest parallel edge of every hop.

Two things are additions, not part of the published tool, and are marked as such:

* ``corrected_mean_mrt`` -- the length-weighted mean MRT of the route (this is the
  line that is commented out in the original ``calculate_statistics``), and
* ``blended_weight`` -- a distance/heat trade-off used by the website demo.
"""
from __future__ import annotations

import networkx as nx
import numpy as np
from pyproj import Transformer
from scipy.spatial import cKDTree


# ------------------------------------------------------------------ graph prep
def to_undirected(G: nx.MultiDiGraph) -> nx.MultiGraph:
    """Undirected multigraph; the reverse copy of a two-way edge is dropped.

    (osmnx ``get_undirected`` keeps parallel edges only when they differ; two-way
    streets are stored once per direction, with identical length.)
    """
    H = nx.MultiGraph(crs=G.graph.get("crs"))
    H.add_nodes_from(G.nodes(data=True))
    seen = set()
    for u, v, k, d in G.edges(keys=True, data=True):
        sig = (frozenset((u, v)), round(float(d["length"]), 3))
        if sig in seen:
            continue
        seen.add(sig)
        H.add_edge(u, v, **d)
    return H


class NodeIndex:
    """Nearest-node lookup in projected coordinates (osmnx ``nearest_nodes``)."""

    def __init__(self, G: nx.Graph):
        self.nodes = list(G.nodes)
        self.tree = cKDTree(np.array([[G.nodes[n]["x"], G.nodes[n]["y"]] for n in self.nodes]))
        self.transformer = Transformer.from_crs("EPSG:4326", G.graph["crs"], always_xy=True)

    def nearest(self, lon: float, lat: float):
        x, y = self.transformer.transform(lon, lat)
        _, i = self.tree.query([x, y])
        return self.nodes[int(i)]


# ------------------------------------------------------------------ weights
def find_the_used_edge(edge_dict, weight):
    """Cheapest of several parallel edges for ``weight`` (name or callable on attrs)."""
    wfun = (lambda d: d[weight]) if isinstance(weight, str) else weight
    idx, value = -1, 1e18
    for key, attrs in edge_dict.items():
        w = wfun(attrs)
        if value > w:
            idx, value = key, w
    return edge_dict[idx]


def graph_mrt_scale(G: nx.Graph) -> float:
    """Graph-wide heat per metre, sum(cost) / sum(length); makes ``cost`` comparable to ``length``."""
    return sum(d["cost"] for *_, d in G.edges(data=True)) / sum(d["length"] for *_, d in G.edges(data=True))


def blended_weight(scale: float, w: float):
    """DEMO EXTENSION (not in the published tool).

    ``(1 - w) * length + w * cost / scale``.  w = 0 gives the shortest route and
    w = 1 the published cool route (``cost / scale`` is a constant multiple of ``cost``);
    values in between trade distance for lower heat exposure.
    """
    return lambda d: (1.0 - w) * d["length"] + w * d["cost"] / scale


def _nx_weight(G, weight):
    if isinstance(weight, str):
        return weight
    # networkx hands the dict of parallel edges to a callable weight on multigraphs
    return lambda u, v, edict: min(weight(d) for d in edict.values())


# ------------------------------------------------------------------ routes
def shortest_route(G: nx.Graph, orig, dest, weight="cost"):
    return nx.shortest_path(G, orig, dest, weight=_nx_weight(G, weight), method="dijkstra")


def calculate_statistics(G: nx.Graph, route, weight="cost") -> dict:
    """``length`` (m), ``mrt`` (sum of edge means), ``average_mrt`` as in the published tool,
    plus the corrected length-weighted mean (``corrected_mean_mrt``)."""
    length = mrt = weighted_sum = heat_len = 0.0
    for a, b in zip(route[:-1], route[1:]):
        edge = find_the_used_edge(G.get_edge_data(a, b), weight)
        length += float(edge["length"])
        mrt += float(edge["mrt"])
        weighted_sum += float(edge["cost"])
        heat_len += float(edge["mrt"]) * float(edge["length"])
    return {
        "length": length,
        "mrt": mrt,
        "average_mrt": weighted_sum / length if length else 0.0,
        "corrected_mean_mrt": heat_len / length if length else 0.0,
    }


def route_geojson(G: nx.Graph, route, weight="cost"):
    """LineString (lon, lat) and the per-hop MRT list, as returned by the tool's API."""
    coords = [(G.nodes[n]["lon"], G.nodes[n]["lat"]) for n in route]
    mrt = [float(find_the_used_edge(G.get_edge_data(a, b), weight)["mrt"])
           for a, b in zip(route[:-1], route[1:])]
    return {"type": "LineString", "coordinates": coords}, mrt


def get_route(G: nx.Graph, index: NodeIndex, start, stop, weight="cost"):
    """``start`` / ``stop`` are ``(lon, lat)``.  Returns ``(stats, geojson, mrt_per_hop, route)``."""
    orig, dest = index.nearest(*start), index.nearest(*stop)
    route = shortest_route(G, orig, dest, weight)
    stats = calculate_statistics(G, route, weight)
    gj, mrt = route_geojson(G, route, weight)
    return stats, gj, mrt, route


def compare_routes(G: nx.Graph, index: NodeIndex, start, stop):
    """What ``/api/route`` returns: the cool route (``cost``) and the shortest route (``length``)."""
    cool = get_route(G, index, start, stop, "cost")
    short = get_route(G, index, start, stop, "length")
    return {"mrt_route": cool, "shortest_route": short}
