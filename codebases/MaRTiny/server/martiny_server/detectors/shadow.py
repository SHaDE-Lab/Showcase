# Copyright 2026 The SHaDE Lab, Arizona State University
# SPDX-License-Identifier: CERN-OHL-P-2.0
"""Shadow detection. The lab uses BDRAR (Zhu et al., ECCV 2018), a network that turns a photo into a shadow map.

The BDRAR network code and its trained weights are NOT part of this repository: the authors' code carries no stated license
and the weights are about 350 MB (see models/README.md). This module is the part that is ours: it runs any network that
maps a normalised RGB tensor to a one-channel probability map, and turns the result into a grey-level shadow map the
size of the photo. You point the server at your copy of the network with MARTINY_SHADOW_NETWORK=module:callable."""
from __future__ import annotations

import importlib
from typing import Callable, Optional

import numpy as np
from PIL import Image


class NullShadowDetector:
    """Reports no shadow anywhere (an all-black map). Lets the server run, and be tested, without a model."""
    def find_shadow(self, image: Image.Image) -> Image.Image:
        return Image.new("L", image.size, 0)


class ShadowDetector:
    """network: a torch module in eval mode taking (1, 3, H, W) and returning (1, 1, H, W) values in 0..1.
    refine: optional function (rgb uint8 array, map uint8 array) -> map uint8 array, for example a dense-CRF clean-up."""
    def __init__(self, network, device: str = "cpu", input_size: int = 416,
                 refine: Optional[Callable[[np.ndarray, np.ndarray], np.ndarray]] = None, threads: int = 1):
        import torch
        from torchvision import transforms
        self._torch = torch
        self._to_pil = transforms.ToPILImage()
        self._resize_back = transforms
        self._transform = transforms.Compose([
            transforms.Resize(input_size),
            transforms.ToTensor(),
            transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225]),
        ])
        self.device, self.refine = device, refine
        self.network = network.to(device).eval()
        torch.set_num_threads(threads)

    def find_shadow(self, image: Image.Image) -> Image.Image:
        torch = self._torch
        rgb = image.convert("RGB")
        w, h = rgb.size
        with torch.no_grad():
            out = self.network(self._transform(rgb).unsqueeze(0).to(self.device)).detach().float().cpu()
            plane = self._to_pil(out.squeeze(0).clamp(0.0, 1.0))
            prediction = np.array(self._resize_back.Resize((h, w))(plane))
        if self.refine is not None:
            prediction = self.refine(np.array(rgb), prediction)
        return Image.fromarray(prediction.astype(np.uint8))


def load_network_factory(spec: str):
    """Imports "package.module:function". The function returns the network, or (network, refine_function)."""
    if ":" not in spec:
        raise ValueError(f"MARTINY_SHADOW_NETWORK must look like module:function, got {spec!r}")
    module_name, _, func_name = spec.partition(":")
    try:
        module = importlib.import_module(module_name)
    except ImportError as exc:
        raise RuntimeError(f"cannot import {module_name!r} named in MARTINY_SHADOW_NETWORK; see models/README.md") from exc
    try:
        return getattr(module, func_name)
    except AttributeError as exc:
        raise RuntimeError(f"{module_name!r} has no function {func_name!r}") from exc


def load_shadow_detector(spec: str, device: str = "cpu"):
    if spec.strip().lower() in {"", "none"}:
        return NullShadowDetector()
    built = load_network_factory(spec)()
    network, refine = built if isinstance(built, tuple) else (built, None)
    return ShadowDetector(network, device=device, refine=refine)
