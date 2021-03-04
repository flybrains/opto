
import sys
import time
import os
import numpy as np
from os import system
import matplotlib.pyplot as plt
import matplotlib.image as mpimg
import pickle
from tqdm import tqdm
import serial
from datetime import datetime
from PIL import Image

from PyQt5 import QtCore, QtGui, QtWidgets, uic
from PyQt5.QtCore import QThread, pyqtSignal, pyqtSlot
from PyQt5.QtWidgets import QLabel, QMainWindow, QTextEdit, QAction, QFileDialog, QApplication, QMessageBox
from PyQt5.QtGui import QIcon, QImage, QPixmap

import moviepy
from moviepy.editor import ImageSequenceClip

import PyCapture2 as pc2

cwd = os.getcwd()
qtCreatorFile = cwd+"/cameraUI.ui"
Ui_MainWindow, QtBaseClass = uic.loadUiType(qtCreatorFile)

class ErrorMsg(QtWidgets.QMessageBox):
	def __init__(self, msg, parent=None):
		super(ErrorMsg, self).__init__(parent)
		self.setIcon(QtWidgets.QMessageBox.Critical)
		self.setText(msg)
		self.setWindowTitle('Error')

class WarningMsg(QtWidgets.QMessageBox):
	def __init__(self, msg, parent=None):
		super(WarningMsg, self).__init__(parent)
		self.setText(msg)
		self.setWindowTitle('Warning')

class Block(object):
	def __init__(self, duration, lightColor, lightIntensity, recording, lightDspTxt, recString):
		self.duration = duration
		self.lightColor = lightColor
		self.lightIntensity = lightIntensity
		self.recording = recording
		self.lightDspTxt = lightDspTxt
		self.recString = recString

class CameraThread(QThread):
	changePixmap = pyqtSignal(QImage)
	finished = pyqtSignal()
	count = pyqtSignal(int, name='count')

	def __init__(self, nFrames, saveDir, cam, fps, res, write=False, testMode=False):
		QThread.__init__(self)
		self.nFrames = nFrames
		self.saveDir = saveDir
		self.write = write
		self.testMode = testMode
		self.cam = cam
		self.video = pc2.FlyCapture2Video()
		self.framerate = fps
		self.resolution = res

		if self.write:
			self.video.MJPGOpen("{}.mp4".format(self.saveDir).encode('utf-8'), self.framerate, 80)

	def __del__(self):
		self.wait()

	def run(self):
		self.threadactive=True
		i = 0
		starttime = time.time()

		while (i < self.nFrames and self.threadactive):

			try:
				image = self.cam.retrieveBuffer()
			except pc2.Fc2error as fc2Err:
				print('Error retrieving buffer : %s' % fc2Err)
				continue
			if self.write:
				self.video.append(image)
			d = image.getData()
			d = np.reshape(d, (self.resolution,self.resolution))

			frame = np.stack((d, d, d), axis=2)

			h, w, ch = frame.shape
			bytesPerLine = ch * w
			convertToQtFormat = QImage(frame.data, w, h, bytesPerLine, QImage.Format_RGB888)
			p = convertToQtFormat.scaled(420, 420, QtCore.Qt.KeepAspectRatio)
			self.changePixmap.emit(p)
			# if self.write==True:
			# 	j = str(i)
			# 	k = str(j.zfill(6))
			#
			# 	image.save('{}/{}.pgm'.format(self.saveDir,str(k)).encode('utf-8'), pc2.IMAGE_FILE_FORMAT.PGM)

			i = i+1
			prog = int(100*(i/self.nFrames))
			if self.write:
				self.count.emit(prog)

		self.finished.emit()
		print('Camera Thread Complete')
		if self.write:
			self.video.close()
		self.cam.stopCapture()
		self.cam.disconnect()
		print(time.time()-starttime)

	def stop(self):
		self.threadactive=False
		self.finished.emit()
		print('Camera Thread Complete')
		self.wait()

class LightThread(QThread):
	lightsFinished = pyqtSignal()

	def __init__(self, ser, programLists):
		QThread.__init__(self)
		self.ser = ser
		self.programLists = programLists

	def __del__(self):
		self.wait()

	def run(self):

		self.threadactive=True

		timeList = self.programLists[0]
		cfgList = self.programLists[1]
		endTarget = '10'+'\n'

		t0 = time.time()
		for index, item in enumerate(cfgList):
			state = int(item[0])
			intensity = int(item[1])
			if intensity ==100:
				intensity = 99

			target = str(state)+str(intensity)


			sendStr = str(target)+'\n'

			dur = timeList[index]

			self.ser.write(str.encode(sendStr))
			print("wrote", sendStr, "sleeping", dur)
			time.sleep(dur)

			# t0 = time.time()
			# while (time.time() - t0) < dur:
			# 	self.ser.write(str.encode(sendStr))
			# 	time.sleep(0.1)

		self.ser.write(str.encode(endTarget))
		self.lightsFinished.emit()
		print('Serial Thread Complete')
		#print(time.time() - t0)
	def stop(self):
		self.threadactive=False
		self.lightsFinished.emit()
		self.wait()

class LiveImage(QMainWindow):
	def __init__(self, parent=None):
		super(LiveImage, self).__init__(parent)

class MainWindow(QMainWindow, Ui_MainWindow):
	def __init__(self):
		# General Initialization
		QtWidgets.QMainWindow.__init__(self)
		Ui_MainWindow.__init__(self)
		self.setupUi(self)
		self.title = 'Behavior Experiment Controller'
		self.setWindowTitle(self.title)
		self.setFixedSize(self.size())

		# Camera Thread Business
		self.startCamPushButton.clicked.connect(self.runCam)
		self.stopCamPushButton.clicked.connect(self.stopCam)

		# Button Connections
		self.addBlockPB.clicked.connect(self.addBlock)
		self.addDupBlocksPB.clicked.connect(self.addDupBlocks)
		self.runPB.clicked.connect(self.runExperiment)
		self.deleteBlockPB.clicked.connect(self.deleteBlock)
		self.pickSavePushButton.clicked.connect(self.pickSaveFolder)
		self.saveProgramPB.clicked.connect(self.saveProgram)
		self.loadProgramPB.clicked.connect(self.loadProgram)
		self.blockList = []
		dString = "{},\t{}\t{}\t{}".format('#', 'Dur (s)', 'Color', 'Intensity')
		lString = "--------------------------------------------------------------------"
		self.programList.addItems([dString, lString])
		self.arduinoCommText.setText('/dev/ttyACM0')
		self.arduinoBaudText.setText('9600')
		self.progressBar.hide()
		self.progressBar.setValue(0)

		self.viewerLockout = False
		self.setBG()


	def updatePGB(self, valueProg):
		#print(valueProg)
		self.progressBar.setValue(valueProg)
		self.progressBar.show()

	def addBlock(self):
		if self.addGreenRadioButton.isChecked():
			lightDspTxt = "Green"
			lightColor = 3
		elif self.addRedRadioButton.isChecked():
			lightDspTxt = "Red"
			lightColor = 2
		else:
			lightDspTxt = "No Light"
			lightColor = 1

		duration = float(self.addTimeSpinBox.value())

		if lightColor == 0:
			lightIntensity = 0
		else:
			lightIntensity = int(self.intensitySpinBox.value())

		recording = True
		recString = 'ON'

		if (lightIntensity == 0) and (lightColor is not 1):
			lightColor = 1
			lightDspTxt = 'No Light'

		newBlock = Block(duration, lightColor, lightIntensity, recording, lightDspTxt, recString)
		self.blockList.append(newBlock)
		listPos = len(self.blockList)

		if lightColor==1:
			lightColor='No Light'
		elif lightColor==2:
			lightColor = 'Red'
		else:
			lightColor = 'Green'

		dispString = "{},\t{}\t{}\t{}".format(listPos, str(duration), lightColor, lightIntensity)
		self.programList.addItems([dispString])
		return None

	def deleteBlock(self):
		d = self.programList.currentRow() - 2
		item = self.programList.takeItem(self.programList.currentRow())
		item = None
		del self.blockList[d]
		entries = [self.programList.item(i).text() for i in range(self.programList.count())]
		reindexed = []
		for idx, entry in enumerate(entries[2:]):
			listOfInfos = entry.split(",")
			listOfInfos[0] = idx+1
			reconstructed = '{},{}'.format(listOfInfos[0], listOfInfos[1])
			reindexed.append(reconstructed)
		self.programList.clear()
		dString = "{},\t{}\t{}\t{}".format('#', 'Dur (s)', 'Color', 'Intensity')
		lString = "--------------------------------------------------------------------"
		self.programList.addItems([dString, lString])
		for reindex in reindexed:
			self.programList.addItems([reindex])
		return None

	def saveProgram(self):
		self.programSavePath = QFileDialog.getSaveFileName(self, 'Select Save Directory', os.getcwd())

		self.programSavePath = self.programSavePath[0]+".pkl"
		entries = [self.programList.item(i).text() for i in range(self.programList.count())]
		savePack = {'dispList':entries,
					'blockList':self.blockList}
		pickle_out = open(self.programSavePath,"wb")
		pickle.dump(savePack, pickle_out)
		pickle_out.close()
		return None

	def loadProgram(self):
		fname = QFileDialog.getOpenFileName(self, 'Select Program to Open', os.getcwd())
		self.openProgramPath = str(fname[0])
		pickle_in = open(self.openProgramPath, "rb")
		savePack = pickle.load(pickle_in)
		self.programList.clear()
		self.blockList = savePack['blockList']
		for entry in savePack['dispList']:
			self.programList.addItems([entry])
		return None

	def addDupBlocks(self):
		single = False
		multi = False


		if self.dupBlockText.toPlainText() != '':
			single = True
			idx = int(self.dupBlockText.toPlainText()) -1
			entries = [self.programList.item(i).text() for i in range(self.programList.count())]
			toAdd = entries[idx+2]

			blockToReplicate = self.blockList[idx]
			blockToAdd = Block(blockToReplicate.duration, blockToReplicate.lightColor,
								   blockToReplicate.lightIntensity, blockToReplicate.recording,
								   blockToReplicate.lightDspTxt,blockToReplicate.recString)
			self.blockList.append(blockToAdd)

			self.dupBlockText.clear()
			listOfInfos = toAdd.split(",")
			listOfInfos[0] = str(len(self.blockList))
			reconstructed = '{},{}'.format(listOfInfos[0], listOfInfos[1])
			self.programList.addItems([reconstructed])

		else:
			if (self.dupBlocksFirstText.toPlainText() != "") and (self.dupBlocksLastText.toPlainText() != ""):
				if single == True:

					msg = 'Cannot add single block and range in same operation'
					self.warning = WarningMsg(msg)
					self.warning.show()

					self.dupBlocksFirstText.clear()
					self.dupBlocksLastText.clear()
				else:
					multi = True
					idxLo = int(self.dupBlocksFirstText.toPlainText())
					idxHi = int(self.dupBlocksLastText.toPlainText())

					if idxLo >= idxHi:
						msg = 'Last entry in range must be larger than first'
						self.error = ErrorMsg(msg)
						self.error.show()


					copyBlocks = list(np.arange(idxLo, (idxHi+1), 1))


					for i in range(self.programList.count()):
						if i in copyBlocks:

							blockToReplicate = self.blockList[i-1]
							blockToAdd = Block(blockToReplicate.duration, blockToReplicate.lightColor,
												   blockToReplicate.lightIntensity, blockToReplicate.recording,
												   blockToReplicate.lightDspTxt,blockToReplicate.recString)
							self.blockList.append(blockToAdd)

							index = str(len(self.blockList))
							toAdd = self.programList.item(i+1).text()
							listOfInfos = toAdd.split(",")
							listOfInfos[0] = index
							reconstructed = '{},{}'.format(listOfInfos[0], listOfInfos[1])
							self.programList.addItems([reconstructed])
						else:
							pass
				self.dupBlocksFirstText.clear()
				self.dupBlocksLastText.clear()

			return None

	def pickSaveFolder(self):
		fname = QFileDialog.getExistingDirectory(self, 'Select Save Directory')
		self.savePath = str(fname)
		self.savePathLabel.setText(self.savePath)
		return None

	@pyqtSlot(QImage)
	def setImage(self, image):
		self.label.setPixmap(QPixmap.fromImage(image))
		self.label.show()

	def runCam(self):
		if self.viewerLockout==False:
			self.setWindowTitle(self.title)
			self.label = QLabel(self)
			self.label.move(10, 40)
			self.label.resize(420, 420)
			bus = pc2.BusManager()
			num_cams = bus.getNumOfCameras()

			if num_cams > 0:
				self.fps = int(self.resolutionComboBox.currentText().split(" @ ")[0].split(" f")[0])
				self.res = int(self.resolutionComboBox.currentText().split(" @ ")[-1].split("x")[0])
				w, h = self.res, self.res
				cam = pc2.Camera()
				cam.connect(bus.getCameraFromIndex(0))
				fmt7_info, supported = cam.getFormat7Info(0)
				osx, osy = int((fmt7_info.maxWidth-w)/2), int((fmt7_info.maxHeight-h)/2)
				fmt7_img_set = pc2.Format7ImageSettings(0, osx, osy, w, h, pc2.PIXEL_FORMAT.MONO8)
				fmt7_pkt_inf, isValid = cam.validateFormat7Settings(fmt7_img_set)
				if not isValid:
					print('Error')
				cam.setFormat7ConfigurationPacket(fmt7_pkt_inf.recommendedBytesPerPacket, fmt7_img_set)
				cam.setProperty(type=pc2.PROPERTY_TYPE.FRAME_RATE, autoManualMode=False, absValue=float(self.fps))
				# fRateProp = cam.getProperty(pc2.PROPERTY_TYPE.FRAME_RATE)
				# framerate = fRateProp.absValue
				cam.startCapture()

			self.camThread = CameraThread(100000, None, cam, self.fps, self.res, write=False)
			self.camThread.changePixmap.connect(self.setImage)
			self.camThread.count.connect(self.updatePGB)
			self.camThread.start()
			self.camThread.finished.connect(self.setBG)
			self.viewerLockout = True
		else:
			msg = 'Cannot start new viewing window when one is active  '
			self.warning = WarningMsg(msg)
			self.warning.show()
			return None

	def stopCam(self):
		self.label.hide()
		self.camThread.stop()
		self.camThread.quit()
		self.camThread.wait()
		self.viewerLockout = False

	def setBG(self):
		try:
			self.label.hide()
		except AttributeError:
			pass
		self.l1 = QLabel(self)
		self.l1.resize(400, 120)
		self.l1.move(45,200)
		self.l1.setText('No Video Feed Connected')
		self.l1.setFont(QtGui.QFont('SansSerif', 20))
		self.l1.show()

	# def saveVid(self):
	# 	pass
	# # 	if self.saveVideo:
	# #
	# # 		print('Pre Processing Frames for Video Save')
	# #
	# # 		for img in tqdm(os.listdir(self.savePath +"/"+self.datetimeString)):
	# # 			address = os.path.join(self.savePath, self.datetimeString, img)
	# #
	# # 			pngaddress = address.split('.')[0]+".png"
	# # 			Image.open(address).save(pngaddress)
	# # 			os.remove(address)
	# #
	# # 			im2d = mpimg.imread(pngaddress)
	# # 			im3d = np.stack((im2d, im2d, im2d), axis=2)
	# # 			plt.imsave(pngaddress, im3d)
	# #
	# # 		print(self.savePath +"/"+self.datetimeString)
	# # 		clip = ImageSequenceClip(self.savePath +"/"+self.datetimeString, fps=config.settings[0])
	# # 		clip.write_videofile(self.savePath+'/videos/'+self.datetimeString+'.mp4', audio=False)
	# 		#clip.write_videofile(self.savePath+'/videos/'+self.datetimeString+'.avi', audio=False, codec='rawvideo')

	def serialCleanup(self):
		sendStr = '10'+'\n'
		self.ser.write(str.encode(sendStr))

	def runExperiment(self):

		if self.viewerLockout:
			msg = 'Cannot start new viewing window when one is active  '
			self.warning = WarningMsg(msg)
			self.warning.show()
			return None
		else:
			self.saveVideo = True#bool(self.saveVideoCheckBox.isChecked())

			if (self.arduinoCommText.toPlainText() is ""):
				msg = 'Must specify Arduino COMM port  '
				self.error = ErrorMsg(msg)
				self.error.show()
				return None

			if (self.arduinoBaudText.toPlainText() is ''):
				msg = 'Must specify Arduino Baudrate  '
				self.error = ErrorMsg(msg)
				self.error.show()
				return None

			try:
				self.savePath
			except AttributeError:
				msg = 'Must select unique save location '
				self.error = ErrorMsg(msg)
				self.error.show()
				return None



			self.progressBar.show()
			self.setWindowTitle(self.title)
			self.label = QLabel(self)
			self.label.move(10, 40)
			self.label.resize(420, 420)

			self.comm = str(self.arduinoCommText.toPlainText())
			self.baud = int(self.arduinoBaudText.toPlainText())

			self.fps = int(self.resolutionComboBox.currentText().split(" @ ")[0].split(" f")[0])
			self.res = int(self.resolutionComboBox.currentText().split(" @ ")[-1].split("x")[0])

			try:
				self.ser = serial.Serial(self.comm, self.baud)
			except serial.serialutil.SerialException:
				msg = 'Unable to establish connection with Arduino. Check COMM and Baud and connection with board. Re-upload program if necessary '
				self.error = ErrorMsg(msg)
				self.error.show()
				return None


			bus = pc2.BusManager()
			num_cams = bus.getNumOfCameras()

			if num_cams > 0:
				w, h = self.res, self.res
				cam = pc2.Camera()
				cam.connect(bus.getCameraFromIndex(0))
				fmt7_info, supported = cam.getFormat7Info(0)
				osx, osy = int((fmt7_info.maxWidth-w)/2), int((fmt7_info.maxHeight-h)/2)
				fmt7_img_set = pc2.Format7ImageSettings(0, osx, osy, w, h, pc2.PIXEL_FORMAT.MONO8)
				fmt7_pkt_inf, isValid = cam.validateFormat7Settings(fmt7_img_set)
				if not isValid:
					print('Error')
				cam.setFormat7ConfigurationPacket(fmt7_pkt_inf.recommendedBytesPerPacket, fmt7_img_set)
				cam.setProperty(type=pc2.PROPERTY_TYPE.FRAME_RATE, autoManualMode=False, absValue=float(self.fps))
				# fRateProp = cam.getProperty(pc2.PROPERTY_TYPE.FRAME_RATE)
				# framerate = fRateProp.absValue
				cam.startCapture()
			else:
				msg = 'Make sure a camera is connected  '
				self.error = ErrorMsg(msg)
				self.error.show()
				self.threadactive=False
				self.finished.emit()
				return None

			time.sleep(1)

			dt = datetime.now()
			self.datetimeString = str(dt.month)+"_"+str(dt.day)+"_"+str(dt.year)+"_"+str(dt.hour)+str(dt.minute)

			timeList = [float(block.duration) for block in self.blockList]
			cfgList = [[block.lightColor, block.lightIntensity] for block in self.blockList]
			self.programLists = [timeList, cfgList]
			timeSum = np.sum(timeList)
			nFrames = int(timeSum*self.fps)

			outFolder = self.savePath + "/" + self.datetimeString

			try:
				self.camThread = CameraThread(nFrames, outFolder, cam, self.fps, self.res, write=True)
				self.camThread.changePixmap.connect(self.setImage)
				self.camThread.count.connect(self.updatePGB)
				self.camThread.start()
				self.camThread.finished.connect(self.setBG)

			except pc2.Fc2error as fc2Err:
				msg = 'Make sure a camera is connected  '
				self.error = ErrorMsg(msg)
				self.error.show()
				return None

			self.lightThread = LightThread(self.ser, self.programLists)
			self.lightThread.start()
			self.lightThread.lightsFinished.connect(self.serialCleanup)
			#self.camThread.finished.connect(self.saveVid)




if __name__ == "__main__":
	app = QtWidgets.QApplication(sys.argv)
	window = MainWindow()
	window.show()
	sys.exit(app.exec_())
