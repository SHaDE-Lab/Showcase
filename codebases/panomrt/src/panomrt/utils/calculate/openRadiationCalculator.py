import numpy as np
from .radiationCalculator import radiationCalc
import math
from .. import definitions as d
from . import calc


class openRadiationCalculator(radiationCalc):
    def __init__(self, atmosphericRadiation):
        super().__init__(atmosphericRadiation)

    def computeDirectShortwave(self, opticalThickness, extraterrestrialRadiation, relativeOpticalAirMass, atmosphericPressure):
        return extraterrestrialRadiation * math.exp(-d.C_LINKE_TURBIDITY * opticalThickness
                                                    * relativeOpticalAirMass * atmosphericPressure / d.C_PRESSURE_AT_SEA_LEVEL)

    def computeMeanRadiantFluxDensity(self, averageDiffuseShortwaveByDirection, averageLongWaveByDirection,
                                      incomingRadiation, surfaceProjectionFactor, sunVisible, skyViewFactor, directShortWave):
        meanRadiantFluxDensity = (d.C_BODY_ABSORPTION / d.C_BODY_EMISSION) * \
            calc.directionalSum(averageDiffuseShortwaveByDirection)

        meanRadiantFluxDensity += calc.directionalSum(
            averageLongWaveByDirection)

        if(sunVisible):
            meanRadiantFluxDensity += d.C_BODY_ABSORPTION / \
                d.C_BODY_EMISSION * directShortWave * surfaceProjectionFactor

        return meanRadiantFluxDensity
