import os
import argparse
from os import system
import moviepy
import matplotlib.pyplot as plt
import matplotlib.image as mpimg
import config
from PIL import Image
from tqdm import tqdm
from moviepy.editor import ImageSequenceClip
import numpy as np

def parse_args():
	parser = argparse.ArgumentParser()
	parser.add_argument('SOURCE_FOLDER', help='Folder where source images are stored')
	args = parser.parse_args()

	return args.SOURCE_FOLDER

def convert2video(folderName):
	if folderName.endswith('/'):
		folderName = folderName[:-1]

	print('Pre Processing Frames for Video Save')

	for img in tqdm(os.listdir(folderName)):
		address = os.path.join(folderName, img)

		pngaddress = address.split('.')[0]+".png"
		Image.open(address).save(pngaddress)
		os.remove(address)

		im2d = mpimg.imread(pngaddress)
		im3d = np.stack((im2d, im2d, im2d), axis=2)
		plt.imsave(pngaddress, im3d)

	clip = ImageSequenceClip(folderName, fps=config.settings[0])
	clip.write_videofile(folderName + '.mp4', audio=False)
	#clip.write_videofile(self.savePath+'/videos/'+self.datetimeString+'.avi', audio=False, codec='rawvideo')

	# subfolders = [os.path.join(os.getcwd(), folderName, i) for i in os.listdir(folderName) if (os.path.isdir(os.path.join(os.getcwd(),folderName,i)) and i !='videos')]
	#
	# for sf in subfolders:
	# 	clip = ImageSequenceClip(sf, fps=30)
	# 	clip.write_videofile(sf+'.mp4', audio=False)
	return None



if __name__ == "__main__":
	sf = parse_args()
	convert2video(sf)
