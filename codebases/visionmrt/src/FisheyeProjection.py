import os
import cv2
import numpy as np
import shutil
from PIL import Image   # used only to suppress libpng iCCP warnings on load
import Config

# ──────────────────────────────────────────────────────────────────────────────
# Helpers (unchanged behaviour)
# ──────────────────────────────────────────────────────────────────────────────

def rotate_image(image, angle):
    """Rotate an image by the specified angle."""
    (h, w) = image.shape[:2]
    center = (w // 2, h // 2)
    M = cv2.getRotationMatrix2D(center, angle, 1.0)
    return cv2.warpAffine(image, M, (w, h))


def brighten_and_contrast(image, alpha=1.5, beta=30):
    return cv2.convertScaleAbs(image, alpha=alpha, beta=beta)


def zoom_image(image, zoom_factor):
    height, width = image.shape[:2]
    new_height, new_width = int(height * zoom_factor), int(width * zoom_factor)
    resized = cv2.resize(image, (new_width, new_height), interpolation=cv2.INTER_LINEAR)
    if zoom_factor > 1:
        crop_x1 = (new_width - width) // 2
        crop_y1 = (new_height - height) // 2
        return resized[crop_y1:crop_y1 + height, crop_x1:crop_x1 + width]
    else:
        pad_x1 = (width - new_width) // 2
        pad_y1 = (height - new_height) // 2
        return cv2.copyMakeBorder(resized, pad_y1, pad_y1, pad_x1, pad_x1,
                                  cv2.BORDER_CONSTANT, value=(0, 0, 0, 0))


# ──────────────────────────────────────────────────────────────────────────────
# Image loading  (PIL strips the bad iCCP profile → no libpng warnings)
# ──────────────────────────────────────────────────────────────────────────────

def _imread_no_icc_warning(path):
    """Load image via PIL (suppresses libpng iCCP warnings) and return BGR numpy array."""
    pil_img = Image.open(path).convert('RGB')
    return cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)


def load_raw_images(base_dir):
    """
    Load all 6 directional images from base_dir as BGR numpy arrays.
    Returns dict keyed by direction string, values are numpy arrays (or None).
    """
    directions = {k: None for k in ['0_90', '0_0', '180_0', '90_0', '270_0', '0_270']}

    tag_map = {
        '_0_90':  '0_90',
        '_0_0':   '0_0',
        '_180_0': '180_0',
        '_90_0':  '90_0',
        '_270_0': '270_0',
        '_0_270': '0_270',
    }

    for filename in os.listdir(base_dir):
        if not (filename.lower().endswith('.jpg') or filename.lower().endswith('.png')):
            continue
        for tag, key in tag_map.items():
            if tag in filename:
                filepath = os.path.join(base_dir, filename)
                img = _imread_no_icc_warning(filepath)
                if img is None:
                    print(f"Warning: Could not read {filepath}")
                else:
                    directions[key] = img
                break

    for k, v in directions.items():
        if v is None:
            print(f"Warning: Missing image for direction {k} in {base_dir}")

    return directions


# kept for backward compatibility — original signature used filepath dict
def load_images_for_site(site_no, base_dir):
    return load_raw_images(base_dir)


# ──────────────────────────────────────────────────────────────────────────────
# Geometry pre-computation (shared across all 6 views for the same output_size)
# ──────────────────────────────────────────────────────────────────────────────

def precompute_geometry(output_size):
    """
    Compute 3-D unit-sphere coords, face masks and circular alpha mask.
    Call once per output_size; reuse for all 6 views and all image types.
    """
    y, x = np.mgrid[0:output_size, 0:output_size]
    center_x = output_size // 2
    center_y = output_size // 2

    x_centered = (x - center_x).astype(np.float32)
    y_centered = (y - center_y).astype(np.float32)
    r          = np.hypot(x_centered, y_centered)
    theta      = np.arctan2(y_centered, x_centered)

    max_radius   = output_size // 2
    r_normalized = r / max_radius
    phi          = r_normalized * (np.pi / 2.0)

    x3d = (np.sin(phi) * np.cos(theta)).astype(np.float32)
    y3d = (np.sin(phi) * np.sin(theta)).astype(np.float32)
    z3d = np.cos(phi).astype(np.float32)

    ax, ay, az = np.abs(x3d), np.abs(y3d), np.abs(z3d)
    masks = {
        'front': (az >= ax) & (az >= ay) & (z3d > 0),
        'right': (ax >= ay) & (ax >= az) & (x3d > 0),
        'left':  (ax >= ay) & (ax >= az) & (x3d < 0),
        'up':    (ay >= ax) & (ay >= az) & (y3d > 0),
        'down':  (ay >= ax) & (ay >= az) & (y3d < 0),
    }

    circular_mask = np.zeros((output_size, output_size), dtype=np.uint8)
    cv2.circle(circular_mask, (center_x, center_y), max_radius, 255, thickness=-1)

    return x3d, y3d, z3d, masks, circular_mask, center_x, center_y, max_radius


# ──────────────────────────────────────────────────────────────────────────────
# Core projection kernel (direction-agnostic)
# ──────────────────────────────────────────────────────────────────────────────

def _project(output_size, x3d, y3d, z3d, masks, circular_mask,
             center_x, center_y, max_radius,
             face_to_img,        # dict: face-name -> prepared image
             face_to_uv_fn,      # dict: face-name -> callable(x3d,y3d,z3d,mask)->(u,v)
             final_rotations):   # int: 1 or 2 x ROTATE_90_CLOCKWISE
    """
    Generic fisheye projection kernel.  All per-direction logic lives in the
    caller (rotation angles, flips, face->image mapping, uv formulae).
    """
    # infer h, w from any face image
    sample = next(iter(face_to_img.values()))
    h, w = sample.shape[:2]

    fisheye = np.zeros((output_size, output_size, 4), dtype=np.uint8)

    for face, mask in masks.items():
        if not np.any(mask):
            continue
        img = face_to_img.get(face)
        if img is None:
            continue

        u, v = face_to_uv_fn[face](x3d, y3d, z3d, mask)

        u = np.clip(((u + 1) * (w - 1) / 2).astype(np.int32), 0, w - 1)
        v = np.clip(((v + 1) * (h - 1) / 2).astype(np.int32), 0, h - 1)

        fisheye[mask, :3] = img[v, u]
        fisheye[mask, 3]  = 255

    for _ in range(final_rotations):
        fisheye = cv2.rotate(fisheye, cv2.ROTATE_90_CLOCKWISE)

    fisheye[:, :, 3] = cv2.bitwise_and(fisheye[:, :, 3], circular_mask)
    fisheye = fisheye[center_y - max_radius:center_y + max_radius,
                      center_x - max_radius:center_x + max_radius]
    return fisheye


# ──────────────────────────────────────────────────────────────────────────────
# UV formulae (one per face, identical to original code)
# ──────────────────────────────────────────────────────────────────────────────

_UV = {
    'front_std':  lambda x3d, y3d, z3d, m: ( x3d[m] / z3d[m],        y3d[m] / z3d[m]),
    'right_std':  lambda x3d, y3d, z3d, m: (-z3d[m] / x3d[m],        y3d[m] / x3d[m]),
    'left_std':   lambda x3d, y3d, z3d, m: ( z3d[m] / (-x3d[m]),     y3d[m] / (-x3d[m])),
    'down_std':   lambda x3d, y3d, z3d, m: ( x3d[m] / y3d[m],       -z3d[m] / y3d[m]),
    'up_std':     lambda x3d, y3d, z3d, m: ( x3d[m] / (-y3d[m]),     z3d[m] / (-y3d[m])),
    # down-view swaps right<->left UV formulae (matches original cube_to_fisheye_down):
    'right_down': lambda x3d, y3d, z3d, m: ( z3d[m] / (-x3d[m]),     y3d[m] / (-x3d[m])),
    'left_down':  lambda x3d, y3d, z3d, m: (-z3d[m] / x3d[m],        y3d[m] / x3d[m]),
}


# ──────────────────────────────────────────────────────────────────────────────
# Per-view functions  (EXACT same rotation_angles, flips, face->dir mapping,
#                      and UV formulae as the original code)
# ──────────────────────────────────────────────────────────────────────────────

def cube_to_fisheye_up(site_no, base_dir, scale_factor=1.0,
                       _raw=None, _geo=None):
    raw = _raw if _raw is not None else load_raw_images(base_dir)

    rotation_angles = {'0_90': 90, '0_0': 90, '180_0': 270, '90_0': 180, '270_0': 0}
    flips = {'90_0', '270_0'}

    dirs = {}
    for key, img in raw.items():
        if img is None:
            print(f"Error: Missing image for direction {key}"); return None
        img = rotate_image(img, rotation_angles.get(key, 0))
        if key in flips:
            img = cv2.flip(img, 1)
        dirs[key] = img

    output_size = 2 * dirs['0_90'].shape[0]
    geo = _geo if _geo is not None else precompute_geometry(output_size)
    x3d, y3d, z3d, masks, circ, cx, cy, mr = geo

    face_img = {
        'front': dirs['0_90'],
        'right': dirs['0_0'],
        'left':  dirs['180_0'],
        'down':  dirs['90_0'],
        'up':    dirs['270_0'],
    }
    face_uv = {
        'front': _UV['front_std'], 'right': _UV['right_std'],
        'left':  _UV['left_std'],  'down':  _UV['down_std'],
        'up':    _UV['up_std'],
    }
    return _project(output_size, x3d, y3d, z3d, masks, circ, cx, cy, mr,
                    face_img, face_uv, final_rotations=1)


def cube_to_fisheye_down(site_no, base_dir, scale_factor=1.0,
                         _raw=None, _geo=None):
    raw = _raw if _raw is not None else load_raw_images(base_dir)

    rotation_angles = {'0_270': 90, '0_0': 270, '180_0': 90, '90_0': 0, '270_0': 180}
    flips = {'90_0', '270_0', '0_0', '180_0'}

    dirs = {}
    for key, img in raw.items():
        if img is None:
            print(f"Error: Missing image for direction {key}"); return None
        img = rotate_image(img, rotation_angles.get(key, 0))
        if key in flips:
            img = cv2.flip(img, 1)
        dirs[key] = img

    output_size = 2 * dirs['0_270'].shape[0]
    geo = _geo if _geo is not None else precompute_geometry(output_size)
    x3d, y3d, z3d, masks, circ, cx, cy, mr = geo

    # NOTE: original cube_to_fisheye_down swaps the UV formula for left<->right faces
    face_img = {
        'front': dirs['0_270'],
        'left':  dirs['0_0'],
        'right': dirs['180_0'],
        'down':  dirs['90_0'],
        'up':    dirs['270_0'],
    }
    face_uv = {
        'front': _UV['front_std'], 'left':  _UV['left_down'],
        'right': _UV['right_down'], 'down': _UV['down_std'],
        'up':    _UV['up_std'],
    }
    return _project(output_size, x3d, y3d, z3d, masks, circ, cx, cy, mr,
                    face_img, face_uv, final_rotations=1)


def cube_to_fisheye_front(site_no, base_dir, scale_factor=1.0,
                          _raw=None, _geo=None):
    raw = _raw if _raw is not None else load_raw_images(base_dir)

    rotation_angles = {k: 180 for k in ['0_90', '0_0', '180_0', '90_0', '270_0', '0_270']}
    flips = {'0_270', '180_0', '0_90'}

    dirs = {}
    for key, img in raw.items():
        if img is None:
            print(f"Error: Missing image for direction {key}"); return None
        img = rotate_image(img, rotation_angles.get(key, 0))
        if key in flips:
            img = cv2.flip(img, 1)
        dirs[key] = img

    output_size = 2 * dirs['0_0'].shape[0]
    geo = _geo if _geo is not None else precompute_geometry(output_size)
    x3d, y3d, z3d, masks, circ, cx, cy, mr = geo

    face_img = {
        'front': dirs['0_0'],
        'right': dirs['270_0'],
        'left':  dirs['90_0'],
        'down':  dirs['0_270'],
        'up':    dirs['0_90'],
    }
    face_uv = {
        'front': _UV['front_std'], 'right': _UV['right_std'],
        'left':  _UV['left_std'],  'down':  _UV['down_std'],
        'up':    _UV['up_std'],
    }
    return _project(output_size, x3d, y3d, z3d, masks, circ, cx, cy, mr,
                    face_img, face_uv, final_rotations=2)


def cube_to_fisheye_back(site_no, base_dir, scale_factor=1.0,
                         _raw=None, _geo=None):
    raw = _raw if _raw is not None else load_raw_images(base_dir)

    rotation_angles = {'0_90': 0, '0_0': 180, '180_0': 180,
                       '90_0': 180, '270_0': 180, '0_270': 0}
    flips = {'90_0', '270_0', '0_270', '180_0'}

    dirs = {}
    for key, img in raw.items():
        if img is None:
            print(f"Error: Missing image for direction {key}"); return None
        img = rotate_image(img, rotation_angles.get(key, 0))
        if key in flips:
            img = cv2.flip(img, 1)
        dirs[key] = img

    output_size = 2 * dirs['0_0'].shape[0]
    geo = _geo if _geo is not None else precompute_geometry(output_size)
    x3d, y3d, z3d, masks, circ, cx, cy, mr = geo

    face_img = {
        'front': dirs['180_0'],
        'right': dirs['270_0'],
        'left':  dirs['90_0'],
        'down':  dirs['0_270'],
        'up':    dirs['0_90'],
    }
    face_uv = {
        'front': _UV['front_std'], 'right': _UV['right_std'],
        'left':  _UV['left_std'],  'down':  _UV['down_std'],
        'up':    _UV['up_std'],
    }
    return _project(output_size, x3d, y3d, z3d, masks, circ, cx, cy, mr,
                    face_img, face_uv, final_rotations=2)


def cube_to_fisheye_right(site_no, base_dir, scale_factor=1.0,
                          _raw=None, _geo=None):
    raw = _raw if _raw is not None else load_raw_images(base_dir)

    rotation_angles = {'0_90': 90, '0_0': 180, '180_0': 180,
                       '90_0': 180, '270_0': 180, '0_270': 270}
    flips = {'270_0', '0_270', '0_90'}

    dirs = {}
    for key, img in raw.items():
        if img is None:
            print(f"Error: Missing image for direction {key}"); return None
        img = rotate_image(img, rotation_angles.get(key, 0))
        if key in flips:
            img = cv2.flip(img, 1)
        dirs[key] = img

    output_size = 2 * dirs['0_0'].shape[0]
    geo = _geo if _geo is not None else precompute_geometry(output_size)
    x3d, y3d, z3d, masks, circ, cx, cy, mr = geo

    face_img = {
        'front': dirs['90_0'],
        'right': dirs['0_0'],
        'left':  dirs['180_0'],
        'down':  dirs['0_270'],
        'up':    dirs['0_90'],
    }
    face_uv = {
        'front': _UV['front_std'], 'right': _UV['right_std'],
        'left':  _UV['left_std'],  'down':  _UV['down_std'],
        'up':    _UV['up_std'],
    }
    return _project(output_size, x3d, y3d, z3d, masks, circ, cx, cy, mr,
                    face_img, face_uv, final_rotations=2)


def cube_to_fisheye_left(site_no, base_dir, scale_factor=1.0,
                         _raw=None, _geo=None):
    raw = _raw if _raw is not None else load_raw_images(base_dir)

    rotation_angles = {'0_90': 270, '0_0': 180, '180_0': 180,
                       '90_0': 180, '270_0': 180, '0_270': 90}
    flips = {'0_270', '0_90'}

    dirs = {}
    for key, img in raw.items():
        if img is None:
            print(f"Error: Missing image for direction {key}"); return None
        img = rotate_image(img, rotation_angles.get(key, 0))
        if key in flips:
            img = cv2.flip(img, 1)
        dirs[key] = img

    output_size = 2 * dirs['0_0'].shape[0]
    geo = _geo if _geo is not None else precompute_geometry(output_size)
    x3d, y3d, z3d, masks, circ, cx, cy, mr = geo

    face_img = {
        'front': dirs['270_0'],
        'right': dirs['180_0'],
        'left':  dirs['0_0'],
        'down':  dirs['0_270'],
        'up':    dirs['0_90'],
    }
    face_uv = {
        'front': _UV['front_std'], 'right': _UV['right_std'],
        'left':  _UV['left_std'],  'down':  _UV['down_std'],
        'up':    _UV['up_std'],
    }
    return _project(output_size, x3d, y3d, z3d, masks, circ, cx, cy, mr,
                    face_img, face_uv, final_rotations=2)


# ──────────────────────────────────────────────────────────────────────────────
# Main workflow  (public API identical to original)
# ──────────────────────────────────────────────────────────────────────────────

_DIRECTION_FN = {
    'up':    (cube_to_fisheye_up,    'fisheye_photo_up_0_90.png'),
    'down':  (cube_to_fisheye_down,  'fisheye_photo_down_0_270.png'),
    'front': (cube_to_fisheye_front, 'fisheye_photo_front_0_0.png'),
    'back':  (cube_to_fisheye_back,  'fisheye_photo_back_180_0.png'),
    'right': (cube_to_fisheye_right, 'fisheye_photo_right_90_0.png'),
    'left':  (cube_to_fisheye_left,  'fisheye_photo_left_270_0.png'),
}


def cube_to_fisheye(site_folder, image_type, direction):
    """Original single-direction entry point (unchanged signature)."""
    base_dir        = f"./output/{site_folder}/color_depth_seg/{image_type}"
    output_base_dir = f"./output/{site_folder}/fisheye/{image_type}"

    try:
        site_no = int(site_folder.split("_")[1])
        fn, filename = _DIRECTION_FN[direction]
        fisheye_image = fn(site_no, base_dir, scale_factor=1.0)

        output_folder = output_base_dir
        os.makedirs(output_folder, exist_ok=True)
        output_path = os.path.join(output_folder, filename)

        if fisheye_image is not None:
            cv2.imwrite(output_path, fisheye_image, [cv2.IMWRITE_PNG_COMPRESSION, 9])
            print(f"Fisheye image saved to {output_path}")
        else:
            print(f"Could not create fisheye image for site {site_no}")
    except ValueError:
        print(f"Skipping invalid folder: {site_folder}")
    except Exception as e:
        print(f"An error occurred processing site {site_folder}: {e}")


def fisheye_projection_type(folder_id, image_type, directions=None):
    """
    Fast version: load images ONCE and precompute geometry ONCE,
    then reuse for all 6 directions.  Output is identical to calling
    cube_to_fisheye() six times.
    """
    base_dir        = f"./output/{folder_id}/color_depth_seg/{image_type}"
    output_base_dir = f"./output/{folder_id}/fisheye/{image_type}"
    os.makedirs(output_base_dir, exist_ok=True)

    # site_no is only ever passed through to the cube_to_fisheye_* helpers, which
    # don't actually use it — this app's folder_id format ("site_<hex>_run_<hex>")
    # isn't a plain integer like the old "XXXX_NNNN" site-numbering scheme, so
    # don't gate the whole function on int-parsing it.
    site_no = folder_id

    # load images once
    raw = load_raw_images(base_dir)

    sample = next((v for v in raw.values() if v is not None), None)
    if sample is None:
        print(f"No images found in {base_dir}")
        return

    # precompute geometry once
    output_size = 2 * sample.shape[0]
    geo = precompute_geometry(output_size)

    # project all 6 directions, reusing raw images and geometry
    if directions is None:
        directions = list(_DIRECTION_FN.keys())

    for direction in directions:
        if direction not in _DIRECTION_FN:
            print(f"Unknown direction: {direction}")
            continue

        fn, filename = _DIRECTION_FN[direction]
        try:
            fisheye_image = fn(site_no, base_dir, scale_factor=1.0,
                               _raw=raw, _geo=geo)
            output_path = os.path.join(output_base_dir, filename)
            if fisheye_image is not None:
                cv2.imwrite(output_path, fisheye_image, [cv2.IMWRITE_PNG_COMPRESSION, 9])
                print(f"Fisheye image saved to {output_path}")
            else:
                print(f"Could not create fisheye image ({direction}) for site {site_no}")
        except Exception as e:
            print(f"Error on {direction} for {folder_id}: {e}")


def file_organization(base_dir):
    image_types = ["color", "depth", "seg"]
    for filename in os.listdir(base_dir):
        file_path = os.path.join(base_dir, filename)
        if not os.path.isfile(file_path):
            continue
        for img_type in image_types:
            if f"_{img_type}." in filename:
                subfolder_path = os.path.join(base_dir, img_type)
                os.makedirs(subfolder_path, exist_ok=True)
                new_path = os.path.join(subfolder_path, filename)
                if os.path.abspath(file_path) == os.path.abspath(new_path):
                    print(f"Skipping {filename} (already organized).")
                    continue
                shutil.move(file_path, new_path)
                if Config.debug_mode:
                    print(f"Moved {filename} -> {subfolder_path}/")
                break
    print("File organization complete.")


def fisheyeTransform(folder_id, only_fisheye_up_down = False):
    if only_fisheye_up_down:
        fisheye_projection_type(folder_id, image_type="color", directions=["up"])
        fisheye_projection_type(folder_id, image_type="color", directions=["down"])
        # fisheye_projection_type(site_folder, image_type="depth", directions=["up"])
        fisheye_projection_type(folder_id, image_type="seg", directions=["up"])
        fisheye_projection_type(folder_id, image_type="seg", directions=["down"])
    else:
        fisheye_projection_type(folder_id, image_type="color")
        fisheye_projection_type(folder_id, image_type="depth")
        fisheye_projection_type(folder_id, image_type="seg")
    


# ──────────────────────────────────────────────────────────────────────────────
# SVF helper (unchanged)
# ──────────────────────────────────────────────────────────────────────────────

def compute_fisheye_radii_and_fractions(image_size=512):
    """
    Computes normalized radii and correct cosine-weighted fractions for fisheye images.

    Primary References:
    - Steyn, D. G. (1980). Atmosphere-Ocean, 18(3), 254-258.
    - Middel, A., et al. (2017). Urban Planning, 2(1), 19-30.
    """
    y, x   = np.indices((image_size, image_size))
    center = image_size // 2
    radii  = np.sqrt((x - center) ** 2 + (y - center) ** 2) / center
    radii  = np.clip(radii, 0, 1)
    theta  = radii * (np.pi / 2)
    fractions = np.cos(theta)
    if Config.debug_mode:
        print("Computed correct radii and fractions for fisheye images.")
    return radii.astype(np.float32), fractions.astype(np.float32)