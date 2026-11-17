import numpy as np
from .radiationCalculator import radiationCalc
from . import calc
from .. import definitions as d
import math


class lindbergRadiationCalculator(radiationCalc):
    def __init__(self, atmosphericRadiation):
        super().__init__(atmosphericRadiation)
        self.debug = 0

    def computeDirectShortwave(self, diffuse_r, global_r, solarAltitude):
        return (global_r - diffuse_r) / math.sin(math.radians(solarAltitude))

    def getI(self, sinGamma, opticalThickness, extraterrestrialRadiation, relativeOpticalAirMass, atmosphericPressure, solarAltitude):
        return extraterrestrialRadiation * sinGamma * math.exp(-d.C_LINKE_TURBIDITY * opticalThickness
                                                    * relativeOpticalAirMass * atmosphericPressure / d.C_PRESSURE_AT_SEA_LEVEL)

    def computeMeanRadiantFluxDensity(self, shortwave, longwave):
        return d.C_BODY_ABSORPTION * calc.directionalSum(shortwave) + d.C_BODY_EMISSION * calc.directionalSum(longwave)


    def computeShortwave(self, sinGamma, diffuseShortwave, direct_shortwave, solarAltitude, azimuthAngle, Sb, Sv):
        
        if(sinGamma != 0):
            I_Prime = direct_shortwave/sinGamma
        else:
            I_Prime = 0
        # lateral directions divided by sin of altitude, diffuse not included
        
        if(Sv == 1):
            k_down = (direct_shortwave + diffuseShortwave[4])
            # math.sin(math.radians(solarAltitude))) +
            k_up = .2 * k_down + diffuseShortwave[5]
        else:
            k_down = diffuseShortwave[4]
            k_up = diffuseShortwave[5]
        k = []
        angles = [(-270, 90), (0, 180), (90, 270), (180, 360)]
        additions = [90, 0, -90, -180]

        #add albedo * kdown * .5 to klateral if sunvis to lateral
        for i in range(4):
            if(i == 0):
                if(((azimuthAngle >= 270 and azimuthAngle < 360) or (azimuthAngle >= 0 and azimuthAngle < 90)) and Sv == 1):
                    if(azimuthAngle >= 270 and azimuthAngle < 360):
                        daz = azimuthAngle - 270
                    elif(azimuthAngle >= 0 and azimuthAngle < 90):
                        daz = azimuthAngle + 90

                    k.append((I_Prime * math.cos(math.radians(
                        solarAltitude)) * math.sin(math.radians(daz))) + diffuseShortwave[i]) 
                else:
                    k.append(diffuseShortwave[i])
            else:
                if((azimuthAngle >= angles[i][0] and azimuthAngle < angles[i][1]) and Sv == 1):
                    daz = azimuthAngle + additions[i]
                    k.append((I_Prime * math.cos(math.radians(
                        solarAltitude)) * math.sin(math.radians(daz))) + diffuseShortwave[i])
                   
                else:
                    k.append(diffuseShortwave[i])

        #all 4 directions have added half of k_down * albedo
        for i in range(4):
            k[i] = k[i] + (k_down * 0.5 * 0.2)

        k.append(k_down)
        k.append(k_up)
        # Multiply all 6 values by d.C_BODY_ABSOPTION (0.7)
        for i in range(6):
            k[i] = k[i] * 1
        if(self.debug):
            print("K: ")
            print(k)
        return k
