#
#   Matthew Huff
#
#

import numpy as np
import math

class fisheyeProjection:
    # Both Rectangular and Fisheye should be 512, numImages should be 6
    def __init__(self, resolutionRectangular, resolutionFisheye, numImages):
        self.resolutionRectangular = resolutionRectangular
        self.nRectangularPoints = resolutionRectangular * resolutionRectangular
        self.resolutionFisheye = resolutionFisheye
        self.nFisheyePoints = resolutionFisheye * resolutionFisheye
        self.fisheyeHistogramData = np.zeros(self.nFisheyePoints)

        self.nCells = 2 * (resolutionRectangular-1)*(resolutionRectangular-1)
        self.pointCoords = np.zeros((5, self.nRectangularPoints*3))
        self.radiusPerImage = np.zeros((5, self.nRectangularPoints))
        self.fractionPerImage = np.zeros((5, self.nRectangularPoints))

        if(not self.tryReadingData()):
            self.produceFisheyeImages(numImages)
            self.compute180FisheyeProjection(numImages)
            self.computeWeights(numImages)
            self.calculateFractions(numImages)
            self.rotateMatrices(numImages)

    def tryReadingData(self):
        try:
            for i in range(5):
                self.pointCoords[i] = np.loadtxt("fisheyeProjection/point_coords{}.txt".format(str(i)))
                self.fractionPerImage[i] = np.loadtxt("fisheyeProjection/fraction_image{}.txt".format(str(i)))
                self.radiusPerImage[i] = np.loadtxt("fisheyeProjection/radius_image{}.txt".format(str(i)))
            return True
        except:
            return False


    def writeImages(self):
        for i in range(5):
            np.savetxt('radius_image' + str(i) + '.txt',
                       self.radiusPerImage[i], delimiter=',')
            np.savetxt('fraction_image' + str(i) + '.txt',
                       self.fractionPerImage[i], delimiter=',')
            np.savetxt('point_coords'+str(i)+'.txt',
                       self.pointCoords[i], delimiter=',')

    def produceDeformedRectangularImages(self, numImages):

        connectivityList = np.zeros((5, self.nCells, self.nCells * 4))
        for i in range(5):
            cIndex = 0
            cL = connectivityList[i]
            for x in range(self.resolutionRectangular-1):
                for y in range(self.resolutionRectangular-1):
                    topLeftCorner = y * self.resolutionRectangular + x
                    cL[cIndex] = 3
                    cL[cIndex+1] = topLeftCorner
                    cL[cIndex+2] = topLeftCorner + 1
                    cL[cIndex+3] = topLeftCorner + self.resolutionRectangular
                    cIndex += 4

                    cL[cIndex] = 3
                    cL[cIndex+1] = topLeftCorner + 1
                    cL[cIndex+2] = topLeftCorner + \
                        1 + self.resolutionRectangular
                    cL[cIndex+3] = topLeftCorner + self.resolutionRectangular
                    cIndex += 4

    # Compute positions on cube
    #       T
    #      LCR
    #       B

    def produceFisheyeImages(self, numImages):
        offset = (self.resolutionRectangular-1)/2
        # print(offset)
        # Center

        pointCoords = self.pointCoords[4]
        pIndex = 0
        for y in range(self.resolutionRectangular-1, -1, -1):
            for x in range(self.resolutionRectangular):
                pointCoords[pIndex] = x - offset
                pointCoords[pIndex+1] = y - offset
                pointCoords[pIndex+2] = offset
                pIndex += 3

        # Left

        pointCoords = self.pointCoords[3]
        pIndex = 0
        for y in range(self.resolutionRectangular):
            for x in range(self.resolutionRectangular-1, -1, -1):
                pointCoords[pIndex] = -offset
                pointCoords[pIndex+1] = offset - x
                pointCoords[pIndex+2] = y - offset
                pIndex += 3

        # Right
        pointCoords = self.pointCoords[1]
        pIndex = 0
        for y in range(self.resolutionRectangular):
            for x in range(self.resolutionRectangular-1, -1, -1):
                pointCoords[pIndex] = offset
                pointCoords[pIndex+1] = x - offset
                pointCoords[pIndex+2] = y - offset
                pIndex += 3

        # Top
        pointCoords = self.pointCoords[0]
        pIndex = 0
        for y in range(self.resolutionRectangular):
            for x in range(self.resolutionRectangular):
                pointCoords[pIndex] = x - offset
                pointCoords[pIndex+1] = offset
                pointCoords[pIndex+2] = y - offset
                pIndex += 3

        # Bottom
        pointCoords = self.pointCoords[2]
        pIndex = 0
        for y in range(self.resolutionRectangular):
            for x in range(self.resolutionRectangular-1, -1, -1):
                pointCoords[pIndex] = x - offset
                pointCoords[pIndex+1] = -offset
                pointCoords[pIndex+2] = y - offset
                pIndex += 3

    def compute180FisheyeProjection(self, numImages):
        scale = int(self.resolutionFisheye / 2)
        offset = self.resolutionFisheye / 2

        for d in range(5):
            pointCoords = self.pointCoords[d]
            radius = self.radiusPerImage[d]
            pIndex = 0
            numNeg = 0
            for i in range(self.nRectangularPoints):
                x = pointCoords[pIndex]
                y = pointCoords[pIndex+1]
                z = pointCoords[pIndex+2]
                pIndex += 3

                if(z >= 0):
                    # perform unit sphere projection
                    temp = x*x + y*y
                    l = math.sqrt(temp+(z*z))

                    # get inclination angle
                    theta = math.acos(z / l)

                    # normalize radius
                    r = theta / (math.pi/2)

                    # perform equiangular fisheye projection
                    l = math.sqrt(temp)

                    rls = r / l * scale
                    x = rls * x + offset
                    y = rls * y + offset
                    z = 0

                    radius[i] = r
                else:
                    x = offset
                    y = offset
                    z = -1

                    radius[i] = -1
                    numNeg += 1
            # print(numNeg)
            #self.radiusPerImage[d] = radius
        # print("")

    def computeWeights(self, numImages):
        for d in range(5):
            pointCoords = self.pointCoords[d]
            pIndex = 0
            for i in range(self.nRectangularPoints):
                x = pointCoords[pIndex]
                y = pointCoords[pIndex+1]
                z = pointCoords[pIndex+2]
                pIndex += 3

                if(z < 0):
                    continue

                xIndex = x
                yIndex = y

                self.fisheyeHistogramData[int((yIndex *
                                               self.resolutionFisheye) + xIndex)] += 1

    def calculateFractions(self, numImages):
        for d in range(5):
            pointCoords = self.pointCoords[d]
            fraction = self.fractionPerImage[d]
            pIndex = 0
            for i in range(self.nRectangularPoints):

                x = pointCoords[pIndex]
                y = pointCoords[pIndex+1]
                z = pointCoords[pIndex+2]
                pIndex += 3

                if(z < 0):
                    fraction[int(pIndex / 3) - 1] = -1
                else:
                    xIndex = x
                    yIndex = y
                    fraction[int(pIndex/3)-1] = 1 / \
                        self.fisheyeHistogramData[int(yIndex *
                                                      self.resolutionFisheye + xIndex)]

    def rotateMatrices(self, numImages):
        bottomRadius = self.radiusPerImage[2]
        bottomFraction = self.fractionPerImage[2]

        # Top
        radius = self.radiusPerImage[0]
        fraction = self.fractionPerImage[0]
        for y in range(self.resolutionRectangular):
            for x in range(self.resolutionRectangular):
                i = y * self.resolutionRectangular + x
                j = (self.resolutionRectangular-1-y) * \
                    self.resolutionRectangular+x
                radius[i] = bottomRadius[j]
                fraction[i] = bottomFraction[j]
        #self.radiusPerImage[0] = radius

        # Right
        radius = self.radiusPerImage[1]
        fraction = self.fractionPerImage[1]
        for y in range(self.resolutionRectangular):
            for x in range(self.resolutionRectangular):
                i = y * self.resolutionRectangular + \
                    ((self.resolutionRectangular-1) - x)
                j = x * self.resolutionRectangular + y
                radius[i] = bottomRadius[j]
                fraction[i] = bottomFraction[j]
        #self.radiusPerImage[1] = radius

        # Left
        radius = self.radiusPerImage[3]
        fraction = self.fractionPerImage[3]
        for y in range(self.resolutionRectangular):
            for x in range(self.resolutionRectangular):
                i = y * self.resolutionRectangular + x
                j = x * self.resolutionRectangular + y
                radius[i] = bottomRadius[j]
                fraction[i] = bottomFraction[j]

    def checkMatrices(self):
        total = 0
        for m in range(5):
            for i in range(len(self.radiusPerImage[m])):
                if(self.radiusPerImage[m][i] < 0):
                    total += 1
            total = 0

        for i in range(5):
            np.savetxt('radius'+str(i)+'.csv',
                       self.radiusPerImage[i].reshape((512, 512)), delimiter=',')
