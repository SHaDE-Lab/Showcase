import numpy as np
import math
from .. import definitions as d


class radiationCalc:

    def __init__(self, atmosphericRadiation):
        self.atmosphericRadiation = atmosphericRadiation
        self.nPixels = 512*512

    def computeLongWaveRadiation(self, surfaceTemperature, vaporPressure, airTemperature, segmentationData):
        surfaceTemperature = surfaceTemperature.flatten()
        surfaceLongWave = np.zeros(len(surfaceTemperature))
        airT = airTemperature + 273.15
        for i in range(len(surfaceTemperature)):
            if(segmentationData[i] == 1):
                e = 46.5 * (vaporPressure/airT)
                epsilonSky = 1 - (1 + e) * \
                    math.exp(-math.sqrt(1.2+3*e))
                surfaceLongWave[i] = epsilonSky * \
                    d.C_STEFAN_BOLTZMANN * (airT**4)
            else:
                Ts = surfaceTemperature[i] + 273.15
                surfaceLongWave[i] = d.C_ENV_EMISSION * d.C_STEFAN_BOLTZMANN * \
                    Ts**2 * Ts**2 + ((1-d.C_ENV_EMISSION) *
                                     self.atmosphericRadiation)

           

        return surfaceLongWave

    def getExterrestrialRadiation(self, dayOfYear):
        return d.G_SC * (1 + 0.03344 * math.cos(math.radians(dayOfYear * 0.9856 - 2.72)))

    def getIncomingRadiationCloudless(self, extraterrestrialRadiation, sinGamma, opticalThickness,
                                      relativeOpticalAirMass, atmosphericPressure):
       
        return (extraterrestrialRadiation * sinGamma * math.exp(-d.C_LINKE_TURBIDITY * opticalThickness * relativeOpticalAirMass * atmosphericPressure / d.C_PRESSURE_AT_SEA_LEVEL))
        

    def getIncomingRadiation(self, incomingRadiationCloudless, cloudCover):
        return incomingRadiationCloudless * (1 - cloudCover)

    def getDiffuseRadiationCloudless(self, globalRadiationCloudless, extraterrestrialRadiation,
                                     incomingRadiationCloudless, sinGamma, skyViewFactor, sunVisible):

        if(sinGamma <= 0):
            return 0

        # incomingRadiation used to be multiplied by sinGamma, reducing it by a lot
        

        globalMinusIncoming = globalRadiationCloudless - incomingRadiationCloudless
        extraterrestrialTimesSinGamma = extraterrestrialRadiation * sinGamma

       
        diffuseIsotropic = globalMinusIncoming * \
            (1 - incomingRadiationCloudless /
             extraterrestrialTimesSinGamma) * skyViewFactor

        diffuseAnisotropic = 0
        if(sunVisible):
            diffuseAnisotropic = globalMinusIncoming * \
                (incomingRadiationCloudless / extraterrestrialTimesSinGamma)
        return diffuseAnisotropic + diffuseIsotropic

    def getDiffuseRadiationOvercast(self, globalRadiationCloudless, skyViewFactor):
        return globalRadiationCloudless * 0.28 * skyViewFactor

    def getDiffuseRadiation(self, diffuseRadiationCloudless, diffuseRadiationOvercast, cloudCover):
        return diffuseRadiationCloudless*(1-cloudCover) + diffuseRadiationOvercast*cloudCover

    # VDI 3789 (19, 20)

    def getGlobalRadiationCloudless(self, extraterrestrialRadiation, sinGamma, atmosphericPressure):
        if(sinGamma <= 0):
            return 0

        return 0.84 * extraterrestrialRadiation * sinGamma * math.exp(
            -0.027 * atmosphericPressure / d.C_PRESSURE_AT_SEA_LEVEL * d.C_LINKE_TURBIDITY / sinGamma)

    def computeAverageRadiationForFisheye(self, diffuseRadiation, longWaveRadiationByDirection,
                                          ringIndiciesByFisheyeSubset, fractionsByFisheyeSubset, longWaveIndicies, fisheyeIndicies, k):

        ringDiffuseShortWave = np.zeros(d.N_RINGS)
        ringLongWave = np.zeros(d.N_RINGS)
        ringTotalFraction = np.zeros(d.N_RINGS)

        diffuseRadiationTerm = diffuseRadiation 

        for i in range(5):

            longWave = longWaveRadiationByDirection[longWaveIndicies[i]]
            ringIndicies = ringIndiciesByFisheyeSubset[fisheyeIndicies[i]]
            fraction = fractionsByFisheyeSubset[fisheyeIndicies[i]]

            for j in range(self.nPixels):
                f = fraction[j]
                if(f < 0):
                    continue

                ringIndex = int(ringIndicies[j])
                ringTotalFraction[ringIndex] += f

                ringLongWave[ringIndex] += longWave[j] * f
                ringDiffuseShortWave[ringIndex] += diffuseRadiationTerm*f

        averageDiffuseShortWave = 0
        averageLongWave = 0

        for i in range(d.N_RINGS):
            averageDiffuseShortWave += ringDiffuseShortWave[i] / \
                ringTotalFraction[i]
            averageLongWave += ringLongWave[i] / ringTotalFraction[i]

        averageDiffuseShortWave = averageDiffuseShortWave / d.N_RINGS
        averageLongWave = averageLongWave / d.N_RINGS

        return (averageDiffuseShortWave, averageLongWave)

    def computeAverageRadiationForEachDirection(self, diffuseRadiation, longWaveRadiation, ringIndicesByFisheyeSubset,
                                                fractionsByFisheyeSubset):

        longwave = np.zeros(6)
        shortwave = np.zeros(6)

        for i in range(6):
            shortwave[i], longwave[i] = self.computeAverageRadiationForFisheye(
                diffuseRadiation, longWaveRadiation,
                ringIndicesByFisheyeSubset, fractionsByFisheyeSubset, d.longWaveIndicies[
                    i], d.fisheyeIndicies[i], i
            )

        return shortwave, longwave

    def computeMeanRadiantTemperature(self, meanRadiantFluxDensity):
        return math.pow(meanRadiantFluxDensity/(d.C_BODY_EMISSION * d.C_STEFAN_BOLTZMANN), 0.25) - 273.15
