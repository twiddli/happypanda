﻿"""
This file is part of Happypanda.
Happypanda is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 2 of the License, or
any later version.
Happypanda is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.
You should have received a copy of the GNU General Public License
along with Happypanda.  If not, see <http://www.gnu.org/licenses/>.
"""

import os, time
import re as regex
import logging, uuid, random , queue

from .gallerydb import Gallery, GalleryDB
from ..gui import gui_constants
from .. import pewnet, settings, utils

from PyQt5.QtCore import QObject, pyqtSignal # need this for interaction with main thread

"""This file contains functions to fetch gallery data"""

log = logging.getLogger(__name__)
log_i = log.info
log_d = log.debug
log_w = log.warning
log_e = log.error
log_c = log.critical

class Fetch(QObject):
	"""A class containing methods to fetch gallery data.
	Should be executed in a new thread.
	Contains following methods:
	local -> runs a local search in the given series_path
	auto_web_metadata -> does a search online for the given galleries and returns their metdata
	"""

	# local signals
	FINISHED = pyqtSignal(object)
	DATA_COUNT = pyqtSignal(int)
	PROGRESS = pyqtSignal(int)

	# WEB signals
	GALLERY_EMITTER = pyqtSignal(Gallery)
	AUTO_METADATA_PROGRESS = pyqtSignal(str)
	GALLERY_PICKER = pyqtSignal(object, list, queue.Queue)
	GALLERY_PICKER_QUEUE = queue.Queue()

	def __init__(self, parent=None):
		super().__init__(parent)
		self.series_path = ""
		self.data = []
		self._curr_gallery = '' # for debugging purposes
		self._error = 'Unknown error' # for debugging purposes

		# web
		self._use_ehen_api = gui_constants.FETCH_EHEN_API
		self._default_ehen_url = gui_constants.DEFAULT_EHEN_URL
		self.galleries = []
		self.galleries_in_queue = []
		self.error_galleries = []

	def local(self):
		"""
		Do a local search in the given series_path.
		"""
		try:
			gallery_l = sorted(os.listdir(self.series_path)) #list of folders in the "Gallery" folder
			mixed = False
		except TypeError:
			gallery_l = self.series_path
			mixed = True
		if len(gallery_l) != 0: # if gallery path list is not empty
			log_i('Gallery folder is not empty')
			try:
				self.DATA_COUNT.emit(len(gallery_l)) #tell model how many items are going to be added
				log_i('Found {} items'.format(len(gallery_l)))
				progress = 0
				for ser_path in gallery_l: # ser_path = gallery folder title
					self._curr_gallery = ser_path
					if mixed:
						path = ser_path
						ser_path = os.path.split(path)[1]
					else:
						path = os.path.join(self.series_path, ser_path)
					if not GalleryDB.check_exists(ser_path):
						log_i('Creating gallery: {}'.format(ser_path.encode('utf-8', 'ignore')))
						new_gallery = Gallery()
						images_paths = []
						try:
							con = os.listdir(path) #all of content in the gallery folder
		
							chapters = sorted([os.path.join(path,sub) for sub in con if os.path.isdir(os.path.join(path, sub))]) #subfolders
							# if gallery has chapters divided into sub folders
							if len(chapters) != 0:
								for numb, ch in enumerate(chapters):
									chap_path = os.path.join(path, ch)
									new_gallery.chapters[numb] = chap_path

							else: #else assume that all images are in gallery folder
								new_gallery.chapters[0] = path
				
							#find last edited file
							times = set()
							for root, dirs, files in os.walk(path, topdown=False):
								for img in files:
									fp = os.path.join(root, img)
									times.add( os.path.getmtime(fp) )
							last_updated = time.asctime(time.gmtime(max(times)))
							new_gallery.last_update = last_updated
							parsed = utils.title_parser(ser_path)
						except NotADirectoryError:
							if ser_path[-4:] in utils.ARCHIVE_FILES:
								#TODO: add support for folders in archive
								new_gallery.chapters[0] = path
								parsed = utils.title_parser(ser_path[:-4])
							else:
								log_w('Skipped {} in local search'.format(path))
								progress += 1 # update the progress bar
								self.PROGRESS.emit(progress)
								continue

						new_gallery.title = parsed['title']
						new_gallery.path = path
						new_gallery.artist = parsed['artist']
						new_gallery.language = parsed['language']
						new_gallery.info = "<i>No description..</i>"
						new_gallery.chapters_size = len(new_gallery.chapters)

						self.data.append(new_gallery)
						log_i('Gallery successful created: {}'.format(ser_path.encode('utf-8', 'ignore')))
					else:
						log_i('Gallery already exists: {}'.format(ser_path.encode('utf-8', 'ignore')))

					progress += 1 # update the progress bar
					self.PROGRESS.emit(progress)
			except:
				log.exception('Local Search Error:')
				self.FINISHED.emit(False)
		else: # if gallery folder is empty
			log_e('Local search error: Invalid directory')
			log_e('Gallery folder is empty')
			self.FINISHED.emit(False)
			# might want to include an error message
		# everything went well
		log_i('Local search: OK')
		log_i('Created {} items'.format(len(self.data)))
		self.FINISHED.emit(self.data)

	def _return_gallery_metadata(self, gallery):
		"Emits galleries"
		assert isinstance(gallery, Gallery)
		if gallery:
			gallery.exed = 1
			if not gallery.link:
				gallery.link = gallery.temp_url
			self.GALLERY_EMITTER.emit(gallery)
			log_d('Success')

	def fetch_metadata(self, gallery, hen, proc=False):
		"""
		Puts gallery in queue for metadata fetching. Applies received galleries and sends
		them to gallery model.
		Set proc to true if you want to process the queue immediately
		"""
		log_i("Fetching metadata for gallery: {}".format(gallery.title.encode(errors='ignore')))
		if not self._use_ehen_api:
			metadata = hen.eh_gallery_parser(gallery.temp_url)
			if not metadata:
				self.AUTO_METADATA_PROGRESS('No metadata found for gallery: {}'.format(gallery.title))
				log_w('No metadata found for gallery: {}'.format(gallery.title.encode(errors='ignore')))
				return False
			self.AUTO_METADATA_PROGRESS.emit("Applying metadata..")
			log_i('Applying metadata')
			title_artist_dict = utils.title_parser(metadata['title'])
			if gui_constants.REPLACE_METADATA:
				gallery.title = title_artist_dict['title']
				if title_artist_dict['artist']:
					gallery.artist = title_artist_dict['artist']
				gallery.type = metadata['type']
				gallery.language = metadata['language']
				gallery.pub_date = metadata['published']
				gallery.tags = metadata['tags']
			else:
				if not gallery.title:
					gallery.title = title_artist_dict['title']
				if not gallery.artist:
					gallery.artist = title_artist_dict['artist']
				if not gallery.type:
					gallery.type = metadata['type']
				if not gallery.language:
					gallery.language = metadata['language']
				if not gallery.pub_date:
					gallery.pub_date = metadata['published']
				if not gallery.tags:
					gallery.tags = metadata['tags']
				else:
					for ns in metadata['tags']:
						if ns in gallery.tags:
							for tag in metadata['tags'][ns]:
								if not tag in gallery.tags[ns]:
									gallery.tags[ns].append(tag)
						else:
							gallery.tags[ns] = metadata['tags'][ns]
		else:
			raise NotImplementedError
		return gallery

	def auto_web_metadata(self):
		"""
		Auto fetches metadata for the provided list of galleries.
		Appends or replaces metadata with the new fetched metadata.
		"""
		log_i('Initiating auto metadata fetcher')
		if self.galleries and not gui_constants.GLOBAL_EHEN_LOCK:
			log_i('Auto metadata fetcher is now running')
			gui_constants.GLOBAL_EHEN_LOCK = True
			if 'exhentai' in self._default_ehen_url:
				try:
					exprops = settings.ExProperties()
					if exprops.ipb_id and exprops.ipb_pass:
						hen = pewnet.ExHen(exprops.ipb_id, exprops.ipb_pass)
						valid_url = 'exhen'
					else:
						raise ValueError
				except ValueError:
					hen = pewnet.EHen()
					valid_url = 'ehen'
			else:
				hen = pewnet.EHen()
				valid_url = 'ehen'
			hen.LAST_USED = time.time()
			checked_galleries = []
			self.AUTO_METADATA_PROGRESS.emit("Checking gallery urls...")

			error_galleries = []
			fetched_galleries = []
			checked_pre_url_galleries = []
			for x, gallery in enumerate(self.galleries):
				self.AUTO_METADATA_PROGRESS.emit("({}/{}) Generating gallery hash: {}".format(x+1, len(self.galleries), gallery.title))
				hash = None
				if gui_constants.HASH_GALLERY_PAGES == 'all':
					if not gallery.hashes:
						if not gallery.gen_hashes():
							continue
					hash = gallery.hashes[random.randint(0, len(gallery.hashes)-1)]
				elif gui_constants.HASH_GALLERY_PAGES == '1':
					try:
						chap_path = gallery.chapters[0]
						imgs = os.listdir(chap_path)
						# filter
						img = [os.path.join(chap_path, x) for x in imgs\
							if x.endswith(tuple(utils.IMG_FILES))][len(imgs)//2]
						with open(img, 'rb') as f:
							hash = utils.generate_img_hash(f)
					except NotADirectoryError:
						zip = ArchiveFile(gallery.chapters[0])
						img = [x for x in zip.namelist()\
							if x.endswith(tuple(utils.IMG_FILES))][len(zip.namelist())//2]
						hash = utils.generate_img_hash(zip.open(img, fp=True))
					except FileNotFoundError:
						self.AUTO_METADATA_PROGRESS
						continue
				if not hash:
					error_galleries.append(gallery)
					log_e("Could not generate hash for gallery: {}".format(gallery.title.encode(errors='ignore')))
					continue
				gallery.hash = hash

				log_i("Checking gallery url")
				if gallery.link:
					check = self.website_checker(gallery.link)
					if check == valid_url:
						gallery.temp_url = gallery.link
						checked_pre_url_galleries.append(gallery)
						continue

				# dict -> hash:[list of title,url tuples] or None
				self.AUTO_METADATA_PROGRESS.emit("({}/{}) Finding url for gallery: {}".format(x+1, len(checked_galleries), gallery.title))
				found_url = hen.eh_hash_search(gallery.hash)
				if not gallery.hash in found_url:
					error_galleries.append(gallery)
					self.AUTO_METADATA_PROGRESS.emit("Could not find url for gallery: {}".format(gallery.title))
					log_w('Could not find url for gallery: {}'.format(gallery.title.encode(errors='ignore')))
					continue
				title_url_list = found_url[gallery.hash]
				if gui_constants.ALWAYS_CHOOSE_FIRST_HIT:
					title = title_url_list[0][0]
					url = title_url_list[0][1]
				else:
					if len(title_url_list) > 1:
						self.AUTO_METADATA_PROGRESS.emit("Multiple galleries found for gallery: {}".format(gallery.title))
						log_e("Multiple galleries found for gallery: {}".format(gallery.title.encode(errors='ignore')))
						self.GALLERY_PICKER.emit(gallery, title_url_list, self.GALLERY_PICKER_QUEUE)
						user_choice = self.GALLERY_PICKER_QUEUE.get()
					else:
						user_choice = title_url_list[0]

					title = user_choice[0]
					url = user_choice[1]

				gallery.temp_url = url
				self.AUTO_METADATA_PROGRESS.emit("({}/{}) Adding to queue: {}".format(
					x+1, len(checked_galleries), gallery.title))
				g = self.fetch_metadata(gallery, hen)
				if not g:
					error_galleries.append(gallery)

			if checked_pre_url_galleries:
				for x, gallery in enumerate(checked_pre_url_galleries):
					self.AUTO_METADATA_PROGRESS.emit("({}/{}) Adding to queue: {}".format(
						x+1, len(checked_pre_url_galleries), gallery.title))
					g = self.fetch_metadata(gallery, hen)
					if not g:
						error_galleries.append(gallery)

			log_d('Auto metadata fetcher is done')
			gui_constants.GLOBAL_EHEN_LOCK = False
			if not error_galleries:
				self.AUTO_METADATA_PROGRESS.emit('Successfully added all galleries to queue!')
				self.FINISHED.emit(True)
			else:
				self.AUTO_METADATA_PROGRESS.emit('Could not add {} galleries to queue. Check happypanda.log for more details!'.format(len(error_galleries)))
				for e in error_galleries:
					log_e("An error occured with gallery: {}".e.title.encode(errors='ignore'))
				self.FINISHED.emit(False)
		else:
			log_e('Auto metadata fetcher is already running')
			self.AUTO_METADATA_PROGRESS.emit('Auto metadata fetcher is already running!')
			self.FINISHED.emit(False)

	def website_checker(self, url):
		if not url:
			return None
		try:
			r = regex.match('^(?=http)', url).group()
			del r
		except AttributeError:
			n_url = 'http://' + url

		if 'g.e-hentai.org' in url:
			return 'ehen'
		elif 'exhentai.org' in url:
			return 'exhen'
		else:
			log_e('Invalid URL')
			return None

