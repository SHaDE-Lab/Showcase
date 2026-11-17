import math

import numpy as np
import pytest

from panomrt.utils import definitions as d
from panomrt.utils.calculate import calc
from panomrt.utils.calculate.PET_fsolve_code import PET, resolution
from panomrt.utils.calculate.UTCI import calcUTCI
from panomrt.utils.calculate.lindbergRadiationCalculator import lindbergRadiationCalculator
from panomrt.utils.calculate.openRadiationCalculator import openRadiationCalculator

L_ATM = calc.getAtmosphericRadiation(30, 15, 0)


def utci(ta, tmrt, v, rh):
    return calcUTCI(ta, v, tmrt, calc.getVaporPressure(rh, ta))


def pet(ta, tmrt, rh, v):
    t_stable = resolution(ta, tmrt, rh, v, 35, 1, 1.8, 80, 1, 80, 0.5, [38, 40, 40])[0]
    return PET(35, 1, 1.8, 75, 1, 80, 0.5, t_stable, -40, 90, 10e-6)


# ---- mean radiant temperature from the radiant flux density ----

@pytest.mark.parametrize("t_c", [-10, 0, 25, 40, 70])
def test_mrt_inverts_the_stefan_boltzmann_law(t_c):
    flux = d.C_BODY_EMISSION * d.C_STEFAN_BOLTZMANN * (t_c + 273.15) ** 4
    assert lindbergRadiationCalculator(L_ATM).computeMeanRadiantTemperature(flux) == pytest.approx(t_c, abs=1e-6)


def test_extraterrestrial_radiation_is_largest_in_january():
    calc_ = lindbergRadiationCalculator(L_ATM)
    assert calc_.getExterrestrialRadiation(3) > calc_.getExterrestrialRadiation(185)
    assert calc_.getExterrestrialRadiation(3) == pytest.approx(1414, abs=5)


# ---- long wave ----

def test_longwave_of_a_surface_follows_stefan_boltzmann_and_sky_is_colder():
    calc_ = lindbergRadiationCalculator(L_ATM)
    surface = np.full(4, 40.0)
    seg = np.array([0, 0, 1, 1])                                    # first two pixels surface, last two sky
    lw = calc_.computeLongWaveRadiation(surface, 15.0, 30.0, seg)
    expected_surface = d.C_ENV_EMISSION * d.C_STEFAN_BOLTZMANN * (313.15 ** 4) + (1 - d.C_ENV_EMISSION) * L_ATM
    assert lw[0] == pytest.approx(expected_surface)
    assert lw[2] < lw[0]                                            # a clear sky radiates less than a 40 C wall
    assert lw[2] == pytest.approx(d.C_STEFAN_BOLTZMANN * 303.15 ** 4 * 0.75, rel=0.25)


# ---- short wave ----

def test_cloudless_global_radiation_vanishes_with_the_sun_below_the_horizon():
    calc_ = lindbergRadiationCalculator(L_ATM)
    assert calc_.getGlobalRadiationCloudless(1360, 0.0, 101325) == 0
    assert calc_.getGlobalRadiationCloudless(1360, 0.9, 101325) > 600


def test_overcast_diffuse_scales_with_sky_view_factor_and_cloud_blend():
    calc_ = lindbergRadiationCalculator(L_ATM)
    assert calc_.getDiffuseRadiationOvercast(800, 0.5) == pytest.approx(800 * 0.28 * 0.5)
    assert calc_.getDiffuseRadiation(100, 50, 0) == 100
    assert calc_.getDiffuseRadiation(100, 50, 1) == 50
    assert calc_.getDiffuseRadiation(100, 50, 0.5) == pytest.approx(75)


def test_lindberg_shortwave_gives_direct_sun_only_to_faces_that_look_at_it():
    calc_ = lindbergRadiationCalculator(L_ATM)
    diffuse = [20.0] * 6
    lit = calc_.computeShortwave(0.8, diffuse, 600.0, 53.0, 180.0, 1, 1)         # sun in the south
    shaded = calc_.computeShortwave(0.8, diffuse, 600.0, 53.0, 180.0, 1, 0)
    assert len(lit) == 6
    assert lit[4] > shaded[4] + 500                                              # the face looking up gets the beam
    south = max(lit[:4])
    assert south > min(lit[:4]) + 100                                            # only one lateral face is lit
    assert all(shaded[i] == pytest.approx(shaded[0]) for i in range(4))          # in shade all four sides are equal


def test_open_method_adds_the_direct_beam_only_when_the_sun_is_visible():
    calc_ = openRadiationCalculator(L_ATM)
    sw, lw = np.full(6, 30.0), np.full(6, 420.0)
    sunny = calc_.computeMeanRadiantFluxDensity(sw, lw, 700, 0.3, 1, 0.8, 700)
    shady = calc_.computeMeanRadiantFluxDensity(sw, lw, 700, 0.3, 0, 0.8, 700)
    assert sunny - shady == pytest.approx((d.C_BODY_ABSORPTION / d.C_BODY_EMISSION) * 700 * 0.3)


# ---- thermal comfort indices ----

def test_utci_is_close_to_air_temperature_in_calm_neutral_conditions():
    assert utci(25, 25, 0.5, 50) == pytest.approx(25, abs=1.5)
    assert utci(10, 10, 1.0, 50) == pytest.approx(10, abs=1.5)


def test_utci_rises_with_radiant_load_and_falls_with_wind():
    assert utci(35, 60, 1, 30) > utci(35, 40, 1, 30) > utci(35, 35, 1, 30)
    assert utci(35, 60, 4, 30) < utci(35, 60, 0.5, 30)


def test_pet_is_near_air_temperature_in_the_shade_and_rises_with_mrt():
    assert pet(20, 20, 50, 0.1) == pytest.approx(20, abs=2.5)
    assert pet(35, 35, 30, 1) < pet(35, 50, 30, 1) < pet(35, 65, 30, 1)


def test_pet_and_utci_agree_on_the_ordering_of_hot_and_mild_places():
    hot, mild = (40, 70, 10, 1), (28, 30, 40, 1)
    assert pet(hot[0], hot[1], hot[2], hot[3]) > pet(mild[0], mild[1], mild[2], mild[3])
    assert utci(hot[0], hot[1], hot[3], hot[2]) > utci(mild[0], mild[1], mild[3], mild[2])
