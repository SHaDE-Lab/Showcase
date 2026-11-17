import argparse

# from numpy.lib.function_base import average, kaiser
from .utils.calculate.openRadiationCalculator import openRadiationCalculator
from .utils.calculate.lindbergRadiationCalculator import lindbergRadiationCalculator
from .utils.calculate import calc
from .utils.image.imageReader import ImageReader
from .utils.image.fisheyeProjection import fisheyeProjection
from .utils.calculate.SunTrajectory import SunTrajectory
from .utils.calculate.UTCI import calcUTCI
from .utils.calculate.PET_fsolve_code import PET, resolution
from .utils import definitions as d
import tempfile
from .utils.image.pano2cube import panorama_to_cubemap

import math
import multiprocessing as mp
import pandas as pd
import datetime
from datetime import timedelta
import numpy as np
import os


class Entrance:
    def __init__(self, args, debug=0):
        self.args = args
        self.fp = fisheyeProjection(512, 512, 6)
        self.fractionsByFisheyeSubset = self.fp.fractionPerImage
        self.radiiByFisheyeSubset = self.fp.radiusPerImage
        
        # Initialize these critical attributes here instead of in parser method
        self.dataFileNames = []
        self.imageFolders = []
        
        # Process args that were passed from __main__.py
        if hasattr(args, 'file') and args.file is not None:
            self.dataFileNames = self.removeEndCommasFromListOfStrings(args.file)
            
        if hasattr(args, 'images') and args.images is not None:
            self.imageFolders = self.removeEndCommasFromListOfStrings(args.images)
            
        # Initialize rowLabels and other attributes
        self.rowLabels = ['ID', 'date', 'time', 'site', 'shade', 'airTC_avg', 'MRT_MaRTy', 'WS', 'RH', 'Latitude', 'Longitude', 'Altitude', 'SW_0', 'SW_1', 'SW_2', 'SW_3', 'SW_4', 'SW_5', 'LW_MaRTy_0', 'LW_MaRTy_1', 'LW_MaRTy_2', 'LW_MaRTy_3', 'LW_MaRTy_4', 'LW_MaRTy_5',
        'cloudCover', 'sinceStart', 'solarAltitude', 'sin_SA', 'cos_SA', 'sin_AA', 'dZenithAngle', 'azimuthAngle', 'skyViewFactor', 'gamma', 
        'sinGamma', 'vaporPressure', 'atmosphericRadiation', 'extraterrestrialRadiation', 'atmosphericPressure', 'relativeOpticalAirMass', 'opticalThickness', 
        'incomingRadiationCloudless', 'diffuseRadiationCloudless', 'diffuseRadiationOvercast', 'diffuseRadiation', 
        'LW_0', 'LW_Diff0', 'LW_1', 'LW_Diff1', 'LW_2', 'LW_Diff2', 'LW_3', 'LW_Diff3', 'LW_4', 'LW_Diff4', 'LW_5', 'LW_Diff5', 'directShortwave', 'GRC-DRC', 'directionalShortwave0', 
        'DS_Diff0', 'directionalShortwave1', 'DS_diff1', 'directionalShortwave2', 'DS_Diff2', 'directionalShortwave3', 'DS_Diff3', 'directionalShortwave5', 'DS_Diff5', 'MRFD', 'Pano_MRT', 'UTCI', 'PET', 'diff']

        self.labels = {
            'ID' : int,
            'date' : datetime.date 
        }
        self.rowArguments = [
            'date', 'time', 'site', 'shade', 'airtc_avg', 'mrt', 'ws_ms_avg', 'rh',
            'latitude', 'longitude', 'altitude'
        ]
        # self.rowArguments = [
        #     'date', 'time', 'site', 'shade', 'airtc_avg', 'mrt', 'ws_ms_avg', 'rh',
        #     'latitude', 'longitude', 'altitude', 'sr_left_avg', 'sr_right_avg',
        #     'sr_front_avg', 'sr_back_avg', 'sr_up_avg', 'sr_down_avg',
        #     'ir_left_corr_avg', 'ir_right_corr_avg', 'ir_front_corr_avg',
        #     'ir_back_corr_avg', 'ir_up_corr_avg', 'ir_down_corr_avg'
        # ]
        self.outputRowArguments = ['date', 'time', 'site', 'shade', 'airTC_Avg',
                                   'MRT_MaRTy', 'WS', 'RH', 'Latitude', 'Longitude', 'Altitude', 'SW_0', 'SW_1', 'SW_2', 'SW_3', 'SW_4', 'SW_5',
                                   'LW_MaRTy_0', 'LW_MaRTy_1', 'LW_MaRTy_2', 'LW_MaRTy_3', 'LW_MaRTy_4', 'LW_MaRTy_5']
        self.additionalRowArguments = [
            'sunVisible', 'cloudCover', 'ID']
            
        # Set debug from args
        if hasattr(args, 'debug'):
            self.debug = args.debug
        else:
            self.debug = debug

        self.results = []

    def removeEndCommasFromListOfStrings(self, lst):
        l = []
        for item in lst:
            if(item.endswith(',')):
                l.append(item[:-1])
            else:
                l.append(item)
        return l

    def addToCSV_str(self, string, data):
        return string + "," + str(data)

    def fillInformation(self, index):
        row = self.df.iloc[index]
        rowData = {}
        rowData['ID'] = index
        sunExposed = 0 if int(row['shade']) != 0 else 1

        for i in range(len(self.rowArguments)):
            rowData[self.outputRowArguments[i]] = row[self.rowArguments[i]]

        rowData['cloudCover'] = 0
        return rowData

    def openDataFile(self, name):
        try:
            df = pd.read_csv(name)
            df.columns = df.columns.str.lower()
            if 'altitude' not in df.columns:
                df['altitude'] = 0
            return df
        except:
            print(
                "Error opening datafile.  Check pathway of file and ensure the filename ends with .csv")

    def createSunTrajectory(self, ID, rowData):
        dt = rowData['date'] + " " + rowData['time']
        d = datetime.datetime.strptime(dt, '%m/%d/%Y %I:%M:%S %p')
        d = d.__add__(timedelta(hours=7))
        startOfYear = datetime.datetime(year=d.year, month=1, day=1)
        sinceStart = d - startOfYear
        rowData['sinceStart'] = sinceStart.days
        self.st = SunTrajectory(
            d, rowData['Longitude'], rowData['Latitude'])
        
        return rowData

    def getSunPositionToImageCoordinates(self):
        zaRad = math.radians(self.st.getSunPosition())
        aRad = math.radians(self.st.azimuthAngle)

        x = math.sin(zaRad) * math.cos(aRad)
        y = math.sin(zaRad) * math.sin(aRad)
        z = math.cos(zaRad)

        r = math.atan2(math.sqrt(x*x+y*y), z) / math.pi
        phi = math.atan2(y, x)

        size = 512
        i = size - (r * math.cos(phi)+0.5) * size
        j = (r * math.sin(phi)+0.5) * size
        return (int(i)-1, int(j)-1)

    def sunVisible(self, segmentationsPerDirection, fractionBottomData, fractionCenterData,
                   ringIndiciesBottom, ringIndiciesCenter, x, y, time, SA):

        if(self.args.sunVisible != -1):
            return self.args.sunVisible
        i, j = self.getSunPositionToImageCoordinates()

        i -= 256
        j -= 256
        seg = 0
        d = datetime.datetime.strptime(time, '%I:%M:%S %p')
        if(d.hour < 10 and self.st.azimuthAngle < 80): # TODO: should not be segmenting by azimuth angle
            seg = 0
        elif(d.hour > 17 and self.st.azimuthAngle > 280):
            seg = 3
        else:
            seg = 4

        p = self.fp.pointCoords[seg]
        loc = 0

        segmentation = segmentationsPerDirection[seg].flatten()
        p = self.fp.pointCoords[seg]
        while True:
            w = 0
            b = 0
            for loc in range(512*512*3):

                if(math.floor(p[loc]) == i and math.floor(p[loc+1]) == j):

                    # check fraction
                    newLoc = int(loc / 3)
                    x = newLoc % 512
                    y = int(newLoc / 512)

                    # Redo this fix.  Try/except block that moved through the possible segmentations
                    if(self.fp.fractionPerImage[seg][512*x+y] < 0):
                        if(self.debug):
                            print(
                                "SEGMENTATION {} NOT SUITABLE FOR I, J".format(seg))
                        if(seg < 4):
                            if(seg == 3):
                                seg = 0
                            else:
                                seg += 1
                        elif(seg == 4):
                            seg = 0
                        continue
                    
                    for q in range(-1, 2):
                        for r in range(-1, 2):

                            if(segmentation[512 * (x + q)+(y + r)] == 1):
                                w += 1
                            else:
                                b += 1

            if(self.debug):
                if(w > b):
                    print("SKY VISIBLE FOR SEGMENTATION {}".format(str(seg)))
                else:
                    print("SKY NOT VISIBLE FOR SEGMENTATION {}".format(str(seg)))
            if (w > b):
                return 1
            else:
                return 0

    def panoramasExist(self, folderName):
        fileNames = []
        for r, d, f in os.walk(folderName):
            for file in f:
                fileNames.append(os.path.join(r, file))
        if(len(fileNames) > 0):
            return 1
        else:
            print("No panoramas found in {}".format(folderName))
            return 0
        
    def runSingleCalculation(self, ID, index, imageLoc):
        rowData = self.fillInformation(index)
        rowData = self.createSunTrajectory(ID, rowData)
        if(self.debug):
            print(rowData['time'])
            print(rowData['site'])
        if(self.args.verbose):
            print("Running site {} at time {} on {}".format(rowData['site'], rowData['time'], rowData['date']))
        imageSetFolder = self.getImageSetFolder(
            rowData['date'], rowData['time'], rowData['site'])
        if self.args.pano:
            import os as _os
            pan_folder = _os.path.join(imageLoc, imageSetFolder)
            panorama_path = None
            for f in _os.listdir(pan_folder):
                if f.lower().endswith(('.jpg', '.png')):
                    panorama_path = _os.path.join(pan_folder, f)
                    break
            if panorama_path is None:
                raise FileNotFoundError(f"No panorama image found in {pan_folder}")
            temp_dir = tempfile.mkdtemp()
            panorama_to_cubemap(panorama_path, temp_dir, cube_size=512)
            self.ir = ImageReader(temp_dir)
            self.surfaceTemperature = self.ir.files # TODO: should introduce code reuse for image data loading
            self.segmentationData = self.ir.segmentationData
        else:
            self.getImages(imageLoc, imageSetFolder)

        if self.args.sunVisibleLabel:
            row = self.df.iloc[index]
            
            try:
                if(int(row['shade']) != 0):
                    SV = 0
                else:
                    SV = 1
            except KeyError:
                if(int(row['shade'] != 0)):
                    SV = 0
                else:
                    SV = 1
        else:
            SV = self.sunVisible(self.segmentationData, 0,
                            self.fractionsByFisheyeSubset[4], 0, 0, 0, 0, rowData['time'], self.st.getSolarAltitude())

        if(self.debug):
            print("SV is {}".format(SV))
        rowData['sunVisible'] = SV

        ringIndiciesByFisheyeSubset = np.empty((5, 512*512))
        solarAltitude = self.st.getSolarAltitude()
        if(solarAltitude > 90):
            solarAltitude = 90 - (solarAltitude - 90)
        rowData['solarAltitude'] = solarAltitude

        rowData['sin_SA'] = math.sin(math.radians(rowData['solarAltitude']))
        rowData['cos_SA'] = math.cos(math.radians(rowData['solarAltitude']))
        rowData['sin_AA'] = math.sin(math.radians(self.st.azimuthAngle))

        for e in range(5):
            radii = self.radiiByFisheyeSubset[e]
            ringIndicies = ringIndiciesByFisheyeSubset[e]
            for i in range(512*512):
                ringIndicies[i] = int((radii[i] * d.N_RINGS))

        rowData['dZenithAngle'] = self.st.getSunPosition(debug=self.debug)
        rowData['azimuthAngle'] = self.st.azimuthAngle

        SVF = calc.computeSkyViewFactor(self.segmentationData, self.fractionsByFisheyeSubset[2],
                                                                       self.fractionsByFisheyeSubset[4], ringIndiciesByFisheyeSubset[2], ringIndiciesByFisheyeSubset[4])
        rowData['skyViewFactor'] = SVF

        rowData['gamma'] = 90 - rowData['dZenithAngle']
        gamma = 90 - rowData['dZenithAngle']

        if(rowData['gamma'] < 0):
            sinGamma = 0
        else:
            sinGamma = math.sin(math.radians(rowData['gamma']))

        rowData['sinGamma'] = sinGamma

        VP = calc.getVaporPressure(rowData['RH'], rowData['airTC_Avg'])
        rowData['vaporPressure'] = VP

        atmosphericRadiation = calc.getAtmosphericRadiation(
            rowData['airTC_Avg'], rowData['vaporPressure'], rowData['cloudCover'])
        rowData['atmosphericRadiation'] = atmosphericRadiation

        if(self.args.method == 'open'):
            radCalc = openRadiationCalculator(
                rowData['atmosphericRadiation'])
            rowData['surfaceProjectionFactor'] = calc.getSurfaceProjectionFactor(rowData['gamma'])
        elif(self.args.method == 'lindberg'):
            radCalc = lindbergRadiationCalculator(
                rowData['atmosphericRadiation'])
            

        extraterrestrialRadiation = radCalc.getExterrestrialRadiation(rowData['sinceStart'])
        rowData['extraterrestrialRadiation'] = extraterrestrialRadiation

        atmosphericPressure = calc.getAtmosphericPressure(rowData['Altitude'])
        rowData['atmosphericPressure'] = atmosphericPressure

        relativeOpticalAirMass = calc.getRelativeOpticalAirMass(rowData['gamma'], rowData['sinGamma'])
        rowData['relativeOpticalAirMass'] = relativeOpticalAirMass

        opticalThickness = calc.getOpticalThickness(rowData['gamma'], rowData['relativeOpticalAirMass'])
        rowData['opticalThickness'] = opticalThickness

        incomingRadiationCloudless = radCalc.getIncomingRadiationCloudless(rowData['extraterrestrialRadiation'], rowData['sinGamma']
                                                                                                , rowData['opticalThickness'], rowData['relativeOpticalAirMass'], rowData['atmosphericPressure'])
        rowData['incomingRadiationCloudless'] = incomingRadiationCloudless

        incomingRadiation = radCalc.getIncomingRadiation(
            rowData['incomingRadiationCloudless'], rowData['cloudCover'])
        rowData['incomingRadiation'] = incomingRadiation

        globalRadiationCloudless = radCalc.getGlobalRadiationCloudless(
            rowData['extraterrestrialRadiation'], rowData['sinGamma'], rowData['atmosphericPressure'])
        rowData['globalRadiationCloudless'] = globalRadiationCloudless

        diffuseRadiationCloudless = radCalc.getDiffuseRadiationCloudless(rowData['globalRadiationCloudless'], rowData['extraterrestrialRadiation']
                                                                        , rowData['incomingRadiationCloudless'], rowData['sinGamma'], rowData['skyViewFactor'], rowData['sunVisible'])
        rowData['diffuseRadiationCloudless'] = diffuseRadiationCloudless

        diffuseRadiationCloudless = radCalc.getDiffuseRadiationOvercast(
            rowData['globalRadiationCloudless'], rowData['skyViewFactor'])
        rowData['diffuseRadiationOvercast'] = diffuseRadiationCloudless

        diffuseRadiation = radCalc.getDiffuseRadiation(
            rowData['diffuseRadiationCloudless'], rowData['diffuseRadiationOvercast'], rowData['cloudCover'])
        rowData['diffuseRadiation'] = diffuseRadiation

        longWaveRadiation = np.zeros((6, 512*512))
        for i in range(6):
            longWaveRadiation[i] = radCalc.computeLongWaveRadiation(
                self.surfaceTemperature[i], rowData['vaporPressure'], rowData['airTC_Avg'], self.segmentationData[i].flatten())
        averageDiffuseShortwaveByDirection = np.zeros(6)
        averageLongWaveByDirection = np.zeros(6)

        averageDiffuseShortwaveByDirection, averageLongWaveByDirection = radCalc.computeAverageRadiationForEachDirection(
            rowData['diffuseRadiation'],
            longWaveRadiation,
            ringIndiciesByFisheyeSubset,
            self.fractionsByFisheyeSubset
        )
        # ? don't think this is needed
        # for i in range(6):
        #     rowData['LW_' + str(i)] = averageLongWaveByDirection[i]

        #     LW_diff = averageLongWaveByDirection[i] - rowData['LW_MaRTy_'+str(i)]
        #     rowData["LW_Diff" + (str(i))] = LW_diff

        if(self.args.method == 'open'):
            rowData['directShortwave'] = radCalc.computeDirectShortwave(
                rowData['opticalThickness'], rowData['extraterrestrialRadiation'], rowData['relativeOpticalAirMass'], rowData['atmosphericPressure'])

            for i in range(len(averageDiffuseShortwaveByDirection)):
                rowData['directionalDiffuseShortwave_' + str(i)] = averageDiffuseShortwaveByDirection[i]
                rowData['DS_Diff'+str(i)] = averageDiffuseShortwaveByDirection[i] - rowData.get('SW_'+str(i), float('nan'))   # SW_ columns exist only when measured radiation is supplied
            MRFD = radCalc.computeMeanRadiantFluxDensity(averageDiffuseShortwaveByDirection, averageLongWaveByDirection, rowData['incomingRadiation']
                                                                              , rowData['surfaceProjectionFactor'], rowData['sunVisible'], rowData['skyViewFactor'], rowData['directShortwave'])
            rowData['MRFD'] = MRFD

        elif(self.args.method == 'lindberg'):
            
            try:
                if(math.sin(math.radians(self.st.getSolarAltitude())) < 0):
                    rowData['directShortwave'] = 0
                else:
                    I = radCalc.getI(rowData['sinGamma'],
                                     rowData['opticalThickness'],
                                     rowData['extraterrestrialRadiation'],
                                     rowData['relativeOpticalAirMass'],
                                     rowData['atmosphericPressure'],
                                     rowData['solarAltitude'])
                    rowData['directShortwave'] = I

            except ZeroDivisionError:
                rowData['directShortwave'] = rowData['incomingRadiation']

            Sb = 1
            Sv = 1
            if(rowData['sunVisible'] == 0):
                Sb = 1
                Sv = 0

            GRCminusDRC = globalRadiationCloudless - diffuseRadiationCloudless
            rowData['GRC-DRC'] = rowData['globalRadiationCloudless'] - rowData['diffuseRadiationCloudless']

            sw_directional = radCalc.computeDirectShortwave(
                rowData['diffuseRadiationCloudless'], rowData['globalRadiationCloudless'], rowData['solarAltitude'])
            shortwave = radCalc.computeShortwave(
                rowData['sinGamma'], averageDiffuseShortwaveByDirection, rowData['directShortwave'], rowData['solarAltitude'], self.st.azimuthAngle, Sb, Sv)
            # ? don't think this is needed
            # for i in range(len(shortwave)):
            #     directionalSW = shortwave[i] - averageDiffuseShortwaveByDirection[i]
            #     rowData['directionalShortwave' + str(i)] = directionalSW

            #     DS_Diff = shortwave[i] - rowData['SW_' + str(i)]
            #     rowData['DS_Diff' + str(i)] = DS_Diff

            MRFD = radCalc.computeMeanRadiantFluxDensity(shortwave, averageLongWaveByDirection)
            rowData['MRFD'] = MRFD
   
        PanoMRT = radCalc.computeMeanRadiantTemperature(MRFD)
        rowData['Pano_MRT'] = PanoMRT

        UTCI = calcUTCI(rowData['airTC_Avg'], rowData['WS'], rowData['Pano_MRT'], rowData['vaporPressure'])
        rowData['UTCI'] = UTCI

        tStable = resolution(rowData['airTC_Avg'], rowData['Pano_MRT'],
                             rowData['RH'], rowData['WS'], 35, 1, 1.8, 80, 1, 80, 0.5, [38, 40, 40])[0]
        PET_val =  PET(35, 1, 1.8, 75, 1, 80, 0.5, tStable, -40, 90, 10e-6)
        rowData['PET'] = PET_val

        if(self.debug):
            print("----")
            print("Location: {}".format(rowData['site']))
            print("Date: {}".format(rowData['date']))
            print("Time: {}".format(rowData['time']))
            print("Calculated MRT: {}".format(rowData['Pano_MRT']))
        return rowData

    def getImageSetFolder(self, date, time, siteNum, override = 0):
        if(override != 0):
            return override
        dt = date + " " + time
        d = datetime.datetime.strptime(dt, '%m/%d/%Y %I:%M:%S %p')
        month = str(d.month)
        if(d.month < 10):
            month = "0" + month
        if(d.day < 10):
            day = '0' + str(d.day)
        else:
            day = d.day
        imageSetFolder = str(d.year) + month + str(day) + "_" + \
            str(int(siteNum)) + str(self.getClosestHourInList(d.hour, d.minute))

        return imageSetFolder

    def getImages(self, imageLoc, imageSetFolder):
        self.ir = ImageReader(imageLoc+imageSetFolder)

        self.surfaceTemperature = self.ir.files
        self.segmentationData = self.ir.segmentationData

    def runCalcs_WORKER(self, arr):
        localResults = []
        for k in range(len(self.dataFileNames)):
            for i in arr:
                site = self.df['site'][i]
                date = self.df['date'][i]
                time = self.df['time'][i]
                imageSetFolder = self.getImageSetFolder(date, time, site)
                if(self.panoramasExist(self.imageFolders[k] + imageSetFolder)):
                    rowData = self.runSingleCalculation(i, i, self.imageFolders[k])
                    localResults.append(rowData)
                else:
                    continue
        return localResults

    def runCalculations(self):
        # Check if dataFileNames and imageFolders have been set
        if not hasattr(self, 'dataFileNames') or not self.dataFileNames:
            raise ValueError("No data file names provided. Use the -f/--file option.")
            
        if not hasattr(self, 'imageFolders') or not self.imageFolders:
            raise ValueError("No image folders provided. Use the -i/--images option.")
            
        # Now proceed with the calculations
        if(len(self.dataFileNames) == len(self.imageFolders)):
            for k in range(len(self.dataFileNames)):
                self.df = self.openDataFile(self.dataFileNames[k])

        if(self.args.num > 0):
            if(self.args.offset > 0):
                numRuns = self.args.num + self.args.offset
            else:
                numRuns = self.args.num
        else:
            numRuns = len(self.df) 
        locationIDs = np.arange(self.args.offset, numRuns)

        #Split into j (num_threads) arrays for workers
        split = np.array_split(locationIDs, self.args.j)

        p = mp.Pool(processes=self.args.j)
        workerResults = p.map(self.runCalcs_WORKER, split)
        p.close()

        for chunk in workerResults:
            self.results.extend(chunk)

        self.combineData()

    def combineData(self):
        # Build a simple DataFrame from self.results
        newRows = [["date", "time", "site", "MRT_MaRTy", "Pano_MRT", "UTCI", "PET"]]
        for rd in self.results:
            newRows.append([
                rd.get('date', ''),
                rd.get('time', ''),
                rd.get('site', ''),
                rd.get('MRT_MaRTy', ''),
                rd.get('Pano_MRT', ''),
                rd.get('UTCI', ''),
                rd.get('PET', '')
            ])
        df = pd.DataFrame(newRows[1:], columns=newRows[0])
        df.to_csv(self.args.output, index=False)

    def getClosestHourInList(self, hour, minute):
        if(minute > 30):
            hour += 1
        if(self.args.hours == []):
            availableTimes = [6, 9, 12, 15, 18, 20]
        else:
            availableTimes = self.args.hours
        smallestTime = 24
        smallestIndex = 0
       
        for i in range(6):
            if(abs(hour - availableTimes[i]) < smallestTime):
                smallestTime = abs(hour-availableTimes[i])
                smallestIndex = i
        
        if(availableTimes[smallestIndex] < 10):
            return "0" + str(availableTimes[smallestIndex])
        else:
            return str(availableTimes[smallestIndex])

    def main(self):
        if self.args.verbose:
            print("Running with the following arguments:")
            print(self.args)
        return self.runCalculations()
