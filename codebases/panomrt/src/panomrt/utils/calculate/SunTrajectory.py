import datetime
import math


class SunTrajectory:

    def __init__(self, date, long, lat):
        self.date = date
        self.long = long
        self.lat = lat
        self.dEarthMeanRadius = 6371.01
        self.dAstronomicalUnit = 149597890
        self.azimuthAngle = 0

    def getSunPosition(self, debug=0):
        rad = math.pi/180
        decimalHours = (self.date.hour + (self.date.minute/60))
        liAux1 = (self.date.month - 14)/12
        liAux2 = (1461.0 * ((self.date.year) + 4800 + liAux1)) / 4.0 + (367.0 * (self.date.month - 2 -
                                                                                 12 * liAux1)) / 12 - (3 * (((self.date.year) + 4900 + liAux1)/100)) / 4 + self.date.day - 32075.0

        julianDate = liAux2 - 0.5 + (decimalHours / 24)
        elapsedJulianDays = julianDate - 2451545

        dOmega = 2.1429 - 1.0394594e-3 * elapsedJulianDays
        dMeanLongitude = 4.895063 + 0.017202791698*elapsedJulianDays
        dMeanAnomaly = 6.24006 + 0.0172019699*elapsedJulianDays
        dEclipticLongitude = dMeanLongitude + 0.03341607 * \
            math.sin(dMeanAnomaly) + 3.4894e-4 * \
            math.sin(2 * dMeanAnomaly) - 1.134e-4 - 2.03e-5 * math.sin(dOmega)

        dEclipticObliquity = 0.4090928 - 6.214e-9 * \
            elapsedJulianDays + 3.96e-5 * math.cos(dOmega)

        # Celestial coordinates

        dSin_EclipticLongitude = math.sin(dEclipticLongitude)
        dY = math.cos(dEclipticObliquity) * dSin_EclipticLongitude
        dX = math.cos(dEclipticLongitude)

        dRightAscension = math.atan2(dY, dX)
        if(dRightAscension < 0):
            dRightAscension = dRightAscension + 2 * math.pi

        dDeclination = math.asin(
            math.sin(dEclipticObliquity) * dSin_EclipticLongitude)

        # Local coordinates in degrees

        dGreenwichMeanSiderealTime = 6.6974243242 + \
            0.0657098283 * elapsedJulianDays + decimalHours

        dLocalMeanSiderealTime = (
            dGreenwichMeanSiderealTime * 15 + self.long) * rad

        dHourAngle = dLocalMeanSiderealTime - dRightAscension
        dLatitudeInRadians = self.lat*rad
        dCos_Latitude = math.cos(dLatitudeInRadians)
        dSin_Latitude = math.sin(dLatitudeInRadians)
        dCos_HourAngle = math.cos(dHourAngle)

        dZenithAngle = math.acos(dCos_Latitude*dCos_HourAngle *
                                 math.cos(dDeclination) + math.sin(dDeclination)*dSin_Latitude)

        dY = -math.sin(dHourAngle)
        dX = math.tan(dDeclination) * dCos_Latitude - \
            dSin_Latitude * dCos_HourAngle
        dAzimuth = math.atan2(dY, dX)
        if(dAzimuth < 0):
            dAzimuth += math.pi * 2
        dAzimuth = dAzimuth / rad
        self.azimuthAngle = dAzimuth

        dParallax = (self.dEarthMeanRadius /
                     self.dAstronomicalUnit) * math.sin(dZenithAngle)
        dZenithAngle = (dZenithAngle + dParallax) / rad

        return dZenithAngle

    # Solar altitude is related to the zenith such that
    # the cosine of one is equal to the sin of the other
    # Return the inverse sine of the cosine of the zenith angle
    # converted to degrees
    def getSolarAltitude(self):
        return math.asin(math.cos(self.getSunPosition() * (math.pi / 180))) * (180 / math.pi)
