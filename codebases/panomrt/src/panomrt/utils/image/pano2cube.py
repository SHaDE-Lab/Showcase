import cv2
import numpy as np
import os

def panorama_to_cubemap(panorama_path, output_dir, cube_size=1024):
    """Convert a panorama image to 6 cubemap directional images.

    Args:
        panorama_path (str): Path to the input panorama image.
        output_dir (str): Directory to save the cubemap images.
        cube_size (int): Size of each cube face (default is 1024x1024).
    """
    panorama = cv2.imread(panorama_path)
    if panorama is None:
        print(f"Error: Failed to load panorama image from {panorama_path}")
        return

    pano_h, pano_w = panorama.shape[:2]
    os.makedirs(output_dir, exist_ok=True)
    face_names = ['180_0', '90_0', '0_0', '270_0', '0_90', '0_270']

    for face in face_names:
        u, v = np.meshgrid(
            np.linspace(-1, 1, cube_size),
            np.linspace(-1, 1, cube_size)
        )

        if face == '180_0':  # front
            x = -np.ones_like(u)
            y = v
            z = -u
        elif face == '0_0':  # back
            x = np.ones_like(u)
            y = v
            z = u
        elif face == '90_0':  # right
            x = -u
            y = v
            z = np.ones_like(u)
        elif face == '270_0':  # left
            x = u
            y = v
            z = -np.ones_like(u)
        elif face == '0_90':  # top
            x = v
            y = -np.ones_like(u)
            z = u
        elif face == '0_270':  # bottom
            x = -v
            y = np.ones_like(u)
            z = u

        norm = np.sqrt(x**2 + y**2 + z**2)
        x /= norm
        y /= norm
        z /= norm

        lon = np.arctan2(z, x)
        lat = np.arcsin(y)

        px = ((lon + np.pi) / (2 * np.pi) * pano_w).astype(np.int32)
        py = ((lat + np.pi / 2) / np.pi * pano_h).astype(np.int32)

        px = np.clip(px, 0, pano_w - 1)
        py = np.clip(py, 0, pano_h - 1)

        cubemap_face = panorama[py, px]
        filename = os.path.splitext(os.path.basename(panorama_path))[0]
        output_path = os.path.join(output_dir, f"{filename}_{face}.jpg")
        cv2.imwrite(output_path, cubemap_face)
        print(f"Saved {face} face to {output_path}")