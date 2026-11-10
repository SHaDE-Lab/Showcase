"""
RELEASE NOTES
--------------------------------------
Methodology is unchanged from the SHaDE Lab VisionMRT code. Changes made for this release only:
  * removed the Windows-only mouse helper, the interactive FPS viewer and the desktop CLI entry point
    (the batch workflow is driven by pipeline.py instead);
  * colour imagery is optional: it only paints vertex colours of the preview mesh and is never read by the
    shadow rays, so sites may ship segmentation + depth only (see _load_color).
"""
"""
Fast Cubemap 3D Reconstruction & Shadow Computation (v5)
=========================================================
Matches the JavaScript reference implementation:
- Inverse perspective projection (90 FOV PerspectiveCamera)
- Axis-angle rotation per face direction
- Vertex-to-sun shadow rays with surface offset
- FPS camera with ground-plane WASD movement
- Tree shadows rendered as dark green (v5)

Author: Pouya (SHaDE Lab, ASU)
"""

import os
import numpy as np
from PIL import Image
import open3d as o3d
import pvlib
import pandas as pd
import pytz
from datetime import datetime, timedelta
from tqdm import tqdm
import glob
import time as timemod

# ============================================================================
# CONFIGURATION
# ============================================================================
MOVE_SPEED = 0.5        # WASD movement speed
LOOK_SPEED = 0.04       # Arrow key rotation speed (radians per press)
VIS_DOWNSAMPLE = 2      # Downsample factor for visualization
SUN_DISTANCE = 1000.0

SHADOW_REGULAR = 0   # black  — shadowed (default/intuitive)
SHADOW_SUNLIT  = 1   # white  — sunlit
SHADOW_TREE    = 2   # dark green [20,80,20]
SHADOW_SAIL    = 3   # dark blue [0,0,100]

TREE_SHADOW_RGB = np.array([20, 80, 20], dtype=np.uint8)
SAIL_SHADOW_COLOR = np.array([0, 0, 100], dtype=np.uint8)

def decode_shadow_rgb_to_type(img_rgb: np.ndarray) -> np.ndarray:
    """
    Convert an RGB shadow map (H,W,3) from shadow_computation_v5
    into a shadow_type array (H,W) uint8 with values 0/1/2.

    Works whether the input comes from in-memory pyshadow_execute()
    or loaded from a saved PNG via PIL.
    """
    out = np.full(img_rgb.shape[:2], SHADOW_SUNLIT, dtype=np.uint8)   # default = sunlit
    out[np.all(img_rgb == [0, 0, 0], axis=-1)]       = SHADOW_REGULAR # black → shadowed
    out[np.all(img_rgb == TREE_SHADOW_RGB, axis=-1)] = SHADOW_TREE    # green → tree
    out[np.all(img_rgb == SAIL_SHADOW_COLOR, axis=-1)] = SHADOW_SAIL  # cyan → shade-sail
    return out

# ============================================================================
# PERSPECTIVE PROJECTION (matching THREE.js PerspectiveCamera)
# ============================================================================

def _build_inverse_projection(fov_deg=90, aspect=1.0, near=0.1, far=1500.0):
    f = 1.0 / np.tan(np.radians(fov_deg) / 2.0)

    P = np.array([
        [f / aspect, 0.0, 0.0,                             0.0],
        [0.0,        f,   0.0,                             0.0],
        [0.0,        0.0, -(far + near) / (far - near),   -2.0 * far * near / (far - near)],
        [0.0,        0.0, -1.0,                            0.0],
    ], dtype=np.float64)

    return np.linalg.inv(P)


INV_PROJ = _build_inverse_projection(90, 1.0, 0.1, 1000.0)


# ============================================================================
# FACE ROTATION MATRICES
# ============================================================================

def _rotation_matrix_y(angle_deg):
    a = np.radians(angle_deg)
    c, s = np.cos(a), np.sin(a)
    return np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]])

def _rotation_matrix_x(angle_deg):
    a = np.radians(angle_deg)
    c, s = np.cos(a), np.sin(a)
    return np.array([[1, 0, 0], [0, c, -s], [0, s, c]])

FACE_ROTATIONS = {
    "North": _rotation_matrix_y(0),
    "South": _rotation_matrix_y(180),
    "West":  _rotation_matrix_y(90),
    "East":  _rotation_matrix_y(270),
    "Down":  _rotation_matrix_x(270),
    "Up":    _rotation_matrix_x(90),
}

DIRECTION_SUFFIX_MAP = {
    "North": "0_0",
    "South": "180_0",
    "East":  "90_0",
    "West":  "270_0",
    "Up":    "0_90",
    "Down":  "0_270",
}

FACE_ORDER = ["North", "South", "East", "West", "Down", "Up"]

# ← CHANGED: added TREE_COLOR_RGBA and TREE_SHADOW_COLOR
# Sky color matches segmentation hmap[1] = [0, 0, 255]
SKY_COLOR_RGBA  = np.array([0,   0,   255, 255], dtype=np.uint8)
# Tree color matches segmentation hmap[2] = [0, 255, 0]
TREE_COLOR_RGBA = np.array([0, 255,     0, 255], dtype=np.uint8)
# Output color for tree-cast shadows in shadow maps
TREE_SHADOW_COLOR = np.array([20, 80, 20], dtype=np.uint8)
# Output color for shade-sail shadows in shadow maps
SHADE_SAIL_COLOR_RGBA = np.array([0, 255, 255, 255], dtype=np.uint8)


# ============================================================================
# CUBEMAP EDGE ADJACENCY (for stitching)
# ============================================================================

EDGE_ADJACENCY = [
    ("North", "right",  "East",  "left",   False),
    ("East",  "right",  "South", "left",   False),
    ("South", "right",  "West",  "left",   False),
    ("West",  "right",  "North", "left",   False),
    ("North", "top",    "Up",    "bottom", False),
    ("East",  "top",    "Up",    "right",  True),
    ("South", "top",    "Up",    "top",    True),
    ("West",  "top",    "Up",    "left",   False),
    ("North", "bottom", "Down",  "top",    False),
    ("East",  "bottom", "Down",  "right",  False),
    ("South", "bottom", "Down",  "bottom", True),
    ("West",  "bottom", "Down",  "left",   True),
]


# ============================================================================
# VECTORIZED 3D RECONSTRUCTION
# ============================================================================


def _load_color(color_path, like):
    """Colour image (H,W,3 uint8) or, when no colour image is shipped, a neutral grey of the same size.
    Colour only paints vertex colours of the preview mesh; shadow rays never read it. [release change]"""
    if color_path is None:
        return np.full(like.shape[:2] + (3,), 128, dtype=np.uint8)
    return np.array(Image.open(color_path).convert("RGB"))

def _load_color_ds(color_path, positions_ds, downsample):
    """Colour image already reduced by `downsample` to match `positions_ds` (H,W,3). [release change]"""
    if color_path is None:
        return _load_color(None, positions_ds)
    img = _load_color(color_path, positions_ds)
    return img[::downsample, ::downsample] if downsample > 1 else img


def reconstruct_face(color_path, depth_path, seg_path, face_name,
                     downsample=1, bottom_depth_override=-0.65):
    """
    Reconstruct a cubemap face using inverse perspective projection.

    Returns:
        mesh, pixel_coords, valid_mask, tree_mask, all_positions, (H,W), downsample
        # ← CHANGED: now also returns tree_mask (H,W bool)
    """
    depth_img = np.array(Image.open(depth_path).convert("RGB")).astype(np.float64)
    color_img = _load_color(color_path, depth_img)
    seg_img   = np.array(Image.open(seg_path).convert("RGBA"))

    if downsample > 1:
        s = downsample
        color_img = color_img[::s, ::s]
        depth_img = depth_img[::s, ::s]
        seg_img   = seg_img[::s, ::s]

    H, W = depth_img.shape[:2]

    # # ← CHANGED: detect tree pixels in addition to sky
    # sky_mask  = np.all(seg_img == SKY_COLOR_RGBA,  axis=-1)
    # tree_mask = np.all(seg_img == TREE_COLOR_RGBA,  axis=-1)
    # valid_mask = ~sky_mask  # trees remain valid geometry — they cast shadows

    sky_mask = np.all(seg_img == SKY_COLOR_RGBA, axis=-1)

    # Only allow tree detection on the UP face
    if face_name == "Up":
        tree_mask = np.all(seg_img == TREE_COLOR_RGBA, axis=-1)
        sail_mask = np.all(seg_img == SHADE_SAIL_COLOR_RGBA, axis=-1)
    else:
        tree_mask = np.zeros_like(sky_mask, dtype=bool)
        sail_mask = np.zeros_like(sky_mask, dtype=bool)

    # # # allow tree detection on Up and Lateral
    # if face_name == "Down":
    #     tree_mask = np.zeros_like(sky_mask, dtype=bool)
    # else:
    #     tree_mask = np.all(seg_img == TREE_COLOR_RGBA, axis=-1) 

    valid_mask = ~sky_mask

    grey = depth_img.mean(axis=-1) / 255.0
    depth_ndc = grey * 2.0 - 1.0

    if face_name == "Down":
        depth_ndc[:] = bottom_depth_override

    u_idx = np.arange(W, dtype=np.float64)
    v_idx = np.arange(H, dtype=np.float64)
    uu, vv = np.meshgrid(u_idx, v_idx)

    texX = (uu / W) * 2.0 - 1.0
    texY = (vv / H) * 2.0 - 1.0

    ones = np.ones((H, W), dtype=np.float64)
    clip = np.stack([texX, -texY, depth_ndc, ones], axis=-1)

    view = np.einsum('ij,...j->...i', INV_PROJ, clip)

    w = view[..., 3:4]
    view = view / np.where(np.abs(w) > 1e-10, w, 1e-10)

    positions_view = view[..., :3]

    R = FACE_ROTATIONS[face_name]
    all_positions = np.einsum('ij,...j->...i', R, positions_view)

    SCENE_SCALE = 100.0
    all_positions *= SCENE_SCALE

    vertices = all_positions[valid_mask]
    colors = color_img[valid_mask].astype(np.float64) / 255.0

    pixel_coords = np.stack([uu[valid_mask].astype(np.int32),
                             vv[valid_mask].astype(np.int32)], axis=-1)

    index_map = np.full((H, W), -1, dtype=np.int32)
    index_map[valid_mask] = np.arange(valid_mask.sum(), dtype=np.int32)

    faces_front = _generate_faces(valid_mask, index_map)
    faces_back = faces_front[:, ::-1].copy()
    faces = np.concatenate([faces_front, faces_back], axis=0)

    normals = _compute_normals(all_positions, valid_mask)

    mesh = o3d.geometry.TriangleMesh()
    mesh.vertices       = o3d.utility.Vector3dVector(vertices)
    mesh.vertex_colors  = o3d.utility.Vector3dVector(colors)
    mesh.vertex_normals = o3d.utility.Vector3dVector(normals)
    mesh.triangles      = o3d.utility.Vector3iVector(faces)

    # ← CHANGED: return tree_mask as new 4th value
    return mesh, pixel_coords, valid_mask, tree_mask, sail_mask, all_positions, (H, W), downsample


def _generate_faces(valid_mask, index_map):
    H, W = valid_mask.shape
    quad_valid = (valid_mask[:-1, :-1] & valid_mask[:-1, 1:] &
                  valid_mask[1:, :-1]  & valid_mask[1:, 1:])
    qy, qx = np.nonzero(quad_valid)
    if len(qy) == 0:
        return np.zeros((0, 3), dtype=np.int32)

    tl = index_map[qy, qx]
    tr = index_map[qy, qx + 1]
    bl = index_map[qy + 1, qx]
    br = index_map[qy + 1, qx + 1]

    tri1 = np.stack([tl, tr, br], axis=-1)
    tri2 = np.stack([tl, br, bl], axis=-1)
    return np.concatenate([tri1, tri2], axis=0)


def _compute_normals(all_positions, valid_mask):
    dy = np.gradient(all_positions, axis=0)
    dx = np.gradient(all_positions, axis=1)
    normals = np.cross(dy, dx)
    norms = np.linalg.norm(normals, axis=-1, keepdims=True)
    normals /= np.maximum(norms, 1e-8)
    return normals[valid_mask]


# ============================================================================
# ← CHANGED: new helper — build a sub-mesh from an arbitrary pixel mask
# ============================================================================

def _build_submesh(all_positions, submask, color_path, H, W, downsample=1):
    """
    Build a mesh from a subset of valid pixels (e.g. only tree pixels).
    Used by build_shadow_scene_once to register tree and non-tree geometry
    separately so cast_shadows can identify which geometry type was hit.
    """
    color_img = _load_color_ds(color_path, all_positions, downsample)

    vertices = all_positions[submask]
    if len(vertices) == 0:
        return o3d.geometry.TriangleMesh()

    colors  = color_img[submask].astype(np.float64) / 255.0
    normals = _compute_normals(all_positions, submask)

    index_map = np.full((H, W), -1, dtype=np.int32)
    index_map[submask] = np.arange(submask.sum(), dtype=np.int32)

    faces_front = _generate_faces(submask, index_map)
    if len(faces_front) == 0:
        faces = np.zeros((0, 3), dtype=np.int32)
    else:
        faces_back = faces_front[:, ::-1].copy()
        faces = np.concatenate([faces_front, faces_back], axis=0)

    m = o3d.geometry.TriangleMesh()
    m.vertices       = o3d.utility.Vector3dVector(vertices)
    m.vertex_colors  = o3d.utility.Vector3dVector(colors)
    m.vertex_normals = o3d.utility.Vector3dVector(normals)
    m.triangles      = o3d.utility.Vector3iVector(faces)
    return m

def _rebuild_mesh_from_positions(all_positions, valid_mask, color_img):
    """Rebuild a mesh after all_positions has been modified (e.g. after reconciliation)."""
    H, W = all_positions.shape[:2]
    vertices = all_positions[valid_mask]
    colors   = color_img[valid_mask].astype(np.float64) / 255.0

    index_map = np.full((H, W), -1, dtype=np.int32)
    index_map[valid_mask] = np.arange(valid_mask.sum(), dtype=np.int32)

    faces_front = _generate_faces(valid_mask, index_map)
    if len(faces_front) == 0:
        faces = np.zeros((0, 3), dtype=np.int32)
    else:
        faces_back = faces_front[:, ::-1].copy()
        faces = np.concatenate([faces_front, faces_back], axis=0)

    normals = _compute_normals(all_positions, valid_mask)

    mesh = o3d.geometry.TriangleMesh()
    mesh.vertices      = o3d.utility.Vector3dVector(vertices)
    mesh.vertex_colors = o3d.utility.Vector3dVector(colors)
    mesh.vertex_normals = o3d.utility.Vector3dVector(normals)
    mesh.triangles     = o3d.utility.Vector3iVector(faces)
    return mesh

# ============================================================================
# EDGE STITCHING — double-sided, vectorized
# ============================================================================

def _get_edge_pixels(edge, H, W):
    if edge == "left":
        return np.arange(H), np.zeros(H, dtype=np.int32)
    elif edge == "right":
        return np.arange(H), np.full(H, W - 1, dtype=np.int32)
    elif edge == "top":
        return np.zeros(W, dtype=np.int32), np.arange(W)
    elif edge == "bottom":
        return np.full(W, H - 1, dtype=np.int32), np.arange(W)
    raise ValueError(f"Unknown edge: {edge}")


def _get_edge_pixels_inward(edge, H, W, band=0):
    """Like _get_edge_pixels but `band` rows inward from the edge."""
    if edge == "left":
        return np.arange(H), np.full(H, band, dtype=np.int32)
    elif edge == "right":
        return np.arange(H), np.full(H, W - 1 - band, dtype=np.int32)
    elif edge == "top":
        return np.full(W, band, dtype=np.int32), np.arange(W)
    elif edge == "bottom":
        return np.full(W, H - 1 - band, dtype=np.int32), np.arange(W)
    raise ValueError(f"Unknown edge: {edge}")


def reconcile_edge_positions(face_info, n_blend_rows=5):
    """
    For each adjacent face pair, blend edge vertices toward each other
    so faces meet in 3D without needing stitching geometry.

    n_blend_rows: rows inward from edge to taper the blend.
                  Row 0 (the actual edge) gets fully averaged.
                  Each subsequent row gets less correction.
    """
    for (face_a, edge_a, face_b, edge_b, is_reversed) in EDGE_ADJACENCY:
        if face_a not in face_info or face_b not in face_info:
            continue

        info_a = face_info[face_a]
        info_b = face_info[face_b]
        H_a, W_a = info_a["shape"]
        H_b, W_b = info_b["shape"]

        for band in range(n_blend_rows):
            # Weight: 1.0 (full average) at edge, tapering to 0 inward
            w = (1.0 - band / n_blend_rows) ** 2

            rows_a, cols_a = _get_edge_pixels_inward(edge_a, H_a, W_a, band)
            rows_b, cols_b = _get_edge_pixels_inward(edge_b, H_b, W_b, band)

            if is_reversed:
                rows_b = rows_b[::-1].copy()
                cols_b = cols_b[::-1].copy()

            la, lb = len(rows_a), len(rows_b)
            if la != lb:
                n = min(la, lb)
                ia = np.linspace(0, la - 1, n).astype(int)
                ib = np.linspace(0, lb - 1, n).astype(int)
                rows_a, cols_a = rows_a[ia], cols_a[ia]
                rows_b, cols_b = rows_b[ib], cols_b[ib]

            va   = info_a["valid_mask"][rows_a, cols_a]
            vb   = info_b["valid_mask"][rows_b, cols_b]
            both = va & vb
            if not both.any():
                continue

            pos_a = info_a["all_positions"][rows_a, cols_a].copy()
            pos_b = info_b["all_positions"][rows_b, cols_b].copy()

            # Midpoint between the two faces at this band
            mid = (pos_a + pos_b) * 0.5

            # Blend each face's edge toward the midpoint by weight w
            info_a["all_positions"][rows_a[both], cols_a[both]] = (
                pos_a[both] * (1 - w) + mid[both] * w
            )
            info_b["all_positions"][rows_b[both], cols_b[both]] = (
                pos_b[both] * (1 - w) + mid[both] * w
            )

def create_stitch_mesh(face_info):
    """Double-sided bridge triangles between adjacent cubemap edges."""
    all_verts = []
    all_tris = []
    vert_offset = 0

    for (face_a, edge_a, face_b, edge_b, is_reversed) in EDGE_ADJACENCY:
        if face_a not in face_info or face_b not in face_info:
            continue

        info_a, info_b = face_info[face_a], face_info[face_b]
        H_a, W_a = info_a["shape"]
        H_b, W_b = info_b["shape"]

        rows_a, cols_a = _get_edge_pixels(edge_a, H_a, W_a)
        rows_b, cols_b = _get_edge_pixels(edge_b, H_b, W_b)

        if is_reversed:
            rows_b = rows_b[::-1].copy()
            cols_b = cols_b[::-1].copy()

        la, lb = len(rows_a), len(rows_b)
        if la != lb:
            n = min(la, lb)
            ia = np.linspace(0, la - 1, n).astype(int)
            ib = np.linspace(0, lb - 1, n).astype(int)
            rows_a, cols_a = rows_a[ia], cols_a[ia]
            rows_b, cols_b = rows_b[ib], cols_b[ib]

        n_edge = len(rows_a)
        if n_edge < 2:
            continue

        pos_a = info_a["all_positions"][rows_a, cols_a].copy()
        pos_b = info_b["all_positions"][rows_b, cols_b].copy()
        va = info_a["valid_mask"][rows_a, cols_a].copy()
        vb = info_b["valid_mask"][rows_b, cols_b].copy()

        pos_a[~va & vb] = pos_b[~va & vb]; va[~va & vb] = True
        pos_b[va & ~vb] = pos_a[va & ~vb]; vb[va & ~vb] = True

        edge_verts = np.empty((n_edge * 2, 3), dtype=np.float64)
        edge_verts[0::2] = pos_a
        edge_verts[1::2] = pos_b

        both = va & vb
        ok = both[:-1] & both[1:]
        qi = np.nonzero(ok)[0]

        if len(qi) > 0:
            ai  = vert_offset + 2 * qi
            bi  = vert_offset + 2 * qi + 1
            ai1 = vert_offset + 2 * (qi + 1)
            bi1 = vert_offset + 2 * (qi + 1) + 1

            tris = np.concatenate([
                np.stack([ai, bi, bi1], axis=-1),
                np.stack([ai, bi1, ai1], axis=-1),
                np.stack([ai, bi1, bi], axis=-1),
                np.stack([ai, ai1, bi1], axis=-1),
            ], axis=0)
            all_tris.append(tris)

        all_verts.append(edge_verts)
        vert_offset += n_edge * 2

    if not all_verts or not all_tris:
        return None

    mesh = o3d.geometry.TriangleMesh()
    mesh.vertices = o3d.utility.Vector3dVector(np.vstack(all_verts))
    mesh.triangles = o3d.utility.Vector3iVector(np.vstack(all_tris))
    mesh.vertex_colors = o3d.utility.Vector3dVector(
        np.full((len(mesh.vertices), 3), 0.2))
    mesh.compute_vertex_normals()
    return mesh


# ============================================================================
# SCENE RECONSTRUCTION
# ============================================================================
def reconstruct_scene(image_pairs, downsample=1):
    meshes    = []
    face_data = []
    face_info = {}
    color_imgs = {}   # keep color images for rebuild

    for face_name in FACE_ORDER:
        paths = image_pairs.get(face_name)
        if paths is None or paths[1] is None:
            print(f"  [SKIP] {face_name}")
            continue

        t0 = timemod.time()
        mesh, pcoords, vmask, tree_mask, sail_mask, all_pos, shape, ds = reconstruct_face(
            *paths, face_name, downsample=downsample)
        dt = timemod.time() - t0

        # Store color image for later rebuild
        color_img = _load_color_ds(paths[0], all_pos, downsample)
        color_imgs[face_name] = color_img

        face_data.append((face_name, pcoords, vmask, shape, ds))
        face_info[face_name] = {
            "all_positions": all_pos, "valid_mask": vmask, "shape": shape}

    print("  Reconciling edge positions...")
    reconcile_edge_positions(face_info, n_blend_rows=8)

    print("  Rebuilding meshes after reconciliation...")
    for face_name, pcoords, vmask, shape, ds in face_data:
        info     = face_info[face_name]
        all_pos  = info["all_positions"]
        color_img = color_imgs[face_name]
        mesh = _rebuild_mesh_from_positions(all_pos, vmask, color_img)
        n_v = len(np.asarray(mesh.vertices))
        n_t = len(np.asarray(mesh.triangles))
        print(f"  {face_name:6s}: {n_v:,} verts, {n_t:,} tris")
        meshes.append(mesh)

    # No stitch needed — pass None
    return meshes, face_data, None

# ============================================================================
# SUN POSITIONS
# ============================================================================

def compute_sun_positions(lat, lon, start, end, freq="5min"):
    times = pd.date_range(start=start, end=end, freq=freq, tz="America/Phoenix")
    solpos = pvlib.solarposition.get_solarposition(times, lat, lon)

    zen = np.radians(solpos["apparent_zenith"].values)
    azi = np.radians(solpos["azimuth"].values)

    sx =  np.sin(azi) * np.sin(zen) * SUN_DISTANCE
    sy =  np.cos(zen) * SUN_DISTANCE
    sz = -np.cos(azi) * np.sin(zen) * SUN_DISTANCE

    sun_pos = np.stack([sx, sy, sz], axis=-1)
    above = solpos["apparent_elevation"].values > 0

    # SUN_SHIFT_SOUTH = 500.0   # adjust this value
    # sun_pos[:, 2] += SUN_SHIFT_SOUTH

    return sun_pos, times, above


def find_sun_at_time(times, sun_pos, target):
    if target.tzinfo is None:
        target = pd.Timestamp(target).tz_localize(times.tz)
    else:
        target = pd.Timestamp(target).tz_convert(times.tz)

    idx = times.get_indexer([target], method="nearest")[0]
    return sun_pos[idx], idx


# ============================================================================
# SHADOW COMPUTATION — vertex-to-sun rays with surface offset
# ============================================================================

# ← CHANGED: cast_shadows now returns shadow_type array instead of bool mask
#   0 = sunlit
#   1 = shadowed by non-tree geometry  (will become black)
#   2 = shadowed by tree geometry      (will become dark green)
def cast_shadows(scene, all_vertices, sun_position, tree_geom_ids=None, sail_geom_ids=None):
    """
    Cast rays FROM each vertex TOWARD the sun.

    Returns:
        shadow_type : uint8 array, length = len(all_vertices)
            0 = sunlit
            1 = shadowed by non-tree geometry
            2 = shadowed by tree geometry (dark green in output)
    """
    if tree_geom_ids is None:
        tree_geom_ids = set()
    if sail_geom_ids is None:
        sail_geom_ids = set()

    N = len(all_vertices)
    sun_pos = np.array(sun_position, dtype=np.float32)

    to_sun = sun_pos - all_vertices
    dist_to_sun = np.linalg.norm(to_sun, axis=1)
    to_sun_dir = to_sun / np.maximum(dist_to_sun[:, np.newaxis], 1e-8)

    inward = -all_vertices
    inward_norm = np.linalg.norm(inward, axis=1, keepdims=True)
    inward = inward / np.maximum(inward_norm, 1e-8)
    ray_origins = all_vertices + inward * 0.3

    rays = np.zeros((N, 6), dtype=np.float32)
    rays[:, :3] = ray_origins
    rays[:, 3:] = to_sun_dir

    hits     = scene.cast_rays(o3d.core.Tensor(rays, dtype=o3d.core.Dtype.Float32))
    t_hit    = hits["t_hit"].numpy()
    # ← CHANGED: also read geometry_ids to identify tree hits
    geom_ids = hits["geometry_ids"].numpy()

    in_shadow = (t_hit > 0) & (t_hit < dist_to_sun - 1.0)

    shadow_type = np.full(N, SHADOW_SUNLIT, dtype=np.uint8)

    tree_hit = np.isin(geom_ids, list(tree_geom_ids)) if tree_geom_ids else np.zeros(N, dtype=bool)
    sail_hit = np.isin(geom_ids, list(sail_geom_ids)) if sail_geom_ids else np.zeros(N, dtype=bool)

    shadow_type[in_shadow & ~tree_hit & ~sail_hit] = SHADOW_REGULAR
    shadow_type[in_shadow & tree_hit] = SHADOW_TREE
    shadow_type[in_shadow & sail_hit] = SHADOW_SAIL

    return shadow_type


# ← CHANGED: shadows_to_2d now takes shadow_type (uint8) instead of bool mask,
#   and produces RGB images instead of grayscale
def shadows_to_2d(shadow_type, face_data, vertex_counts):
    """
    Map per-vertex shadow_type back to 2D face images (RGB).

    Pixel values:
        [128, 128, 128] — sky (not part of geometry)
        [255, 255, 255] — sunlit surface
        [  0,   0,   0] — regular shadow (buildings, ground, etc.)
        [ 20,  80,  20] — tree shadow (TREE_SHADOW_COLOR)
    """
    images = {}
    idx = 0

    for i, (name, pcoords, vmask, (H, W), ds) in enumerate(face_data):

        # ← CHANGED: RGB image instead of grayscale
        img = np.full((H, W, 3), 128, dtype=np.uint8)   # sky = grey
        img[vmask] = [0, 0, 0]                           # default: shadowed (black) ← 0=SHADOW_REGULAR

        if i < len(vertex_counts):
            n  = vertex_counts[i]
            st = shadow_type[idx:idx + n]
            rows = pcoords[:n, 1]
            cols = pcoords[:n, 0]

            # Sunlit — white (value 1)
            mask_sun  = st == SHADOW_SUNLIT
            img[rows[mask_sun],  cols[mask_sun]]  = [255, 255, 255]

            # Tree shadow — dark green (value 2)
            mask_tree = st == SHADOW_TREE
            img[rows[mask_tree], cols[mask_tree]] = TREE_SHADOW_COLOR

            # Sail shadow — dark blue (value 3)
            mask_sail = st == SHADOW_SAIL
            img[rows[mask_sail], cols[mask_sail]] = SAIL_SHADOW_COLOR

            idx += n

        if ds > 1:
            img = np.array(
                Image.fromarray(img).resize((W * ds, H * ds), Image.NEAREST)
            )

        images[name] = img

    return images


# ← CHANGED: make_fully_shadowed now outputs RGB
def make_fully_shadowed(face_data):
    """Sun below horizon — all geometry pixels painted black, sky grey."""
    images = {}
    for name, _, vmask, (H, W), ds in face_data:
        img = np.full((H, W, 3), 128, dtype=np.uint8)   # sky = grey
        img[vmask] = [0, 0, 0]                           # all shadowed = black
        if ds > 1:
            img = np.array(Image.fromarray(img).resize((W * ds, H * ds), Image.NEAREST))
        images[name] = img
    return images


# ============================================================================
# EXECUTE SHADOWS FOR GIVEN TIMESTEPS
# ============================================================================

# ← CHANGED: added tree_geom_ids parameter, forwarded to cast_shadows
def execute_timestep(scene,
                     face_data,
                     vertex_counts,
                     all_vertices,
                     latitude,
                     longitude,
                     timesteps,
                     tree_geom_ids=None,
                     sail_geom_ids=None
                     ):
    """
    Compute shadow maps for a list of datetime timesteps.

    Returns:
        results = list of (datetime, shadow_images_dict)
        shadow_images_dict values are now RGB arrays (H, W, 3).
    """
    results = []

    times = pd.DatetimeIndex(timesteps)

    if times.tz is None:
        print("[INFO] Localizing naive timestamps to America/Phoenix")
        times = times.tz_localize("America/Phoenix")
    else:
        print(f"[INFO] Timestamps already timezone-aware: {times.tz}")
    # Timestamps arriving here should already be timezone-aware, localized by
    # the caller (main.py) to the site's actual resolved timezone — not
    # Phoenix. We don't force-convert to a fixed timezone since tz_convert
    # only changes display, not the underlying instant pvlib uses; the naive
    # fallback below is a last resort only, and intentionally does NOT assume
    # Phoenix, since that would silently misdate any non-Phoenix site.
    if times.tz is None:
        print("[WARN] Received naive (tz-unaware) timestamps in execute_timestep — "
              "solar position may be computed for the wrong instant. "
              "Caller should localize timesteps before calling this function.")
        times = times.tz_localize("UTC")
    else:
        print(f"[INFO] Timestamps already timezone-aware: {times.tz}")

    solpos = pvlib.solarposition.get_solarposition(times, latitude, longitude)

    zen = np.radians(solpos["apparent_zenith"].values)
    azi = np.radians(solpos["azimuth"].values)

    sx =  np.sin(azi) * np.sin(zen) * SUN_DISTANCE
    sy =  np.cos(zen) * SUN_DISTANCE
    sz = -np.cos(azi) * np.sin(zen) * SUN_DISTANCE

    sun_positions = np.stack([sx, sy, sz], axis=-1)
    # SUN_SHIFT_SOUTH = 500.0
    # sun_positions[:, 2] += SUN_SHIFT_SOUTH
    above = solpos["apparent_elevation"].values > 0

    print("First timestamp:", times[0])
    print("Solar elevation:", solpos["apparent_elevation"].iloc[0])

    for i, ts in enumerate(times):
        if above[i]:
            # ← CHANGED: cast_shadows now returns shadow_type, pass tree_geom_ids
            shadow_type = cast_shadows(
                scene,
                all_vertices,
                sun_positions[i].astype(np.float32),
                tree_geom_ids=tree_geom_ids,
                sail_geom_ids=sail_geom_ids
            )
            shadow_imgs = shadows_to_2d(shadow_type, face_data, vertex_counts)
        else:
            shadow_imgs = make_fully_shadowed(face_data)

        results.append((ts, shadow_imgs))

    return results


# ============================================================================
# BUILD SHADOW SCENE ONCE (Reusable)
# ============================================================================

# ← CHANGED: now builds tree and non-tree meshes separately per face so that
#   cast_shadows can identify tree hits via geometry_ids.
#   Returns tree_geom_ids (set of int) as new last return value.
def build_shadow_scene_once(image_pairs, downsample=1):
    """
    Build a RaycastingScene with tree and non-tree geometry registered
    as separate objects. This lets cast_shadows identify which type of
    geometry each shadow ray hit.

    Returns:
        scene, meshes, stitch, face_data, vertex_counts, all_vertices,
        tree_geom_ids  ← NEW
    """
    scene = o3d.t.geometry.RaycastingScene()

    meshes        = []
    face_data     = []
    face_info     = {}
    color_imgs    = {}   # ← ADD: needed for mesh rebuild
    tree_geom_ids = set()
    sail_geom_ids = set()
    geom_id       = 0

    for face_name in FACE_ORDER:
        paths = image_pairs.get(face_name)
        if paths is None or paths[1] is None:
            print(f"  [SKIP] {face_name}")
            continue

        t0 = timemod.time()
        mesh, pcoords, vmask, tree_mask, sail_mask, all_pos, shape, ds = reconstruct_face(
            *paths, face_name, downsample=downsample)
        H, W = shape

        # Store color image for later rebuild
        color_img = _load_color_ds(paths[0], all_pos, downsample)
        color_imgs[face_name] = color_img

        non_tree_mask  = vmask & ~tree_mask & ~sail_mask
        tree_only_mask = vmask & tree_mask
        sail_only_mask = vmask & sail_mask

        n_tree     = int(tree_only_mask.sum())
        n_non_tree = int(non_tree_mask.sum())
        print(f"  {face_name:6s}: non-tree {n_non_tree:,} verts, "
            f"tree {n_tree:,} verts  ({timemod.time()-t0:.2f}s)")

        face_data.append((face_name, pcoords, vmask, shape, ds))
        face_info[face_name] = {
            "all_positions": all_pos,
            "valid_mask":    vmask,
            "shape":         shape,
            "tree_mask":     tree_mask,
            "sail_mask":     sail_mask,
            "paths":         paths,
        }

    # ── Reconcile FIRST, then build scene geometry ────────────────────────
    print("  Reconciling edge positions...")
    reconcile_edge_positions(face_info, n_blend_rows=30)   # ← larger = fewer gaps

    for face_name, pcoords, vmask, shape, ds in face_data:
        info       = face_info[face_name]
        all_pos    = info["all_positions"]
        H, W       = shape
        tree_mask  = info["tree_mask"]
        sail_mask  = info["sail_mask"]
        paths      = info["paths"]
        color_img  = color_imgs[face_name]

        non_tree_mask  = vmask & ~tree_mask & ~sail_mask
        tree_only_mask = vmask & tree_mask
        sail_only_mask = vmask & sail_mask

        # Build submeshes from RECONCILED positions
        if non_tree_mask.any():
            nt_mesh = _build_submesh(all_pos, non_tree_mask, paths[0], H, W, downsample)
            if len(nt_mesh.vertices) > 0 and len(nt_mesh.triangles) > 0:
                scene.add_triangles(o3d.t.geometry.TriangleMesh.from_legacy(nt_mesh))
                geom_id += 1

        if tree_only_mask.any():
            tr_mesh = _build_submesh(all_pos, tree_only_mask, paths[0], H, W, downsample)
            if len(tr_mesh.vertices) > 0 and len(tr_mesh.triangles) > 0:
                scene.add_triangles(o3d.t.geometry.TriangleMesh.from_legacy(tr_mesh))
                tree_geom_ids.add(geom_id)
                geom_id += 1

        if sail_only_mask.any():
            sail_mesh = _build_submesh(all_pos, sail_only_mask, paths[0], H, W, downsample)
            if len(sail_mesh.vertices) > 0 and len(sail_mesh.triangles) > 0:
                scene.add_triangles(o3d.t.geometry.TriangleMesh.from_legacy(sail_mesh))
                sail_geom_ids.add(geom_id)
                geom_id += 1

        # Rebuild visualization mesh from RECONCILED positions
        rebuilt = _rebuild_mesh_from_positions(all_pos, vmask, color_img)
        meshes.append(rebuilt)

    print(f"  Tree geometry IDs in scene: {tree_geom_ids}")

    vertex_counts = [len(np.asarray(m.vertices)) for m in meshes]
    all_vertices  = np.vstack([
        np.asarray(m.vertices) for m in meshes
        if len(m.vertices) > 0
    ]).astype(np.float32)

    return scene, meshes, None, face_data, vertex_counts, all_vertices, tree_geom_ids, sail_geom_ids

# ============================================================================
# BATCH PROCESSING
# ============================================================================

def process_all_shadows(image_pairs, folder_id, lat, lon, start, end,
                        time_delta_min=5, downsample=1, output_dir=None):
    if output_dir is None:
        output_dir = f"output/{folder_id}/pyshadow"

    print("=" * 60)
    print("CUBEMAP SHADOW COMPUTATION v5")
    print("=" * 60)

    print("\n[1/4] Reconstructing 3D scene...")
    t0 = timemod.time()
    meshes, fdata, stitch = reconstruct_scene(image_pairs, downsample=downsample)
    tv = sum(len(np.asarray(m.vertices)) for m in meshes)
    tt = sum(len(np.asarray(m.triangles)) for m in meshes)
    print(f"  Total: {tv:,} verts, {tt:,} tris  ({timemod.time()-t0:.2f}s)")

    print("\n[2/4] Sun positions...")
    sun_pos, times, above = compute_sun_positions(lat, lon, start, end,
                                                   freq=f"{time_delta_min}min")
    n_total = len(times)
    print(f"  {n_total} steps, {above.sum()} above horizon")

    print("\n[3/4] Building raycasting scene...")
    t0 = timemod.time()
    # ← CHANGED: unpack tree_geom_ids
    scene, meshes, stitch, fdata, vcounts, all_verts, tree_geom_ids, sail_geom_ids = \
        build_shadow_scene_once(image_pairs, downsample=downsample)
    print(f"  Ready ({timemod.time()-t0:.2f}s)")

    print(f"\n[4/4] Shadows for {n_total} timesteps...")
    os.makedirs(output_dir, exist_ok=True)
    results = []

    for bi in tqdm(range(n_total), desc="Shadows"):
        if above[bi]:
            # ← CHANGED: shadow_type instead of smask, pass tree_geom_ids
            shadow_type = cast_shadows(scene, all_verts, sun_pos[bi].astype(np.float32),
                                       tree_geom_ids=tree_geom_ids, sail_geom_ids=sail_geom_ids)
            simgs = shadows_to_2d(shadow_type, fdata, vcounts)
        else:
            simgs = make_fully_shadowed(fdata)

        for name, img in simgs.items():
            suffix = DIRECTION_SUFFIX_MAP[name]
            # ← CHANGED: RGB save (PIL auto-detects mode from (H,W,3) shape)
            Image.fromarray(img).save(os.path.join(output_dir, f"shadowmap{bi}_{suffix}.png"))

        results.append((times[bi], simgs))

    print(f"\nDone! {n_total} sets → {output_dir}")
    return results


# ============================================================================
# IMAGE PAIR GENERATION
# ============================================================================

def generate_image_pairs(folder_id):
    """(color_path | None, depth_path, seg_path) per cube face, from output/<folder_id>/color_depth_seg/
    {color,depth,seg}/<lat>_<lon>_<heading>_<pitch>_<kind>.png.  Colour is optional. [release change]"""
    base = os.path.join("output", folder_id, "color_depth_seg")

    suffix_map = {
        "_0_0": "North", "_180_0": "South", "_90_0": "East",
        "_270_0": "West", "_0_90": "Up", "_0_270": "Down",
    }
    pairs = {n: (None, None, None) for n in FACE_ORDER}

    if not os.path.isdir(base):
        print(f"ERROR: {base} not found")
        return pairs

    for sp in glob.glob(os.path.join(base, "seg", "*_seg.png")):
        bn = os.path.basename(sp)[:-len("_seg.png")]
        for sfx, name in suffix_map.items():
            if bn.endswith(sfx):
                depth_path = os.path.join(base, "depth", f"{bn}_depth.png")
                color_path = os.path.join(base, "color", f"{bn}_color.png")
                if not os.path.exists(depth_path):
                    print(f"  [WARNING] Missing depth for {bn}")
                    break
                pairs[name] = (color_path if os.path.exists(color_path) else None, depth_path, sp)
                break

    found = sum(1 for v in pairs.values() if v[1] is not None)
    print(f"  Found {found}/6 faces (seg + depth)")
    return pairs
