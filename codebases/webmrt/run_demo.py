"""Regenerate the browser-demo assets from this code.

    python run_demo.py [--data path/to/RF_Data.csv] [--out ../../demos/webmrt/data]

Trains the LightGBM model exactly as src/webmrt/model.py does (default: on data/sample_RF_Data.csv), then writes
  model.json   the trained trees in a compact flat form (for the JavaScript evaluator in demos/webmrt/demo.js)
  golden.json  Python reference values: model predictions, pvlib solar position, held-out predictions, metrics
The JavaScript demo is verified against golden.json by demos/webmrt/parity.test.mjs.
"""
import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))
import webmrt as w  # noqa: E402  (lightgbm is imported first inside the package)
from pvlib import solarposition  # noqa: E402
from webmrt.solar import LATITUDE, LONGITUDE, PHOENIX  # noqa: E402

PAPER = {"r2": 0.92, "rmse": 3.43, "mape": 5.33, "mbe": 0.20}  # AlKhaled et al. 2024, full model


def flatten_tree(node, out):
    """LightGBM dump_model nested tree -> flat arrays. Children: index >= 0 is a split node, ~index is a leaf."""
    splits, leaves = out["split"], out["leaf"]

    def walk(n):
        if "leaf_value" in n:
            leaves.append(n["leaf_value"])
            return ~(len(leaves) - 1)
        i = len(splits)
        splits.append(None)
        assert n["decision_type"] == "<=" and n["missing_type"] == "None", n
        left, right = walk(n["left_child"]), walk(n["right_child"])
        splits[i] = [n["split_feature"], n["threshold"], left, right]
        return i

    root = walk(node)
    return root


def export_model(booster):
    dump = booster.dump_model()
    trees = []
    for t in dump["tree_info"]:
        out = {"split": [], "leaf": []}
        root = flatten_tree(t["tree_structure"], out)
        trees.append({"root": root, "f": [s[0] for s in out["split"]], "t": [s[1] for s in out["split"]],
                      "l": [s[2] for s in out["split"]], "r": [s[3] for s in out["split"]], "v": out["leaf"]})
    assert dump["average_output"] is False and dump["objective"].startswith("regression")
    # Gain importance: total loss reduction contributed by splits on each feature (LightGBM's own measure),
    # normalised to sum to 1. This, not the number of splits, is what "feature importance" means; a yes/no
    # input such as "shaded" needs few splits but can have a very large effect.
    gain = [float(g) for g in booster.feature_importance(importance_type="gain")]
    tot = sum(gain) or 1.0
    return {"features": dump["feature_names"], "trees": trees, "importance_gain": [g / tot for g in gain]}


def solar_reference(date, time):
    dt = datetime.strptime(f"{date} {time}", "%Y-%m-%d %H:%M")
    sp = solarposition.get_solarposition(PHOENIX.localize(dt), LATITUDE, LONGITUDE)
    return {"date": date, "time": time, "elevation": float(sp["elevation"].iloc[0]),
            "azimuth": float(sp["azimuth"].iloc[0])}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=None)
    ap.add_argument("--out", default=str(Path(__file__).resolve().parents[2] / "demos" / "webmrt" / "data"))
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)

    booster, metrics = w.train_model(a.data)
    model = export_model(booster)
    model["sunrise_as_deployed"] = w.SUNRISE_AS_DEPLOYED.strftime("%Y-%m-%d %H:%M:%S")
    model["site"] = {"latitude": LATITUDE, "longitude": LONGITUDE, "utc_offset_hours": -7}
    model["params"] = w.LGBM_PARAMS
    (out / "model.json").write_text(json.dumps(model, separators=(",", ":")))

    # golden model predictions (through the same code path the live tool uses)
    rng = np.random.default_rng(7)
    cases = []
    for i in range(300):
        frac = rng.dirichlet([1.0, 1.0, 1.0])
        date = f"2023-{rng.integers(6, 9):02d}-{rng.integers(1, 29):02d}"
        time = f"{rng.integers(5, 20):02d}:{rng.choice([0, 15, 30, 45]):02d}"
        row = w.build_feature_row(date, time, frac[0], frac[1], frac[2], rng.random(), int(rng.integers(0, 2)),
                                  float(rng.uniform(26, 44)))
        cases.append({"in": {"date": date, "time": time, "svf": frac[0], "trees": frac[1], "buildings": frac[2],
                             "pervious": float(row[3]), "shaded": row[4], "airC": row[5]},
                      "row": row, "tmrt": w.predict_tmrt(booster, row)})

    solar = [solar_reference(d, t) for d in ("2023-06-01", "2023-06-21", "2023-07-15", "2023-08-31")
             for t in ("05:00", "06:30", "09:00", "12:30", "15:45", "18:30", "19:45")]

    X_train, X_test, y_train, y_test = w.load_training_data(a.data)
    pred = booster.predict(np.asarray(X_test, dtype=np.float64), num_threads=1)
    golden = {"cases": cases, "solar": solar,
              "heldout": {"observed": [round(float(v), 3) for v in y_test],
                          "predicted": [round(float(v), 3) for v in pred]},
              "metrics": metrics, "paper_metrics": PAPER,
              "training": {"source": Path(a.data).name if a.data else "sample_RF_Data.csv",
                           "n_train": int(len(y_train)), "n_test": int(len(y_test))}}
    (out / "golden.json").write_text(json.dumps(golden, separators=(",", ":")))
    print("sample-model held-out metrics:", {k: round(v, 3) for k, v in metrics.items()})
    print("wrote", out)


if __name__ == "__main__":
    main()
