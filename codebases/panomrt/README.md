# PanoMRT

**Mean radiant temperature (MRT), UTCI and PET from a thermal 360° panorama and standard weather data**: the open-source model
behind the PanoMRT paper of the SHaDE Lab at Arizona State University.

> **Open source (Apache-2.0).** This folder holds the model code and a test suite that runs it end to end on **synthetic
> panoramas**. No imagery, measurements or validation data are included. License: [Apache-2.0](LICENSE).

## What it does

```
thermal panorama ─► six cube faces ─► five fisheye views (32 zenith rings) ─► sky view factor
      │                                                                          │
      └─► surface temperature per pixel ─► long wave ─┐                          │
sun position + weather ─► short wave (direct + diffuse) ─┴─► six-direction budget ─► MRT ─► UTCI · PET
```

1. **Cube faces.** `--pano` converts an equirectangular panorama into six cube faces (`utils/image/pano2cube.py`); without
   it, pre-made faces are read (`utils/image/imageReader.py`). Each grey value is a **surface temperature in °C**; pixels
   below 4 °C are treated as sky.
2. **Fisheye weights.** `utils/image/fisheyeProjection.py` projects the faces to equiangular fisheye views and gives every
   pixel an equal-solid-angle weight, grouped into 32 rings by zenith angle.
3. **Sky view factor.** Cosine-weighted share of open sky (Steyn 1980), `calc.computeSkyViewFactor`.
4. **Sun.** `SunTrajectory.py` (Blanco-Muriel et al. 2001) gives zenith and azimuth; the sun is "visible" if the sky mask is
   open at its position in the image (or you pass `-sv` / `-svl`).
5. **Radiation.** Long wave from the sky (Prata-type emissivity from vapour pressure) and from surfaces (Stefan-Boltzmann);
   short wave from a clear-sky model (VDI 3789): direct beam on the faces that look at the sun, diffuse scaled by the sky
   view factor. Two short-wave treatments: **`lindberg`** (default; direction-dependent, as in SOLWEIG) and **`open`**.
6. **MRT, UTCI, PET.** Weighted six-direction flux density → MRT = (flux / (εσ))^¼ − 273.15; UTCI by the published
   polynomial; PET by the VDI 3787 routine (`utils/calculate/`).

## Quick start

```bash
pip install -r requirements.txt          # Python 3.8+; tested on 3.10
python -m pytest -m "not slow"           # 43 unit tests, about 15 seconds
python -m pytest                         # adds the end-to-end runs: 51 tests, about 3 minutes
pip install -e .                         # optional: installs the `panomrt` command
```

```bash
panomrt -f measurements.csv -i path/to/panoramas/ -o output.csv --pano -j 4
# or, without installing:  PYTHONPATH=src python -m panomrt -f ...
```

### Input

**`measurements.csv`**, one row per measurement (the column names are case-insensitive; `altitude` is optional, in metres):

```csv
date,time,site,shade,airtc_avg,mrt,ws_ms_avg,rh,latitude,longitude,altitude
6/21/2020,12:00:00 PM,100,0,38.0,60.0,1.0,15.0,33.42,-111.935,331
```

**Images**: a folder per measurement, named `<YYYYMMDD>_<site><HH>` where `HH` is the closest picture hour to the
measurement (`--hours`, default `6 9 12 15 18 20`), e.g. `20200621_10012/`. It holds either one panorama (`.jpg` or `.png`,
with `--pano`) or six cube faces ending `_0_0.jpg` (front), `_90_0.jpg` (right), `_180_0.jpg` (back), `_270_0.jpg` (left),
`_0_90.jpg` (up) and `_0_270.jpg` (down).

### Output

`output.csv` with `date, time, site, MRT_MaRTy, Pano_MRT, UTCI, PET`. `MRT_MaRTy` is the measured MRT from the input, kept
next to the modelled `Pano_MRT` for comparison.

| Flag | Meaning |
|---|---|
| `-f`, `-i` | Data file(s) and image folder(s). One folder for all files, or one per file |
| `-m lindberg` / `open` | Short-wave method |
| `--pano` | Inputs are equirectangular panoramas |
| `-sv -1 / 0 / 1` | Sun visibility: automatic from the image (default), forced shade, forced sun |
| `-svl` | Take sun visibility from the `shade` column instead of the image |
| `-j N` | Worker processes. `-n`, `--offset` run a slice of the rows. `-v`, `-d` print progress and debug output |

## What is in this folder

| Path | Contents |
|---|---|
| `src/panomrt/PanoMRT.py`, `__main__.py` | Driver and command line |
| `src/panomrt/utils/calculate/` | Sun position, radiation budget, `calc` formulas, UTCI, PET |
| `src/panomrt/utils/image/` | Panorama → cube faces, image reader, fisheye weights |
| `tests/` | 51 tests: formulas, geometry, SVF against the analytic sin²θ cone, sun position, comfort indices, synthetic end-to-end runs |

**Deliberately not included:** the field imagery and measurements behind the paper, the experiment notebooks
(`experiments/`, about 1.2 MB of notebook output), and IDE settings.

## Changes from the lab repository

* `__init__.py` files so the package installs; unused demo code under `if __name__ == "__main__"` removed.
* The `open` method crashed in two places (it needed measured `SW_*` columns, and `MRFD` was never assigned in that
  branch). Both are fixed; a test runs it.
* Nothing else in the methodology was changed. The points below are **left as published** and are covered by tests that
  document them.

## Known limitations (please read before using it outside Arizona)

1. **Time zone.** `createSunTrajectory` adds 7 hours to the local time to reach UTC. That is right for Arizona (UTC−7, no
   daylight saving) and wrong everywhere else.
2. **Vapour pressure.** `calc.getVaporPressure` uses `273.15 + T` where the Magnus formula has `237.3 + T`, which gives
   19.8 hPa instead of 23.4 hPa at 20 °C and 100 % RH. An `xfail` test records it.
3. **Surface projection factor.** `calc.getSurfaceProjectionFactor` takes the sun height in radians and omits the `/50000`
   term of the Fanger formula; it turns negative above about 60°. Only the `open` method uses it. An `xfail` test records it.
4. **Image orientation (to confirm).** `ImageReader` flips the sky mask vertically but not the temperature array. For the
   lateral faces the code therefore reads temperatures from the opposite half of the image from the one the mask refers to.
   It may be intended for the lab's camera export; **TODO (PI): confirm the orientation convention** and whether
   the temperature array should be flipped too.
5. **Cloud cover** is fixed at 0 (clear sky).
6. **Several data files.** Only the last data file is loaded into the table; the image folders are matched by index.
7. **`--hours`** must list at least six hours.
8. **Speed.** The per-pixel loops are plain Python: about a minute per measurement.
9. **PET routine licence.** See [NOTICE](NOTICE); the upstream licence has not been verified.

## Citation

> Middel, A., Huff, M., Krayenhoff, E. S., Schneider, F. A., Udupa, A. (2023). PanoMRT: Panoramic infrared thermography to
> model human thermal exposure and comfort. *Science of The Total Environment* 859, 160301.
> [doi:10.1016/j.scitotenv.2022.160301](https://doi.org/10.1016/j.scitotenv.2022.160301)

See [CITATION.cff](CITATION.cff).
