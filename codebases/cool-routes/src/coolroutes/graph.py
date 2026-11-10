"""Walking network + per-edge MRT.

Curated from ``solweig_server/form_graphml.py`` (``readFromGeopackage`` and
``make_walking_network_graph``) of the SHaDE Lab Cool Routes server.

The published code builds the graph with OSMnx.  This release performs the same
steps with ``networkx`` / ``geopandas`` / ``shapely`` / ``pyproj`` only, so it is
easy to install.  The logic is unchanged:

1. read the pedestrian network (GeoPackage layers ``nodes`` and ``edges``),
2. project nodes and edge geometries into the CRS of the MRT raster
   (osmnx ``project_graph``),
3. for every edge, sample the raster once per CRS unit along the edge geometry
   (``num_samples = int(length * granularity)``, at least 1, ``num_samples + 1``
   samples at ``alpha = i / num_samples``), clamp negative values to 0 and store

   * ``mrt``  = total / (num_samples + 1)   (mean MRT along the edge, degC)
   * ``cost`` = total                         (sum of the samples, degC x samples)
"""
from __future__ import annotations

import geopandas as gpd
import networkx as nx
from pyproj import Transformer
from shapely.geometry import LineString
from shapely.ops import linemerge, transform as shp_transform

from .raster import MrtRaster


def _as_linestring(geom):
    """The network file stores each edge as a single-part MultiLineString; use the LineString."""
    return linemerge(geom) if geom.geom_type == "MultiLineString" else geom


def read_walk_graph(gpkg_path) -> nx.MultiDiGraph:
    """Read the walking network GeoPackage into a directed multigraph (WGS84).

    Node attributes: ``x`` (lon), ``y`` (lat), ``lon``, ``lat``.
    Edge attributes: everything in the ``edges`` layer, incl. ``length`` (m, geodesic
    length stored with the network) and ``geometry``.
    """
    nodes = gpd.read_file(gpkg_path, layer="nodes")
    edges = gpd.read_file(gpkg_path, layer="edges")
    G = nx.MultiDiGraph(crs="EPSG:4326")
    for rec in nodes.drop(columns="geometry").to_dict("records"):
        osmid = int(rec.pop("osmid"))
        G.add_node(osmid, lon=rec["x"], lat=rec["y"], **rec)
    for rec, geom in zip(edges.drop(columns="geometry").to_dict("records"), edges.geometry):
        u, v, key = int(rec.pop("u")), int(rec.pop("v")), int(rec.pop("key_"))
        rec["length"] = float(rec["length"])
        G.add_edge(u, v, key=key, geometry=_as_linestring(geom), **rec)
    return G


def project_graph(G: nx.MultiDiGraph, to_crs) -> nx.MultiDiGraph:
    """Project node coordinates and edge geometries (osmnx ``project_graph``)."""
    tr = Transformer.from_crs("EPSG:4326", to_crs, always_xy=True)
    H = nx.MultiDiGraph(crs=str(to_crs))
    for n, d in G.nodes(data=True):
        d = dict(d)
        d["x"], d["y"] = tr.transform(d["lon"], d["lat"])
        H.add_node(n, **d)
    for u, v, k, d in G.edges(keys=True, data=True):
        d = dict(d)
        if d.get("geometry") is not None:
            d["geometry"] = shp_transform(tr.transform, d["geometry"])
        H.add_edge(u, v, key=k, **d)
    return H


def edge_mrt(G: nx.MultiDiGraph, u, v, data, raster: MrtRaster, granularity: float = 1):
    """Return ``(mean_mrt, total_mrt, num_samples)`` for one projected edge."""
    geom = data.get("geometry")
    if geom is not None:
        line = LineString(geom)
        num_samples = int(line.length * granularity)
        num_samples = num_samples if num_samples > 0 else 1
        total = 0.0
        for i in range(num_samples + 1):
            p = line.interpolate(i / num_samples, normalized=True)
            total += max(raster.sample(p.x, p.y), 0)
    else:  # no geometry: straight line between the end nodes
        ux, uy = G.nodes[u]["x"], G.nodes[u]["y"]
        vx, vy = G.nodes[v]["x"], G.nodes[v]["y"]
        length = ((ux - vx) ** 2 + (uy - vy) ** 2) ** 0.5
        num_samples = int(length * granularity)
        num_samples = num_samples if num_samples > 0 else 1
        total = 0.0
        for i in range(num_samples + 1):
            a = i / num_samples
            total += max(raster.sample(ux + a * (vx - ux), uy + a * (vy - uy)), 0)
    return total / (num_samples + 1), total, num_samples


def make_walking_network_graph(raster: MrtRaster, gpkg_path, granularity: float = 1) -> nx.MultiDiGraph:
    """Annotate every edge of the walking network with ``mrt`` and ``cost`` for one raster."""
    G = project_graph(read_walk_graph(gpkg_path), raster.crs)
    for u, v, data in G.edges(data=True):
        mean, total, _ = edge_mrt(G, u, v, data, raster, granularity)
        data["mrt"] = float(mean)
        data["cost"] = float(total)
    return G
