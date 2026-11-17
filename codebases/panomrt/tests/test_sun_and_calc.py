import datetime
import math

import pytest

from panomrt.utils import definitions as d
from panomrt.utils.calculate import calc
from panomrt.utils.calculate.SunTrajectory import SunTrajectory

LON, LAT = -111.935, 33.42          # Tempe, Arizona (no daylight saving; the pipeline adds 7 h to reach UTC)


def sun(hour, month=6, day=21):
    t = datetime.datetime(2020, month, day, hour) + datetime.timedelta(hours=7)
    st = SunTrajectory(t, LON, LAT)
    return st, st.getSunPosition()


def test_solar_noon_zenith_matches_latitude_and_declination():
    _, zenith = sun(12)
    assert zenith == pytest.approx(LAT - 23.44, abs=2.0)           # about 10 degrees at the June solstice


def test_winter_noon_sun_is_lower_than_summer_noon():
    assert sun(12, 12, 21)[1] > sun(12, 6, 21)[1] + 30


def test_sun_is_below_the_horizon_at_night_and_above_by_day():
    assert sun(2)[1] > 90 and sun(12)[1] < 90


def test_azimuth_goes_from_east_in_the_morning_to_west_in_the_afternoon():
    morning, _ = sun(8)
    morning.getSunPosition()
    afternoon, _ = sun(16)
    afternoon.getSunPosition()
    assert 45 < morning.azimuthAngle < 135
    assert 225 < afternoon.azimuthAngle < 315


def test_solar_altitude_is_the_complement_of_zenith():
    st, zenith = sun(10)
    assert st.getSolarAltitude() == pytest.approx(90 - zenith, abs=1e-6)


def test_directional_weights_sum_to_one():
    assert calc.directionalSum([1] * 6) == pytest.approx(1.0)       # 4 x 0.22 + 2 x 0.06
    assert calc.directionalSum([0, 0, 0, 0, 1, 0]) == pytest.approx(0.06)


def test_relative_optical_air_mass():
    assert calc.getRelativeOpticalAirMass(90, 1.0) == pytest.approx(1.0, abs=0.01)    # sun overhead
    assert calc.getRelativeOpticalAirMass(10, math.sin(math.radians(10))) > 4          # low sun, long path
    assert calc.getRelativeOpticalAirMass(-5, 0) == 0.0408                             # below the horizon


@pytest.mark.parametrize("gamma,expected", [(-1, 0.0408), (0.5, 0.0435), (1.5, 0.0463), (2.5, 0.0491), (3.5, 0.0519), (4.5, 0.0548)])
def test_optical_thickness_table_near_the_horizon(gamma, expected):
    assert calc.getOpticalThickness(gamma, 5.0) == expected


def test_optical_thickness_formula_above_five_degrees():
    assert calc.getOpticalThickness(30, 2.0) == pytest.approx(1 / (0.9 * 2.0 + 9.4))


def test_atmospheric_pressure_falls_with_altitude():
    assert calc.getAtmosphericPressure(0) == pytest.approx(101325)
    assert calc.getAtmosphericPressure(331) == pytest.approx(97411, rel=1e-3)      # Tempe
    assert calc.getAtmosphericPressure(2000) < calc.getAtmosphericPressure(331)


def test_vapour_pressure_is_proportional_to_relative_humidity_and_rises_with_temperature():
    assert calc.getVaporPressure(50, 30) == pytest.approx(calc.getVaporPressure(100, 30) / 2)
    assert calc.getVaporPressure(40, 40) > calc.getVaporPressure(40, 20) > calc.getVaporPressure(40, 0)
    assert calc.getVaporPressure(0, 30) == 0


@pytest.mark.xfail(strict=True, reason="getVaporPressure writes 273.15 + T where the Magnus formula has 237.3 + T, "
                                       "so it underestimates saturation vapour pressure (19.8 hPa at 20 C instead of 23.4). "
                                       "Kept as published; this test documents the deviation.")
def test_saturation_vapour_pressure_matches_magnus_at_20_c():
    assert calc.getVaporPressure(100, 20) == pytest.approx(23.4, rel=0.02)


def test_atmospheric_radiation_is_in_a_physical_range_and_grows_with_cloud():
    clear = calc.getAtmosphericRadiation(30, 15, 0)
    cloudy = calc.getAtmosphericRadiation(30, 15, 1)
    assert 300 < clear < 450
    assert cloudy == pytest.approx(clear * 1.21)


def test_surface_projection_factor_is_a_fraction_for_moderate_sun_heights():
    for gamma in (0, 20, 45):
        assert 0 < calc.getSurfaceProjectionFactor(gamma) < 0.4


@pytest.mark.xfail(strict=True, reason="getSurfaceProjectionFactor uses the sun height in radians and no /50000 term, so it turns "
                                       "negative above about 60 degrees; the Fanger form 0.308 cos(g (0.998 - g^2/50000)), g in degrees, "
                                       "gives 0.078 at 90 degrees. Only the 'open' method uses it. Kept as published; this test documents the deviation.")
def test_surface_projection_factor_matches_the_fanger_form_for_a_high_sun():
    g = 90.0
    assert calc.getSurfaceProjectionFactor(g) == pytest.approx(0.308 * math.cos(math.radians(g * (0.998 - g ** 2 / 50000))), abs=0.01)


def test_definitions_are_consistent():
    assert d.C_STEFAN_BOLTZMANN == pytest.approx(5.67e-8, rel=0.01)
    assert d.N_RINGS == 32 and d.numLayers == 4
