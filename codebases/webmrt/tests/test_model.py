"""Model checks: real training on the bundled sample, no stored answers."""
import os

import numpy as np
import pandas as pd
import pytest

import webmrt as w


@pytest.fixture(scope="module")
def trained():
    return w.train_model()  # (booster, held-out metrics) on data/sample_RF_Data.csv


def test_training_is_deterministic(trained):
    booster, metrics = trained
    booster2, metrics2 = w.train_model()
    row = w.build_feature_row("2023-07-15", "13:00", 0.5, 0.25, 0.25, 0.5, 0, 40)
    assert w.predict_tmrt(booster, row) == w.predict_tmrt(booster2, row)
    assert metrics == metrics2


def test_held_out_skill_on_the_sample(trained):
    _, m = trained
    # The sample model is small (about 450 rows): demand real skill, not the paper's numbers.
    assert m["r2"] > 0.75, m
    assert m["rmse"] < 6.5, m
    assert abs(m["mbe"]) < 2.0, m
    assert m["n_test"] == pytest.approx(0.3 * len(pd.read_csv(w.model.DEFAULT_DATA)), abs=1)


def test_pervious_normalisation_spans_zero_to_one():
    X_train, X_test, _, _ = w.load_training_data()
    allp = pd.concat([X_train["surr_pervious"], X_test["surr_pervious"]])
    assert allp.min() == pytest.approx(0.0) and allp.max() == pytest.approx(1.0)
    assert list(X_train.columns) == w.X_COLUMNS


def test_shade_lowers_tmrt_at_midday(trained):
    booster, _ = trained
    for date in ("2023-06-21", "2023-07-15", "2023-08-10"):
        sunny = w.predict_tmrt(booster, w.build_feature_row(date, "13:00", 0.6, 0.2, 0.2, 0.3, 0, 40))
        shaded = w.predict_tmrt(booster, w.build_feature_row(date, "13:00", 0.6, 0.2, 0.2, 0.3, 1, 40))
        assert shaded < sunny - 5, (date, sunny, shaded)


def test_predictions_are_plausible_over_the_day(trained):
    booster, _ = trained
    preds = [w.predict_tmrt(booster, w.build_feature_row("2023-07-15", f"{h:02d}:00", 0.5, 0.25, 0.25, 0.5, 0, 38))
             for h in range(6, 20)]
    assert all(-10 < p < 85 for p in preds)
    assert max(preds) > min(preds) + 3  # not a constant function of time


def test_hotter_air_gives_hotter_tmrt(trained):
    booster, _ = trained
    cool = w.predict_tmrt(booster, w.build_feature_row("2023-07-15", "13:00", 0.5, 0.25, 0.25, 0.5, 0, 30))
    hot = w.predict_tmrt(booster, w.build_feature_row("2023-07-15", "13:00", 0.5, 0.25, 0.25, 0.5, 0, 42))
    assert hot > cool


def test_deployed_sunrise_feature_is_outside_the_training_range():
    """Documented behaviour of the live tool: the fixed (Greenwich) sunrise puts the feature far below the training
    range, where a tree model treats it as 'smaller than every split'. Pin it so any change is noticed."""
    X_train, _, _, _ = w.load_training_data()
    row = w.build_feature_row("2023-07-15", "13:00", 0.5, 0.25, 0.25, 0.5, 0, 40)
    assert row[-1] < X_train["min_from_sunrise"].min() - 1000


@pytest.mark.skipif(not os.environ.get("WEBMRT_FULL_DATA"), reason="set WEBMRT_FULL_DATA=<path to full RF_Data.csv>")
def test_full_dataset_reproduces_paper_scale_metrics():
    _, m = w.train_model(os.environ["WEBMRT_FULL_DATA"])
    assert m["r2"] > 0.90 and m["rmse"] < 4.0, m
