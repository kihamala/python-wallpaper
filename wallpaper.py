#
# A humble utility for changing the Windows wallpaper heavily based on James Clarke's flick.py/wallpaper.py,
# Lev Pasha's Instagram-API-python, Hardik Vasa's google-images-download, Kevin Eichhorn's DeviantArt API,
# Hau Van's pinterest-client.
#
# Copyright 2018 Kimmo Hämäläinen
# Tested with Python v3.7
#
# Required ("pip install <module>"): pillow, (httplib2, oauth2,) tkcalendar, babel, InstagramAPI, google_images_download, requests, deviantart
#
# License: LGPLv2

# TODO: allow selecting a folder of photos
# FIXME: cropping feature when selecting wallpaper

import ctypes
import flickr
#import urllib.request
import requests
#import urllib.parse
from PIL import Image, ImageTk, ImageSequence
#from PIL import GifImagePlugin
import os
import random
import sys
import tkinter
import tkinter as tk
import tkinter.ttk as tk
from tkinter import messagebox
import configparser
import argparse
import time
from tkcalendar import DateEntry
import babel  # required by DateEntry
from InstagramAPI import InstagramAPI
import winreg
import datetime
#from google_images_download import google_images_download
import google_images_download
import tempfile
from io import BytesIO
import deviantartapi
import webbrowser
import threading
import queue
from requests_toolbelt.threaded import pool
from pinterest import Pinterest
import math
import copy
#from io import StringIO
# For Oauth code:
#import oauth2 as oauth
#import httplib2

class Config(object):
	def __init__(self):
		# not all attribs are created here to convey whether or not they were provided on the command line
		self.verbose = True
		self.configFileName = os.path.join(os.getcwd(), 'wallpaper.cfg')
		self.screenWidth = 0
		self.screenHeight = 0
		self.screenAspect = 0
		self.showConfig = False

	def isValid(self):
		return hasattr(self, 'flickrApiKey') and self.flickrApiKey

def readConfig(filename):
	parser = configparser.ConfigParser()
	config = Config()
	try:
		parser.read(filename)
	except FileNotFoundError:
		print('Configuration file', filename, 'not found')
		return {}
	config.groups = []
	try:
		groups = str.split(parser['default']['groupIds'])
		for id in groups:
			d = {'gid': id, 'tag': '', 'name': '<unknown>', 'user': '', 'matches': ''}
			if id in parser.sections():
				d['tag'] = parser[id]['tag']
				d['name'] = parser[id]['name']
				d['user'] = parser[id]['user']
			config.groups.append(d)
	except KeyError as err:
		print(str(err))
	config.strVars = ['largestSizeToRequest', 'flickrApiKey', 'flickrApiSecret',
					'resizePhoto', 'rotateByExif', 'freeText', 'globalTagMode',
					'userId', 'minUploadDate', 'maxUploadDate', 'resizeAlgo',
					'instagramLogin', 'instagramTag',
					'googleKeywords', 'googleImageSize', 'googleImageFormat', 'googleImageLicense',
					'googleImageColor', 'googleImageColorType', 'googleImageType',
					'wallpaperMode',
					'devartApiKey', 'devartApiSecret', 'devartTag', 'devartEndpoint',
					'devartCategoryPath', 'devartMatureContent', 'devartQueryString',
					'pinterestUsername', 'pinterestQuery']
	for var in config.strVars:
		try:
			setattr(config, var, '')
			setattr(config, var, parser['default'][var])
			print('"' + parser['default'][var] + '"')
		except KeyError:
			print('default.' + var + ' is missing')
	config.listVars = ['globalTags', 'recentPhotoIds']
	for var in config.listVars:
		try:
			setattr(config, var, [])
			setattr(config, var, str.split(parser['default'][var]))
		except KeyError:
			print('default.' + var + ' is missing')
	config.recentPhotos = []
	try:
		# FIXME use a number only
		recentPhotos = str.split(parser['default']['recentPhotos'])
		for index, recent in enumerate(recentPhotos):
			if recent in parser.sections():
				res = Gui.ResultPhoto()
				res.index = index
				res.url = parser[recent]['url'].replace('%%', '%')
				res.thumbnailUrl = parser[recent]['thumbnailUrl'].replace('%%', '%')
				res.title = parser[recent]['title'].replace('%%', '%')
				config.recentPhotos.append(res)
	except KeyError as err:
		print(str(err))
	print('Read', len(config.recentPhotos), 'recent photos')
	#print(str(config.groups))
	return config;

def saveConfig(config):
	parser = configparser.ConfigParser()
	groupIds = ''
	for group in config.groups:
		gid = group['gid']
		if not gid.strip():
			continue
		groupIds = (groupIds + ' ' if groupIds else '') + gid
		parser[gid] = {}
		parser[gid]['tag'] = group['tag']
		parser[gid]['name'] = group['name']
		parser[gid]['user'] = group['user']
	parser['default'] = {}
	parser['default']['groupIds'] = groupIds
	for var in config.strVars:
		parser['default'][var] = str(getattr(config, var))
		#print('saveConfig', var, str(getattr(config, var)))
	for var in config.listVars:
		parser['default'][var] = ' '.join(getattr(config, var))
		#print('saveConfig', var, str(getattr(config, var)))
	recentPhotoList = []
	for index, res in enumerate(config.recentPhotos.values()):
		section = 'recentPhoto' + str(index)
		parser[section] = {}
		parser[section]['url'] = res.url.replace('%', '%%')
		parser[section]['thumbnailUrl'] = res.thumbnailUrl.replace('%', '%%')
		parser[section]['title'] = res.title.replace('%', '%%')
		recentPhotoList.append(section)
	parser['default']['recentPhotos'] = ' '.join(recentPhotoList)
	with open(config.configFileName, 'w') as configfile:
		parser.write(configfile)

def addToRecents(config, photoId):
	if config.verbose:
		print('Saving', photoId, 'to recents')
	while len(config.recentPhotoIds) >= 5:
		print('Reduce recentPhotoIds size')
		config.recentPhotoIds = config.recentPhotoIds[1:]
	config.recentPhotoIds.append(photoId)
	#print('addToRecents(): list is now', str(config.recentPhotoIds))

def createTempFile():
	tempFile = tempfile.NamedTemporaryFile(delete = False)
	tempFile.close()
	return tempFile.name

reqSession = requests.Session()
reqSession.headers.update({'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_10_1) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/39.0.2171.95 Safari/537.36'})
def load_photo(url):
	file, mime, photo = '', '', {}
	try:
		# timeout hack
		#startTime = time.time()
		#body = bytes()
		request = {}
		try:
			request = reqSession.get(url, timeout=10, verify=False, stream=True)
			mime = request.headers['content-type']
			#for chunk in request.iter_content(4096):
			#	body = body + chunk
			#	if time.time() > (startTime + 60):
			#		body = []
			#		print('load_photo: timeout')
			#		break
		except requests.exceptions.ConnectionError as err:
			print('load_photo error: ' + str(err))
			#body = request = []
			request = []
		if request:
			#photo = Image.open(file)

			bytesio = BytesIO(request.content)
			#bytesio = BytesIO(body)
			photo = Image.open(bytesio)
			
			#photo.save(file)
	except OSError as err:
		print('load_photo error:', str(err))
	return photo, file, mime
	
def getNextSize(size):
	nextSize = {'Original': 'Large', 'Large': 'Medium', 'Medium': 'Small', 'Small': 'Thumbnail', 'Thumbnail': ''}
	return nextSize[size]

def getURL(config, photo, size, equal=False, allSizes=False):
	"""Retrieves a url for the photo.  (flickr.photos.getSizes)
	
	photo - the photo
	size - preferred size 'Thumbnail, Small, Medium, Large, Original'
	equal - should width == height?
	"""
	data = {}
	while True:
		if not data:
			method = 'flickr.photos.getSizes'
			data = flickr._doget(method, photo_id=photo.id)
		if allSizes:
			ret = {}
			for psize in data.rsp.sizes.size:
				if psize.label == size:
					ret['width'] = psize.width
					ret['height'] = psize.height
				ret[psize.label] = psize.source
			while not ('width' in ret):
				size = getNextSize(size)
				if size:
					for psize in data.rsp.sizes.size:
						if psize.label == size:
							ret['width'] = psize.width
							ret['height'] = psize.height
				else:
					print('could not find width & height')
					ret['width'] = ret['height'] = 0
			return ret
		else:
			for psize in data.rsp.sizes.size:
				if psize.label == size:
					if not equal or (equal and psize.width == psize.height):
						return {'url': psize.source, 'width': psize.width, 'height': psize.height}
		prevSize = size
		size = getNextSize(size)
		if not size:
			raise flickr.FlickrError('No URL found for photo ' + photo.id)
		elif config.verbose:
			print('No size', prevSize + ', trying size', size)

def getPhotoURLs(config, groupId='', tags=[], tag_mode='any', per_page=25, page=1,
				user_id='', text='', getOnlyOne=False, pagesTotalOnly=False, recycleGroup={}, allSizes=False, callback={}):
	#ret = getOAuthToken()
	#verifier = '4e3416bb6ac57bc6' #OAuthAuthorizeStep(ret[1])
	#token = '72157670877344247-a50a0ff4d5df3c66'
	#getOAuthAccessToken(verifier, oauth_token, tokenObj)
	#return
	
	# getOnlyOne parameter is workaround for the inability to have per_page=1
	pagesTotal = '0'
	photosTotal = '0'
	photos = []
	flickrGroup = recycleGroup  # if recycleGroup was provided we avoid a round-trip to Flickr
	if groupId:
		if not flickrGroup:
			flickrGroup = flickr.Group(groupId)
		try:
			if config.verbose:
				print('Requesting page', page, 'in group', flickrGroup.name, '(' + flickrGroup.id + ') by user "' + user_id + '" with tags: ' + str(tags))
			photos, pagesTotal, photosTotal = flickrGroup.getPhotos(page=page, per_page=per_page, tags=tags, user_id=user_id)
		except flickr.FlickrError as err:
			print('flickr.py error: "' + str(err) + '"')
	elif tags or text or user_id:
		if config.verbose:
			print('Requesting page', page, 'with', tag_mode, 'of tags: ' + str(tags), 'between upload dates:',
				config.minUploadDate, config.maxUploadDate, 'free text: "' + text + '", uploaded by user: ' + user_id)
		try:
			photos, pagesTotal, photosTotal = flickr.photos_search(group_id=groupId, user_id=user_id, tags=tags, tag_mode=tag_mode,
																min_upload_date=config.minUploadDate, max_upload_date=config.maxUploadDate,
																page=page, per_page=per_page, text=text, media='photos')
			#pagesTotal = flickr.photos_search_pages(tags=tags, page=page, per_page=per_page, media='photos')
		except flickr.FlickrError as err:
			print('flickr.py error: "' + str(err) + '"')
	else:
		if config.verbose:
			print('No group or tags, giving fake pagesTotal')
		pagesTotal = photosTotal = '1'
		if not pagesTotalOnly:
			try:
				photos = flickr.photos_get_recent(page=page, per_page=per_page)
			except flickr.FlickrError as err:
				print('flickr.py error: "' + str(err) + '"')
	urls = []
	flickrPhotos = []
	if pagesTotalOnly:
		# only asking the number of available pages
		return {'urls': urls, 'flickrPhotos': flickrPhotos, 'pagesTotal': pagesTotal, 'photosTotal': photosTotal, 'flickrGroup': flickrGroup}
	if config.verbose:
		print('Page', str(page) + ' of ' + pagesTotal, 'has', len(photos), 'of', photosTotal, 'total photos')
	if len(photos) > 0:
		try:
			if getOnlyOne:
				# avoid unnecessary getSizes method calls by getting a random photo on the page
				random.seed()
				randIndex = random.randint(0, len(photos) - 1)
				photo = photos[randIndex]
				urls.append(getURL(config, photo, config.largestSizeToRequest, allSizes=allSizes))
				flickrPhotos.append(photo)
			else:
				flickrPhotos = photos
				for index, photo in enumerate(photos):
					urlDict = getURL(config, photo, config.largestSizeToRequest, allSizes=allSizes)
					urls.append(urlDict)
					if callback:
						callback(urlDict=urlDict, pagesTotal=pagesTotal, photosTotal=photosTotal, flickrPhoto=photo,
								imageIndex=(per_page * (page - 1) + index), firstPhoto=True if index == 0 else False)
		except flickr.FlickrError as err:
			print('flickr.py error: "' + str(err) + '"')
	return {'urls': urls, 'flickrPhotos': flickrPhotos, 'pagesTotal': pagesTotal, 'photosTotal': photosTotal, 'flickrGroup': flickrGroup}

def rotateByExif(config, flickrPhoto, image):
	if flickrPhoto and hasattr(config, 'rotateByExif') and config.rotateByExif:
		rotation = ''
		try:
			exif = flickrPhoto.getExif()
			for t in exif.tags:
				if t.label == 'Orientation':
					if t.raw.find('Rotate ') == 0:
						rotation = t.raw
					break
		except flickr.FlickrError:
			if config.verbose:
				print('Could not get EXIF info')

		if rotation:
			print('Rotation from EXIF:', rotation)
			#rotation = 'Rotate 270 CW'
			try:
				details = str.split(rotation)
				if details[2] == 'CW':
					image = image.rotate(-int(details[1]), expand=1)
				elif details[2] == 'CCW':
					image = image.rotate(int(details[1]), expand=1)
			except:
				print('Parsing rotation string failed')
	return image
	
# TODO: use generic class instead of flickr.Photo
def resizeToScreen(config, flickrPhoto, image):
	image = rotateByExif(config, flickrPhoto, image)
	origSize = image.size
	aspect = image.size[0] / image.size[1]
	newSize = {}
	if aspect >= config.screenAspect:
		if image.size[0] < config.screenWidth or image.size[0] > config.screenWidth:
			newSize = (config.screenWidth, int(config.screenWidth / aspect))
	else:
		if image.size[1] < config.screenHeight or image.size[1] > config.screenHeight:
			newSize = (int(config.screenHeight * aspect), int(config.screenHeight))
	if newSize:
		image = image.resize(newSize, getattr(Image, config.resizeAlgo))
		if config.verbose:
			print('Resized', flickrPhoto.id if flickrPhoto else 'image', 'from', origSize, 'to', newSize, 'using', config.resizeAlgo)
	elif config.verbose:
		print('Keep size', origSize)
	return image
	
def photoAsStr(photo):
	tags = ''
	if photo.tags:
		for tag in photo.tags:
			tags = tags + tag.text + ' '
		tags = tags[:-1]
	return '(name: ' + photo.title + ', id: ' + photo.id + ', tags: ' + tags + ', user_id: ' + photo.owner.id + ' (' + photo.owner.username + '), views: ' + photo.views + ', url: ' + photo.url + ')'

class Gui(object):
	photoCountOnPage = 8
	autoHideDuration = 2000
	
	class GuiInfo(object):
		def __init__(self):
			self.root = {}
			#self.tmpImages = []
			#self.resultsNextIndex = 0
			self.resultPage = {}
			self.bigPhotoWindow = {}
			self.groups = []

	def __init__(self):
		self.cancelPressed = self.saveAndQuitPressed = False

	# From https://stackoverflow.com/questions/39458337/is-there-a-way-to-add-close-buttons-to-tabs-in-tkinter-ttk-notebook
	class CustomNotebook(tk.Notebook):
		"""A ttk Notebook with close buttons on each tab"""

		__initialized = False

		def __init__(self, *args, **kwargs):
			self.images = []
			if not self.__initialized:
				self.__initialize_custom_style()
				self.__inititialized = True

			kwargs["style"] = "CustomNotebook"
			tk.Notebook.__init__(self, *args, **kwargs)

			self._active = None

			self.bind("<ButtonPress-1>", self.on_close_press, True)
			self.bind("<ButtonRelease-1>", self.on_close_release)

		def on_close_press(self, event):
			"""Called when the button is pressed over the close button"""

			element = self.identify(event.x, event.y)

			if "close" in element:
				index = self.index("@%d,%d" % (event.x, event.y))
				self.state(['pressed'])
				self._active = index

		def on_close_release(self, event):
			"""Called when the button is released over the close button"""
			if not self.instate(['pressed']):
				return

			element =  self.identify(event.x, event.y)
			index = self.index("@%d,%d" % (event.x, event.y))

			if "close" in element and self._active == index:
				self.forget(index)
				self.event_generate("<<NotebookTabClosed>>")

			self.state(["!pressed"])
			self._active = None
			
		def __initialize_custom_style(self):
			style = tk.Style()
			self.images.append((
				tkinter.PhotoImage("img_close", data='''
					R0lGODlhCAAIAMIBAAAAADs7O4+Pj9nZ2Ts7Ozs7Ozs7Ozs7OyH+EUNyZWF0ZWQg
					d2l0aCBHSU1QACH5BAEKAAQALAAAAAAIAAgAAAMVGDBEA0qNJyGw7AmxmuaZhWEU
					5kEJADs=
					'''),
				tkinter.PhotoImage("img_closeactive", data='''
					R0lGODlhCAAIAMIEAAAAAP/SAP/bNNnZ2cbGxsbGxsbGxsbGxiH5BAEKAAQALAAA
					AAAIAAgAAAMVGDBEA0qNJyGw7AmxmuaZhWEU5kEJADs=
					'''),
				tkinter.PhotoImage("img_closepressed", data='''
					R0lGODlhCAAIAMIEAAAAAOUqKv9mZtnZ2Ts7Ozs7Ozs7Ozs7OyH+EUNyZWF0ZWQg
					d2l0aCBHSU1QACH5BAEKAAQALAAAAAAIAAgAAAMVGDBEA0qNJyGw7AmxmuaZhWEU
					5kEJADs=
				'''))
			)

			if 'close' not in style.element_names():
				style.element_create("close", "image", "img_close",
									("active", "pressed", "!disabled", "img_closepressed"),
									("active", "!disabled", "img_closeactive"), border=8, sticky='')
			style.layout('CustomNotebook', [("CustomNotebook.client", {"sticky": "nswe"})])
			#if closeButton:
			style.layout("CustomNotebook.Tab", [
				("CustomNotebook.tab", {
					"sticky": "nswe", 
					"children": [
						("CustomNotebook.padding", {
							"side": "top", 
							"sticky": "nswe",
							"children": [
								("CustomNotebook.focus", {
									"side": "top", 
									"sticky": "nswe",
									"children": [
										("CustomNotebook.label", {"side": "left", "sticky": ''}),
										("CustomNotebook.close", {"side": "left", "sticky": ''}),
									]
								})
							]
						})
					]
				})
			])
			#return style

	def updateConfig(self, config, gui):
		for group in gui.groups:
			name = group['name']['text']
			# remove '(xx matches)' from the name
			if name.endswith(group['matches']):
				i = name.rfind(group['matches'])
				name = name[:i]
			d = {'gid': group['gid'].get(),
				'tag': group['tag'].get(),
				'user': group['user'].get(),
				'name': name,
				'nameWidget': group['name']}
			foundIndex = -1
			for index, g in enumerate(config.groups):
				if d['gid'] == g['gid']:
					foundIndex = index
					break
			if foundIndex < 0:
				config.groups.append(d)
				print('config.groups append', d)
			else:
				# set only the label widget
				config.groups[foundIndex]['nameWidget'] = d['nameWidget']
		for key in gui.tkVars:
			obj = gui.tkVars[key]
			conf = getattr(config, key)
			if isinstance(conf, list):
				setattr(config, key, str.split(obj.get()))
			else:
				setattr(config, key, str(obj.get()))
			print('updateConfig:', key, '=', str(obj.get()))
		if hasattr(gui, 'minDateEntry') and gui.minDateEntry:
			d = gui.minDateEntry.get_date()
			config.minUploadDate = '%d/%d/%d' % (d.year, d.month, d.day)
		if hasattr(gui, 'maxDateEntry') and gui.maxDateEntry:
			d = gui.maxDateEntry.get_date()
			config.maxUploadDate = '%d/%d/%d' % (d.year, d.month, d.day)
		flickr.API_KEY = config.flickrApiKey
		flickr.API_SECRET = config.flickrApiSecret
		
	def onSaveButton(self, config, gui, justQuit=False):
		self.updateConfig(config, gui)
		gui.root.destroy()
		saveConfig(config)
		if justQuit:
			self.saveAndQuitPressed = True

	def onCancelButton(self, gui):
		self.cancelPressed = True
		gui.root.destroy()

	def onRemoveGroupRow(self, config, gui, index):
		self.updateConfig(config, gui)
		gui.groupsParent.destroy()
		config.groups.remove(config.groups[index])
		self.createGroupEntries(config, gui)

	def onAddGroupRow(self, config, gui):
		self.updateConfig(config, gui)
		gui.groupsParent.destroy()
		config.groups.append({'gid': '', 'tag': '', 'name': '<unknown>', 'user': '', 'matches': ''})
		self.createGroupEntries(config, gui)
	
	def applyColorStyle(self, widget, uniqueStr, colorName):
		style = tk.Style()
		translate = {'Label': '.TLabel'}
		style.configure(uniqueStr + translate[widget.__class__.__name__], foreground=colorName)
		widget.config(style=uniqueStr + translate[widget.__class__.__name__])
		
	def updateGroupNameLabel(self, config, groupInfo, matches, newName):
		if matches > 1:
			text = ' (' + str(matches) + ' matches)'
		elif matches == 1:
			text = ' (1 match)'
		else:
			text = ' (no matches)'
		groupInfo['matches'] = text
		# FIXME: nameWidgets are broken after loading next page
		#self.applyColorStyle(groupInfo['nameWidget'], groupInfo['gid'], 'green' if matches >= 1 else 'red')
		#groupInfo['nameWidget'].config(text = newName + text)

	def onGroupQuery(self, config, gui, index, pageNum=1, results={}):
		self.updateConfig(config, gui)
		if not results:
			#self.destroyResultsTab(config, gui, 'photoLoadCallback')
			results = Gui.Results(config, self, gui, loadPageFunc = lambda resObj, n: self.onGroupQuery(config, gui, index, results=resObj, pageNum=n))
		#if not prevUrls:
		#	self.destroyResultsTab(config, gui, 'photoLoadCallback')
		groupInfo = config.groups[index] #gui.groups[index]
		groupId = groupInfo['gid']
		if 'flickrGroup' in groupInfo:
			flickrGroup = groupInfo['flickrGroup']  # cached flickrGroup object
			newName = flickrGroup.name
		else:
			flickrGroup = {}
			newName = ''
		try:
			if not flickrGroup:
				flickrGroup = flickr.Group(groupId)
			if not newName:
				newName = flickrGroup.name
			#	groupInfo['nameWidget'].config(text=newName)
		except flickr.FlickrError as err:
			if config.verbose:
				print('flickr.py error:', err)
			#	groupInfo['nameWidget'].config(text='<not found>')
			return
		#self.ResultPhoto.currPage = pageNum
		#urls = prevUrls
		ret = getPhotoURLs(config, groupId=groupId, tags=[groupInfo['tag']], user_id=groupInfo['user'],
							per_page=Gui.photoCountOnPage, page=pageNum, allSizes=True, recycleGroup=flickrGroup,
							callback=lambda **kwargs: self.photoLoadCallback(config, gui, results, **kwargs))
		#self.ResultPhoto.numPages = int(ret['pagesTotal'])
		matches = int(ret['photosTotal'])
		#if matches == 0:
		#	
		#	resultPage = self.createAndSelectResultsPage(config, gui, 'onGroupQuery', title='Result page ' + str(pageNum))
		#	#resultPage.resultsNextIndex = (pageNum - 1) * Gui.photoCountOnPage
		#else:
		resultPage = gui.resultPagePhotoLoadCallback
		self.updateGroupNameLabel(config, groupInfo, matches, newName)
		#for i, url in enumerate(ret['urls']):
		#	flickrPhoto = ret['flickrPhotos'][i]
		#	urls.append(self.retToResultPhoto(config, gui, url, flickrPhoto))
		#if pageNum < int(ret['pagesTotal']):
		#	resultPage.loadMoreFunc = lambda: gui.root.after_idle(lambda: self.onGroupQuery(config, gui, index, pageNum=pageNum+1, results=results))
		#else:
		#	resultPage.loadMoreFunc = {}
		resultPage.loadMoreButtons = lambda results, parent, frame: self.defaultLoadMoreButtons(config, gui, results, frame)
		self.createResultPageButtons(config, gui, results, resultPage)

	def addGroupRow(self, config, gui, parent, gridColumn, gridRow, group):
		#parent.grid_rowconfigure(gridRow, pad=10)
		nameLabel = tk.Label(parent, text=group['name'])
		nameLabel.grid(row=gridRow, column=gridColumn, sticky=tkinter.W, padx=10)
		gidEntry = tk.Entry(parent)
		gidEntry.grid(row=gridRow, column=gridColumn + 1, sticky=tkinter.W+tkinter.E, padx=10)
		gidEntry.insert(0, group['gid'])
		userEntry = tk.Entry(parent)
		userEntry.grid(row=gridRow, column=gridColumn + 2, sticky=tkinter.W+tkinter.E, padx=10)
		userEntry.insert(0, group['user'])
		tagEntry = tk.Entry(parent)
		tagEntry.grid(row=gridRow, column=gridColumn + 3, sticky=tkinter.W+tkinter.E, padx=10)
		tagEntry.insert(0, group['tag'])
		tk.Button(parent, text='Remove group', command=lambda: self.onRemoveGroupRow(config, gui, gridRow - 1)).grid(row=gridRow, column=gridColumn + 4, padx=10)
		tk.Button(parent, text='Show matches',
			command=lambda: gui.root.after_idle(lambda: self.onGroupQuery(config, gui, gridRow - 1))).grid(row=gridRow, column=gridColumn + 5, padx=10)
		return {'gid': gidEntry, 'tag': tagEntry, 'name': nameLabel, 'user': userEntry, 'matches': ''}

	def createGroupEntries(self, config, gui):
		gui.groupsParent = parent = tk.LabelFrame(gui.flickrPage, text='Flickr Groups (flickr.groups.pools.getPhotos API)', relief=tkinter.GROOVE)
		parent.grid(row=2, columnspan=3, sticky=tkinter.W+tkinter.E, padx=10, pady=10)
		gui.groups = []
		if hasattr(config, 'groups') and len(config.groups) > 0:
			for col in range(4):
				parent.grid_columnconfigure(col, weight=1, pad=10)
			tk.Label(parent, text='Name').grid(column=0, padx=10)
			tk.Label(parent, text='Group id').grid(row=0, column=1, padx=10)
			tk.Label(parent, text='Uploaded by user (optional)').grid(row=0, column=2, padx=10)
			tk.Label(parent, text='Tag (optional)').grid(row=0, column=3, padx=10)
			gridRow = 1
			for group in config.groups:
				gui.groups.append(self.addGroupRow(config, gui, parent, 0, gridRow, group))
				gridRow += 1
		tk.Button(parent, text='Add group', command=lambda: self.onAddGroupRow(config, gui)).grid(row=len(gui.groups) + 1, sticky=tkinter.W, padx=10, pady=10)

	def onAboutMenu(self, config, gui):
		print('About menu item')
		
	def onWindowClose(self, config, gui):
		if messagebox.askokcancel("Quit", "Do you want to quit without saving?"):
			self.onCancelButton(gui)

	def checkResizeAlgoDisable(self, *args):
		for w in self.resizeAlgoWidgets:
			w.config(state = 'disabled' if self.resizeVar.get() == 0 else 'normal')
	
	def retToResultPhoto(self, config, gui, urlDict, flickrPhoto):
		res = self.ResultPhoto()
		res.flickrPhoto = flickrPhoto
		res.size = (int(urlDict['width']), int(urlDict['height']))
		res.title = flickrPhoto.title + '. ' + flickrPhoto.description
		# FIXME: 'similar images' search is broken (google can't access photos)
		res.createTitleFunc = lambda parent: self.createDefaultLabelWithSimilarButton(parent, config, gui, res)
		#urlDict = ret['urlDict']
		#print(str(urlDict))
		# Small looks better than thumbnail
		if 'Small' in urlDict:
			res.thumbnailUrl = urlDict['Small']
		elif 'Thumbnail' in urlDict:
			res.thumbnailUrl = urlDict['Thumbnail']

		size = config.largestSizeToRequest
		while size:
			if size in urlDict:
				res.url = urlDict[size]
				break
			size = getNextSize(size)
		return res
	
	def flickrTabTitleFunc(self, config, gui, resultsNextIndex, pagesTotal):
		print('flickrTabTitleFunc', resultsNextIndex, pagesTotal)
		return 'Result page ' + str(Gui.calculatePageNumber(resultsNextIndex)) + ' of ' + str(pagesTotal)
		
	def createFlickrResultPage(self, config, gui, results):
		gui.resultPagePhotoLoadCallback = resultPage = self.createAndSelectResultsPage(config, gui, 'photoLoadCallback', copyFromOld=True,
															titleFunc=lambda nextIndex: self.flickrTabTitleFunc(config, gui, nextIndex, results.pagesTotal),
															results=results)
		return resultPage
	
	def photoLoadCallback(self, config, gui, results, **kwargs):
		index = kwargs['imageIndex']
		results.nextIndex = index  # set for the tab title function
		results.pagesTotal = int(kwargs['pagesTotal'])
		results.photosTotal = int(kwargs['photosTotal'])
		if kwargs['firstPhoto']:
			print('firstPhoto')
			resultPage = self.createFlickrResultPage(config, gui, results)
		else:
			resultPage = gui.resultPagePhotoLoadCallback
		#print('photoLoadCallback called, kwargs:', str(kwargs))
		print('photoLoadCallback', index, len(results))
		res = self.retToResultPhoto(config, gui, kwargs['urlDict'], kwargs['flickrPhoto'])
		res.index = index
		#urls.append(res)
		results.addItem(res)
		self.showOnePhoto(config, gui, res, resultPage)
		results.nextIndex = index + 1
		
	'''
	def flickrLoadMoreButtons(self, config, gui, resObj, parent, frame):
		nextPage = Gui.calculatePageNumber(resObj.nextIndex)
		if nextPage > 2 and not resObj.pageIsCached(nextPage - 2):
			tk.Button(frame, text='Load prev page', command=lambda np=nextPage: gui.root.after_idle(lambda np=np: resObj.loadPage(np-2))).pack(pady=10)
		for n in [10, 100, 1000, 10000]:
			if nextPage - n - 1 > 0:
				tk.Button(frame, text='Back ' + str(n) + ' pages', command=lambda n=n, np=nextPage: gui.root.after_idle(lambda n=n, np=np: resObj.loadPage(np-n-1))).pack(pady=10)
		
		if nextPage < resObj.pagesTotal and not resObj.pageIsCached(nextPage):
			tk.Button(frame, text='Load next page', command=lambda np=nextPage: gui.root.after_idle(lambda np=np: resObj.loadPage(np))).pack(pady=10)
		for n in [10, 100, 1000, 10000]:
			if nextPage + n - 1 < resObj.pagesTotal:
				tk.Button(frame, text='Jump ' + str(n) + ' pages', command=lambda n=n, np=nextPage: gui.root.after_idle(lambda n=n, np=np: resObj.loadPage(np+n-1))).pack(pady=10)
	'''
	
	def onPhotosSearch(self, config, gui, pageNum=1, results={}):
		self.updateConfig(config, gui)
		if not results:
			#self.destroyResultsTab(config, gui, 'photoLoadCallback')
			results = Gui.Results(config, self, gui, loadPageFunc = lambda resObj, n: self.onPhotosSearch(config, gui, results=resObj, pageNum=n))
		elif results.pagesTotal < pageNum:
			return False
		#if not results.pageIsCached(pageNum):
		ret = getPhotoURLs(config, user_id=config.userId, tags=config.globalTags, text=config.freeText, tag_mode=config.globalTagMode,
							per_page=Gui.photoCountOnPage, page=pageNum, allSizes=True,
							callback=lambda **kwargs: self.photoLoadCallback(config, gui, results, **kwargs))
		if not ret:
			return False
		resultPage = gui.resultPagePhotoLoadCallback
		#else:
		#	results.nextIndex = firstIndex = (pageNum - 1) * Gui.photoCountOnPage
		#	resultPage = self.createFlickrResultPage(config, gui, results)
		#	for index in map(lambda n: firstIndex + n, range(Gui.photoCountOnPage)):
		#		if results.itemIsCached(index):
		#			self.showOnePhoto(config, gui, results.getItem(index), resultPage)
		#			results.nextIndex += 1
		#		else:
		#			break
		'''
		matches = results.photosTotal
		if matches > 1:
			#text = str(matches) + ' matching photos'
			resultPage = gui.resultPagePhotoLoadCallback
		elif matches == 1:
			#text = '1 matching photo'
			resultPage = gui.resultPagePhotoLoadCallback
		else:
			resultPage = self.createAndSelectResultsPage(config, gui, 'onPhotosSearch', title='Result page ' + str(pageNum), results=results)
			#resultPage.resultsNextIndex = (pageNum - 1) * Gui.photoCountOnPage
			#text = 'No matching photos'
		'''
		# FIXME: broken because flickr page is created on-demand?
		#self.applyColorStyle(self.queryLabel, 'MatchesText', 'green' if matches >= 1 else 'red')
		#self.queryLabel.config(text=text)
		
		resultPage.loadMoreButtons = lambda results, parent, frame: self.defaultLoadMoreButtons(config, gui, results, frame)
		self.createResultPageButtons(config, gui, results, resultPage)
		return True # if ret else False
	
	def destroyResultsTab(self, config, gui, type):
		if (type in gui.resultPage) and gui.resultPage[type]:
			gui.resultPage[type].destroy()
			gui.resultPage[type] = {}
	
	def raiseWindow(self, config, gui, w):
		w.attributes('-topmost', True)
		gui.root.after_idle(w.attributes, '-topmost', False)
	
	def onWallpaperSettingsOK(self, config, gui, photo, file, mime):
		gui.wallpaperSettings.destroy()
		self.updateConfig(config, gui)
		setWallpaper(config, photo, file, mime)
	
	def showSetWallpaperConfig(self, config, gui, photo, file, mime, resultPhoto):
		gui.wallpaperSettings = root = tkinter.Toplevel(gui.root)
		root.title('Wallpaper Settings')
		self.raiseWindow(config, gui, root)
		tkVars = gui.tkVars
		tk.Checkbutton(root, text='Resize photo to screen size', variable=tkVars['resizePhoto'],
			onvalue=1, offvalue=0).grid(row=3, column=1, sticky=tkinter.W, padx=10)
		tk.Checkbutton(root, text='Rotate photo based on Exif tags', variable=tkVars['rotateByExif'],
			onvalue=1, offvalue=0).grid(row=4, column=1, sticky=tkinter.W, padx=10)
		self.resizeVar = tkVars['resizePhoto']
		tkVars['resizePhoto'].trace('w', self.checkResizeAlgoDisable)

		self.resizeAlgoWidgets = []
		l = tk.Label(root, text='Wallpaper resize algorithm:')
		self.resizeAlgoWidgets.append(l)
		l.grid(row=3, column=2, sticky=tkinter.W, padx=10)
		for row, (text, value) in enumerate([('Lanczos (best quality but slow)', 'LANCZOS'),
											 ('Bicubic', 'BICUBIC'),
											 ('Hamming', 'HAMMING'),
											 ('Bilinear', 'BILINEAR')], 4):
			r = tk.Radiobutton(root, text=text, variable=tkVars['resizeAlgo'], value=value)
			r.grid(row=row, column=2, padx=20, sticky=tkinter.W)
			self.resizeAlgoWidgets.append(r)
		self.checkResizeAlgoDisable()

		tk.Label(root, text='Wallpaper mode:').grid(row=3, column=0, sticky=tkinter.W, padx=10)
		for row, (text, value) in enumerate([('Center', 0),
											 ('Tile', 1),
											 ('Stretch', 2),
											 ('Fit', 3),
											 ('Fill', 4)], 4):
			tk.Radiobutton(root, text=text, variable=tkVars['wallpaperMode'], value=value).grid(row=row, column=0, padx=20, sticky=tkinter.W)
		tk.Button(root, text='OK', command=lambda: self.onWallpaperSettingsOK(config, gui, photo, file, mime)).grid(row=10, column=0, padx=10, pady=30)
		tk.Button(root, text='Cancel', command=lambda: root.destroy()).grid(row=10, column=2, padx=10, pady=30)
	
	def onSetWallpaperButton(self, config, gui, photo, file, mime, resultPhoto):
		config.recentPhotos.addRecentItem(resultPhoto)
		gui.bigPhotoWindow.destroy()
		gui.bigPhotoWindow = {}
		self.showSetWallpaperConfig(config, gui, photo, file, mime, resultPhoto)
	
	def bigPhotoMouseWheel(self, event, **kwargs):
		config, gui = kwargs['config'], kwargs['gui']
		window = gui.bigPhotoWindow
		prevZoom = window.bigPhotoZoom
		if event.delta < 0:
			newZoom = prevZoom - 0.02
		else:
			newZoom = prevZoom + 0.02
		if newZoom >= 0.1 and newZoom <= 3.0:
			photo = window.bigPhoto
			w, h = photo.width, photo.height
			window.bigPhotoZoom = newZoom
			newW, newH = int(w * newZoom), int(h * newZoom)
			window.zoomPhoto = photo.resize((newW, newH), Image.BILINEAR)
			self.bigPhotoWindowUpdateBigPhoto(config, gui, window.zoomPhoto)
	
	def bigPhotoMouseDrag(self, event, **kwargs):
		gui, config = kwargs['gui'], kwargs['config']
		window = gui.bigPhotoWindow
		self.bigPhotoRefreshTimer(config, gui)
		if not window.userIsDragging:
			window.userIsDragging = True
			window.canvas.scan_mark(event.x, event.y)
			window.dragStart = (event.x, event.y)
		elif abs(window.dragStart[0] - event.x) > 10 or abs(window.dragStart[1] - event.y) > 10:
			window.canvas.scan_dragto(event.x, event.y, gain=1)
			
	def bigPhotoMouseButtonUp(self, event, **kwargs):
		gui, config = kwargs['gui'], kwargs['config']
		gui.bigPhotoWindow.userIsDragging = False
		self.bigPhotoRefreshTimer(config, gui)
	
	'''
	class AutoScrollbar(tk.Scrollbar):
		# stolen from https://stackoverflow.com/questions/41095385/autohide-tkinter-canvas-scrollbar-with-pack-geometry
		# a scrollbar that hides itself if it's not needed.  only
		# works if you use the grid geometry manager.
		def __init__(self, master=None, **kwargs):
			tk.Scrollbar.__init__(self, master, **kwargs)
			self.oldLo = self.oldHi = 100.0
			self.isPacked = True
	
		def set(self, lo, hi):
			if lo == self.oldLo and hi == self.oldHi:
				return
		
			if float(lo) <= 0.0 and float(hi) >= 1.0:
				if self.isPacked:
					self.pack_forget()
					self.isPacked = False
			elif not self.isPacked:
				if self.cget("orient") == tkinter.HORIZONTAL:
					self.pack(side=tkinter.BOTTOM, fill=tkinter.X)
				else:
					self.pack(side=tkinter.RIGHT, fill=tkinter.Y)
				self.isPacked = True
			tk.Scrollbar.set(self, lo, hi)
			self.oldLo, self.oldHi = lo, hi
		def grid(self, **kw):
			raise(tkinter.TclError, "cannot use grid with this widget")
		def place(self, **kw):
			raise(tkinter.TclError, "cannot use place with this widget")
	'''

	def onCropPhoto(self, config, gui, photo, canvas, bFrame):
		# TODO: take zoom into account
		x, y = canvas.canvasx(0), canvas.canvasy(0)
		w = min(photo.width, gui.bigPhotoWindow.winfo_width())
		h = min(photo.height, bFrame.winfo_rooty() + bFrame.winfo_height())
		#x, y = max(0, x), max(0, y)
		print(x, y, w, h)
		if x == y == 0 and w == photo.width and h == photo.height:
			print('onCropPhoto: nothing to do')
			return
		self.bigPhotoWindowUpdateBigPhoto(config, gui, photo.crop((x, y, w + x, h + y)))
	
	def nextImageFrame(self, config, gui, index):
		window = gui.bigPhotoWindow
		if not window:
			return
		#print('frame', index)
		if index in window.render and window.render[index]:
			pass
		else:
			window.bigPhoto.seek(index)
			#window.canvas.delete(window.canvasImage)
			window.render[index] = render = ImageTk.PhotoImage(image=window.bigPhoto)
		setattr(window, 'canvasImage' + str(index), window.canvas.create_image((0, 0), image=window.render[index], anchor=tkinter.NW))
		index += 1
		if gui.bigPhotoWindow.frameCount <= index:
			index = 0
		gui.root.after(100, lambda: self.nextImageFrame(config, gui, index))
		
	def bigPhotoWindowUpdateBigPhoto(self, config, gui, photo):
		w = gui.bigPhotoWindow
		if not hasattr(w, 'render'):
			w.render = {}
		if not hasattr(w, 'bigPhotoZoom'):
			w.bigPhotoZoom = 1.0
		w.render[0] = render = ImageTk.PhotoImage(image=photo)
		if hasattr(w, 'canvasImage'):
			w.canvas.delete(w.canvasImage)
		w.canvasImage = w.canvas.create_image((0, 0), image=render, anchor=tkinter.NW)
		w.canvas.config(scrollregion = w.canvas.bbox(tkinter.ALL))
		w.textLabel.config(wraplength=min(photo.width, config.screenWidth))
		gui.root.update_idletasks()  # calculate required spaces
		x = y = 0
		imageW, imageH = photo.width, photo.height
		width = min(imageW, config.screenWidth)
		#print(w.bFrame.winfo_reqheight(), w.hscroll.winfo_reqheight())
		height = min(imageH, config.screenHeight)
		if width < config.screenWidth:
			x = int((config.screenWidth - width) / 2)
		if height < config.screenHeight:
			y = int((config.screenHeight - height) / 2)
		if imageW > config.screenWidth - 10 or imageH > config.screenHeight - 20:
			#overrideredirect = True
			w.overrideredirect(True)
		else:
			#overrideredirect = False
			w.overrideredirect(False)
			y -= 20  # compensate for window title bar
		print("%dx%d%+d%+d" % (width, height, x, y))
		#w.geometry("%dx%d%+d%+d" % (width, height, x, y))
		#w.overrideredirect(overrideredirect)
		gui.root.after(10, w.geometry, "%dx%d%+d%+d" % (width, height, x, y))

	def bigPhotoWindowDestroyed(self, event, config, gui):
		if hasattr(gui.bigPhotoWindow, 'autoHideTimer') and gui.bigPhotoWindow.autoHideTimer:
			gui.root.after_cancel(gui.bigPhotoWindow.autoHideTimer)
		gui.bigPhotoWindow = {}
	
	def bigPhotoRefreshTimer(self, config, gui):
		w = gui.bigPhotoWindow
		if hasattr(w, 'autoHideTimer') and w.autoHideTimer:
			gui.root.after_cancel(w.autoHideTimer)
		if not w.bFrame.isVisible:
			self.bigPhotoWindowToggleButtons(config, gui)
		else:
			w.autoHideTimer = gui.root.after(Gui.autoHideDuration, lambda: self.bigPhotoWindowToggleButtons(config, gui))
	
	def bigPhotoMouseDown(self, event, config, gui):
		self.bigPhotoRefreshTimer(config, gui)
	
	def bigPhotoWindowToggleButtons(self, config, gui):
		w = gui.bigPhotoWindow
		if w.bFrame.isVisible:
			w.bFrame.grid_forget()
			w.vscroll.pack_forget()
			w.hscroll.pack_forget()
		else:
			w.vscroll.pack(side=tkinter.RIGHT, fill=tkinter.Y)
			w.hscroll.pack(side=tkinter.BOTTOM, fill=tkinter.X)
			w.bFrame.grid(row=2)
		w.bFrame.isVisible = not w.bFrame.isVisible
		
	def bigPhotoWindowDisableTimer(self, config, gui):
		w = gui.bigPhotoWindow
		if hasattr(w, 'autoHideTimer') and w.autoHideTimer:
			gui.root.after_cancel(w.autoHideTimer)
		if not w.bFrame.isVisible:
			self.bigPhotoWindowToggleButtons(config, gui)
	
	def onPhotoButton(self, config, gui, res):
		if gui.bigPhotoWindow:
			gui.bigPhotoWindow.destroy()
		#print('onPhotoButton():', str(res))
		gui.bigPhotoWindow = window = tkinter.Toplevel(gui.root)
		window.bind('<Destroy>', lambda event: self.bigPhotoWindowDestroyed(event, config, gui))
		window.autoHideTimer = {}
		#window.overrideredirect(True)  # Remove window decorations
		if res.photo:
			window.minsize(width=res.photo.width, height=res.photo.height)
		else:
			window.minsize(width=250, height=300)
		window.maxsize(width=config.screenWidth, height=config.screenHeight)
		window.grid_rowconfigure(0, weight=1, pad=0)
		window.grid_columnconfigure(0, weight=1, pad=0)
		window.canvas = canvas = tkinter.Canvas(window)
		canvas.config(borderwidth=0)
		canvas.grid(sticky=tkinter.W + tkinter.E + tkinter.S + tkinter.N, padx=0, pady=0, ipadx=0, ipady=0)
		#gui.bigPhotoWindow.vscroll = vscroll = Gui.AutoScrollbar(canvas, orient=tkinter.VERTICAL, command=canvas.yview)
		#vscroll.pack(side=tkinter.RIGHT, fill=tkinter.Y)
		#gui.bigPhotoWindow.hscroll = hscroll = Gui.AutoScrollbar(canvas, orient=tkinter.HORIZONTAL, command=canvas.xview)
		#hscroll.pack(side=tkinter.BOTTOM, fill=tkinter.X)
		thumbnailCanvasImage = canvas.create_image((0, 0), image=res.render, anchor=tkinter.NW)
		#canvas.config(scrollregion=canvas.bbox(tkinter.ALL), xscrollcommand=hscroll.set, yscrollcommand=vscroll.set)
		window.config(borderwidth=0, padx=0, pady=0)
		# TODO: flickr image size should be changeable without new query
		# TODO: this window could be used to resize/crop the image for wallpaper
		window.bFrame = bFrame = tk.Frame(window)
		bFrame.grid(row=2)
		bFrame.isVisible = True
		bFrame.bind('<Enter>', lambda event: self.bigPhotoWindowDisableTimer(config, gui))
		bFrame.bind('<Leave>', lambda event: self.bigPhotoRefreshTimer(config, gui))
		tk.Button(bFrame, text='Close', command=lambda: gui.bigPhotoWindow.destroy()).grid(row=1, column=1, padx=10, pady=2)
		noNewLines = Gui.makeTclSafeString(res.title.replace('\n', ' ').strip())
		window.textLabel = textLabel = tk.Label(bFrame, text='Use mouse wheel to zoom in/out and drag to scroll. Size: '
										+ Gui.photoSizeStr(res) + '. Title: ' + noNewLines)
		textLabel.grid(row=0, column=0, columnspan=3, padx=10, pady=2)
		textLabel.config(wraplength=min(res.photo.width, config.screenWidth))
		#print('onPhotoButton go to update()')
		gui.root.update_idletasks()  # show the thumbnail and Close button while the larger image is loading
		#print('onPhotoButton left update()')
		if res.url or res.filePath:
			if res.url:
				print('onPhotoButton(): Loading', str(res.url).encode('utf-8'))
				photo, file, mime = load_photo(res.url)
				photo = rotateByExif(config, res.flickrPhoto, photo)
				if photo and str(mime).find('image/gif') >= 0:
					count = 0
					for frame in ImageSequence.Iterator(photo):
						count += 1
					window.frameCount = count
					print('GIF with', str(count), 'frames')
			elif res.filePath:
				print('onPhotoButton(): Loading', res.filePath)
				file = res.filePath
				mime = 'Content-Type: image/jpeg'
				photo = Image.open(res.filePath)
			if not photo:
				l = tk.Label(bFrame, text='Failed to load photo')
				l.grid(row=1)
				self.applyColorStyle(l, 'PhotoLoadFailText', 'red')
			else:
				#window.render = {}
				#window.render[0] = render = ImageTk.PhotoImage(image=photo)
				window.bigPhoto = photo
				#window.bigPhotoZoom = 1.0
				if hasattr(window, 'frameCount') and window.frameCount > 1:
					gui.root.after(100, lambda: self.nextImageFrame(config, gui, 1))
				canvas.delete(thumbnailCanvasImage)
				#window.canvasImage = canvas.create_image((0, 0), image=render, anchor=tkinter.NW)

				window.vscroll = vscroll = tk.Scrollbar(canvas, orient=tkinter.VERTICAL, command=canvas.yview)
				vscroll.pack(side=tkinter.RIGHT, fill=tkinter.Y)
				window.hscroll = hscroll = tk.Scrollbar(canvas, orient=tkinter.HORIZONTAL, command=canvas.xview)
				hscroll.pack(side=tkinter.BOTTOM, fill=tkinter.X)
				canvas.config(xscrollcommand=hscroll.set, yscrollcommand=vscroll.set)

				canvas.bind('<MouseWheel>', lambda event: self.bigPhotoMouseWheel(event, config=config, gui=gui))
				window.userIsDragging = False
				canvas.bind('<B1-Motion>', lambda event: self.bigPhotoMouseDrag(event, config=config, gui=gui))
				canvas.bind('<ButtonRelease-1>', lambda event: self.bigPhotoMouseButtonUp(event, config=config, gui=gui))
				canvas.bind('<Button-1>', lambda event: self.bigPhotoMouseDown(event, config, gui))
				tk.Button(bFrame, text='Set as wallpaper',
					command=lambda: gui.root.after_idle(lambda: self.onSetWallpaperButton(config, gui, photo, file, mime, res))).grid(column=0, row=1, padx=10, pady=2)
				#tk.Button(bFrame, text='Fit to screen',
				#		command=lambda: self.onCropPhoto(config, gui, photo, canvas, bFrame)).grid(sticky=tkinter.W, column=2, row=0, padx=20, pady=2)
				tk.Button(bFrame, text='Crop to window area',
						command=lambda: self.onCropPhoto(config, gui, photo, canvas, bFrame)).grid(column=2, row=1, padx=10, pady=2)
				window.autoHideTimer = gui.root.after(Gui.autoHideDuration, lambda: self.bigPhotoWindowToggleButtons(config, gui))
				self.bigPhotoWindowUpdateBigPhoto(config, gui, photo)
				self.raiseWindow(config, gui, window)
		else:
			tk.Label(bFrame, text='No larger photo URL').grid(row=1)
	
	def nextResultImagePosition(self, config, gui, parent):
		parent.resultsCol += 1
		if parent.resultsCol == 4:
			parent.resultsCol = 0
			parent.resultsRow += 1

	@staticmethod
	def photoSizeStr(url):
		if url.size and url.size != (0, 0):
			return '(' + str(url.size[0]) + 'x' + str(url.size[1]) + ') '
		return ''
	
	threadResults = {}
	threadResultsLock = threading.Lock()
	threadResultEvent = threading.Event()
	
	@staticmethod
	def loadImageThread(resultPhoto, photoIndex):
		Gui.threadResultsLock.acquire()
		Gui.threadResults[photoIndex] = resultPhoto
		Gui.threadResultsLock.release()
		Gui.threadResultEvent.set()
		print('thread', photoIndex, 'exiting')
		
	def showThumbnailImage(self, config, gui, resultPhoto, parent):
		photoIndex = resultPhoto.index
		if resultPhoto.render:
			frame = tk.LabelFrame(parent, text=str(photoIndex) + ': ' + Gui.photoSizeStr(resultPhoto), relief=tkinter.GROOVE)
			frame.grid(row=parent.resultsRow, column=parent.resultsCol)
			tk.Button(frame, image=resultPhoto.render, command=lambda: gui.root.after_idle(lambda: self.onPhotoButton(config, gui, resultPhoto))).pack()
			resultPhoto.createTitleFunc(frame).pack()
			self.nextResultImagePosition(config, gui, parent)
			#if file:
			#	os.remove(file)
			#print('showThumbnailImage go to update_idletasks()')
			gui.root.update_idletasks()
			#print('showThumbnailImage left update_idletasks()')
		else:
			print('showOnePhoto(): skip ResultPhoto', str(photoIndex))
	
	def showOnePhoto(self, config, gui, resultPhoto, parent):
		print('showOnePhoto', str(resultPhoto.index))
		file, photo = '', {}
		if not resultPhoto.render:
			if resultPhoto.photo:
				print('showOnePhoto(): already loaded')
				# it's already loaded (possibly in earlier call to showOnePhoto())
				photo = resultPhoto.photo
			elif resultPhoto.thumbnailUrl:
				print('showOnePhoto(): Loading URL required', str(resultPhoto.thumbnailUrl).encode('utf-8'))
				photo, file, mime = load_photo(resultPhoto.thumbnailUrl)
				#return resultPhoto.thumbnailUrl
			elif resultPhoto.thumbnailFilePath:
				print('showOnePhoto(): Loading file', resultPhoto.thumbnailFilePath)
				photo = Image.open(resultPhoto.thumbnailFilePath)
				#file = url.thumbnailFilePath
			if photo:
				resultPhoto.render = ImageTk.PhotoImage(image=photo)
				resultPhoto.photo = photo
				self.showThumbnailImage(config, gui, resultPhoto, parent)
			else:
				print('no photo object for', resultPhoto.index)
			#resultPhoto.thread = threading.Thread(name='loadImageThread' + str(photoIndex), target=lambda: Gui.loadImageThread(resultPhoto, photoIndex))
			#resultPhoto.thread.start()
		else:
			self.showThumbnailImage(config, gui, resultPhoto, parent)
		return ''
	
	def createResultPageButtons(self, config, gui, urls, parent):
		print('createResultPageButtons', urls.nextIndex, len(urls), Gui.photoCountOnPage)
		#tk.Button(parent, text='Close tab', command=lambda: self.destroyResultsTab(config, gui, parent.type)).grid(row=0, column=5, padx=10, pady=10, sticky=tkinter.NE)
		frame = tk.Frame(parent)
		frame.grid(row=1, column=5)
		if urls.nextIndex > Gui.photoCountOnPage and urls.itemIsCached(urls.nextIndex - Gui.photoCountOnPage - 1):
			tk.Button(frame, text='<<',
				command=lambda urls=urls: gui.root.after_idle(lambda urls=urls: self.loadPrevPage(config, gui, urls, parent))).pack(pady=10)
		if urls.itemIsCached(urls.nextIndex):
			tk.Button(frame, text='>>',
				command=lambda urls=urls: gui.root.after_idle(lambda urls=urls: self.loadNextPage(config, gui, urls, parent))).pack(pady=10)
		elif parent.loadMoreFunc:
			tk.Button(frame, text='Load more', command=parent.loadMoreFunc).pack(pady=10)
		if parent.loadMoreButtons:
			parent.loadMoreButtons(urls, parent, frame)

	def loadPrevPage(self, config, gui, urls, parent):
		print('loadPrevPage old:', urls.nextIndex)
		if urls.nextIndex <= Gui.photoCountOnPage:
			print('loadPrevPage: already on the first page')
		if urls.nextIndex % Gui.photoCountOnPage > 0:
			urls.nextIndex -= Gui.photoCountOnPage + urls.nextIndex % Gui.photoCountOnPage
		else:
			urls.nextIndex -= 2 * Gui.photoCountOnPage
		print('loadPrevPage new:', urls.nextIndex)
		#parent = self.createAndSelectResultsPage(config, gui, parent.type, title='Result page', results=urls, copyFromOld=True)
		self.loadNextPage(config, gui, urls, parent)
	
	def loadNextPage(self, config, gui, urls, parent):
		print('loadNextPage:', urls.nextIndex)
		parent = self.createAndSelectResultsPage(config, gui, parent.type, title='Result page', results=urls, copyFromOld=True)
		assert gui.resultPage[parent.type] == parent
		#for widget in parent.grid_slaves():
		#	widget.destroy()
		count = len(urls)
		if count == 0:
			tk.Label(parent, text='No results').grid(padx=10, pady=10)
		else:
			startIndex = urls.nextIndex # min(urls.nextIndex, count - 1)
			endIndex = urls.nextIndex + Gui.photoCountOnPage - 1 # min(urls.nextIndex + Gui.photoCountOnPage - 1, count - 1)
			tk.Label(parent, text='Loading photos ' + str(startIndex) + '..' + str(endIndex)).grid(padx=10, pady=10)
			print('Loading photos ' + str(startIndex) + '..' + str(endIndex))
			#print('loadNextPage go to update_idletasks()')
			gui.root.update_idletasks()
			#print('loadNextPage left update_idletasks()')
			parent.resultsRow = parent.resultsCol = 0
			showed = urls.showPageItems(startIndex, parent)
			urls.nextIndex += showed
			#for urlIndex in range(startIndex, endIndex + 1):
			#	ret = urls.showItem(urlIndex, parent)
			#	if ret:
			#		#self.showOnePhoto(config, gui, item, parent)
			#		urls.nextIndex += 1
		self.createResultPageButtons(config, gui, urls, parent)

	@staticmethod
	def makeTclSafeString(title):
		# a hack to remove illegal unicode that Tcl does not like
		char_list = [title[j] for j in range(len(title)) if ord(title[j]) in range(65536)]
		safeTitle=''
		for j in char_list:
			safeTitle = safeTitle + j
		return safeTitle
	
	# virtual list of results implementation
	class Results(object):
		def __init__(self, config, gui, guiinfo, items = [], loadPageFunc = {}):
			self.nextIndex = self.pagesTotal = 0
			self.items = {}
			for i in items:
				self.items[i.index] = i
			self.loadPageFunc = loadPageFunc
			self.config = config
			self.gui = gui
			self.guiinfo = guiinfo
		
		def __len__(self):
			return len(self.items)
			
		def values(self):
			return self.items.values()

		# different logic here because item index does not make sense in recents list
		def addRecentItem(self, item):
			if item in self.items.values():
				return
			newItem = copy.copy(item)
			newItem.index = len(self.items)
			assert not newItem.index in self.items
			self.items[newItem.index] = newItem
		
		def addItem(self, item):
			self.items[item.index] = item
			
		def itemIsCached(self, index):
			return index in self.items
			
		def pageIsCached(self, pageNum):
			firstIndex = (pageNum - 1) * Gui.photoCountOnPage
			return firstIndex in self.items
		
		'''
		def getPageItems(self, pageNum):
			assert pageNum > 0
			items = []
			firstIndex = (pageNum - 1) * Gui.photoCountOnPage
			failedPages = []
			for index in map(lambda n: firstIndex + n, range(Gui.photoCountOnPage)):
				itemPage = Gui.calculatePageNumber(index)
				if not index in self.items and not itemPage in failedPages:
					ret = self.loadPage(itemPage)
					if not ret:
						failedPages.append(itemPage)
				if index in self.items:
					items.append(self.items[index])
			return items
		'''
		def loadPage(self, pageNum):
			wasCached = self.pageIsCached(pageNum)
			oldCount = len(self.items)
			if self.loadPageFunc:
				ret = self.loadPageFunc(self, pageNum)
			return len(self.items) > oldCount or wasCached
		
		def showPageItems(self, firstItem, parent):
			#pageNum = Gui.calculatePageNumber(firstItem)
			#if not self.pageIsCached(pageNum):
			#	self.loadPage(pageNum)
			showed = 0
			for i in map(lambda n: firstItem + n, range(Gui.photoCountOnPage)):
				item = self.getItem(i)
				if item:  #self.itemIsCached(i):
					self.gui.showOnePhoto(self.config, self.guiinfo, item, parent)
					showed += 1
			return showed
		
		def getItem(self, index):
			if index in self.items:
				return self.items[index]
			self.loadPage(Gui.calculatePageNumber(index))
			if index in self.items:
				return self.items[index]
			print('Results.getItem failed to load', index)
			return None
			
	class ResultPhoto(object):
		def __init__(self):
			self.thumbnailFilePath = ''
			self.filePath = ''
			self.thumbnailUrl = ''
			self.url = ''
			self.size = (0, 0)
			self.title = ''
			self.photo = {}
			self.render = {}
			self.createTitleFunc = lambda parent: self._createTitle(parent)
			self.flickrPhoto = {}
			self.index = -1   # index in all results

		# Create a tk/ttk widget that is placed under the thumbnail image. Default implementation
		def _createTitle(self, parent):
			# Take max. 3 lines
			tmp = str.split(self.title, '\n')
			if isinstance(tmp, list):
				threeRows = tmp[:2]
				threeRows = '\n'.join(threeRows)
			else:
				threeRows = tmp
			title = threeRows[:100] + ('...' if len(threeRows) >= 100 else '')
			return tk.Label(parent, text=Gui.makeTclSafeString(title), wraplength=250)

	def on_close_press(self, event, gui):
		"""Called when the button is pressed over the close button"""
		notebook = gui.notebook
		element = notebook.identify(event.x, event.y)
		print(element)
		clicked_tab = notebook.tk.call(notebook._w, "identify", "tab", event.x, event.y)
		print(clicked_tab)
		clicked_tab = notebook.tk.call(notebook._w, "identify", "element", event.x, event.y)
		print(clicked_tab)

		if "close" in element:
			index = notebook.index("@%d,%d" % (event.x, event.y))
			
	def createAndSelectResultsPage(self, config, gui, type, title='Results', results={}, titleFunc={}, copyFromOld=False):
		print(str(title), str(titleFunc), str(copyFromOld))
		resultPage = tk.Frame(gui.notebook)
		resultPage.type = type
		resultPage.loadMoreFunc = resultPage.loadMoreButtons = {}
		if copyFromOld and (type in gui.resultPage) and gui.resultPage[type]:
			oldPage = gui.resultPage[type]
			#resultPage.resultsNextIndex = oldPage.resultsNextIndex
			resultPage.loadMoreFunc = oldPage.loadMoreFunc
			resultPage.loadMoreButtons = oldPage.loadMoreButtons
			resultPage.resultsRow = resultPage.resultsCol = 0
			resultPage.titleFunc = oldPage.titleFunc
			#if hasattr(oldPage, 'pagesTotal'):
			#	resultPage.pagesTotal = oldPage.pagesTotal
			resultPage.title = oldPage.title if not oldPage.titleFunc else oldPage.titleFunc(results.nextIndex)
		else:
			resultPage.resultsRow = resultPage.resultsCol = 0
			resultPage.titleFunc = titleFunc
			resultPage.title = title if not titleFunc else titleFunc(0)
		self.destroyResultsTab(config, gui, type)
		gui.notebook.add(resultPage, text=resultPage.title)
		for row in range(6):
			resultPage.grid_rowconfigure(row, pad=5)
		for col in range(4):
			resultPage.grid_columnconfigure(col, pad=5)
		count = gui.notebook.index('end')
		gui.notebook.select(count - 1)
		gui.resultPage[type] = resultPage
		return resultPage
	
	def createDefaultLabelWithSimilarButton(self, parent, config, gui, res):
		frame = tk.Frame(parent)
		defaultLabel = res._createTitle(frame)
		defaultLabel.pack()
		tk.Button(frame, text='Google similar images',
			command=lambda: gui.root.after_idle(lambda: self.googleQuery(config, gui, similar_images=res.url))).pack()
		return frame

	def instaTabTitleFunc(self, config, gui, resultsNextIndex, prefix):
		print('instaTabTitleFunc', resultsNextIndex, prefix)
		return prefix + str(Gui.calculatePageNumber(resultsNextIndex))
		
	def instaQuery(self, config, gui, maxid='', results={}):
		print('instaQuery', maxid, len(results))
		self.updateConfig(config, gui)
		if not results:
			results = Gui.Results(config, self, gui)
		config.instagramTag = config.instagramTag.replace('\n', '').replace('#', '').replace(' ', '').strip()
		resultPage = self.createAndSelectResultsPage(config, gui, 'instagram', results=results,
						titleFunc=lambda nextIndex: self.instaTabTitleFunc(config, gui, nextIndex, '#' + config.instagramTag + ' page '),
						copyFromOld=True if results else False)
		# Note: cannot cache this, does not work for different searches
		gui.instaApi = api = InstagramAPI(config.instagramLogin, gui.instaPW.get())
		if (api.login()):
			#api.getSelfUserFeed()  # get self user feed
			api.getHashtagFeed(config.instagramTag, maxid=maxid)
			#print(str(api.LastJson).encode('utf-8'))  # print last response JSON
			if api.LastJson['items'] and ('next_max_id' in api.LastJson):
				print('next_max_id:', str(api.LastJson['next_max_id']))
				resultPage.next_max_id = str(api.LastJson['next_max_id'])
				resultPage.loadMoreButtons = lambda resObj, parent, frame: self.defaultLoadMoreButtons(config, gui, resObj, frame, canSkipPages=False)
				resultPage.loadMoreFunc = lambda: gui.root.after_idle(lambda: self.instaQuery(config, gui, maxid=resultPage.next_max_id, results=results))
			else:
				resultPage.next_max_id = ''
				resultPage.loadMoreFunc = {}
			index = results.nextIndex
			showed = 0
			print('item count:', len(api.LastJson['items']))
			for photo in api.LastJson['items']:
				if photo['media_type'] == 1:
					res = self.ResultPhoto()
					res.index = index
					if photo['caption'] and photo['caption']['text']:
						#tmp = str.split(photo['caption']['text'], '\n')
						#res.title = tmp[0]
						res.title = photo['caption']['text']
					thumbSize = (1000, 1000)
					for c in photo['image_versions2']['candidates']:
						# find the smallest (thumbnail) and the biggest photo
						if c['width'] < thumbSize[0] and c['height'] < thumbSize[1]:
							res.thumbnailUrl = c['url']
							thumbSize = (c['width'], c['height'])
						if c['width'] > res.size[0] and c['height'] > res.size[1]:
							res.url = c['url']
							res.size = (c['width'], c['height'])
					if res.thumbnailUrl:
						res.createTitleFunc = lambda parent, res=res: self.createDefaultLabelWithSimilarButton(parent, config, gui, res)
						results.addItem(res)
						if showed < Gui.photoCountOnPage:
							#print(str(photo.keys()))
							#print(str(photo['image_versions2']['candidates']))
							self.showOnePhoto(config, gui, res, resultPage)
							results.nextIndex += 1
							showed += 1
					index += 1
				else:
					print('wrong media_type:', photo['media_type'])

			#sys.exit()
			#items = api.LastJson["ranked_items"]
			#print('ranked_items:')
			#for photo in items:
			#	if photo['media_type'] == 1:
			#		for c in photo['image_versions2']['candidates']:
			#			print(str(c['width']).encode('utf-8'))
			#			print(str(c['height']).encode('utf-8'))
			#			print(str(c['url']).encode('utf-8'))
			#			break
			
			self.createResultPageButtons(config, gui, results, resultPage)
		else:
			gui.instaPW.set('')
			gui.tkVars['instagramLogin'].set('Login failed!')

	@staticmethod
	def getDatetime(s):
		year, month, day = str.split(s, '/')
		#print(str(str.split(s, '/')))
		return datetime.date(year=int(year), month=int(month), day=int(day))

	def createGoogleLabel(self, config, gui, parent, res):
		frame = tk.Frame(parent)
		tk.Label(frame, text=Gui.makeTclSafeString(res.title), wraplength=max(250, res.photo.width)).pack()
		tk.Button(frame, text='Open host page (' + res.imageHost + ')', command=lambda: webbrowser.open(res.sourcePage, new=2)).pack()
		tk.Button(frame, text='Similar images',
			command=lambda: gui.root.after_idle(lambda: self.googleQuery(config, gui, similar_images=res.url))).pack()
		return frame

	def googleSimilarImagesWithUpload(self, config, gui, filePath='testimage.jpg'):
		if not hasattr(gui, 'googleAPI') or not gui.googleAPI:
			obj = gui.googleAPI = google_images_download.googleimagesdownload()
		else:
			obj = gui.googleAPI
		obj.similar_images_upload_image(filePath)

	def googleTabTitleFunc(self, config, gui, resultsNextIndex, prefix, postfix):
		print('googleTabTitleFunc', resultsNextIndex, prefix, postfix)
		return prefix + str(Gui.calculatePageNumber(resultsNextIndex)) + postfix
		
	def googleQuery(self, config, gui, similar_images=''):
		results = Gui.Results(config, self, gui)
		self.updateConfig(config, gui)
		if not hasattr(gui, 'googleAPI') or not gui.googleAPI:
			obj = gui.googleAPI = google_images_download.googleimagesdownload()
		else:
			obj = gui.googleAPI
		config.googleKeywords = str.strip(config.googleKeywords, '\n')  # TODO make common keyword clean-up func
		arguments = {'keywords': config.googleKeywords if not similar_images else '', 'print_urls': False, 'limit': 100,
					'output_directory': 'googleimages', 'no_directory': True,
					'thumbnail': True, 'similar_images': similar_images, 'returnUrlsOnly': True}
		if config.googleImageFormat != 'Not specified':
			arguments['format'] = config.googleImageFormat
		if config.googleImageType:
			arguments['type'] = config.googleImageType
		if config.googleImageSize != 'Not specified':
			arguments['size'] = config.googleImageSize
		if config.googleImageLicense:
			arguments['usage_rights'] = config.googleImageLicense
		if config.googleImageColor:
			arguments['color'] = config.googleImageColor
		if config.googleImageColorType:
			arguments['color_type'] = config.googleImageColorType
		paths,urls = obj.download(arguments)
		results.pagesTotal = Gui.calculatePageNumber(len(urls) - 1)
		if similar_images:
			resultPage = self.createAndSelectResultsPage(config, gui, 'googleSimilar', results=results,
							titleFunc=lambda nextIndex: self.googleTabTitleFunc(config, gui, nextIndex,
								'Similar images page ', ' of ' + str(results.pagesTotal)))
		else:
			resultPage = self.createAndSelectResultsPage(config, gui, 'google', results=results,
							titleFunc=lambda nextIndex: self.googleTabTitleFunc(config, gui, nextIndex,
								'"' + str(config.googleKeywords) + '" page ', ' of ' + str(results.pagesTotal)))
		#resultPhotos = []
		#loading = 0
		for index, obj in enumerate(urls):
			res = self.ResultPhoto()
			res.index = index
			res.url = obj['image_link']
			res.thumbnailUrl = obj['image_thumbnail_url']
			res.title = obj['image_description']
			res.size = (int(obj['image_width']), int(obj['image_height']))
			res.sourcePage = obj['image_source']
			res.imageHost = obj['image_host']
			res.createTitleFunc = lambda parent, res=res: self.createGoogleLabel(config, gui, parent, res)
			results.addItem(res)
			if index < Gui.photoCountOnPage:
				self.showOnePhoto(config, gui, res, resultPage)
				results.nextIndex += 1
		#while loading > 0:
		#	if not Gui.threadResultEvent.isSet():
		#		print('main thread: waiting event')
		#		Gui.threadResultEvent.wait()
		#	Gui.threadResultsLock.acquire()
		#	for key, value in Gui.threadResults:
		#		self.showThumbnailImage(config, gui, value, resultPage)
		#		loading -= 1
		#	Gui.threadResultsLock.release()
		#	assert loading >= 0
		resultPage.loadMoreButtons = lambda resObj, parent, frame: self.defaultLoadMoreButtons(config, gui, resObj, frame, canSkipPages=False)
		self.createResultPageButtons(config, gui, results, resultPage)
		
	def createGooglePage(self, config, gui):
		gpage = gui.googlePage
		tkVars = gui.tkVars
		for col in range(5):
			gpage.grid_columnconfigure(col, pad=10, weight=1)
		tk.Label(gpage, text='Search keywords').grid(row=0, sticky=tkinter.W, padx=10)
		tk.Entry(gpage, textvariable=tkVars['googleKeywords']).grid(row=1, columnspan=2, column=0, sticky=tkinter.W+tkinter.E, padx=10)

		biggerThanFrame = tk.Frame(gpage)
		for col in range(2):
			biggerThanFrame.grid_columnconfigure(col, pad=1)
		biggerThanFrame.grid(row=10, padx=10, sticky=tkinter.W)
		tk.Label(biggerThanFrame, text='Preferred photo size:').grid(sticky=tkinter.W, columnspan=2, padx=10)
		for row, text in enumerate(['Not specified', 'large','medium','icon','>400*300','>640*480','>800*600','>1024*768',
									'>2MP','>4MP','>6MP','>8MP','>10MP','>12MP','>15MP','>20MP','>40MP','>70MP'], 1):
			tk.Radiobutton(biggerThanFrame, text=text, variable=tkVars['googleImageSize'], value=text).grid(row=row, sticky=tkinter.W)

		typeContainer = tk.Frame(gpage)
		typeContainer.grid(row=10, column=1, padx=10, sticky=tkinter.W)
		formatFrame = tk.Frame(typeContainer)
		formatFrame.pack(pady=10)
		tk.Label(formatFrame, text='Image format:').grid(padx=10, sticky=tkinter.W)
		for row, text in enumerate(['Not specified', 'jpg', 'gif', 'png', 'bmp', 'webp', 'ico'], 1):
			tk.Radiobutton(formatFrame, text=text, variable=tkVars['googleImageFormat'], value=text).grid(row=row, padx=10, sticky=tkinter.W)

		#'face':'itp:face','photo':'itp:photo','clip-art':'itp:clip-art','line-drawing':'itp:lineart','animated':'itp:animated'
		typeFrame = tk.Frame(typeContainer)
		typeFrame.pack()
		tk.Label(typeFrame, text='Image type:').grid(padx=10, sticky=tkinter.W)
		for row, (text, value) in enumerate([('Not specified', ''), ('Face', 'face'), ('Photo', 'photo'), ('Clip art', 'clip-art'),
											 ('Line drawing', 'line-drawing'), ('Animated', 'animated')], 1):
			tk.Radiobutton(typeFrame, text=text, variable=tkVars['googleImageType'], value=value).grid(row=row, padx=10, sticky=tkinter.W)

		licenseFrame = tk.Frame(gpage)
		licenseFrame.grid(row=10, column=2, padx=10, sticky=tkinter.W)
		tk.Label(licenseFrame, text='Usage rights:').grid(padx=10, sticky=tkinter.W)
		for row, (text, value) in enumerate([('Not specified', ''),
											 ('Labeled for reuse with modification', 'labeled-for-reuse-with-modifications'),
											 ('Labeled for reuse', 'labeled-for-reuse'),
											 ('Labeled for non-commercial reuse with modification', 'labeled-for-noncommercial-reuse-with-modification'),
											 ('Labeled for non-commercial reuse', 'labeled-for-nocommercial-reuse')], 1):
			tk.Radiobutton(licenseFrame, text=text, variable=tkVars['googleImageLicense'], value=value).grid(row=row, padx=10, sticky=tkinter.W)

		#{'red':'ic:specific,isc:red', 'orange':'ic:specific,isc:orange', 'yellow':'ic:specific,isc:yellow', 'green':'ic:specific,isc:green', 'teal':'ic:specific,isc:teel', 'blue':'ic:specific,isc:blue', 'purple':'ic:specific,isc:purple', 'pink':'ic:specific,isc:pink', 'white':'ic:specific,isc:white', 'gray':'ic:specific,isc:gray', 'black':'ic:specific,isc:black', 'brown':'ic:specific,isc:brown'}
		
		colorContainer = tk.Frame(gpage)
		colorContainer.grid(row=10, column=3, padx=10, sticky=tkinter.W)
		colorFrame = tk.Frame(colorContainer)
		colorFrame.pack(pady=10)
		tk.Label(colorFrame, text='Color:').grid(padx=10, sticky=tkinter.W)
		for row, (text, value) in enumerate([('Not specified', ''), ('Red', 'red'), ('Orange', 'orange'), ('Yellow', 'yellow'), ('Green', 'green'),
											 ('Teal', 'teal'), ('Blue', 'blue'), ('Purple', 'purple'), ('Pink', 'pink'), ('White', 'white'),
											 ('Gray', 'gray'), ('Black', 'black'), ('Brown', 'brown')], 1):
			tk.Radiobutton(colorFrame, text=text, variable=tkVars['googleImageColor'], value=value).grid(row=row, sticky=tkinter.W)

		#'full-color':'ic:color', 'black-and-white':'ic:gray','transparent':'ic:trans'
		colorTypeFrame = tk.Frame(colorContainer)
		colorTypeFrame.pack()
		tk.Label(colorTypeFrame, text='Color type:').grid(padx=10, sticky=tkinter.W)
		for row, (text, value) in enumerate([('Not specified', ''), ('Full color', 'full-color'),
											 ('Black and white', 'black-and-white'), ('Transparent', 'transparent')], 1):
			tk.Radiobutton(colorTypeFrame, text=text, variable=tkVars['googleImageColorType'], value=value).grid(row=row, sticky=tkinter.W)

		tk.Button(gpage, text='Show matches (max. 100)',
			command=lambda: gui.root.after_idle(lambda: self.googleQuery(config, gui))).grid(row=20, padx=10, pady=10, sticky=tkinter.W)

	def createPinterestLabel(self, config, gui, parent, res):
		frame = tk.Frame(parent)
		tk.Label(frame, text=Gui.makeTclSafeString(res.title[:200]), wraplength=max(250, res.photo.width if res.photo else 250)).pack()
		if res.imageHost and res.sourcePage:
			tk.Button(frame, text='Open host page (' + res.imageHost + ')', command=lambda: webbrowser.open(res.sourcePage, new=2)).pack()
		tk.Button(frame, text='Similar images',
			command=lambda: gui.root.after_idle(lambda: self.googleQuery(config, gui, similar_images=res.url))).pack()
		return frame

	@staticmethod
	def calculatePageNumber(index):
		print('calculatePageNumber', index)
		#addOne = ((index + Gui.photoCountOnPage) % Gui.photoCountOnPage) > 0
		modulo = index % Gui.photoCountOnPage
		return int(max(1, math.ceil((index + Gui.photoCountOnPage - modulo) / Gui.photoCountOnPage))) #+ (1 if addOne else 0)
	
	def pinterestTabTitleFunc(self, config, gui, resultsNextIndex, prefix):
		print('pinterestTabTitleFunc', resultsNextIndex, prefix)
		return prefix + str(Gui.calculatePageNumber(resultsNextIndex))

	def pinterestQuery(self, config, gui, nextPage=False, results={}):
		print('pinterestQuery()', nextPage, len(results))
		self.updateConfig(config, gui)
		if not results:
			results = Gui.Results(config, self, gui)
		config.pinterestQuery = config.pinterestQuery.replace('\n', '').strip()
		resultPage = self.createAndSelectResultsPage(config, gui, 'pinterest', results=results,
						titleFunc=lambda nextIndex: self.pinterestTabTitleFunc(config, gui, nextIndex, '"' + config.pinterestQuery + '" page '),
						copyFromOld=True if results else False)
		if not hasattr(gui, 'pinterestApi'):
			gui.pinterestApi = api = Pinterest(username_or_email = config.pinterestUsername, password = gui.pinterestPW.get())
		else:
			api = gui.pinterestApi
		if api.login():
			pins = api.search_pins(query = config.pinterestQuery, next_page = nextPage)
			if pins:
				startIndex = results.nextIndex
				print(str(pins[0]['img']))
				for index, obj in enumerate(pins):
					res = self.ResultPhoto()
					res.index = index + startIndex
					orig = obj['img']['orig']
					res.url = orig['url']
					res.thumbnailUrl = obj['img']['170x']['url']
					res.title = obj['title'] + ('. ' if obj['title'] and not obj['title'].endswith('.') else '') + (obj['description'] if not obj['description'].startswith(obj['title']) else '')
					res.size = (int(orig['width']), int(orig['height']))
					res.sourcePage = obj['link']
					res.imageHost = obj['domain']
					res.createTitleFunc = lambda parent, r=res: self.createPinterestLabel(config, gui, parent, r)
					results.addItem(res)
					if index < Gui.photoCountOnPage:
						self.showOnePhoto(config, gui, res, resultPage)
						results.nextIndex += 1
		# TODO: find out if there's next page
		resultPage.loadMoreFunc = lambda: gui.root.after_idle(lambda: self.pinterestQuery(config, gui, nextPage=True, results=results))
		resultPage.loadMoreButtons = lambda resObj, parent, frame: self.defaultLoadMoreButtons(config, gui, resObj, frame, canSkipPages=False)
		self.createResultPageButtons(config, gui, results, resultPage)

	def createPinterestPage(self, config, gui):
		ppage = gui.pinterestPage
		tkVars = gui.tkVars
		for col in range(5):
			ppage.grid_columnconfigure(col, pad=10, weight=1)

		tk.Label(ppage, text='Username or e-mail').grid(sticky=tkinter.W)
		tk.Entry(ppage, textvariable=tkVars['pinterestUsername']).grid(row=1, sticky=tkinter.W+tkinter.E, padx=3)
		tk.Label(ppage, text='Password (not saved)').grid(row=0, column=2, sticky=tkinter.W)
		gui.pinterestPW = pwEntry = tk.Entry(ppage, show='*')
		pwEntry.grid(row=1, column=2, sticky=tkinter.W+tkinter.E, padx=3)

		tk.Label(ppage, text='Query').grid(row=3, sticky=tkinter.W)
		tk.Entry(ppage, textvariable=tkVars['pinterestQuery']).grid(row=4, columnspan=2, sticky=tkinter.W+tkinter.E, padx=3)

		tk.Button(ppage, text='Show matches',
			command=lambda: gui.root.after_idle(lambda: self.pinterestQuery(config, gui))).grid(row=5, padx=10, pady=10, sticky=tkinter.W)

	def createInstaPage(self, config, gui):
		ipage = gui.instaPage
		tkVars = gui.tkVars
		#for row in range(6):
		#	ipage.grid_rowconfigure(row, pad=10)
		for col in range(3):
			ipage.grid_columnconfigure(col, pad=10, weight=1)

		tk.Label(ipage, text='Instagram login').grid(row=0, sticky=tkinter.W, padx=10)
		tk.Label(ipage, text='Instagram password (not saved)').grid(row=0, column=2, sticky=tkinter.W, padx=10)

		tk.Entry(ipage, textvariable=tkVars['instagramLogin']).grid(row=1, column=0, sticky=tkinter.W+tkinter.E, padx=10)
		gui.instaPW = tkinter.StringVar()
		tk.Entry(ipage, textvariable=gui.instaPW, show='*').grid(row=1, column=2, sticky=tkinter.W+tkinter.E, padx=10)

		tk.Label(ipage, text='Hash tag').grid(row=3, sticky=tkinter.W, padx=10)
		tk.Entry(ipage, textvariable=tkVars['instagramTag']).grid(row=4, sticky=tkinter.W+tkinter.E, padx=10)

		tk.Button(ipage, text='Show matches',
			command=lambda: gui.root.after_idle(lambda c=config, g=gui, m='', r={}: self.instaQuery(c, g, maxid=m, results=r))).grid(row=5, padx=10, pady=10, sticky=tkinter.W)
		
	def createFlickrPage(self, config, gui):
		fpage = gui.flickrPage
		tkVars = gui.tkVars

		#for row in range(12):
		#	fpage.grid_rowconfigure(row, pad=(10 if row < 6 else 1))
		for col in range(3):
			fpage.grid_columnconfigure(col, weight=1, pad=10)

		tk.Label(fpage, text='API key (mandatory)').grid(sticky=tkinter.W)
		tk.Entry(fpage, textvariable=tkVars['flickrApiKey']).grid(row=1, sticky=tkinter.W+tkinter.E, padx=3)
		tk.Label(fpage, text='API secret (optional)').grid(row=0, column=2, sticky=tkinter.W)
		tk.Entry(fpage, textvariable=tkVars['flickrApiSecret']).grid(row=1, column=2, sticky=tkinter.W+tkinter.E, padx=3)

		self.createGroupEntries(config, gui)

		parent = tk.LabelFrame(fpage, text='Photos Search (flickr.photos.search API)', relief=tkinter.GROOVE)
		parent.grid(row=3, columnspan=3, sticky=tkinter.W+tkinter.E, padx=10)
		for column in range(3):
			parent.grid_columnconfigure(column, pad=10, weight=1, minsize=30)
		#for row in range(7):
		#	parent.grid_rowconfigure(row, pad=10)
		tk.Label(parent, text='Space-separated tags (optional)').grid(row=0, sticky=tkinter.W, padx=10)
		tk.Entry(parent, textvariable=tkVars['globalTags']).grid(row=1, columnspan=3, sticky=tkinter.W+tkinter.E, padx=10)
		tk.Radiobutton(parent, text='Match any', variable=tkVars['globalTagMode'], value='any').grid(row=0, column=1, sticky=tkinter.W)
		tk.Radiobutton(parent, text='Match all', variable=tkVars['globalTagMode'], value='all').grid(row=0, column=2, sticky=tkinter.W)
		tk.Label(parent, text='''Photos who's title, description or tags contain the text below, "-cat" excludes results that match "cat"''').grid(row=2, sticky=tkinter.W, padx=10, columnspan=3)
		tk.Entry(parent, textvariable=tkVars['freeText']).grid(row=3, columnspan=3, sticky=tkinter.W+tkinter.E, padx=10)
		tk.Label(parent, text='Uploaded by user (optional):').grid(row=4, sticky=tkinter.W, padx=10)
		tk.Entry(parent, textvariable=tkVars['userId']).grid(row=5, sticky=tkinter.W+tkinter.E, padx=10)

		tk.Label(parent, text='Min. upload date:').grid(row=4, column=1, sticky=tkinter.W, padx=10)
		gui.minDateEntry = DateEntry(parent, width=12)
		gui.minDateEntry.grid(row=5, column=1, sticky=tkinter.W, padx=10)
		if config.minUploadDate:
			gui.minDateEntry.set_date(Gui.getDatetime(config.minUploadDate))
		tk.Label(parent, text='Max. upload date:').grid(row=4, column=2, sticky=tkinter.W, padx=10)
		gui.maxDateEntry = DateEntry(parent, width=12)
		gui.maxDateEntry.grid(row=5, column=2, sticky=tkinter.W, padx=10)
		if config.maxUploadDate:
			gui.maxDateEntry.set_date(Gui.getDatetime(config.maxUploadDate))

		tk.Button(parent, text='Show matches',
			command=lambda: gui.root.after_idle(lambda: self.onPhotosSearch(config, gui))).grid(row=6, padx=10, pady=10, sticky=tkinter.W)
		self.queryLabel = tk.Label(parent)
		self.queryLabel.grid(row=6, column=1, sticky=tkinter.W, padx=10)
		
		tk.Label(fpage, text='Preferred photo size:').grid(row=6, sticky=tkinter.W, padx=10)
		for row, text in enumerate(['Original', 'Large', 'Medium', 'Small'], 7):
			tk.Radiobutton(fpage, text=text, variable=tkVars['largestSizeToRequest'], value=text).grid(row=row, padx=20, sticky=tkinter.W)

	def devartAuthorization(self, config, gui):
		self.updateConfig(config, gui)
		#create new client with the authorization code grant type
		da = deviantart.Api(
			config.devartApiKey,
			config.devartApiSecret,

			#must be the same as defined as in your application on DeviantArt
			redirect_uri="http://www.icesus.org/Icesus/",

			standard_grant_type="authorization_code",

			#the scope you want to access (default => everything)
			#scope="axilirator"
		);

		#The authorization URI: redirect your users to this
		auth_uri = da.auth_uri

		print("Please authorize app: " + str(auth_uri))

		#Enter the value of the code parameter, found in to which DeviantArt redirected to
		code = input("Enter code:")

		#Try to authenticate with the given code
		try:
			da.auth(code=code)
		except deviantart.api.DeviantartError as e:
			print("Couldn't authorize user. Error: {}".format(e))

		#If authenticated and access_token present
		if da.access_token:

			print("The access token {}.".format(da.access_token))
			print("The refresh token {}.".format(da.refresh_token))

			#the User object of the authorized user
			user = da.get_user()

			print("The name of the authorized user is {}.".format(user.username))

	def createDevartLabel(self, config, gui, parent, res):
		frame = tk.Frame(parent)
		l = tk.Label(frame, text=Gui.makeTclSafeString(res.title), wraplength=250)
		l.pack()
		# use Text widget for category_path so that it can be copied to the clipboard
		text = ('Cat.: ' + res.category_path).strip()
		t = tkinter.Text(frame, height=1, width=len(text), font=tk.Style().lookup('TLabel', 'font'))
		t.insert(tkinter.END, text)
		t.configure(state='disabled', bg=gui.root.cget('bg'), relief=tkinter.FLAT)
		t.pack()
		tk.Button(frame, text='More like this',
			command=lambda: gui.root.after_idle(lambda: self.onDevartQuery(config, gui, seed=res.deviationid, endpoint='morelikethis'))).pack()
		return frame

	def defaultLoadMoreButtons(self, config, gui, resObj, frame, canSkipPages=True):
		nextPage = Gui.calculatePageNumber(resObj.nextIndex)
		print('defaultLoadMoreButtons', resObj.nextIndex, len(resObj), 'next page:', nextPage, '/', resObj.pagesTotal)
		if nextPage > 2 and not resObj.pageIsCached(nextPage - 2) and resObj.loadPageFunc:
			tk.Button(frame, text='Load prev page', command=lambda np=nextPage: gui.root.after_idle(lambda np=np: resObj.loadPage(np-2))).pack(pady=10)
		if canSkipPages:
			for n in [10, 100, 1000, 10000]:
				if nextPage - n - 1 > 0:
					tk.Button(frame, text='Back ' + str(n) + ' pages', command=lambda n=n, np=nextPage: gui.root.after_idle(lambda n=n, np=np: resObj.loadPage(np-n-1))).pack(pady=10)
		
		if nextPage <= resObj.pagesTotal and not resObj.pageIsCached(nextPage) and resObj.loadPageFunc:
			tk.Button(frame, text='Load next page', command=lambda np=nextPage: gui.root.after_idle(lambda np=np: resObj.loadPage(np))).pack(pady=10)
		if canSkipPages:
			for n in [10, 100, 1000, 10000]:
				if nextPage + n - 1 < resObj.pagesTotal:
					tk.Button(frame, text='Fwd ' + str(n) + ' pages', command=lambda n=n, np=nextPage: gui.root.after_idle(lambda n=n, np=np: resObj.loadPage(np+n-1))).pack(pady=10)

	def devartTabTitleFunc(self, config, gui, nextIndex, prefix = 'Result page '):
		print('devartTabTitleFunc', nextIndex)
		return prefix + str(Gui.calculatePageNumber(nextIndex))
	
	def onDevartQuery(self, config, gui, next_offset=0, results={}, seed='', endpoint=''):
		self.updateConfig(config, gui)
		print('onDevartQuery', endpoint, seed, next_offset, len(results))
		config.devartQueryString = config.devartQueryString.strip()
		if not hasattr(gui, 'devartApi'):
			gui.devartApi = da = deviantartapi.Api(config.devartApiKey, config.devartApiSecret)
		else:
			da = gui.devartApi
		if not endpoint:
			endpoint = config.devartEndpoint
		if not results:
			results = Gui.Results(config, self, gui)
		res = {}
		copyFromOld = True if results else False
		if endpoint == 'morelikethis':
			resultPage = self.createAndSelectResultsPage(config, gui, 'deviantmore', results=results,
								titleFunc=lambda nextIndex: self.devartTabTitleFunc(config, gui, nextIndex, 'Similar image page '), copyFromOld=copyFromOld)
		else:
			resultPage = self.createAndSelectResultsPage(config, gui, 'deviantart', results=results,
								titleFunc=lambda nextIndex: self.devartTabTitleFunc(config, gui, nextIndex), copyFromOld=copyFromOld)
		try:
			res = da.browse(endpoint, tag=config.devartTag,
							limit=Gui.photoCountOnPage, offset=next_offset, seed=seed, q=config.devartQueryString,
							category_path=config.devartCategoryPath, mature_content=config.devartMatureContent)
		except AssertionError as err:
			print(str(err))
		if res:
			showed = 0
			index = results.nextIndex
			print('got', str(len(res['results'])), 'results')
			for result in res['results']:
				resultPhoto = self.ResultPhoto()
				resultPhoto.deviationid = result.deviationid
				resultPhoto.category_path = result.category_path
				if result.is_downloadable:
					bigPhoto = da.download_deviation(result.deviationid)
					resultPhoto.url = bigPhoto['src']
					resultPhoto.size = (bigPhoto['width'], bigPhoto['height'])

				if not resultPhoto.url:
					if result.content:
						resultPhoto.url = result.content['src']
						resultPhoto.size = (result.content['width'], result.content['height'])
					else:
						print('skip', str(result))
						continue
				resultPhoto.index = index
				index += 1
				resultPhoto.title = result.title
				resultPhoto.thumbnailUrl = result.thumbs[1]['src']   # TODO make robust
				resultPhoto.createTitleFunc = lambda parent, r=resultPhoto: self.createDevartLabel(config, gui, parent, r)
				results.addItem(resultPhoto)
				if showed < Gui.photoCountOnPage:  # we get more than Gui.photoCountOnPage when endpoint is 'dailydeviations'
					self.showOnePhoto(config, gui, resultPhoto, resultPage)
					showed += 1
			if res['has_more'] and 'next_offset' in res:
				print('next_offset', res['next_offset'])
				next_offset = res['next_offset']
				results.nextIndex = min(showed + results.nextIndex, next_offset)
				results.pagesTotal = Gui.calculatePageNumber(next_offset)
				resultPage.loadMoreFunc = lambda: gui.root.after_idle(lambda: self.onDevartQuery(config, gui, next_offset=next_offset, results=results, seed=seed, endpoint=endpoint))
				resultPage.loadMoreButtons = lambda resObj, parent, frame: self.defaultLoadMoreButtons(config, gui, resObj, frame, canSkipPages=False)
			else:
				results.loadMoreFunc = {}
				results.nextIndex = showed + results.nextIndex
				results.pagesTotal = Gui.calculatePageNumber(index - 1)
		self.createResultPageButtons(config, gui, results, resultPage)
		
	def createDevartPage(self, config, gui):
		dpage = gui.devartPage
		tkVars = gui.tkVars
		for col in range(3):
			dpage.grid_columnconfigure(col, weight=1, pad=10)

		tk.Label(dpage, text='API id (mandatory)').grid(sticky=tkinter.W)
		tk.Entry(dpage, textvariable=tkVars['devartApiKey']).grid(row=1, sticky=tkinter.W+tkinter.E, padx=3)
		tk.Label(dpage, text='API secret (mandatory)').grid(row=0, column=1, sticky=tkinter.W)
		tk.Entry(dpage, textvariable=tkVars['devartApiSecret']).grid(row=1, column=1, sticky=tkinter.W+tkinter.E, padx=3)

		tk.Label(dpage, text='Endpoint:').grid(row=2, column=0, sticky=tkinter.W, padx=10)
		for row, (text, value) in enumerate([('Daily deviations', 'dailydeviations'),
											 ('Hot', 'hot'),
											# TODO: add entry for the seed?
											# ('More like this (TODO seed)', 'morelikethis'),
											 ('Newest', 'newest'),
											 ('Undiscovered', 'undiscovered'),
											 ('Popular', 'popular'),
											 ('Tags', 'tags')], 3):
			tk.Radiobutton(dpage, text=text, variable=tkVars['devartEndpoint'], value=value).grid(row=row, column=0, padx=20, sticky=tkinter.W)

		# TODO: add 'q'
		tk.Label(dpage, text='Tag (tags endpoint only)').grid(row=3, column=1, sticky=tkinter.W, padx=10)
		tk.Entry(dpage, textvariable=tkVars['devartTag']).grid(row=4, column=1, sticky=tkinter.W+tkinter.E, padx=10)

		tk.Label(dpage, text='Category path (others but tags endpoint)').grid(row=3, column=2, sticky=tkinter.W, padx=10)
		tk.Entry(dpage, textvariable=tkVars['devartCategoryPath']).grid(row=4, column=2, sticky=tkinter.W+tkinter.E, padx=10)

		tk.Label(dpage, text='Query string (newest & popular endpoints)').grid(row=5, column=1, sticky=tkinter.W, padx=10)
		tk.Entry(dpage, textvariable=tkVars['devartQueryString']).grid(row=6, column=1, sticky=tkinter.W+tkinter.E, padx=10)

		tk.Checkbutton(dpage, text='Mature content', variable=tkVars['devartMatureContent'], onvalue='true', offvalue='false').grid(row=6, column=2, sticky=tkinter.W, padx=10)

		tk.Button(dpage, text='Show matches',
			command=lambda: gui.root.after_idle(lambda: self.onDevartQuery(config, gui))).grid(row=20, padx=10, pady=10, sticky=tkinter.W)
		#tk.Button(dpage, text='Authorize app', command=lambda: self.devartAuthorization(config, gui)).grid(row=6, column=1, padx=10, pady=10, sticky=tkinter.W)

	def removeRecentPhoto(self, config, gui, parent, res):
		# FIXME: should not go to beginning of recents list
		if res in config.recentPhotos:
			config.recentPhotos.remove(res)
		self.onShowRecentImages(config, gui)
		
	def createRecentPhotoLabel(self, config, gui, parent, res):
		frame = tk.Frame(parent)
		l = tk.Label(frame, text=Gui.makeTclSafeString(res.title), wraplength=250)
		l.pack()
		tk.Button(frame, text='Remove this',
				command=lambda: gui.root.after_idle(lambda: self.removeRecentPhoto(config, gui, parent, res))).pack()
		tk.Button(frame, text='Similar images on Google',
			command=lambda: gui.root.after_idle(lambda: self.googleQuery(config, gui, similar_images=res.url))).pack()
		return frame
		
	def onShowRecentImages(self, config, gui):
		self.updateConfig(config, gui)
		if hasattr(config, 'recentPhotos') and config.recentPhotos:
			resultPage = self.createAndSelectResultsPage(config, gui, 'recents', title=str(len(config.recentPhotos)) + ' recent images')
			#for photo in config.recentPhotos:
			#	photo.createTitleFunc = lambda parent, photo=photo: self.createRecentPhotoLabel(config, gui, parent, photo)
			self.loadNextPage(config, gui, config.recentPhotos, resultPage)
		else:
			print('No recent images')
			
	def onTabChangeEvent(self, event, config, gui):
		index = event.widget.index('current')
		#print('onTabChangeEvent', index)
		if index == 0 and not gui.flickrPage.grid_slaves():
			self.createFlickrPage(config, gui)
		elif index == 1 and not gui.devartPage.grid_slaves():
			self.createDevartPage(config, gui)
		elif index == 2 and not gui.instaPage.grid_slaves():
			self.createInstaPage(config, gui)
		elif index == 3 and not gui.googlePage.grid_slaves():
			self.createGooglePage(config, gui)
		elif index == 4 and not gui.pinterestPage.grid_slaves():
			self.createPinterestPage(config, gui)
		# empty other pages
		for i, page in enumerate([gui.flickrPage, gui.devartPage, gui.instaPage, gui.googlePage, gui.pinterestPage]):
			if index != i:
				for widget in page.grid_slaves():
					widget.destroy()
		if index != 0: # FIXME should be more elegant way, e.g. use flickrPage specific object to store these
			gui.groups = gui.minDateEntry = gui.maxDateEntry = {}
	
	def ensureConfig(self, config):
		gui = self.GuiInfo()
		self.root = gui.root = root = tkinter.Tk()
		#root.tk.call('encoding', 'system', 'utf-8')
		config.screenWidth = root.winfo_screenwidth()
		config.screenHeight = root.winfo_screenheight()
		config.screenAspect = config.screenWidth / config.screenHeight

		tk.Style().configure('TLabel', padding=3) #, font=('Arial', 10))
		tk.Style().configure('TLabelFrame', padding=10)
		
		# take values from the cfg file unless they were provided in the command line
		configFile = readConfig(config.configFileName)
		if configFile:
			config.strVars = configFile.strVars
			config.listVars = configFile.listVars
			for var in config.strVars + config.listVars:
				if not hasattr(config, var):
					setattr(config, var, getattr(configFile, var))
			if not hasattr(config, 'groups'):
				config.groups = configFile.groups
			# convert list of recent photos to Gui.Results
			results = Gui.Results(config, self, gui)
			for item in configFile.recentPhotos:
				item.createTitleFunc = lambda parent, r=item: self.createRecentPhotoLabel(config, gui, parent, r)
				results.addItem(item)
			config.recentPhotos = results

		if config.showConfig or not config.isValid():
			root.title('Configuration (' + config.configFileName + ')')
			for col in range(3):
				root.grid_columnconfigure(col, pad=10, weight=1)
			for row in range(12):
				root.grid_rowconfigure(row, pad=(10 if row < 4 else 1))
			
			gui.notebook = Gui.CustomNotebook(root) #tk.Notebook(root)
			gui.flickrPage = tk.Frame(gui.notebook)
			gui.devartPage = tk.Frame(gui.notebook)
			gui.instaPage = tk.Frame(gui.notebook)
			gui.googlePage = tk.Frame(gui.notebook)
			gui.pinterestPage = tk.Frame(gui.notebook)
			gui.notebook.add(gui.flickrPage, text='Flickr')
			gui.notebook.add(gui.devartPage, text='DeviantArt')
			gui.notebook.add(gui.instaPage, text='Instagram')
			gui.notebook.add(gui.googlePage, text='Google images')
			gui.notebook.add(gui.pinterestPage, text='Pinterest')
			gui.notebook.grid(row=0, column=0, sticky=tkinter.E+tkinter.W, columnspan=3, padx=10)

			gui.tkVars = tkVars = {'resizePhoto': tkinter.IntVar(),
									'rotateByExif': tkinter.IntVar(),
									'flickrApiKey': tkinter.StringVar(),
									'flickrApiSecret': tkinter.StringVar(),
									'globalTags': tkinter.StringVar(),
									'globalTagMode': tkinter.StringVar(),
									'freeText': tkinter.StringVar(),
									'userId': tkinter.StringVar(),
									'resizeAlgo': tkinter.StringVar(),
									'largestSizeToRequest': tkinter.StringVar(),
									'instagramLogin': tkinter.StringVar(),
									'instagramTag': tkinter.StringVar(),
									'googleKeywords': tkinter.StringVar(),
									'googleImageSize': tkinter.StringVar(),
									'googleImageFormat': tkinter.StringVar(),
									'wallpaperMode': tkinter.IntVar(),
									'devartApiKey': tkinter.StringVar(),
									'devartApiSecret': tkinter.StringVar(),
									'devartTag': tkinter.StringVar(),
									'devartEndpoint': tkinter.StringVar(),
									'devartCategoryPath': tkinter.StringVar(),
									'devartMatureContent': tkinter.StringVar(),
									'devartQueryString': tkinter.StringVar(),
									'googleImageLicense': tkinter.StringVar(),
									'googleImageColor': tkinter.StringVar(),
									'googleImageColorType': tkinter.StringVar(),
									'googleImageType': tkinter.StringVar(),
									'pinterestUsername': tkinter.StringVar(),
									'pinterestQuery': tkinter.StringVar()}
			for key in tkVars.keys():
				obj = tkVars[key]
				conf = getattr(config, key)
				if isinstance(obj, tkinter.IntVar):
					obj.set(int(conf if conf else 0))
				else:
					if isinstance(conf, list):
						obj.set(' '.join(conf))
					else:
						obj.set(str(conf))

			self.createFlickrPage(config, gui)
			#self.createDevartPage(config, gui)
			#self.createInstaPage(config, gui)
			#self.createGooglePage(config, gui)
			# create other tabs on-demand to avoid CPU usage bug
			gui.notebook.bind("<<NotebookTabChanged>>", lambda event: self.onTabChangeEvent(event, config, gui))
			
			#tk.Button(root, text='Save & set wallpaper', command=lambda: self.onSaveButton(config, gui)).grid(row=10, column=0, padx=10)
			tk.Button(root, text='Save settings and quit', command=lambda: self.onSaveButton(config, gui, justQuit=True)).grid(row=10, column=0, padx=10)
			tk.Button(root, text='Cancel', command=lambda: self.onCancelButton(gui)).grid(row=10, column=2, padx=10)
			root.grid_rowconfigure(10, pad=30)
			
			menubar = tkinter.Menu(root)
			#filemenu = tkinter.Menu(menubar, tearoff=0)
			#filemenu.add_command(label='About', command=lambda: self.onAboutMenu(config, gui))
			menubar.add_command(label='About', command=lambda: self.onAboutMenu(config, gui))
			#filemenu.add_command(label='Quit', command=lambda: self.onWindowClose(config, gui))
			#menubar.add_command(label='Quit', command=lambda: self.onWindowClose(config, gui))
			#menubar.add_cascade(label="File", menu=filemenu)
			menubar.add_command(label='Recent images', command=lambda: self.onShowRecentImages(config, gui))
			root.protocol("WM_DELETE_WINDOW", lambda: self.onWindowClose(config, gui))
			root.config(menu=menubar)

			#glwindow = GlFrame(width=1024, height=768) #, master=root)
			#glwindow.grid(columnspan=3, rowspan=3)
			#glwidget.mainloop()

			root.mainloop()
		return config

# Modified Tim Martin's code from http://code.activestate.com/recipes/435877-change-the-wallpaper-under-windows/
def setWallpaperMode(config):
	desktopKey = winreg.OpenKey(winreg.HKEY_CURRENT_USER, 'Control Panel\\Desktop', 0, winreg.KEY_SET_VALUE)
	'''
	WallpaperStyle:
	0 - Center
	1 - Tile
	2 - Stretch
	3 - Fit
	4 - Fill
	'''
	winreg.SetValueEx(desktopKey, 'WallpaperStyle', 0, winreg.REG_SZ, str(config.wallpaperMode))
	winreg.SetValueEx(desktopKey, 'TileWallpaper', 0, winreg.REG_SZ, '0')
	
def setWallpaper(config, image, file, mime, flickrPhoto={}):
	if config.verbose:
		print(file, mime)
	origFile = ''
	newFile = os.path.join(os.getcwd(), 'flickrwallpaper.png')  # save as PNG to avoid additional compression artifacts
	#for type in ['png', 'jpeg', 'gif', 'bmp', 'ico', 'webp']:
	#	if str(mime).find('image/' + type) >= 0:
	image.format = image.format.lower()
	if image.format == 'jpeg':
		image.format = 'jpg'
	origFile = os.path.join(os.getcwd(), 'flickrwallpaper_orig.' + image.format)
	if not origFile:
		print('Unknown MIME type: ' + str(mime))
		return
	image.save(origFile)

	if config.resizePhoto:
		image = resizeToScreen(config, flickrPhoto, image)
	elif config.verbose:
		print('Keep size', image.size)
	if config.verbose:
		print('Saving photo', photoAsStr(flickrPhoto) if flickrPhoto else '', 'to', newFile)
	image.save(newFile)
	try:
		os.remove(origFile)  # remove previous original file
	except FileNotFoundError:
		pass
	if file:
		try:
			os.rename(file, origFile)
		except PermissionError as err:
			print('setWallpaper() error:', str(err))
		except FileNotFoundError as err:
			print('setWallpaper() error:', str(err))
	if flickrPhoto:
		addToRecents(config, flickrPhoto.id)
	saveConfig(config)
	setWallpaperMode(config)
	ctypes.windll.user32.SystemParametersInfoW(20, 0, newFile, 3)

def main(config):
	gui = Gui()
	config = gui.ensureConfig(config)
	flickr.API_KEY = config.flickrApiKey
	flickr.API_SECRET = config.flickrApiSecret
	image = {}
	flickrPhoto = {}
	file = ''
	if hasattr(config, 'photoUrlToUse'):
		image, file, mime = load_photo(config.photoUrlToUse)
		# FIXME: flickrPhoto missing
		#photoTuple = (config.photoUrlToUse, image)
	else:
		if gui.cancelPressed:
			if config.verbose:
				print('Canceled')
			return
		elif gui.saveAndQuitPressed:
			if config.verbose:
				print('Done')
			return

		# TODO: make the random image code generic and put it into a separate function
		group = ''
		user = config.userId  # user id for photos_search
		tags = []
		freeText = ''
		random.seed()
		if len(config.groups) > 0:
			# choose a random Flickr group
			random.shuffle(config.groups)
			group = config.groups[0]['gid']
			tags = [config.groups[0]['tag']]
			user = config.groups[0]['user']
		else:
			if hasattr(config, 'globalTags'):
				tags = config.globalTags
			if hasattr(config, 'freeText'):
				freeText = config.freeText

		# first get the number of pages there are (page size is as small as possible to make requests faster)
		ret = getPhotoURLs(config, groupId=group, user_id=user, tags=tags, tag_mode=config.globalTagMode,
							text=freeText, per_page=20, page=1, pagesTotalOnly=True)

		if int(ret['photosTotal']) == 0 or int(ret['pagesTotal']) == 0:
			sys.exit('No photos found.')
		elif config.verbose:
			print('pagesTotal:', ret['pagesTotal'], 'photosTotal:', ret['photosTotal'])

		# Choose a random page, and a random image on it
		# FIXME: let the user decide
		while True:
			# Sometimes the received page does not have photos at all, so try different pages until success or max. tries.
			# Another problem is that sometimes Flickr sends the same photos even though we ask for different result page
			# (at least with photos_search), hence we request bigger pages for bigger probability for getting a new photo.
			tries = 1
			while not ret['urls'] and tries <= 10:
				print('try', tries)
				random.seed()
				pageNum = random.randint(1, int(ret['pagesTotal']))
				ret = getPhotoURLs(config, groupId=group, user_id=user, tags=tags, tag_mode=config.globalTagMode,
									text=freeText, per_page=20, page=pageNum, getOnlyOne=True, recycleGroup=ret['flickrGroup'])
				tries = tries + 1
			if ret['urls']:
				if config.verbose:
					print('pagesTotal:', ret['pagesTotal'], 'photosTotal:', ret['photosTotal'], 'len(urls):', str(len(ret['urls'])))
				flickrPhoto = ret['flickrPhotos'][0]
				if int(ret['photosTotal']) > 1000 and flickrPhoto.id in config.recentPhotoIds:
					print(flickrPhoto.id, 'found from recents, retrying...')
					continue
				image, file, mime = load_photo(ret['urls'][0]['url'])
				break

	if image and flickrPhoto and file and mime:
		setWallpaper(config, image, file, mime, flickrPhoto=flickrPhoto)
	else:
		sys.exit('No photos found.')

'''
def getOAuthToken():
	url = "http://www.flickr.com/services/oauth/request_token"

	# Set the base oauth_* parameters along with any other parameters required
	# for the API call.
	params = {
		'oauth_timestamp': str(int(time.time())),
		'oauth_signature_method':"HMAC-SHA1",
		'oauth_version': "1.0",
		'oauth_callback': "http://www.mkelsey.com",
		'oauth_nonce': oauth.generate_nonce(),
		'oauth_consumer_key': flickr.API_KEY
	}

	# Setup the Consumer with the api_keys given by the provider
	consumer = oauth.Consumer(key=flickr.API_KEY, secret=flickr.API_SECRET)

	# Create our request. Change method, etc. accordingly.
	req = oauth.Request(method="GET", url=url, parameters=params)

	# Create the signature
	signature = oauth.SignatureMethod_HMAC_SHA1().sign(req, consumer, None)

	# Add the Signature to the request
	req['oauth_signature'] = signature

	# Make the request to get the oauth_token and the oauth_token_secret
	# I had to directly use the httplib2 here, instead of the oauth library.
	h = httplib2.Http(".cache")
	resp, content = h.request(req.to_url(), "GET")
	#print('content:', str(content))
	return (resp, content)

def getOAuthVerifierAndTokenObject(content):
	authorize_url = "http://www.flickr.com/services/oauth/authorize"

	content = str(content)
	#parse the content
	request_token = dict(urllib.parse.parse_qsl(content))

	#token_i = str.find(content, 'oauth_token')
	#if token_i == -1:
	#	print('oauth_token not found')
	#	return
	#end_i = str.find(content, r'&', token_i + 1)
	#if end_i == -1:
	#	print('end "&" not found')
	#	return
	#token = content[token_i + 12 : end_i]

	print("Request Token:")
	print("    - oauth_token        = %s" % request_token['oauth_token'])
	print("    - oauth_token_secret = %s" % request_token['oauth_token_secret'])
	print()

	# Create the token object with returned oauth_token and oauth_token_secret
	token = oauth.Token(request_token['oauth_token'], request_token['oauth_token_secret'])

	# You need to authorize this app via your browser.
	print("Go to the following link in your browser:")
	print("%s?oauth_token=%s&perms=read" % (authorize_url, request_token['oauth_token']))
	print()

	# Once you get the verified pin, input it
	accepted = 'n'
	while accepted.lower() == 'n':
		accepted = input('Have you authorized me? (y/n) ')
	oauth_verifier = input('What is the PIN? ')

	#set the oauth_verifier token
	token.set_verifier(oauth_verifier)
	return oauth_verifier, request_token, token

def getOAuthAccessToken(oauth_verifier, oauth_token, token):
	# url to get access token
	access_token_url = "http://www.flickr.com/services/oauth/access_token"

	# Now you need to exchange your Request Token for an Access Token
	# Set the base oauth_* parameters along with any other parameters required
	# for the API call.
	access_token_parms = {
		'oauth_consumer_key': flickr.API_KEY,
		'oauth_nonce': oauth.generate_nonce(),
		'oauth_signature_method':"HMAC-SHA1",
		'oauth_timestamp': str(int(time.time())),
		'oauth_token': oauth_token,
		'oauth_verifier' : oauth_verifier
	}
	consumer = oauth.Consumer(key=flickr.API_KEY, secret=flickr.API_SECRET)

	#setup request
	req = oauth.Request(method="GET", url=access_token_url, parameters=access_token_parms)

	#create the signature
	signature = oauth.SignatureMethod_HMAC_SHA1().sign(req, consumer, token)

	# assign the signature to the request
	req['oauth_signature'] = signature

	#make the request
	h = httplib2.Http(".cache")
	resp, content = h.request(req.to_url(), "GET")

	#parse the response
	access_token_resp = dict(urlparse.parse_qsl(content))

	#write out a file with the oauth_token and oauth_token_secret
	with open('token', 'w') as f:
		f.write(access_token_resp['oauth_token'] + '\n')
		f.write(access_token_resp['oauth_token_secret'])
	f.closed
'''

'''
class Controller(object):
	def __init__(self):
		pass

	def onResize(self, w, h):
		glViewport(0, 0, w, h)

	def onLeftDown(self, x, y):
		print('onLeftDown', x, y)

	def onLeftUp(self, x, y):
		print('onLeftUp', x, y)

	def onMiddleDown(self, x, y):
		print('onMiddleDown', x, y)

	def onMiddleUp(self, x, y):
		print('onMiddleUp', x, y)

	def onRightDown(self, x, y):
		print('onRightDown', x, y)

	def onRightUp(self, x, y):
		print('onRightUp', x, y)

	def onMotion(self, x, y):
		print('onMotion', x, y)

	def onWheel(self, d):
		print('onWheel', d)

	def onKeyDown(self, keycode):
		print('onKeyDown', keycode)

	def onUpdate(self, d):
		print('onUpdate', d)

	def draw(self):
		glClearColor(0.9, 0.5, 0.0, 0.0)
		glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)

		glBegin(GL_TRIANGLES)
		glVertex(-1.0,-1.0)
		glVertex( 1.0,-1.0)
		glVertex( 0.0, 1.0)
		glEnd()

		glFlush()

class GlFrame(tk.Frame):
	def __init__(self, width, height, master=None, **kw):
		#super(Frame, self).__init__(master, **kw)
		tk.Frame.__init__(self, master, **kw)
		# setup opengl widget
		self.controller = Controller()
		self.glwidget = togl.Widget(self, self.controller, width=width, height=height)
		self.glwidget.pack(fill=tkinter.BOTH, expand=True)
		# event binding(require focus)
		self.bind('<Key>', self.onKeyDown)
		self.bind('<MouseWheel>', lambda e: self.controller.onWheel(-e.delta) and self.glwidget.onDraw())
	def onKeyDown(self, event):
		key=event.keycode
		if key==27:
			# Escape
			sys.exit()
		if key==81:
			# q
			sys.exit()
		else:
			print("keycode: %d" % key)
'''

if __name__ == '__main__':
	print('Python encoding:', sys.stdin.encoding, sys.stdout.encoding)
	config = Config()
	argparser = argparse.ArgumentParser(description='''Set a random photo from Flickr as the Windows wallpaper.
					The photo is resized (while keeping the aspect ratio) to the screen size by default.''',
					epilog='The configuration file is ' + config.configFileName + '.')
	argparser.add_argument('--config', '-c', help='show the configuration window', action='store_const', const=1)
	argparser.add_argument('--groups', nargs='+', help='space-separated Flickr group ids', metavar='ID')
	argparser.add_argument('--noresize', help='do not resize the photo to the screen size', action='store_const', const=1)
	argparser.add_argument('--size', nargs=1, help='preferred photo size, if not available, smaller sizes are tried in decreasing order',
							choices=['Original', 'Large', 'Medium', 'Small', 'Thumbnail'])
	argparser.add_argument('--tags', nargs='+', help='space-separated tags to match', metavar='TAG')
	argparser.add_argument('--url', nargs=1, help='use the provided photo URL (for testing)', metavar='URL')
	argparser.add_argument('--quiet', '-q', help='do not print messages', action='store_const', const=1)
	ns = argparser.parse_args()
	if ns.config:
		config.showConfig = True
	if ns.tags:
		config.globalTags = ns.tags[0]
	if ns.groups:
		config.groups = ns.groups
	if ns.noresize:
		config.resizePhoto = False
	if ns.size:
		config.size = ns.size[0]
	if ns.quiet:
		config.verbose = False
	if ns.url:
		config.photoUrlToUse = ns.url[0]
	main(config)
