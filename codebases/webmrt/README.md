# WebMRT: example code release

LightGBM prediction of summertime mean radiant temperature (T<sub>mrt</sub>) in Phoenix, Arizona, from the
surroundings (sky, tree and building fractions, pervious ground, shade), air temperature and the sun's position.
This is a curated, runnable extract of the method behind the [WebMRT online tool](https://shadelab.asu.edu/WebMRT),
developed at the SHaDE Lab, Arizona State University.

> **This is an example release.** It demonstrates the published method on a small sample of the training data.
> It does **not** reproduce the paper's full validation, and the model trained here is **not** the model behind the
> live tool (which is trained on the full dataset).

## Citation

AlKhaled, S. R., Middel, A., Shaeri, P., Buo, I., & Schneider, F. A. (2024). WebMRT: An online tool to predict
summertime mean radiant temperature using machine learning. *Sustainable Cities and Society*, 115, 105861.
https://doi.org/10.1016/j.scs.2024.105861 (see `CITATION.cff`).

## What is included

| Path | What it is |
|---|---|
| `src/webmrt/model.py` | The model as the deployed tool builds it: feature set, training-data preparation (min-max normalised `surr_pervious`, 70/30 split, `random_state=42`), LightGBM parameters, held-out metrics (R², RMSE, MAPE, MBE) |
| `src/webmrt/solar.py` | Solar altitude (pvlib, Phoenix) and the `min_from_sunrise` feature, derived exactly as the deployed tool derives them |
| `src/webmrt/svf_pixel.py` | The colour-threshold sky / tree / building fractions from a segmented fisheye image (the tool's fallback method) |
| `src/webmrt/sampling.py` | Script that created the sample (seeded, stratified) |
| `data/sample_RF_Data.csv` | 451-row stratified sample of the 2,159-row training table (see `data/README.md`) |
| `tests/` | pytest suite (see below) |
| `run_demo.py` | Retrains and re-exports the assets used by the in-browser demo (`demos/webmrt/`) |

## What is deliberately not included

* The Flask web app, rate limiting, deployment files and server configuration.
* The SegFormer photo-analysis pipeline (`segmentation.py`): it needs PyTorch and downloaded network weights, and
  is a convenience for reading fractions off a photo rather than part of the prediction method.
* The fisheye *drawing* code and its image assets (visualisation only).
* The full training dataset. To reproduce the live model's training, pass the full table yourself
  (`WEBMRT_DATA=/path/RF_Data.csv`).

## Run it

```bash
python -m venv venv && source venv/bin/activate      # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

```python
import sys; sys.path.insert(0, "src")
import webmrt as w

booster, metrics = w.train_model()                    # trains on data/sample_RF_Data.csv
print(metrics)                                        # held-out R2, RMSE, MAPE, MBE
row = w.build_feature_row("2023-07-15", "13:00", svf=0.5, trees=0.25, buildings=0.25,
                          pervious=0.5, shaded=0, air_temp_c=38)
print(w.predict_tmrt(booster, row))                   # predicted Tmrt in degC
```

Regenerate the browser-demo assets with `python run_demo.py`.

## How it is tested

```bash
python -m pytest              # 17 tests (+1 optional), about 5 s
WEBMRT_FULL_DATA=/path/to/RF_Data.csv python -m pytest   # also runs the full-dataset check
node ../../demos/webmrt/parity.test.mjs                  # JS demo vs Python (needs node >= 18)
```

The tests train the real model and check behaviour; nothing is a stored answer: determinism, held-out skill on the
sample (R² > 0.75), shade lowering midday T<sub>mrt</sub>, plausible ranges, solar altitude against an independent
pvlib call and against the solstice geometry, and the colour-threshold fractions on synthetic fisheye images with
known composition.

## Results, stated carefully

| | R² | RMSE (°C) | MAPE (%) | MBE (°C) |
|---|---|---|---|---|
| Paper (full model, full data) | 0.92 | 3.43 | 5.33 | 0.20 |
| This code on the full table (run locally, 648 held-out rows) | 0.915 | 3.40 | 5.22 | 0.13 |
| This code on the bundled sample (136 held-out rows) | 0.854 | 4.51 | 6.92 | −0.24 |

The second row is close to the paper but is *not* claimed to be a reproduction: library versions and the exact
evaluation protocol of the paper may differ. The third row is what you get from the bundled sample: a smaller
training set gives a weaker model, as expected.

## Known behaviour of the deployed tool (kept as is)

These are reproduced on purpose, so that this code behaves like the live tool, and documented so nobody is surprised.
Each is worth a look by the maintainers.

1. **`min_from_sunrise` uses a fixed reference instant.** The tool computes the sunrise of 2023-12-04 once and
   subtracts it from every chosen date-time. Because `LocationInfo("Phoenix", "US/Arizona")` carries no coordinates,
   astral falls back to its default observer (Greenwich), giving 07:47:07 on 2023-12-04. For June to August dates the
   feature is therefore about −200,000 minutes, far below the training range (132 to 912), and the trees treat it
   as "below every split". The prediction then effectively depends on the other seven features. The training
   column holds true minutes since sunrise on the measurement day. `solar.min_from_sunrise(dt, "same_day")`
   computes that for comparison (in the cases we checked it moved predictions by up to about 1.5 °C).
2. **Night-time and very early/late hours are extrapolation.** Field data are almost all daytime, so predictions for
   a sun below the horizon are not supported by data.
3. **`Shade_AtMeasurement`** takes the values 0, 1 and 2 in the training data; the tool passes 0 or 1.
4. **Library versions.** With numpy 1.24 / pandas 2.0, importing pandas before lightgbm 4.7 crashed LightGBM
   (access violation) in our test environment; numpy 1.26 / pandas 2.2 worked. `requirements.txt` pins safe floors.

## Limitations

* Phoenix-Tempe summer data only (measurements 2016-07-12 to 2019-07-15); not valid elsewhere or in other seasons.
* Inputs outside the training ranges (for example more than 54% trees or 86% buildings) are extrapolated.
* The sample is for demonstration; use the full dataset for any scientific use.

## License

Apache License 2.0, see [LICENSE](LICENSE) and [NOTICE](NOTICE). `data/sample_RF_Data.csv` is a seeded sample of the lab's MaRTy field measurements, included for demonstration; use the full dataset for any scientific use.
