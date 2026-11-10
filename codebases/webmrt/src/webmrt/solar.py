"""Solar features used by WebMRT, derived exactly as the deployed tool (app.py, /predict) derives them.

Original authors: S. R. AlKhaled, A. Middel, P. Shaeri, I. Buo, F. A. Schneider (SHaDE Lab, Arizona State University).
Citation: https://doi.org/10.1016/j.scs.2024.105861
"""
from datetime import datetime

from astral import LocationInfo
from astral.sun import sun
from pvlib import solarposition
from pytz import timezone

# AZ - Phoenix (fixed)
LATITUDE, LONGITUDE = 33.448376, -112.074036
PHOENIX = timezone("America/Phoenix")  # Arizona does not observe daylight saving time

# The deployed model has always been given the sunrise of ONE fixed day (2023-12-04), reduced to a naive datetime;
# `min_from_sunrise` is then the difference between the chosen date-time and THAT instant. It is kept here as is so
# that this code reproduces the live tool. NOTE: LocationInfo("Phoenix", "US/Arizona") carries no coordinates, so
# astral falls back to its default observer (Greenwich, 51.47 N, 0.00 E) and the instant is 07:47:07 (UTC) on
# 2023-12-04. See README ("Known behaviour of the deployed tool").
_sunrise = sun(LocationInfo("Phoenix", "US/Arizona").observer, date=datetime(2023, 12, 4))["sunrise"]
SUNRISE_AS_DEPLOYED = datetime.strptime(_sunrise.replace(microsecond=0).strftime("%Y-%m-%d %H:%M:%S"),
                                        "%Y-%m-%d %H:%M:%S")


def parse_datetime(date_input: str, time_input: str) -> datetime:
    """'2023-06-15', '14:00' -> naive local (Phoenix) datetime."""
    return datetime.strptime(date_input + " " + time_input, "%Y-%m-%d %H:%M")


def solar_altitude(dt: datetime) -> float:
    """Solar elevation (degrees above the horizon) for a naive Phoenix-local datetime."""
    localized = PHOENIX.localize(dt)
    return float(solarposition.get_solarposition(localized, LATITUDE, LONGITUDE)["elevation"].iloc[0])


def min_from_sunrise(dt: datetime, mode: str = "as_deployed") -> int:
    """Minutes from sunrise.

    mode="as_deployed": difference to the fixed 2023-12-04 sunrise instant, as the live tool computes it
                        (truncated toward zero by int()). For June to August dates this is a large negative number.
    mode="same_day":    minutes since the sunrise of the chosen day (what the training column contains), computed
                        with astral for Phoenix. Provided for comparison only.
    """
    if mode == "as_deployed":
        return int((dt - SUNRISE_AS_DEPLOYED).total_seconds() / 60)
    if mode == "same_day":
        observer = LocationInfo("Phoenix", "US/Arizona", latitude=LATITUDE, longitude=LONGITUDE).observer
        s = sun(observer, date=dt.date(), tzinfo=PHOENIX)["sunrise"]
        return int((PHOENIX.localize(dt) - s).total_seconds() / 60)
    raise ValueError("mode must be 'as_deployed' or 'same_day'")
