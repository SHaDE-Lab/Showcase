import cv2
import numpy as np
import os


# ORDER:  TOP RIGHT BACK LEFT CENTER
# 0_0 -> FRONT
# 0_90 -> TOP
# 0_270 -> BOTTOM
# 90_0 -> RIGHT
# 180_0 -> BACK
# 270_0 -> LEFT
class ImageReader:
    def __init__(self, folderName):
        self.fileNames = []

        for r, d, f in os.walk(folderName):
            for file in f:
                self.fileNames.append(os.path.join(r, file))
        # print(self.fileNames)
        # FRONT BOTTOM  TOP   BACK    LEFT    RIGHT
        # 0_0,  0_270,  0_90, 180_0,  270_0,  90_0
        # Reads as openCV objects and flattens 3 identical values into 1 value for each pixel location.
        self.switchFileNames()
        self.files = [cv2.imread(i)[:, :, :1] for i in self.fileNames]

        self.files = np.squeeze(self.files)

        self.createSegmentationData()

    # Creates a segmentation where True = sky, False = not sky.
    def createSegmentationData(self):
        self.segmentationData = np.ma.masked_less(
            self.files, 4, copy=True).mask # 4 degrees C
        try:
            if(self.segmentationData == False):
                self.segmentationData = np.full((6, 512, 512), False)
        except ValueError:
            pass
        # flip for radius/fraction to count bottom half instead
        # print(self.segmentationData)
        self.segmentationData = np.flip(self.segmentationData, axis=1)

    def writeOutThermalDegrees(self):
        n = 0
        for i in self.segmentationData:
            np.savetxt(str('thermal_degrees'+str(n)+'.txt'),
                       self.files[n], delimiter=',')
            np.savetxt(str(n)+'.txt', i, delimiter=',')
            n += 1

    def printInformation(self):
        print("Filenames: {}".format(self.fileNames))
        print("Length of files array: {}".format(len(self.files)))
        print("Shape of first item in files array: {}".format(
            str(self.files[0].shape)))
        print("Line from item in files array: {}".format(
            str(self.files[2][255][8])))
        print("Number of zeros: {}".format(
            str(len(np.where(self.files[2] == 0)[0]))
        ))
        
        np.savetxt('out.csv', self.files[2], delimiter=',')

    def switching(self, num1, num2):
        d = self.fileNames.copy()
        temp1 = d[num1]
        d[num1] = d[num2]
        d[num2] = temp1
        self.fileNames = d

    def imageFilesExist(self):
        if(len(self.fileNames) > 0):
            
            return 1
        else:
            
            return 0
    
    def switchFileNames(self):
        fileNames = [0, 0, 0, 0, 0, 0]
        
        for i in range(6):
            if(self.fileNames[i].endswith('_0_0.jpg')):
                fileNames[0] = self.fileNames[i]
            elif(self.fileNames[i].endswith('_90_0.jpg')):
                fileNames[1] = self.fileNames[i]
            elif(self.fileNames[i].endswith('_180_0.jpg')):
                fileNames[2] = self.fileNames[i]
            elif(self.fileNames[i].endswith('_270_0.jpg')):
                fileNames[3] = self.fileNames[i]
            elif(self.fileNames[i].endswith('_0_90.jpg')):
                fileNames[4] = self.fileNames[i]
            elif(self.fileNames[i].endswith('_0_270.jpg')):
                fileNames[5] = self.fileNames[i]

        self.fileNames = fileNames
        # print(self.fileNames)
