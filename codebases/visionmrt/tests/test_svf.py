"""Sky view factor: analytic checks (Steyn 1980: a sky open within a cone of half-angle t has SVF = sin^2 t)."""
import numpy as np
import pytest
from PIL import Image

import svf as S

N = S.FACE_SIZE


def _face_directions():
    """Unit viewing direction (x, y up, z) of every pixel of each cube face, built independently of svf._weights."""
    u = ((np.arange(N) + 0.5) / N) * 2.0 - 1.0
    v = 1.0 - ((np.arange(N) + 0.5) / N) * 2.0
    U, V = np.meshgrid(u, v)
    one = np.ones_like(U)
    raw = {"North": (U, V, one), "South": (-U, V, -one), "East": (one, V, -U), "West": (-one, V, U), "Up": (U, one, -V)}
    out = {}
    for k, (x, y, z) in raw.items():
        n = np.sqrt(x * x + y * y + z * z)
        out[k] = (x / n, y / n, z / n)
    return out


DIRS = _face_directions()


def cone_masks(half_angle_deg):
    """Sky = every pixel whose zenith angle is within the cone."""
    c = np.cos(np.radians(half_angle_deg))
    return {k: (y >= c) for k, (x, y, z) in DIRS.items()}


@pytest.mark.parametrize("t", [15, 30, 45, 60, 75])
def test_cone_matches_sin_squared(t):
    res = S.svf_from_sky_faces(cone_masks(t))
    assert res["svf"] == pytest.approx(np.sin(np.radians(t)) ** 2, abs=0.01)
    assert not res["partial"]


def test_fully_open_and_fully_blocked():
    horizon = {k: (y > 0) for k, (x, y, z) in DIRS.items()}            # everything above the horizon is sky
    blocked = {k: np.zeros((N, N), bool) for k in DIRS}
    assert S.svf_from_sky_faces(horizon)["svf"] == pytest.approx(1.0, abs=1e-6)
    assert S.svf_from_sky_faces(blocked)["svf"] == 0.0
    # pixels below the horizon carry no weight, so marking them sky changes nothing
    everything = {k: np.ones((N, N), bool) for k in DIRS}
    assert S.svf_from_sky_faces(everything)["svf"] == pytest.approx(1.0, abs=1e-6)


def test_cosine_weighting_not_a_plain_pixel_share():
    """A 30-degree overhead cone and the 60-90 degree horizon ring both give SVF = 0.25 (sin^2 30 = 1 - sin^2 60),
    although the ring covers about four times the solid angle and many more pixels."""
    overhead = {k: (y >= np.cos(np.radians(30))) for k, (x, y, z) in DIRS.items()}
    ring = {k: ((y < np.cos(np.radians(60))) & (y > 0)) for k, (x, y, z) in DIRS.items()}
    assert S.svf_from_sky_faces(overhead)["svf"] == pytest.approx(0.25, abs=0.01)
    assert S.svf_from_sky_faces(ring)["svf"] == pytest.approx(0.25, abs=0.01)
    assert sum(m.sum() for m in ring.values()) > 2 * sum(m.sum() for m in overhead.values())


def test_rotating_the_side_faces_does_not_change_svf():
    rng = np.random.default_rng(1)
    m = {k: rng.random((N, N)) > 0.6 for k in ("Up", "North", "East", "South", "West")}
    base = S.svf_from_sky_faces(m)["svf"]
    rot = dict(m, North=m["East"], East=m["South"], South=m["West"], West=m["North"])
    assert S.svf_from_sky_faces(rot)["svf"] == pytest.approx(base, abs=1e-9)


def test_symmetric_obstruction_is_symmetric():
    """A wall on the north side blocks as much as the same wall on the south side."""
    open_ = cone_masks(90)
    north_wall = dict(open_, North=np.zeros((N, N), bool))
    south_wall = dict(open_, South=np.zeros((N, N), bool))
    a, b = S.svf_from_sky_faces(north_wall)["svf"], S.svf_from_sky_faces(south_wall)["svf"]
    assert a == pytest.approx(b, abs=1e-9) and a < 1.0


def test_missing_up_face_gives_no_value_and_missing_side_is_partial():
    assert S.svf_from_sky_faces({"North": np.ones((N, N), bool)})["svf"] is None
    part = S.svf_from_sky_faces({"Up": np.ones((N, N), bool)})
    assert part["partial"] and part["svf"] is not None


@pytest.mark.parametrize("t", [20, 40, 60, 80])
def test_fisheye_cone_matches_sin_squared(t):
    """Equidistant fisheye: radius is proportional to zenith angle, the rim is the horizon."""
    size = 721
    y, x = np.indices((size, size))
    r = np.hypot(x - (size - 1) / 2, y - (size - 1) / 2) / (size / 2)
    sky = r <= t / 90.0
    assert S.svf_from_fisheye(sky) == pytest.approx(np.sin(np.radians(t)) ** 2, abs=0.01)


def test_all_sky_colour_face_is_not_mistaken_for_a_label_map(tmp_path):
    """An all-sky face is blue (0,0,255); a label map is gray with R == G == B."""
    blue = np.zeros((8, 8, 3), np.uint8)
    blue[..., 2] = 255
    Image.fromarray(blue).save(tmp_path / "a.png")
    Image.fromarray(np.ones((8, 8), np.uint8)).save(tmp_path / "b.png")        # label map, 1 = sky
    assert S.sky_mask_from_png(tmp_path / "a.png").all()
    assert S.sky_mask_from_png(tmp_path / "b.png").all()
