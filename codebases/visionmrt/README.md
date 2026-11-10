# VisionMRT: example code release

Physics-based **mean radiant temperature (MRT), UTCI and PET from a 360° view of a place**: the method behind the
[VisionMRT web tool](https://shadelab.asu.edu/VisionMRT) of the SHaDE Lab at Arizona State University.

> **Status: example release, open source (Apache-2.0).** This folder runs the published workflow end to end on **two example
> sites**. It is *not* the paper's validation (that used 132 measured sites) and it is *not* the full web tool.
> License: [Apache-2.0](LICENSE).

## What it does

```
cube-face segmentation + depth ──► fisheye (sky-up) view ──► sky view factor (SVF)
        └─► 3D scene ──► ray-cast shadows, hour by hour ──┐
hourly weather ────────────────────────────────────────────┴─► surface energy balance ─► MRT · UTCI · PET
```

* **SVF** is the cosine-weighted share of open sky from the six cube faces (Steyn 1980), `src/svf.py`.
* **Shadows**: depth + segmentation are turned into a 3D mesh; shadow rays are cast toward the sun for each hour
  (`src/PyShadowComputation.py`, Open3D ray casting).
* **Energy balance**: radiosity-based surface temperatures, six-direction short- and longwave fluxes, MRT, UTCI and
  PET (`src/SurfaceTemperature.py`).
* `src/pipeline.py` strings these together exactly as the web tool's "Compute All Day" does, without the web layer.

## Quick start

```bash
pip install -r requirements.txt        # Python 3.10
python run_demo.py                     # both sites, one day (~2 min); writes data/expected and the website demo assets
python -m pytest                       # 41 tests, ~4 min  (python -m pytest -m "not slow" for the ~30-second subset)
```

```python
import sys; sys.path.insert(0, "src")
import pipeline as P
weather = P.load_weather("data/weather/tempe_2018-06-09.json")
res = P.run_site("data/sites/site_b_enclosed", "out/site_b", "2018-06-09", weather)
res["svf"], res["results"][["Hour", "MRT_CalcSW_CalcLW", "UTCI", "PET"]]
```

## What is in this folder

| Path | Contents |
|---|---|
| `src/svf.py`, `FisheyeProjection.py`, `SurfaceTemperature.py`, `Config.py` | Methodology, **unchanged** from the web tool |
| `src/PyShadowComputation.py` | Shadow casting; interactive viewer and desktop entry point removed, colour imagery made optional (header lists the changes) |
| `src/pipeline.py` | Offline batch driver (new); also the segmentation loader fix below |
| `data/sites/` | Two example sites: **segmentation and depth only** (6 cube faces each) |
| `data/weather/` | Hourly weather for the example day (Open-Meteo, CC BY 4.0) |
| `data/expected/` | Outputs the tests compare against |
| `tests/` | SVF analytics, shadow geometry on synthetic scenes, end-to-end runs |
| `run_demo.py` | Regenerates the expected outputs and the website widget (`../../demos/visionmrt`) |

**Deliberately not included:** the web server, job queue, deployment files, the segmentation/depth neural networks and
their weights (the example sites ship with their results), street-level-imagery API integration and any credentials,
the Seg Editor, the 3D viewer, unpublished experiments.

## The two example sites

| | Site A | Site B |
|---|---|---|
| Character | more open sky (all-sky overhead) | more enclosed (trees and buildings overhead) |
| Sky view factor | 0.84 | 0.62 |
| Location | Tempe, AZ (see file names) | Tempe, AZ (see file names) |

They differ most in the morning and evening: on 2018-06-09 the direct sun reaches the person at Site A from 08:00, but only
from 09:00 at Site B, giving an 18 °C MRT difference at 08:00. At midday both are sun-exposed and the MRT is within
1–2 °C. They are a small illustration, not a representative contrast.

## Data provenance (read before redistributing)

* **No photographs are shipped.** The sites contain segmentation class maps and depth maps. The source photographs are
  excluded on purpose: the sample package does not record where the imagery came from, and its naming
  (`<lat>_<lon>_<heading>_<pitch>`) matches street-level-imagery APIs. **TODO (PI): confirm the imagery source.**
  If it was Mapillary, derived data fall under CC BY-SA 4.0 (attribution and share-alike). If it was Google Street View,
  its terms may not allow redistributing derived data, and the data folder should be replaced.
* Weather: [Open-Meteo](https://open-meteo.com) historical API, CC BY 4.0. Wind is the 10 m value reduced to 1.1 m with the log law.

## Differences from the web tool, and one bug found

1. Weather is read from a file instead of downloaded, so runs are offline and repeatable.
2. **Bug in the web tool's segmentation loader** (`_load_seg_for_execute`): it treats an image as a grayscale label map when
   red equals green. A face that is entirely sky, RGB (0, 0, 255), satisfies that, is read as all "background", and the
   sun is then reported blocked all day. `pipeline.load_seg_labels` also checks the blue channel (as `svf.py` always did).
   The upstream web tool should be fixed the same way. A regression test covers it.
3. `SurfaceTemperature.determine_sun_visibility_sophisticated` draws a random number when cloud cover exceeds 0.8, so
   overcast days are not exactly repeatable. The example day is clear.
4. The sample package from the web tool included an older results file in which the sun is visible from 07:00 to 19:00 at both
   sites. The current code decides low-sun hours differently, so those early/late values do not match; the stored
   expected outputs are from the code in this folder. The shadow maps do match the package's maps (within 0.5 % of pixels).

## What the tests show, and do not show

They check the maths (SVF against the analytic sin²θ cone, symmetry, fisheye vs cube-face agreement), shadow geometry on
scenes with known answers (open sky leaves the ground fully sunlit, a roof overhead shades it), the end-to-end outputs
against stored values (±0.3 °C, ±0.002 SVF) and physical plausibility. The stored values were produced by this code, so
they guard against regressions; **they are not a validation against measured MRT.** Accuracy claims belong to the paper.

## Citation

Cite the VisionMRT paper (Middel, Shaeri, Woo & Krayenhoff, accepted in *Sustainable Cities and Society*; preprint: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=7191292; **TODO: add the DOI once published**) and, for the image-based MRT approach:

> Shaeri, P., AlKhaled, S., & Middel, A. (2025). A Multimodal Physics-Informed Neural Network Approach for Mean Radiant
> Temperature Modeling. *Proceedings of the IEEE/CVF ICCV Workshops*, 6606–6615. https://ieeexplore.ieee.org/document/11375311

See `CITATION.cff`.

## License

Apache License 2.0, see [LICENSE](LICENSE) and [NOTICE](NOTICE). The sample weather data is Open-Meteo (CC BY 4.0). The sample sites' source-imagery provenance is documented above; only derived segmentation and depth maps are included.
