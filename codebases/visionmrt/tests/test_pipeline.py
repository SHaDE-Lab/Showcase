"""End to end: segmentation + depth -> SVF -> shadows -> weather -> energy balance -> MRT / UTCI / PET, on both sites.

Expected values in data/expected/*.json were produced by run_demo.py from this same code; the tolerances below absorb
platform and library-version noise only. They are a regression guard, NOT a validation against measurements:
the paper's accuracy comes from 132 measured sites, not from these two."""
import numpy as np
import pytest

import pipeline as P

pytestmark = pytest.mark.slow

MRT_TOL, INDEX_TOL, SVF_TOL = 0.3, 0.3, 0.002          # degrees C, degrees C, unitless
SITES = ["site_a_open", "site_b_enclosed"]


@pytest.mark.parametrize("site", SITES)
def test_matches_stored_expected_outputs(runs, expected, site):
    r, e = runs[site]["results"], expected[site]
    assert runs[site]["svf"] == pytest.approx(e["svf"], abs=SVF_TOL)
    assert r["Hour"].tolist() == e["hours"]
    assert np.allclose(r["MRT_CalcSW_CalcLW"], e["mrt"], atol=MRT_TOL)
    assert np.allclose(r["UTCI"], e["utci"], atol=INDEX_TOL)
    assert np.allclose(r["PET"], e["pet"], atol=INDEX_TOL)
    assert r["SunVisible"].astype(bool).tolist() == e["sun_visible"]


@pytest.mark.parametrize("site", SITES)
def test_physical_plausibility(runs, weather, site):
    r = runs[site]["results"]
    mrt, ta = r["MRT_CalcSW_CalcLW"].to_numpy(), r["AirTemperature"].to_numpy()
    assert len(r) == len(P.SHADOW_HOURS) == 13
    assert np.isfinite(r[["MRT_CalcSW_CalcLW", "UTCI", "PET"]].to_numpy()).all()
    assert ((mrt > 15) & (mrt < 80)).all()                                   # sane for a Phoenix-area June day
    midday = r["Hour"].between(10, 16).to_numpy()
    assert (mrt[midday] > ta[midday] + 10).all()                              # sun-exposed: MRT far above air temperature
    assert mrt[r["Hour"] == 15].item() > mrt[r["Hour"] == 7].item() + 15      # hotter mid-afternoon than at 7 AM
    assert np.corrcoef(mrt, r["UTCI"])[0, 1] > 0.75                           # UTCI follows MRT (it also depends on air temperature, wind, humidity)
    assert (r.loc[midday, "UTCI"].to_numpy() > ta[midday]).all()               # a hot radiant load makes it feel hotter than the air


@pytest.mark.parametrize("site", SITES)
def test_sunlit_hours_are_hotter_than_shaded_hours_at_the_same_site(runs, site):
    r = runs[site]["results"]
    sun = r["SunVisible"].astype(bool).to_numpy()
    assert sun.any() and (~sun).any()
    # compare hours with similar air temperature: late-afternoon shade vs midday sun
    assert r.loc[sun, "MRT_CalcSW_CalcLW"].mean() > r.loc[~sun, "MRT_CalcSW_CalcLW"].mean() + 10


def test_enclosed_site_has_lower_sky_view_than_open_site(runs):
    assert runs["site_b_enclosed"]["svf"] < runs["site_a_open"]["svf"] - 0.1


def test_the_site_that_sees_the_sun_earlier_is_hotter_in_the_morning(runs):
    """At 8 AM the open site (A) is sunlit while the enclosed site (B) is still in shade."""
    a = runs["site_a_open"]["results"].set_index("Hour")
    b = runs["site_b_enclosed"]["results"].set_index("Hour")
    assert bool(a.loc[8, "SunVisible"]) and not bool(b.loc[8, "SunVisible"])
    assert a.loc[8, "MRT_CalcSW_CalcLW"] > b.loc[8, "MRT_CalcSW_CalcLW"] + 10


@pytest.mark.parametrize("site", SITES)
def test_six_direction_components_reproduce_the_model_mrt(runs, site):
    r = runs[site]["results"]
    c = P.radiation_components(r)
    assert np.allclose(c["MRT_from_components"], r["MRT_CalcSW_CalcLW"], atol=0.02)
    assert (c["SW_absorbed"] >= 0).all() and (c["LW_absorbed"] > 300).all()
    noon = c["Hour"] == 12
    assert c.loc[noon, "SW_absorbed"].item() > c.loc[c["Hour"] == 7, "SW_absorbed"].item()


@pytest.mark.parametrize("site", SITES)
def test_outputs_are_written(runs, site):
    r = runs[site]
    assert r["fisheye_up"].exists()
    assert (r["fisheye_up"].parent / "results.csv").exists() and (r["fisheye_up"].parent / "svf.json").exists()
