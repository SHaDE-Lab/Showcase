"""End-to-end runs on synthetic panoramas: equirectangular thermal image -> cube faces -> fisheye views -> SVF ->
radiation budget -> MRT, UTCI, PET. Slow because the code loops over every pixel in pure Python (about a minute per site)."""
import math
import os
import subprocess
import sys
from types import SimpleNamespace

import pandas as pd
import pytest

from panomrt.PanoMRT import Entrance

pytestmark = pytest.mark.slow

ROW = {"date": "6/21/2020", "time": "12:00:00 PM", "site": 100, "shade": 0, "airtc_avg": 38.0, "mrt": 60.0,
       "ws_ms_avg": 1.0, "rh": 15.0, "latitude": 33.42, "longitude": -111.935, "altitude": 331.0}


def args(**kw):
    base = dict(file=["x.csv"], images=["x"], output="out.csv", method="lindberg", sunVisibleLabel=False, num=0, offset=0, j=1,
                hours=[6, 9, 12, 15, 18, 20], verbose=False, debug=False, sunVisible=1, print=False, pano=True)
    base.update(kw)
    return SimpleNamespace(**base)


@pytest.fixture(scope="module")
def engine():
    e = Entrance(args())
    e.df = pd.DataFrame([ROW])
    return e


def run(engine, folder, sun_visible, method="lindberg"):
    engine.args.sunVisible = sun_visible
    engine.args.method = method
    return engine.runSingleCalculation(0, 0, folder + os.sep)


@pytest.fixture(scope="module")
def results(engine, panos):
    return {
        "open_sun": run(engine, panos["open"], 1),
        "open_shade": run(engine, panos["open"], 0),
        "enclosed_sun": run(engine, panos["enclosed"], 1),
    }


def test_outputs_are_finite_and_physically_plausible(results):
    for r in results.values():
        for key in ("Pano_MRT", "UTCI", "PET", "skyViewFactor", "MRFD"):
            assert math.isfinite(r[key]), key
        assert 0 < r["Pano_MRT"] < 100
        assert 10 < r["UTCI"] < 70 and 10 < r["PET"] < 70
        assert 0.0 <= r["skyViewFactor"] <= 1.0


def test_sky_view_factor_separates_open_from_enclosed_places(results):
    assert results["open_sun"]["skyViewFactor"] > 0.85
    assert results["enclosed_sun"]["skyViewFactor"] < 0.55


def test_sun_geometry_at_solar_noon_in_tempe(results):
    r = results["open_sun"]
    assert r["solarAltitude"] == pytest.approx(78, abs=3)
    assert r["dZenithAngle"] == pytest.approx(12, abs=3)


def test_direct_sun_raises_mrt_and_the_comfort_indices(results):
    sun, shade = results["open_sun"], results["open_shade"]
    assert sun["Pano_MRT"] > shade["Pano_MRT"] + 10
    assert sun["UTCI"] > shade["UTCI"] and sun["PET"] > shade["PET"]


def test_more_sky_means_more_diffuse_light(results):
    assert results["open_sun"]["diffuseRadiation"] > results["enclosed_sun"]["diffuseRadiation"]


def test_open_method_runs_without_measured_radiation_columns(engine, panos):
    r = run(engine, panos["open"], 1, method="open")
    assert math.isfinite(r["Pano_MRT"]) and 0 < r["Pano_MRT"] < 100
    assert math.isnan(r["DS_Diff0"])                                          # no measured SW_ columns in the input


def test_command_line_writes_the_output_csv(tmp_path, panos):
    data = tmp_path / "data.csv"
    pd.DataFrame([{"DATE": ROW["date"], "TIME": ROW["time"], "Site": ROW["site"], "Shade": 0, "AirTC_Avg": ROW["airtc_avg"],
                   "MRT": ROW["mrt"], "WS_ms_Avg": ROW["ws_ms_avg"], "RH": ROW["rh"], "Latitude": ROW["latitude"],
                   "Longitude": ROW["longitude"]}]).to_csv(data, index=False)
    out = tmp_path / "out.csv"
    src = os.path.join(os.path.dirname(__file__), "..", "src")
    env = dict(os.environ, PYTHONPATH=src)
    done = subprocess.run([sys.executable, "-m", "panomrt", "-f", str(data), "-i", panos["open"] + os.sep, "-o", str(out),
                           "--pano", "-sv", "1"], capture_output=True, text=True, env=env, timeout=900)
    assert done.returncode == 0, done.stderr[-2000:]
    table = pd.read_csv(out)
    assert list(table.columns) == ["date", "time", "site", "MRT_MaRTy", "Pano_MRT", "UTCI", "PET"]
    assert len(table) == 1 and 0 < table.loc[0, "Pano_MRT"] < 100


def test_command_line_rejects_num_with_several_data_files(tmp_path):
    src = os.path.join(os.path.dirname(__file__), "..", "src")
    done = subprocess.run([sys.executable, "-m", "panomrt", "-f", "a.csv", "b.csv", "-i", "x", "--num", "3"],
                          capture_output=True, text=True, env=dict(os.environ, PYTHONPATH=src))
    assert done.returncode != 0 and "Cannot pass num or offset" in done.stderr
