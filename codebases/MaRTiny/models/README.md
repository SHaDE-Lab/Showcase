# MaRTiny models

The image server uses two machine-learning models. **The weights are not stored in this repository**, for reasons that matter if you publish or reuse this code.

| Model | Job | Needed for | License |
|---|---|---|---|
| **YOLOv8x** | finds people (and bicycles, cats, dogs, umbrellas) in each photo | `MARTINY_DETECTOR=yolo` | **AGPL-3.0** (Ultralytics) |
| **BDRAR** | turns a photo into a shadow map, so the server can tell who stands in shade | `MARTINY_SHADOW_NETWORK` | not stated by its authors |
| Faster R-CNN (torchvision) | alternative people detector | `MARTINY_DETECTOR=torchvision` | BSD-3-Clause code |

## Why the weights are not here

* **Size.** The BDRAR checkpoint is 170 MB and its ResNeXt backbone 177 MB. GitHub refuses ordinary files above 100 MB, so they would need Git LFS, which counts against the organisation's storage and bandwidth quota once the repository is public.
* **License.** YOLOv8 and the `ultralytics` package are **AGPL-3.0**. This folder is released under CERN-OHL-P-2.0, which is permissive; the two do not mix. Nothing from Ultralytics is copied into this repository. The code only imports it if you choose `MARTINY_DETECTOR=yolo`, so check that AGPL suits how you run the server (a modified, network-facing service must offer its source under AGPL). If it does not, use `MARTINY_DETECTOR=torchvision`, or a commercial Ultralytics license.
* **BDRAR has no stated license.** Neither the authors' code, nor the lab's adapted copy of it, nor the weights carry a license, so they are not republished here. Please cite the paper below. If the authors confirm a license that allows it, the files can be added with Git LFS.

## What you need to do

**People detection.** Nothing for `torchvision` beyond `pip install torch torchvision` (it downloads its weights from PyTorch). For `yolo`, `pip install ultralytics`; the weights `yolov8x.pt` download on first use.

**Shadow detection.** Get the BDRAR network code and the two weight files (the lab's copies are in its private `MaRTiny-server` repository, Git LFS), then:

1. Put the weights in `models/BDRAR/ckpt/3000.pth` and `models/BDRAR/resnext/resnext_101_32x4d.pth`.
2. Put the BDRAR network code in `models/bdrar_src/` (`model.py` and the `resnext/` package). In the lab's copy, change the first import in `model.py` from `src.service.ShadowDetection.BDRAR.resnext` to `resnext`. The lab's `ResNeXt101` loads the backbone file when it is built, so both weight files are needed.
3. Copy `bdrar_local.py.example` to `bdrar_local.py`, and set `MARTINY_SHADOW_NETWORK=bdrar_local:build` in `server/.env`.
4. Check your files with `python models/verify_models.py`. It compares sizes and SHA-256 checksums with the files the lab runs (`models.json`).

All of these paths are in `.gitignore`, so you cannot commit them by accident.

## What was checked

With the lab's real network and the 170 MB checkpoint loaded through the server's shadow wrapper, shadow maps came out at the photo's size, as 8-bit images, at roughly 4 to 5 seconds per photo on a laptop CPU. On six of the lab's sample photos they agreed with the maps the lab's own pipeline produced for 80 to 92 percent of pixels. They mark somewhat **more** area as shadow, because the lab's pipeline adds a dense-CRF clean-up step (`pydensecrf`) that this repository does not include; you can supply it as the optional `refine` function (`return net, refine_function` from `build()`). Count how many people are in shade only after calibrating against your own site's photos.

## Citation

Zhu, L., Deng, Z., Hu, X., Fu, C.-W., Xu, X., Qin, J., & Heng, P.-A. (2018). Bidirectional Feature Pyramid Network with Recurrent Attention Residual Modules for Shadow Detection. *ECCV*. The network implementation was written by Zijun Deng.
