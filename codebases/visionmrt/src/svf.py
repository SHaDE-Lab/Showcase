"""Sky view factor (SVF) of a site: ONE implementation, used by the upload, the segmentation step, the Seg Editor, the
panel in the viewer and the MRT computation, so they all show and use exactly the same number.

SVF is the share of the radiation a flat, upward-facing surface would get from the whole sky that really comes from open
sky: the sky's solid angle weighted by the cosine of the angle from the zenith (Steyn 1980; Johnson & Watson 1984).
For a fully open sky it is 1, for a sky that is open only within a cone of half-angle t around the zenith it is sin(t)^2.
(A plain "share of sky pixels" in a fisheye picture is not that: it counts the sky near the horizon as much as the
sky overhead, although overhead sky delivers far more radiation.)

It is computed straight from the six cube faces of the segmentation (exact solid angle and cosine of every pixel), so it
does not depend on how a fisheye picture was resampled.

Files, per site folder:  <site>/color_depth_seg/seg/*_seg.png   (the segmentation, sky = blue (0,0,255) or label 1)
                         <site>/svf.json                          (the result, kept so that it can be shown at once)
"""
import hashlib
import json
import os
import time
from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image

SKY_RGB = (0, 0, 255)
SKY_LABEL = 1
FACE_SUFFIX = {"North": "0_0", "South": "180_0", "East": "90_0", "West": "270_0", "Up": "0_90", "Down": "0_270"}
SIDE_FACES = ("North", "South", "East", "West")
FACE_SIZE = 512
CHANGE_EPS = 0.0005            # smaller differences are not reported as a change


# ---------------------------------------------------------------------------------------------------------------------
# Geometry: how much does every pixel of a cube face count?
# ---------------------------------------------------------------------------------------------------------------------
@lru_cache(maxsize=4)
def _weights(n: int) -> dict:
    """Per face: an n x n array with the pixel's cosine-weighted solid angle. A pixel at face coordinates (u, v) in -1..1
    looks along d = (x, y, z) (y up); its solid angle is dA / |d|^3 (the face is one unit away) and the cosine of its
    angle from the zenith is y / |d|. Pixels at or below the horizon count 0."""
    u = ((np.arange(n) + 0.5) / n) * 2.0 - 1.0                  # columns, left to right
    v = 1.0 - ((np.arange(n) + 0.5) / n) * 2.0                  # rows, top to bottom
    U, V = np.meshgrid(u, v)
    one = np.ones_like(U)
    dirs = {                                                    # the same face layout as the hemisphere / fisheye code
        "North": (U, V, one),
        "South": (-U, V, -one),
        "East": (one, V, -U),
        "West": (-one, V, U),
        "Up": (U, one, -V),
    }
    cell = (2.0 / n) ** 2
    out = {}
    for name, (x, y, z) in dirs.items():
        r2 = x * x + y * y + z * z
        w = np.where(y > 0.0, y / (r2 ** 2) * cell, 0.0)         # y / |d|^4
        out[name] = w
    return out


# ---------------------------------------------------------------------------------------------------------------------
# SVF from sky masks
# ---------------------------------------------------------------------------------------------------------------------
def svf_from_sky_faces(masks: dict) -> dict:
    """masks: face name -> boolean array (True = sky), any square size (resampled to 512). The Up face is required; a missing
    side face is left out of the sum (and of the total), and the result is marked partial.
    Returns {"svf": float 0..1, "faces": [...], "partial": bool}, or {"svf": None} when there is no Up face."""
    if "Up" not in masks:
        return {"svf": None, "faces": [], "partial": True}
    weights = _weights(FACE_SIZE)
    sky = total = 0.0
    used = []
    for face in ("Up",) + SIDE_FACES:
        m = masks.get(face)
        if m is None:
            continue
        m = np.asarray(m, dtype=bool)
        if m.shape != (FACE_SIZE, FACE_SIZE):
            m = np.array(Image.fromarray(m.astype(np.uint8) * 255).resize((FACE_SIZE, FACE_SIZE), Image.NEAREST)) > 127
        w = weights[face]
        sky += float((w * m).sum())
        total += float(w.sum())
        used.append(face)
    svf = sky / total if total > 0 else None
    return {"svf": None if svf is None else float(min(1.0, max(0.0, svf))), "faces": used,
            "partial": any(f not in used for f in SIDE_FACES)}


def svf_from_fisheye(sky_mask: np.ndarray, rings: int = 90) -> float:
    """SVF from an equidistant fisheye picture of the sky (the disc fills the square; r = R * zenith angle / 90 degrees):
    the sky share of each zenith-angle ring, weighted by sin(2 * angle) (= the cosine-weighted solid angle of the ring).
    Pixels outside the disc are ignored (the old ring code let them dilute the outermost ring)."""
    m = np.asarray(sky_mask, dtype=bool)
    h, w = m.shape
    cy, cx = (h - 1) / 2.0, (w - 1) / 2.0
    radius = min(h, w) / 2.0
    y, x = np.indices(m.shape)
    r = np.hypot(x - cx, y - cy)
    inside = r <= radius
    ring = np.minimum((r / radius * rings).astype(np.int32), rings - 1)
    tot = np.bincount(ring[inside], minlength=rings).astype(np.float64)
    sky = np.bincount(ring[inside & m], minlength=rings).astype(np.float64)
    frac = np.divide(sky, tot, out=np.zeros(rings), where=tot > 0)
    theta = (np.arange(rings) + 0.5) / rings * (np.pi / 2.0)
    return float(min(1.0, max(0.0, (np.sin(2.0 * theta) * frac).sum() * (np.pi / 2.0) / rings)))


# ---------------------------------------------------------------------------------------------------------------------
# A site's segmentation on disk
# ---------------------------------------------------------------------------------------------------------------------
def _seg_dir(site_dir) -> Path:
    return Path(site_dir) / "color_depth_seg" / "seg"


def _face_png(seg_dir: Path, face: str):
    found = sorted(seg_dir.glob(f"*_{FACE_SUFFIX[face]}_seg.png"))
    return found[0] if found else None


def sky_mask_from_png(path) -> np.ndarray:
    """Sky pixels of one segmentation picture: a colour map (sky = blue 0,0,255) or a label map (R = G = B = label, sky = 1)."""
    raw = np.array(Image.open(path).convert("RGB"))
    if (raw[:, :, 0] == raw[:, :, 1]).all() and (raw[:, :, 1] == raw[:, :, 2]).all() and raw.max() < 8:
        return raw[:, :, 0] == SKY_LABEL
    return np.all(raw == SKY_RGB, axis=-1)


def seg_signature(site_dir) -> str:
    """A fingerprint of the segmentation files (names, sizes, times): when it changes, the SVF has to be computed again."""
    seg_dir = _seg_dir(site_dir)
    parts = []
    for face in FACE_SUFFIX:
        p = _face_png(seg_dir, face) if seg_dir.is_dir() else None
        if p is not None:
            st = p.stat()
            parts.append(f"{face}:{p.name}:{st.st_size}:{st.st_mtime_ns}")
    return hashlib.sha1("|".join(parts).encode()).hexdigest() if parts else ""


def compute_site_svf(site_dir) -> dict:
    """Reads the site's segmentation and returns svf_from_sky_faces(...) (svf None when there is no usable segmentation)."""
    seg_dir = _seg_dir(site_dir)
    masks = {}
    if seg_dir.is_dir():
        for face in ("Up",) + SIDE_FACES:
            p = _face_png(seg_dir, face)
            if p is not None:
                try:
                    masks[face] = sky_mask_from_png(p)
                except Exception:
                    pass
    return svf_from_sky_faces(masks)


# ---------------------------------------------------------------------------------------------------------------------
# svf.json: the result, with what it was before, so the viewer can say "more sky" / "less sky"
# ---------------------------------------------------------------------------------------------------------------------
def _json_path(site_dir) -> Path:
    return Path(site_dir) / "svf.json"


def read_site_svf(site_dir):
    try:
        return json.loads(_json_path(site_dir).read_text(encoding="utf-8"))
    except Exception:
        return None


def _write(site_dir, info: dict):
    p = _json_path(site_dir)
    tmp = p.with_name(p.name + f".tmp{os.getpid()}")
    tmp.write_text(json.dumps(info, indent=1), encoding="utf-8")
    os.replace(tmp, p)                                          # atomic: a reader never sees a half-written file


def ensure_site_svf(site_dir, force: bool = False, source: str = None):
    """The site's SVF, computed again when the segmentation has changed since it was last computed (or when forced).
    Returns a dict {svf, previous_svf, delta, changed, source, computed_at, signature, faces, partial} or None when the site
    has no usable segmentation yet. The previous value is kept, so a change can be shown."""
    site_dir = Path(site_dir)
    signature = seg_signature(site_dir)
    cached = read_site_svf(site_dir)
    if cached and not force and cached.get("signature") == signature and signature:
        return cached
    if not signature:
        return None
    res = compute_site_svf(site_dir)
    if res["svf"] is None:
        return None
    svf = round(res["svf"], 4)
    previous = cached.get("svf") if cached else None
    info = {
        "svf": svf,
        "previous_svf": previous,
        "delta": None if previous is None else round(svf - previous, 4),
        "changed": previous is not None and abs(svf - previous) >= CHANGE_EPS,
        "source": source or (cached or {}).get("source") or "segmentation",
        "computed_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "signature": signature,
        "faces": res["faces"],
        "partial": res["partial"],
        "method": "cosine-weighted solid angle of the sky on the six cube faces (Steyn 1980)",
    }
    _write(site_dir, info)
    return info
