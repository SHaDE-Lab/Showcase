"""Solar features, checked against an independent pvlib call and basic astronomy."""
from datetime import datetime

import pandas as pd
import pytest
from pvlib import solarposition

import webmrt as w
from webmrt.solar import LATITUDE, LONGITUDE


def independent_elevation(dt):
    ts = pd.Timestamp(dt, tz="Etc/GMT+7")  # fixed UTC-7: Phoenix has no daylight saving
    return float(solarposition.get_solarposition(ts, LATITUDE, LONGITUDE)["elevation"].iloc[0])


@pytest.mark.parametrize("dt", [datetime(2023, 6, 21, 12, 30), datetime(2023, 7, 15, 9, 0),
                                datetime(2023, 8, 31, 18, 45), datetime(2023, 6, 1, 5, 0)])
def test_altitude_matches_independent_pvlib(dt):
    assert w.solar_altitude(dt) == pytest.approx(independent_elevation(dt), abs=1e-6)


def test_solstice_noon_altitude_is_physical():
    # latitude 33.45 N, declination +23.44 deg -> about 80 deg at solar noon (about 12:30 local in Phoenix)
    best = max(w.solar_altitude(datetime(2023, 6, 21, 12, m)) for m in range(0, 60, 5))
    assert best == pytest.approx(90 - LATITUDE + 23.44, abs=0.7)
    assert w.solar_altitude(datetime(2023, 6, 21, 2, 0)) < 0  # night


def test_min_from_sunrise_as_deployed_is_the_fixed_instant_difference():
    dt = datetime(2023, 12, 4, 10, 47, 7)
    assert w.SUNRISE_AS_DEPLOYED == datetime(2023, 12, 4, 7, 47, 7)
    assert w.min_from_sunrise(dt) == 180
    assert w.min_from_sunrise(datetime(2023, 7, 15, 13, 0)) < -200000  # summer date, fixed December instant


def test_min_from_sunrise_same_day_is_minutes_since_phoenix_sunrise():
    # July 15 Phoenix sunrise is about 05:30 MST -> 13:00 is about 450 min later
    assert w.min_from_sunrise(datetime(2023, 7, 15, 13, 0), "same_day") == pytest.approx(450, abs=10)
    with pytest.raises(ValueError):
        w.min_from_sunrise(datetime(2023, 7, 15, 13, 0), "nonsense")
