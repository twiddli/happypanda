#"""
#This file is part of Happypanda.
#Happypanda is free software: you can redistribute it and/or modify
#it under the terms of the GNU General Public License as published by
#the Free Software Foundation, either version 2 of the License, or
#any later version.
#Happypanda is distributed in the hope that it will be useful,
#but WITHOUT ANY WARRANTY; without even the implied warranty of
#MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#GNU General Public License for more details.
#You should have received a copy of the GNU General Public License
#along with Happypanda.  If not, see <http://www.gnu.org/licenses/>.
#"""

import html
import logging
import os
import random
import re as regex
import requests
import shutil
import threading
import time
import uuid
from datetime import datetime
from queue import Queue
from tempfile import (
    NamedTemporaryFile,
    mkstemp
)

from bs4 import BeautifulSoup
from robobrowser import RoboBrowser
from robobrowser.exceptions import RoboError

from PyQt5.QtCore import QObject, pyqtSignal

from happypanda import app_constants
from happypanda import utils
from happypanda import settings
from happypanda.utils import makedirs_if_not_exists

log = logging.getLogger(__name__)
log_i = log.info
log_d = log.debug
log_w = log.warning
log_e = log.error
log_c = log.critical

class DownloaderItem(QObject):
    "Convenience class"
    IN_QUEUE, DOWNLOADING, FINISHED, CANCELLED = range(4)
    file_rdy = pyqtSignal(object)
    def __init__(self, url="", session=None):
        super().__init__()
        self.session = session
        self.download_url = url
        self.file = ""
        self.name = ""

        self.total_size = 0
        self.current_size = 0
        self.current_state = self.IN_QUEUE

    def cancel(self):
        self.current_state = self.CANCELLED

    def open(self, containing=False):
        if self.file:
            if containing:
                p = os.path.split(self.file)[0]
                utils.open_path(p, self.file)
            else:
                utils.open_path(self.file)

class Downloader(QObject):
    """
    A download manager.
    Emits signal item_finished with tuple of url and path to file when a download finishes
    """
    _inc_queue = Queue()
    _browser_session = None
    _threads = []
    item_finished = pyqtSignal(object)
    active_items = []

    def __init__(self):
        super().__init__()
        # download dir
        self.base = os.path.abspath(app_constants.DOWNLOAD_DIRECTORY)
        if not os.path.exists(self.base):
            os.mkdir(self.base)

    @staticmethod
    def add_to_queue(item, session=None, dir=None):
        """
        Add a DownloaderItem or url
        An optional requests.Session object can be specified
        A temp dir to be used can be specified

        Returns a downloader item
        """
        if isinstance(item, str):
            item = DownloaderItem(item)

        log_i("Adding item to download queue: {}".format(item.download_url))
        if dir:
            Downloader._inc_queue.put({'dir':dir, 'item':item})
        else:
            Downloader._inc_queue.put(item)
        Downloader._session = session

        return item

    @staticmethod
    def remove_file(filename):
        """Remove file and ignore any error when doing it.

        Args:
            filename: filename to be removed.
        """
        try:
            os.remove(filename)
        except:
            pass

    @staticmethod
    def _get_total_size(response):
        """get total size from requests response.
        Args:
            response (requests.Response): Response from request.
        """
        try:
            return int(response.headers['content-length'])
        except KeyError:
            return 0

    def _get_response(self, url):
        """get response from url.
        Args:
            url : Url of the response
        Returns:
            requests.Response: Response from url
        """
        if self._browser_session:
            r = self._browser_session.get(url, stream=True)
        else:
            r = requests.get(url, stream=True)
        return r

    def _get_item_and_temp_base(self):
        """get item and temporary folder if specified.

        Returns:
            tuple: (item, temp_base), where temp_base is the temporary folder.
        """
        item = self._inc_queue.get()
        temp_base = None
        if isinstance(item, dict):
            temp_base = item['dir']
            item = item['item']
        return item, temp_base

    def _get_filename(self, item, temp_base=None):
        """get filename based on input.

        Args:
            item: Download item
            temp_base: Optional temporary folder

        Returns:
            str: Edited filename
        """
        file_name = item.name if item.name else str(uuid.uuid4())
        invalid_chars = '\\/:*?"<>|'
        for x in invalid_chars:
            file_name = file_name.replace(x, '')
        file_name = os.path.join(self.base, file_name) if not temp_base else \
            os.path.join(temp_base, file_name)
        return file_name

    @staticmethod
    def _download_with_simple_method(target_file, response, item, interrupt_state):
        """download single file with simple method.
        Args:
            target_file: Target filename where url will be downloaded.
            response (requests.Response): Response from url.
            item: Download item.
            interrupt_state (bool): Interrupt state.
        Returns:
            tuple: (item, interrupt_state) where both variables
                is the changed variables from input.
        """
        chunk_size = 1024
        with open(target_file, 'wb') as f:
            for data in response.iter_content(chunk_size=chunk_size):
                if item.current_state == item.CANCELLED:
                    interrupt_state = True
                    break
                if data:
                    item.current_size += len(data)
                    f.write(data)
                    f.flush()

        return item, interrupt_state

    @staticmethod
    def _download_with_catch_error(
            target_file, response, item, interrupt_state,
            use_tempfile=False, catch_errors=None
    ):
        """Download single file from url response and return changed item and interrupt state.

        Args:
            target_file: Target filename where url will be downloaded.
            response (requests.Response): Response from url.
            item: Download item.
            interrupt_state (bool): Interrupt state.
            use_tempfile (bool): Use tempfile when downloading or not.
            catch_errors (tuple): List of error that will be catched when downloading.

        Returns:
            tuple: (item, interrupt_state) where both variables
                is the changed variables from input.
        """
        if catch_errors is None:
            catch_errors = tuple()

        # compatibility
        DownloaderObject = Downloader

        download_finished = False
        while not download_finished:
            try:
                item, interrupt_state = DownloaderObject._download_single_file(
                    target_file=target_file,
                    response=response,
                    item=item,
                    interrupt_state=interrupt_state,
                    use_tempfile=use_tempfile
                )
                download_finished = True
            except catch_errors as err:
                log_d('Redownloading because following error.\n{}'.format(err))

        return item, interrupt_state

    @staticmethod
    def _download_with_tempfile_windows(
            target_file, response, item, interrupt_state
    ):
        """Download file with tempfile return changed item and interrupt state.

        method used on window taken and modified from http://stackoverflow.com/a/15259358

        Args:
            target_file: Target filename where url will be downloaded.
            response (requests.Response): Response from url.
            item: Download item.
            interrupt_state (bool): Interrupt state.
        Returns:
            tuple: (item, interrupt_state) where both variables
                is the changed variables from input.

        """
        # compatibilty
        DownloaderObject = Downloader
        closed_ = False
        deleted_ = False
        file_, tempfile = mkstemp()
        try:
            item, interrupt_state = DownloaderObject._download_single_file(
                    target_file=tempfile,
                    response=response,
                    item=item,
                    interrupt_state=interrupt_state,
                    use_tempfile=False
                )

            if item.current_state != item.CANCELLED:
                    os.close(file_)
                    closed_ = True
                    shutil.copyfile(tempfile, target_file)
                    os.remove(tempfile)
                    deleted_ = True
        finally:
            if not closed_:
                os.close(file_)
            if not deleted_:
                os.remove(tempfile)
        return item, interrupt_state



    @staticmethod
    def _download_single_file(
            target_file, response, item, interrupt_state,
            use_tempfile=False, catch_errors=None
    ):
        """Download single file from url response and return changed item and interrupt state.

        this method is wrapper for these methods::

        - _download_with_catch_error
        - _download_with_simple_method

        Note:
            item's current size may not give exact size.
            especially when there is multiple interupt and tempfile is used.

        Args:
            target_file: Target filename where url will be downloaded.
            response (requests.Response): Response from url.
            item: Download item.
            interrupt_state (bool): Interrupt state.
            use_tempfile (bool): Use tempfile when downloading or not.
            catch_errors (tuple): List of error that will be catched when downloading.

        Returns:
            tuple: (item, interrupt_state) where both variables
                is the changed variables from input.
        """
        # compatibilty
        DownloaderObject = Downloader

        if catch_errors:
            item, interrupt_state = DownloaderObject._download_with_catch_error(
                target_file=target_file,
                response=response,
                item=item,
                interrupt_state=interrupt_state,
                use_tempfile=use_tempfile,
                catch_errors=catch_errors

            )
        elif use_tempfile:
            if app_constants.OS_NAME == 'windows':
                item, interrupt_state = DownloaderObject._download_with_tempfile_windows(
                        target_file=target_file,
                        response=response,
                        item=item,
                        interrupt_state=interrupt_state,
                    )
            else: # unix
                with NamedTemporaryFile() as tempfile:
                    item, interrupt_state = DownloaderObject._download_single_file(
                        target_file=tempfile.name,
                        response=response,
                        item=item,
                        interrupt_state=interrupt_state,
                        use_tempfile=False
                    )
                    if item.current_state != item.CANCELLED:
                        shutil.copyfile(tempfile.name, target_file)
        else:
            item, interrupt_state = DownloaderObject._download_with_simple_method(
                target_file=target_file,
                response=response,
                item=item,
                interrupt_state=interrupt_state,
            )

        return item, interrupt_state

    @staticmethod
    def _rename_file(filename, filename_part, max_loop=100):
        """Custom rename file method.

        Args:
            filename: Target filename.
            filename_part: Temporary filename
            max_loop (int): Maximal loop  on error when renaming the file.

        Returns:
            str: Filename or filename_part
        """
        # compatibility
        file_name = filename
        file_name_part = filename_part

        n = 0
        file_split = os.path.split(file_name)
        while n < max_loop:
            try:
                if file_split[1]:
                    src_file = file_split[0]
                    target_file = "({}){}".format(n, file_split[1])
                else:
                    src_file = file_name_part
                    target_file = "({}){}".format(n, file_name)
                os.rename(src_file, target_file)
                break
            except:
                n += 1
        if n > max_loop:
            file_name = file_name_part
        return file_name

    @staticmethod
    def _get_total_size_prediction(known_filesize, urls_len):
        """get total size prediction.

        Args:
            known_filesize (list): List of known filesize.
            urls_len (int): Number of urls_len

        Returns:
            int: Total size predictions.
        """
        if not known_filesize:  # empty list
            return 0
        if len(known_filesize) == urls_len:
            return int(sum(known_filesize))
        return int(sum(known_filesize) * urls_len / len(known_filesize))

    @staticmethod
    def _get_local_filesize(path):
        """Get local filesize.

        Args:
            path: Path of the file.

        Returns:
            filesize of the file or zero.
        """
        try:
            return os.path.getsize(path)
        except OSError:
            return 0

    def _download_item_with_multiple_dl_url(self, item, folder, interrupt_state):
        """download item with multiple download url.

        This method is modified from _download_item_with_single_dl_url method.

        Important changes::
        - Create new folder for download.
        - Method to calculate total size
        - item.file is now folder name instead of filename

        Args:
            item: Item with single download url.
            folder (str): Folder for downloaded file.
            interrupt_state (bool): Interrupt state

        Returns:
            Modified item
        """
        download_url = item.download_url
        total_known_filesize = []
        download_url_len = len(download_url)

        makedirs_if_not_exists(folder)
        for single_url in download_url:
            # response
            r = self._get_response(url=single_url)

            # get total size
            current_response_filesize = self._get_total_size(response=r)
            total_known_filesize.append(current_response_filesize)
            item.total_size = self._get_total_size_prediction(
                known_filesize=total_known_filesize, urls_len=download_url_len)

            url_basename = os.path.basename(single_url)
            target_file = os.path.join(folder, url_basename)
            target_filesize = self._get_local_filesize(path=target_file)
            if target_filesize == current_response_filesize and target_filesize != 0:
                item.current_size += current_response_filesize
                log_d('File is already downloaded.\n{}'.format(target_file))
            else:
                # downloading to temp file (file_name_part)
                item, interrupt_state = self._download_single_file(
                    target_file=target_file, response=r, item=item,
                    interrupt_state=interrupt_state, use_tempfile=True,
                    catch_errors=(requests.ConnectionError,)
                    # NOTE:
                    # You can't catch when in list, only tuple
                    # This causes a TypeError:
                    #   try:
                    #     raise Exception
                    #   except [Exception] as err:
                    #     pass

                    # But this doesn't:
                    #   try:
                    #     raise Exception
                    #   except (Exception,) as err:
                    #     pass
                    
                )

        if not interrupt_state:
            item.current_state = item.FINISHED
            item.file = folder
            # emit
            item.file_rdy.emit(item)
            self.item_finished.emit(item)
        return item

    def _download_item_with_single_dl_url(self, item, filename, interrupt_state):
        """download item with single download url.
        Args:
            item: Item with single download url.
            filename (str): Filename for downloaded file.
            interrupt_state (bool): Interrupt state
        Returns:
            Modified item
        """
        # compatibility
        file_name = filename
        interrupt = interrupt_state
        download_url = item.download_url
        file_name_part = file_name + '.part'

        # response
        r = self._get_response(url=download_url)
        # get total size
        item.total_size = self._get_total_size(response=r)

        # downloading to temp file (file_name_part)
        item, interrupt = self._download_single_file(
            target_file=file_name_part, response=r, item=item, interrupt_state=interrupt)

        if not interrupt:
            # post operation when no interrupt
            try:
                os.rename(file_name_part, file_name)
            except OSError:
                file_name = self._rename_file(
                    filename=file_name, filename_part=file_name_part)

            item.file = file_name
            item.current_state = item.FINISHED
            # emit
            item.file_rdy.emit(item)
            self.item_finished.emit(item)
        else:
            self.remove_file(filename=file_name_part)
        return item

    def _downloading(self):
        "The downloader. Put in a thread."
        while True:
            log_d("Download items in queue: {}".format(self._inc_queue.qsize()))
            interrupt = False
            item, temp_base = self._get_item_and_temp_base()

            log_d("Stating item download")
            item.current_state = item.DOWNLOADING

            file_name = self._get_filename(item=item, temp_base=temp_base)

            download_url = item.download_url
            log_d("Download url:{}".format(download_url))

            self.active_items.append(item)

            if isinstance(item.download_url, list):
                # NOTE: file_name will be used as folder name when multiple url.
                item = self._download_item_with_multiple_dl_url(
                    item=item, folder=file_name, interrupt_state=interrupt)
            else:
                item = self._download_item_with_single_dl_url(
                    item=item, filename=file_name, interrupt_state=interrupt)

            log_d("Items in queue {}".format(self._inc_queue.empty()))
            log_d("Finished downloading: {}".format(download_url))
            self.active_items.remove(item)
            self._inc_queue.task_done()

    def start_manager(self, max_tasks):
        "Starts download manager where max simultaneous is mask_tasks"
        log_i("Starting download manager with {} jobs".format(max_tasks))
        for x in range(max_tasks):
            thread = threading.Thread(
                    target=self._downloading,
                    name='Downloader {}'.format(x),
                    daemon=True)
            thread.start()
            self._threads.append(thread)

class HenItem(DownloaderItem):
    "A convenience class that most methods in DLManager and its subclasses returns"
    thumb_rdy = pyqtSignal(object)
    def __init__(self, session=None):
        super().__init__(session=session)
        self.thumb_url = "" # an url to gallery thumb
        self.thumb = None
        self.cost = "0"
        self.size = ""
        self.metadata = {}
        self.gallery_name = ""
        self.gallery_url = ""
        self.download_type = app_constants.DOWNLOAD_TYPE_OTHER
        self.torrents_found = 0
        self.file_rdy.connect(self.check_type)

    def fetch_thumb(self):
        "Fetches thumbnail. Emits thumb_rdy, when done"
        def thumb_fetched():
            self.thumb = self._thumb_item.file
            self.thumb_rdy.emit(self)
        self._thumb_item = Downloader.add_to_queue(self.thumb_url, self.session, app_constants.temp_dir)
        self._thumb_item.file_rdy.connect(thumb_fetched)

    def check_type(self):
        if self.download_type == app_constants.DOWNLOAD_TYPE_TORRENT:
            utils.open_torrent(self.file)

    def update_metadata(self, key, value):
        """
        Recommended way of inserting metadata. Keeps the original EH API response structure
        Remember to call commit_metadata when done!
        """
        if not self.metadata:
            self.metadata = {
                    "gmetadata": [
                        {
                                "gid":1,
                                "title": "",
                                "title_jpn": "",
                                "category": "Manga",
                                "uploader": "",
                                "Posted": "",
                                "filecount": "0",
                                "filesize": 0,
                                "expunged": False,
                                "rating": "0",
                                "torrentcount": "0",
                                "tags":[]
                            }
                        ]
                }
        try:
            metadata = self.metadata['gmetadata'][0]
        except KeyError:
            return

        metadata[key] = value

    def commit_metadata(self):
        "Call this method when done updating metadata"
        g_id = 'sample'
        try:
            d_m = {self.metadata['gmetadata'][0]['gid']:g_id}
        except KeyError:
            return
        self.metadata = EHen.parse_metadata(self.metadata, d_m)[g_id]

class DLManager(QObject):
    "Base class for site-specific download managers"
    _browser = RoboBrowser(history=True,
                        user_agent="Mozilla/5.0 (Windows NT 6.3; rv:36.0) Gecko/20100101 Firefox/36.0",
                        parser='html.parser', allow_redirects=False)
    def __init__(self, download_type=app_constants.DOWNLOAD_TYPE_OTHER):
        super().__init__()
        self._download_type = download_type

    def _error(self):
        pass

    def from_gallery_url(self, url):
        """
        Needs to be implemented in site-specific subclass
        URL checking and class instantiating is done in GalleryDownloader class in io_misc.py
        Basic procedure for this method:
        - open url with self._browser and do the parsing
        - create HenItem and fill out its attributes
        - specify download type (important) from app_constants
        - fetch optional thumbnail on HenItem
        - set download url on HenItem (important)
        - add h_item to download queue
        - return h-item if everything went successfully, else return none

        Metadata should imitiate the offical EH API response.
        It is recommended to use update_metadata in HenItem when adding metadata
        see the ChaikaManager class for a complete example
        EH API: http://ehwiki.org/wiki/API
        """
        raise NotImplementedError

    def ensure_browser_on_url(self, url):
        """open browser on input url if not already.

        Args:
            url: Url where browser to open (or alreadery opened)
        """
        open_url = False  # assume not opening the url
        try:
            current_url = self._browser.url
            if current_url != url:
                open_url = True
        except RoboError:
            open_url = True
        if open_url:
            self._browser.open(url)

class ChaikaManager(DLManager):
    "panda.chaika.moe manager"

    def __init__(self):
        super().__init__()
        self.url = "http://panda.chaika.moe/"
        self.api = "http://panda.chaika.moe/jsearch/?"

    def from_gallery_url(self, url):
        h_item = HenItem(self._browser.session)
        h_item.download_type = self._download_type
        chaika_id = os.path.split(url)
        if chaika_id[1]:
            chaika_id = chaika_id[1]
        else:
            chaika_id = os.path.split(chaika_id[0])[1]

        if '/gallery/' in url:
            a_id = self._gallery_page(chaika_id, h_item)
            if not a_id:
                return
            self._archive_page(a_id, h_item)
        elif '/archive' in url:
            g_id = self._archive_page(chaika_id, h_item)
            if not g_id:
                return
            self._gallery_page(g_id, h_item)
        else:
            return
        h_item.commit_metadata()
        h_item.name = h_item.gallery_name+'.zip'
        Downloader.add_to_queue(h_item, self._browser.session)
        return h_item

    def _gallery_page(self, g_id, h_item):
        "Returns url to archive and updates h_item metadata from the /gallery/g_id page"
        g_url = self.api + "gallery={}".format(g_id)
        r = requests.get(g_url)
        try:
            r.raise_for_status()
            chaika = r.json()

            h_item.update_metadata('title', chaika['title'])
            h_item.update_metadata('title_jpn', chaika['title_jpn'])
            h_item.update_metadata('category', chaika['category'])
            h_item.update_metadata('rating', chaika['rating'])
            h_item.update_metadata('filecount', chaika['filecount'])
            h_item.update_metadata('filesize', chaika['filesize'])
            h_item.update_metadata('posted', chaika['posted'])

            h_item.gallery_name = chaika['title']
            h_item.gallery_url = self.url + "gallery/{}".format(g_id)
            h_item.size = "{0:.2f} MB".format(chaika['filesize']/1048576)
            tags = []
            for t in chaika['tags']:
                tag = t.replace('_', ' ')
                tags.append(tag)
            h_item.update_metadata('tags', tags)

            if chaika['archives']:
                h_item.download_url = self.url + chaika['archives'][0]['download'][1:]
                return chaika['archives'][0]['id']
        except AttributeError:
            log.exception("HTML parsing error")
            raise app_constants.HTMLParsing
        except requests.ConnectionError:
            log.exception("Connection Error")

    def _archive_page(self, a_id, h_item):
        "Returns url to gallery and updates h_item metadata from the /archive/a_id page"
        a_url = self.api + "archive={}".format(a_id)
        r = requests.get(a_url)
        try:
            r.raise_for_status()
            chaika = r.json()
            return chaika['gallery']
        except requests.ConnectionError:
            log.exception('Error parsing chaika')

class HenManager(DLManager):
    "G.e or Ex gallery manager"

    def __init__(self):
        super().__init__()
        if app_constants.HEN_DOWNLOAD_TYPE:
            self._download_type = app_constants.DOWNLOAD_TYPE_TORRENT
        else:
            self._download_type = app_constants.DOWNLOAD_TYPE_ARCHIVE

        self.e_url = 'https://e-hentai.org/'

        exprops = settings.ExProperties()
        cookies = exprops.cookies
        if not cookies:
            if exprops.username and exprops.password:
                cookies = EHen.login(exprops.username, exprops.password)
            else:
                raise app_constants.NeedLogin

        self._browser.session.cookies.update(cookies)


    def _archive_url_d(self, gid, token, key):
        "Returns the archiver download url"
        base = self.e_url + 'archiver.php?'
        d_url = base + 'gid=' + str(gid) + '&token=' + token + '&or=' + key
        return d_url

    def _torrent_url_d(self, gid, token):
        "Returns the torrent download url and filename"
        try:
            base = self.e_url + 'gallerytorrents.php?'
            torrent_page = base + 'gid=' + str(gid) + '&t=' + token
            self._browser.open(torrent_page)
            torrents = self._browser.find_all('table')
            if not torrents:
                return
            torrent = None # [seeds, url, name]
            for t in torrents:
                parts = t.find_all('tr')
                # url & name
                url = parts[2].td.a.get('href')
                name = parts[2].td.a.text + '.torrent'

                # seeds peers etc... NOT uploader
                meta = [x.text for x in parts[0].find_all('td')]
                seed_txt = meta[3]
                # extract number
                seeds = int(seed_txt.split(' ')[1])

                if not torrent:
                    torrent = [seeds, url, name]
                else:
                    if seeds > torrent[0]:
                        torrent = [seeds, url, name]

            _, url, name = torrent # just get download url

            # TODO: make user choose?
            return url, name
        except AttributeError:
            raise app_constants.HTMLParsing

    @staticmethod
    def gtoEh(g_url):
        "convert g.e-h to e-h"
        if 'g.e-hentai' in g_url:
            g_url = g_url.replace('g.e-hentai', 'e-hentai')
            if not 'https' in g_url and 'http' in g_url:
                g_url = g_url.replace('http', 'https')
        return g_url

    def from_gallery_url(self, g_url):
        """
        Finds gallery download url and puts it in download queue
        """
        if not g_url:
            return False
        if 'exhentai' in g_url:
            hen = ExHen(settings.ExProperties().cookies)
            if not hen.check_login(hen.cookies) == 2:
                raise app_constants.NeedLogin
        else:
            hen = EHen()
            if not hen.check_login(hen.cookies):
                raise app_constants.NeedLogin
        log_d("Using {}".format(hen.__repr__()))
        api_metadata, gallery_gid_dict = hen.add_to_queue(g_url, True, False)
        gallery = api_metadata['gmetadata'][0]
        log_d("EH API:\n\t".format(gallery))

        h_item = HenItem(self._browser.session)
        h_item.download_type = self._download_type
        h_item.gallery_url = g_url
        h_item.metadata = EHen.parse_metadata(api_metadata, gallery_gid_dict)
        try:
            h_item.metadata = h_item.metadata[g_url]
        except KeyError:
            raise app_constants.WrongURL
        h_item.thumb_url = gallery['thumb']
        h_item.gallery_name = gallery['title']
        h_item.size = "{0:.2f} MB".format(gallery['filesize']/1048576)

        if self._download_type == app_constants.DOWNLOAD_TYPE_ARCHIVE:
            try:
                d_url = self._archive_url_d(gallery['gid'], gallery['token'], gallery['archiver_key'])

                # ex/g.e
                log_d("Opening {}".format(d_url))
                self._browser.open(d_url)
                # check for availability
                log_d(self._browser.parsed)
                if 'gallery is currently unavailable' in '{}'.format(self._browser.parsed):
                    raise app_constants.GNotAvailable

                download_btn = self._browser.get_form()
                if download_btn:
                    log_d("Parsing download button!")
                    f_div = self._browser.find('div', id='db')
                    divs = f_div.find_all('div')
                    h_item.cost = divs[0].find('strong').text
                    h_item.cost = divs[0].find('strong').text
                    h_item.size = divs[1].find('strong').text
                    self._browser.submit_form(download_btn)
                    log_d("Submitted download button!")

                if self._browser.response.status_code == 302:
                    self._browser.open(self._browser.response.headers['location'], "post")

                # get dl link
                log_d("Getting download URL!")
                continue_p = self._browser.find("p", id="continue")
                if continue_p:
                    dl = continue_p.a.get('href')
                else:
                    dl_a = self._browser.find('a')
                    dl = dl_a.get('href')
                if 'forums.e-hentai.org' in dl:
                    raise app_constants.NeedLogin
                self._browser.open(dl)
                succes_test = self._browser.find('p')
                if succes_test and 'successfully' in succes_test.text:
                    gallery_dl = self._browser.find('a').get('href')
                    gallery_dl = self._browser.url.split('/archive')[0] + gallery_dl
                    f_name = succes_test.find('strong').text
                    h_item.download_url = gallery_dl
                    h_item.fetch_thumb()
                    h_item.name = f_name
                    Downloader.add_to_queue(h_item, self._browser.session)
                    return h_item
            except AttributeError:
                log.exception("HTML parsing error")
                raise app_constants.HTMLParsing

        elif self._download_type == app_constants.DOWNLOAD_TYPE_TORRENT:
            h_item.torrents_found = int(gallery['torrentcount'])
            h_item.fetch_thumb()
            if  h_item.torrents_found > 0:
                g_id_token = EHen.parse_url(g_url)
                if g_id_token:
                    url_and_file = self._torrent_url_d(g_id_token[0], g_id_token[1])
                    if url_and_file:
                        h_item.download_url = url_and_file[0]
                        h_item.name = url_and_file[1]
                        Downloader.add_to_queue(h_item, self._browser.session)
                        return h_item
            else:
                return h_item
        return False

class ExHenManager(HenManager):
    "ExHentai Manager"
    def __init__(self):
        super().__init__()
        self.e_url = "https://exhentai.org/"


class CommenHen:
    "Contains common methods"
    LOCK = threading.Lock()
    TIME_RAND = app_constants.GLOBAL_EHEN_TIME
    QUEUE = []
    COOKIES = {}
    LAST_USED = time.time()
    HEADERS = {'user-agent':"Mozilla/5.0 (Windows NT 6.3; rv:36.0) Gecko/20100101 Firefox/36.0"}
    _QUEUE_LIMIT = 25
    _browser = RoboBrowser(user_agent=HEADERS['user-agent'], parser='html.parser')

    def begin_lock(self):
        log_d('locked')
        self.LOCK.acquire()
        t1 = time.time()
        while int(time.time() - self.LAST_USED) < self.TIME_RAND:
            t = random.randint(3, self.TIME_RAND)
            time.sleep(t)
        t2 = time.time() - t1
        log_d("Slept for {}".format(t2))

    def end_lock(self):
        log_d('unlocked')
        self.LAST_USED = time.time()
        self.LOCK.release()

    def add_to_queue(self, url='', proc=False, parse=True):
        """Add url the the queue, when the queue has reached _QUEUE_LIMIT entries will auto process
        :proc -> proccess queue
        :parse -> return parsed metadata
        """
        if url:
            self.QUEUE.append(url)
            log_i("Status on queue: {}/{}".format(len(self.QUEUE), self._QUEUE_LIMIT))
        try:
            if proc:
                if parse:
                    return self.parse_metadata(*self.process_queue())
                return self.process_queue()
            if len(self.QUEUE) >= self._QUEUE_LIMIT:
                if parse:
                    return self.parse_metadata(*self.process_queue())
                return self.process_queue()
            else:
                return 1
        except TypeError:
            return None

    def process_queue(self):
        """
        Process the queue if entries exists, deletes entries.
        Note: Will only process _QUEUE_LIMIT entries (first come first out) while
            additional entries will get deleted.
        """
        log_i("Processing queue...")
        if len(self.QUEUE) < 1:
            return None

        try:
            if len(self.QUEUE) >= self._QUEUE_LIMIT:
                api_data, galleryid_dict = self.get_metadata(self.QUEUE[:self._QUEUE_LIMIT])
            else:
                api_data, galleryid_dict = self.get_metadata(self.QUEUE)
        except TypeError:
            return None
        finally:
            log_i("Flushing queue...")
            self.QUEUE.clear()
        return api_data, galleryid_dict

    @classmethod
    def login(cls, user, password, relogin=False):
        pass

    @classmethod
    def check_login(cls, cookies):
        pass

    def check_cookie(self, cookie):
        cookies = self.COOKIES.keys()
        present = []
        for c in cookie:
            if c in cookies:
                present.append(True)
            else:
                present.append(False)
        if not all(present):
            log_i("Updating cookies...")
            try:
                self.COOKIES.update(cookie)
            except requests.cookies.CookieConflictError:
                pass

    def handle_error(self, response):
        pass

    @classmethod
    def parse_metadata(cls, metadata_json, dict_metadata):
        """
        :metadata_json <- raw data provided by site
        :dict_metadata <- a dict with gallery id's as keys and url as value

        returns a dict with url as key and gallery metadata as value
        """
        pass

    def get_metadata(self, list_of_urls, cookies=None):
        """
        Fetches the metadata from the provided list of urls
        returns raw api data and a dict with gallery id as key and url as value
        """
        pass

    @classmethod
    def apply_metadata(cls, gallery, data, append=True):
        """
        Applies fetched metadata to gallery
        """
        pass

    def search(self, search_string, **kwargs):
        """
        Searches for the provided string or list of hashes,
        returns a dict with search_string:[list of title & url tuples] of hits found or emtpy dict if no hits are found.
        """
        pass

class NHen(CommenHen):
    "Fetches galleries from nhen"
    LOGIN_URL = "http://nhentai.net/login/"

    @classmethod
    def login(cls, user, password, relogin=False):
        exprops = settings.ExProperties(settings.ExProperties.NHENTAI)
        if not relogin:
            if cls.COOKIES:
                if cls.check_login(cls.COOKIES):
                    return cls.COOKIES
            elif exprops.cookies:
                if cls.check_login(exprops.cookies):
                    cls.COOKIES.update(exprops.cookies)
                    return cls.COOKIES

        cls._browser.open(cls.LOGIN_URL)
        login_form = cls._browser.get_form()
        if login_form:
            login_form['username'].value = user
            login_form['password'].value = password
            cls._browser.submit_form(login_form)

        n_c = cls._browser.session.cookies.get_dict()
        if not cls.check_login(n_c):
            log_w("NH login failed")
            raise app_constants.WrongLogin

        log_i("NH login succes")
        exprops.cookies = n_c
        exprops.username = user
        exprops.password = password
        exprops.save()
        cls.COOKIES.update(n_c)
        return n_c

    @classmethod
    def check_login(cls, cookies):
        if "sessionid" in cookies:
            return True

    @classmethod
    def apply_metadata(cls, gallery, data, append = True):
        return super().apply_metadata(gallery, data, append)

    def search(self, search_string, cookies = None, **kwargs):
        pass


class EHen(CommenHen):
    "Fetches galleries from ehen"
    def __init__(self, cookies = None):
        self.cookies = cookies if cookies else settings.ExProperties().cookies
        self.e_url = "https://e-hentai.org/api.php"
        self.e_url_o = "https://e-hentai.org/"


    @classmethod
    def apply_metadata(cls, g, data, append = True):
        "Applies metadata to gallery, returns gallery"
        if app_constants.USE_JPN_TITLE:
            try:
                title = data['title']['jpn']
            except KeyError:
                title = data['title']['def']
        else:
            title = data['title']['def']

        if 'Language' in data['tags']:
            try:
                lang = [x for x in data['tags']['Language'] if not x == 'translated'][0].capitalize()
            except IndexError:
                lang = ""
        else:
            lang = ""

        title_artist_dict = utils.title_parser(title)
        if not append:
            g.title = title_artist_dict['title']
            if title_artist_dict['artist']:
                g.artist = title_artist_dict['artist']
            g.language = title_artist_dict['language'].capitalize()
            if 'Artist' in data['tags']:
                g.artist = data['tags']['Artist'][0].capitalize()
            if lang:
                g.language = lang
            g.type = data['type']
            g.pub_date = data['pub_date']
            g.tags = data['tags']
            if 'url' in data:
                g.link = data['url']
            else:
                g.link = g.temp_url
        else:
            if not g.title:
                g.title = title_artist_dict['title']
            if not g.artist:
                g.artist = title_artist_dict['artist']
                if 'Artist' in data['tags']:
                    g.artist = data['tags']['Artist'][0].capitalize()
            if not g.language:
                g.language = title_artist_dict['language'].capitalize()
                if lang:
                    g.language = lang
            if not g.type or g.type == 'Other':
                g.type = data['type']
            if not g.pub_date:
                g.pub_date = data['pub_date']
            if not g.tags:
                g.tags = data['tags']
            else:
                for ns in data['tags']:
                    if ns in g.tags:
                        for tag in data['tags'][ns]:
                            if not tag in g.tags[ns]:
                                g.tags[ns].append(tag)
                    else:
                        g.tags[ns] = data['tags'][ns]
            if 'url' in data:
                if not g.link:
                    g.link = data['url']
            else:
                if not g.link:
                    g.link = g.temp_url
        return g

    @classmethod
    def check_login(cls, cookies):
        """
        Checks if user is logged in
        """
        if cookies.get('ipb_member_id') and cookies.get('ipb_pass_hash'):
            # check if there is access to ex
            ex = settings.ExProperties()
            if ex.custom: # this is to avoid spamming ex with requests
                return ex.custom.get('login')
            else:
                custom = {}
                custom['login'] = 0

                s = requests.Session()
                s.cookies.update(cookies)
                s.headers.update(cls.HEADERS)
                try:
                    r = cls.handle_error(cls, s.get('https://exhentai.org/'), wait=False)
                except requests.ConnectionError:
                    log.exception("connection error")
                    return 0
                if r:
                    custom['login'] = 2 # access to ex
                if r is None:
                    custom['login'] = 1 # we get sadpanda

                ex.custom = custom
                ex.save()
                return custom['login']
        return 0 # we've been banned, wrong credentials or haven't signed in

    def handle_error(self, response, wait=True):
        content_type = response.headers['content-type']
        text = response.text
        if 'image/gif' in content_type:
            app_constants.NOTIF_BAR.add_text('Provided exhentai credentials are incorrect!')
            log_e('Provided exhentai credentials are incorrect!')
            if wait:
                time.sleep(5)
            return None
        elif 'text/html' and 'Your IP address has been' in text:
            app_constants.NOTIF_BAR.add_text("Your IP address has been temporarily banned from g.e-/exhentai")
            log_e('Your IP address has been temp banned from g.e- and ex-hentai')
            if wait:
                time.sleep(5)
            return False
        elif 'text/html' in content_type and 'You are opening' in text:
            time.sleep(random.randint(10,50))
        return True

    @classmethod
    def parse_url(cls, url):
        "Parses url into a list of gallery id and token"
        gallery_id_token = regex.search('(?<=g/)([0-9]+)/([a-zA-Z0-9]+)', url)
        if not gallery_id_token:
            log_e("Error extracting g_id and g_token from url: {}".format(url))
            return None
        gallery_id_token = gallery_id_token.group()
        gallery_id, gallery_token = gallery_id_token.split('/')
        parsed_url = [int(gallery_id), gallery_token]
        return parsed_url

    def get_metadata(self, list_of_urls, cookies=None):
        """
        Fetches the metadata from the provided list of urls
        through the official API.
        returns raw api data and a dict with gallery id as key and url as value
        """
        assert isinstance(list_of_urls, list)
        if len(list_of_urls) > 25:
            log_e('More than 25 urls are provided. Aborting.')
            return None

        payload = {"method": "gdata",
             "gidlist": [],
             "namespace": 1
             }
        dict_metadata = {}
        for url in list_of_urls:
            parsed_url = EHen.parse_url(url.strip())
            if parsed_url:
                dict_metadata[parsed_url[0]] = url # gallery id
                payload['gidlist'].append(parsed_url)

        if payload['gidlist']:
            self.begin_lock()
            try:
                if cookies:
                    self.check_cookie(cookies)
                    r = requests.post(self.e_url, json=payload, timeout=30, headers=self.HEADERS, cookies=self.COOKIES)
                else:
                    r = requests.post(self.e_url, json=payload, timeout=30, headers=self.HEADERS)
            except requests.ConnectionError as err:
                self.end_lock()
                log_e("Could not fetch metadata: {}".format(err))
                raise app_constants.MetadataFetchFail("connection error")
            self.end_lock()
            if not self.handle_error(r):
                return 'error'
        else: return None
        try:
            r.raise_for_status()
        except:
            log.exception('Could not fetch metadata: status error')
            return None
        return r.json(), dict_metadata

    @classmethod
    def parse_metadata(cls, metadata_json, dict_metadata):
        """
        :metadata_json <- raw data provided by E-H API
        :dict_metadata <- a dict with gallery id's as keys and url as value

        returns a dict with url as key and gallery metadata as value
        """
        def invalid_token_check(g_dict):
            if 'error' in g_dict:
                return False
            else: return True

        parsed_metadata = {}
        for gallery in metadata_json['gmetadata']:
            url = dict_metadata[gallery['gid']]
            if invalid_token_check(gallery):
                new_gallery = {}
                def fix_titles(text):
                    t = html.unescape(text)
                    t = " ".join(t.split())
                    return t
                try:
                    gallery['title_jpn'] = fix_titles(gallery['title_jpn'])
                    gallery['title'] = fix_titles(gallery['title'])
                    new_gallery['title'] = {'def':gallery['title'], 'jpn':gallery['title_jpn']}
                except KeyError:
                    gallery['title'] = fix_titles(gallery['title'])
                    new_gallery['title'] = {'def':gallery['title']}

                new_gallery['type'] = gallery['category']
                new_gallery['pub_date'] = datetime.fromtimestamp(int(gallery['posted']))
                tags = {'default':[]}
                for t in gallery['tags']:
                    if ':' in t:
                        ns_tag = t.split(':')
                        namespace = ns_tag[0].capitalize()
                        tag = ns_tag[1].lower().replace('_', ' ')
                        if not namespace in tags:
                            tags[namespace] = []
                        tags[namespace].append(tag)
                    else:
                        tags['default'].append(t.lower().replace('_', ' '))
                new_gallery['tags'] = tags
                parsed_metadata[url] = new_gallery
            else:
                log_e("Error in received response with URL: {}".format(url))

        return parsed_metadata

    @classmethod
    def login(cls, user, password, relogin=False):
        """
        Logs into g.e-h
        """
        log_i("Attempting EH Login")
        eh_c = {}
        exprops = settings.ExProperties()
        if not relogin:
            if cls.COOKIES:
                if cls.check_login(cls.COOKIES):
                    return cls.COOKIES
            elif exprops.cookies:
                if cls.check_login(exprops.cookies):
                    cls.COOKIES.update(exprops.cookies)
                    return cls.COOKIES
        p = {
            'ipb_member_id':user,
            'ipb_pass_hash':password
            }

        s = requests.Session()
        s.headers.update(cls.HEADERS)
        s.cookies.update(p)
        r =  s.get('https://e-hentai.org/')

        if not cls.check_login(s.cookies):
            log_w("EH login failed")
            raise app_constants.WrongLogin

        log_i("EH login succes")
        exprops.cookies = s.cookies
        exprops.username = user
        exprops.password = password
        exprops.save()
        cls.COOKIES.update(s.cookies)

        return s.cookies

    def search(self, search_string, **kwargs):
        """
        Searches ehentai for the provided string or list of hashes,
        returns a dict with search_string:[list of title & url tuples] of hits found or emtpy dict if no hits are found.
        """
        assert isinstance(search_string, (str, list))
        if isinstance(search_string, str):
            search_string = [search_string]

        cookies = kwargs.pop('cookies', {})

        def no_hits_found_check(soup):
            "return true if hits are found"
            if not soup:
                log_e("There is no soup!")
            f_div = soup.body.find_all('div')
            for d in f_div:
                if 'No hits found' in d.text:
                    return False
            return True

        def do_filesearch(filepath):
            file_search_delay = 5
            if "exhentai" in self.e_url_o:
                f_url = "https://exhentai.org/upload/image_lookup.php/"
            else:
                f_url = "https://upload.e-hentai.org/image_lookup.php/"
            if cookies:
                self.check_cookie(cookies)
                self._browser.session.cookies.update(self.COOKIES)
            log_d("searching with color img: {}".format(filepath))
            files = {'sfile': open(filepath,'rb')}
            values = {'fs_similar': '1'}
            if app_constants.INCLUDE_EH_EXPUNGED:
                values['fs_exp'] = '1'
            try:
                r = self._browser.session.post(f_url, files=files, data=values)
            except requests.ConnectionError:
                time.sleep(file_search_delay+3)
                r = self._browser.session.post(f_url, files=files, data=values)
                
            s = BeautifulSoup(r.text, "html.parser")
            if "Please wait a bit longer between each file search." in "{}".format(s):
                log_e("Retrying filesearch due to interval response with delay: {}".format(file_search_delay))
                time.sleep(file_search_delay)
                s = do_filesearch(filepath)
            return s


        found_galleries = {}
        log_i('Initiating hash search on ehentai')
        log_d("search strings: ".format(search_string))
        for h in search_string:
            log_d('Hash search: {}'.format(h))
            self.begin_lock()
            try:
                if 'color' in kwargs:
                    soup = do_filesearch(h)
                else:
                    hash_url = self.e_url_o + '?f_shash='
                    hash_search = hash_url + h
                    if app_constants.INCLUDE_EH_EXPUNGED:
                        hash_search + '&fs_exp=1'
                    if cookies:
                        self.check_cookie(cookies)
                        r = requests.get(hash_search, timeout=30, headers=self.HEADERS, cookies=self.COOKIES)
                    else:
                        r = requests.get(hash_search, timeout=30, headers=self.HEADERS)
                    log_d("searching with greyscale img: {}".format(hash_search))
                    if not self.handle_error(r):
                        return 'error'
                    soup = BeautifulSoup(r.text, "html.parser")
            except requests.ConnectionError as err:
                self.end_lock()
                log.exception("Could not search for gallery: {}".format(err))
                raise app_constants.MetadataFetchFail("connection error")
            self.end_lock()

            if not no_hits_found_check(soup):
                log_e('No hits found with hash/image: {}'.format(h))
                continue
            log_i('Parsing html')
            try:
                if soup.body:
                    found_galleries[h] = []
                    # list view or grid view
                    type = soup.find(attrs={'class':'itg'}).name
                    if type == 'div':
                        visible_galleries = soup.find_all('div', attrs={'class':'id1'})
                    elif type == 'table':
                        visible_galleries = soup.find_all('div', attrs={'class':'it5'})

                    log_i('Found {} visible galleries'.format(len(visible_galleries)))
                    for gallery in visible_galleries:
                        title = gallery.text
                        g_url = gallery.a.attrs['href']
                        found_galleries[h].append((title,g_url))
            except AttributeError:
                log.exception('Unparseable html')
                log_d("\n{}\n".format(soup.prettify()))
                continue

        if found_galleries:
            log_i('Found {} out of {} galleries'.format(len(found_galleries), len(search_string)))
            return found_galleries
        else:
            log_w('Could not find any galleries')
            return {}

class ExHen(EHen):
    "Fetches gallery metadata from exhen"
    def __init__(self, cookies=None):
        super().__init__(cookies)
        self.e_url = "https://exhentai.org/api.php"
        self.e_url_o = "https://exhentai.org/"

    def get_metadata(self, list_of_urls):
        return super().get_metadata(list_of_urls, self.cookies)

    def search(self, hash_string, **kwargs):
        return super().search(hash_string, cookies=self.cookies, **kwargs)

class ChaikaHen(CommenHen):
    "Fetches gallery metadata from panda.chaika.moe"
    g_url = "http://panda.chaika.moe/gallery/"
    g_api_url = "http://panda.chaika.moe/jsearch?gallery="
    a_api_url = "http://panda.chaika.moe/jsearch?archive="
    def __init__(self):
        self.url = "http://panda.chaika.moe/jsearch?sha1="
        self._QUEUE_LIMIT = 1

    def search(self, search_string, **kwargs):
        """
        search_string should be a list of hashes
        will actually just put urls together
        return search_string:[list of title & url tuples]
        """
        if not isinstance(search_string, (list,tuple)):
            search_string = [search_string]
        x = {}
        for h in search_string:
            x[h] = [("", self.url+h)]
        return x

    def get_metadata(self, list_of_urls):
        """
        Fetches the metadata from the provided list of urls
        through the official API.
        returns raw api data and a dict with gallery id as key and url as value
        """
        data = []
        g_id_data = {}
        g_id = 1
        for url in list_of_urls:
            hash_search = True
            chaika_g_id = None
            old_url = url
            re_string = "^(http\:\/\/|https\:\/\/)?(www\.)?([^\.]?)(panda\.chaika\.moe\/(archive|gallery)\/[0-9]+)" # to validate chaika urls
            if regex.match(re_string, url):
                g_or_a_id = regex.search("([0-9]+)", url).group()
                if 'gallery' in url:
                    url = self.g_api_url+g_or_a_id
                    chaika_g_id = g_or_a_id
                else:
                    url = self.a_api_url+g_or_a_id
                hash_search = False
            try:
                try:
                    r = requests.get(url)
                except requests.ConnectionError as err:
                    log_e("Could not fetch metadata: {}".format(err))
                    raise app_constants.MetadataFetchFail("connection error")
                r.raise_for_status()
                if not r.json():
                    return None
                if hash_search:
                    g_data = r.json()[0] # TODO: multiple archives can be returned! Please fix!
                else:
                    g_data = r.json()
                if chaika_g_id:
                    g_data['gallery'] = chaika_g_id
                g_data['gid'] = g_id
                data.append(g_data)
                if hash_search:
                    g_id_data[g_id] = url
                else:
                    g_id_data[g_id] = old_url
                g_id += 1
            except requests.RequestException:
                log_e("Could not fetch metadata: status error")
                return None
        return data, g_id_data

    @classmethod
    def parse_metadata(cls, data, dict_metadata):
        """
        :data <- raw data provided by site
        :dict_metadata <- a dict with gallery id's as keys and url as value

        returns a dict with url as key and gallery metadata as value
        """
        eh_api_data = {
                "gmetadata":[]
            }
        g_urls = {}
        for d in data:
            eh_api_data['gmetadata'].append(d)
            # to get correct gallery urls
            g_urls[dict_metadata[d['gid']]] = cls.g_url + str(d['gallery']) + '/'
        p_metadata =  EHen.parse_metadata(eh_api_data, dict_metadata)
        # to get correct gallery urls instead of .....jsearch?sha1=----long-hash----
        for url in g_urls:
            p_metadata[url]['url'] = g_urls[url]
        return p_metadata

    @classmethod
    def apply_metadata(cls, g, data, append = True):
        "Applies metadata to gallery, returns gallery"
        return EHen.apply_metadata(g, data, append)
        


def hen_list_init():
    h_list = []
    for h in app_constants.HEN_LIST:
        if h == "ehen":
            h_list.append(EHen)
        elif h == "exhen":
            h_list.append(ExHen)
        elif h == "chaikahen":
            h_list.append(ChaikaHen)
    return h_list
