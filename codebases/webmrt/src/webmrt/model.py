"""WebMRT prediction model: the LightGBM Tmrt regressor exactly as the deployed tool (app.py) builds it.

Original authors: S. R. AlKhaled, A. Middel, P. Shaeri, I. Buo, F. A. Schneider (SHaDE Lab, Arizona State University).
Citation: https://doi.org/10.1016/j.scs.2024.105861

This module trains on whatever CSV it is given. data/sample_RF_Data.csv is a small stratified
sample; pass the full dataset path (or set WEBMRT_DATA) to reproduce the live model.
"""
import os
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.metrics import mean_squared_error, r2_score
from sklearn.model_selection import train_test_split

from .solar import min_from_sunrise, parse_datetime, solar_altitude

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATA = ROOT / "data" / "sample_RF_Data.csv"

X_COLUMNS = ["SVF_Up", "surr_trees", "surr_buildings", "surr_pervious",
             "Shade_AtMeasurement", "AirT_C_detrended", "Solar_Altitude",
             "min_from_sunrise"]
Y_COLUMN = ["MRT_C_detrended"]
LGBM_PARAMS = {"learning_rate": 0.05, "min_data_in_leaf": 10, "n_estimators": 200, "subsample": 0.6,
               "random_state": 42}


def data_path(path=None) -> Path:
    return Path(path or os.environ.get("WEBMRT_DATA") or DEFAULT_DATA)


def load_training_data(path=None):
    """Same preparation as the deployed tool: drop the index column, min-max normalise `surr_pervious`, then a
    70/30 split with random_state=42. Returns X_train, X_test, y_train, y_test."""
    df = pd.read_csv(data_path(path))
    df = df.drop(columns="Unnamed: 0")
    df["surr_pervious"] = (df["surr_pervious"] - df["surr_pervious"].min()) / (
        df["surr_pervious"].max() - df["surr_pervious"].min())
    X_train, X_test, y_train, y_test = train_test_split(df[X_COLUMNS], df[Y_COLUMN], test_size=0.3, random_state=42)
    return (X_train.reset_index(drop=True), X_test.reset_index(drop=True),
            np.ravel(y_train.reset_index(drop=True)), np.ravel(y_test.reset_index(drop=True)))


def train_model(path=None):
    """Train LightGBM; returns (booster, metrics on the held-out 30%)."""
    X_train, X_test, y_train, y_test = load_training_data(path)
    model = lgb.LGBMRegressor(**LGBM_PARAMS, n_jobs=2, verbose=-1)
    model.fit(X_train, y_train)
    return model.booster_, evaluate(model.booster_, X_test, y_test)


def evaluate(booster, X_test, y_test) -> dict:
    """R2, RMSE, MAPE (%), MBE (mean bias error) on a held-out set (the four metrics the paper reports)."""
    pred = booster.predict(np.asarray(X_test, dtype=np.float64), num_threads=1)
    y = np.asarray(y_test, dtype=float)
    return {"r2": float(r2_score(y, pred)),
            "rmse": float(np.sqrt(mean_squared_error(y, pred))),
            "mape": float(np.mean(np.abs((y - pred) / y)) * 100),
            "mbe": float(np.mean(pred - y)),
            "n_test": int(len(y))}


def build_feature_row(date_input, time_input, svf, trees, buildings, pervious, shaded, air_temp_c,
                      sunrise_mode="as_deployed"):
    """Feature vector in X_COLUMNS order for a chosen Phoenix date ('YYYY-MM-DD') and time ('HH:MM')."""
    dt = parse_datetime(date_input, time_input)
    return [float(svf), float(trees), float(buildings), float(pervious), float(shaded), float(air_temp_c),
            solar_altitude(dt), min_from_sunrise(dt, sunrise_mode)]


def predict_tmrt(booster, row) -> float:
    """Predicted Tmrt (degC) for one feature row."""
    return float(booster.predict(np.array([row], dtype=np.float64), num_threads=1)[0])
