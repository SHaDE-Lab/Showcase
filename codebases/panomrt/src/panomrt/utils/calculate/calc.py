import math
from .. import definitions as d
import numpy as np


def getSurfaceProjectionFactor(gamma):
    return 0.308 * math.cos(math.radians(gamma) * (0.998 - math.pow(math.radians(gamma), 2)))


def getVaporPressure(relativeHumidity, airTemperature):
    return (relativeHumidity / 100) * (6.11 * math.pow(10, 7.5 * (airTemperature / (273.15 + airTemperature))))


def getAtmosphericPressure(altitude):
    return 101325 * math.pow(1 - (2.25577 / 1e5 * altitude), 5.25588)


def getRelativeOpticalAirMass(gamma, sinGamma):
    if(gamma < 0):
        return 0.0408
    else:
        return 1 / (sinGamma + 0.50572 * math.pow(gamma + 6.07995, -1.6364))


def getOpticalThickness(gamma, relativeOpticalAirMass):
    if(gamma < 0):
        return 0.0408
    elif(gamma < 1):
        return 0.0435
    elif(gamma < 2):
        return 0.0463
    elif(gamma < 3):
        return 0.0491
    elif(gamma < 4):
        return 0.0519
    elif(gamma < 5):
        return 0.0548
    else:
        return 1 / (0.9 * relativeOpticalAirMass + 9.4)


def computeSkyViewFactor(segmentationsPerDirection, fractionBottomData, fractionCenterData,
                         ringIndiciesBottom, ringIndiciesCenter):

    nRings = 32
    nPoints = 512 * 512
    ringTotal = np.zeros(nRings)
    ringSky = np.zeros(nRings)

    for d in range(5):
        segmentation = segmentationsPerDirection[d].flatten()
        if(d < 4):
            ringIndicies = ringIndiciesBottom
            fraction = fractionBottomData
        else:
            ringIndicies = ringIndiciesCenter
            fraction = fractionCenterData

        for i in range(nPoints):
            f = fraction[i]

            if(f < 0):
                continue

            ringIndex = ringIndicies[i]
            ringTotal[int(ringIndex)] += f
            if(segmentation[i] == 1):
                ringSky[int(ringIndex)] += f

    svf = 0
    temp = nRings / math.pi

    for i in range(1, nRings):

        svf += math.sin((i+0.5)/temp) * (ringSky[i]/ringTotal[i])

    svf *= math.pi / (2*nRings)
    return svf


def directionalSum(arr):
    return (.22 * (arr[0] + arr[1] + arr[2] + arr[3])) + (.06 * (arr[4] + arr[5]))


def getAtmosphericRadiation(airTemperature, vaporPressure, cloudCover):
    return d.C_STEFAN_BOLTZMANN * (math.pow(airTemperature + 273.15, 4) *
                                   (0.82-0.25 * math.pow(10, -0.0945 * vaporPressure)) *
                                   (1 + 0.21 * math.pow(cloudCover, 2.5)))
