"""asmhentai module."""
import logging
from pprint import pformat

try:  # pragma: no cover
    from app_constants import DOWNLOAD_TYPE_OTHER, VALID_GALLERY_CATEGORY
    from dl_manager_obj import DLManagerObject
    from downloader_obj import DownloaderObject
    from hen_item import HenItem
except ImportError:
    from .app_constants import DOWNLOAD_TYPE_OTHER, VALID_GALLERY_CATEGORY
    from .dl_manager_obj import DLManagerObject
    from .downloader_obj import DownloaderObject
    from .hen_item import HenItem

log = logging.getLogger(__name__)
""":class:`logging.Logger`: Logger for module."""
log_i = log.info
""":meth:`logging.Logger.info`: Info logger func"""
log_d = log.debug
""":meth:`logging.Logger.debug`: Debug logger func"""
log_w = log.warning
""":meth:`logging.Logger.warning`: Warning logger func"""
log_e = log.error
""":meth:`logging.Logger.error`: Error logger func"""
log_c = log.critical
""":meth:`logging.Logger.critical`: Critical logger func"""


class AsmManager(DLManagerObject):
    """asmhentai manager.

    Attributes:
        url (str): Base url for manager.
    """

    url = 'http://asmhentai.com/'

    @staticmethod
    def _find_tags(browser):
        """find tags from browser.

        Args:
            browser: Robobrowser instance.

        Returns:
            list: List of doujin/manga tags on the page.
        """
        sibling_tags = browser.select('.tags h3')
        tags = list(map(
            lambda x: (
                x.text.split(':')[0],
                x.parent.select('span')
            ),
            sibling_tags
        ))
        res = []
        for tag in tags:
            for span_tag in tag[1]:
                res.append('{}:{}'.format(tag[0], span_tag.text))
        return res

    def _get_metadata(self, g_url):
        """get metadata.

        for key to fill see HenItem class.

        Args:
            g_url: Gallery url.

        Returns:
            dict: Metadata from gallery url.
        """
        self.ensure_browser_on_url(url=g_url)
        html_soup = self._browser
        res = {}
        res['title'] = html_soup.select('.info h1')[0].text
        res['title_jpn'] = html_soup.select('.info h2')[0].text
        res['filecount'] = html_soup.select('.pages')[0].text.split('Pages:')[1].strip()
        res['tags'] = self._find_tags(browser=self._browser)
        if any('Category:' in x for x in res['tags']):
            res['category'] = [tag.split(':')[1] for tag in res['tags'] if 'Category:' in tag][0]
        return res

    def _get_server_id(self, link_parts):
        """get server id.

        Args:
            link_parts (tuple): Tuple of (gallery_id, url_basename)

        Returns:
            server_id (str): server id.
        """
        gallery_id, url_basename = link_parts
        url = 'http://asmhentai.com/gallery/{gallery_id}/{url_basename}/'.format(
            gallery_id=gallery_id, url_basename=url_basename)
        self._browser.open(url)
        link_tags = self._browser.select('img.no_image')
        # e.g.
        # link_tag_src = '//images.asmhentai.com/001/12623/1.jpg'
        link_tag_src = link_tags[0].get('src')
        return link_tag_src.split('//images.asmhentai.com/')[1].split('/')[0]

    @staticmethod
    def _split_href_links_to_parts(links):
        """Split href links to parts.

        Args:
            links (list): List of hrefs.

        Returns:
            list of tuple contain url parts.
        """
        return [(x.split('/')[2], x.split('/')[-2]) for x in links]

    def _get_dl_urls(self, g_url):
        """get image urls from gallery url.

        Args:
            g_url: Gallery url.

        Returns:
            list: Image from gallery url.
        """
        # ensure the url
        self.ensure_browser_on_url(url=g_url)
        links = self._browser.select('.preview_thumb a')
        links = [x.get('href') for x in links]
        # link = '/gallery/168260/22/'
        links_parts = self._split_href_links_to_parts(links)
        server_id = self._get_server_id(links_parts[0])
        log_d('Server id: {}'.format(server_id))
        imgs = list(map(
            lambda x:
            'http://images.asmhentai.com/{}/{}/{}.jpg'.format(server_id, x[0], x[1]),
            links_parts
        ))
        return imgs

    @staticmethod
    def _set_ehen_metadata(h_item, dict_metadata):
        """set ehen metadata.

        unlike set_metadata method, This will update metadata based on required metadata in
        Ehen.apply_method.

        Args:
            h_item (hen_item.HenItem): Item.
            dict_metadata (dict): Metadata source.

        Returns:
            Updated h_item
        """
        new_data_tags = {}
        for tag in dict_metadata['tags']:
            namespace, tag_value = tag.split(':', 1)
            new_data_tags.setdefault(namespace, []).append(tag_value)
        new_data = {
            'title': {
                'jpn': dict_metadata['title_jpn'],
                'def': dict_metadata['title'],

            },
            'tags': new_data_tags,
            'type': dict_metadata['category'],
            'pub_date': ''  # asm manager don't parse publication date. it is not exist.
        }
        h_item.metadata.update(new_data)
        return h_item

    @staticmethod
    def _set_metadata(h_item, dict_metadata):
        """set metadata on item from dict_metadata.

        Args:
            h_item (hen_item.HenItem): Item.
            dict_metadata (dict): Metadata source.

        Returns:
            Updated h_item
        """
        keys = ['title_jpn', 'title', 'filecount', "tags"]
        for key in keys:
            value = dict_metadata.get(key, None)
            if value:
                h_item.update_metadata(key=key, value=value)
        # for hitem gallery value
        catg_val = dict_metadata.get('category', None)
        category_dict = {vcatg.lower(): vcatg for vcatg in VALID_GALLERY_CATEGORY}
        category_value = category_dict.get(catg_val, catg_val)
        if category_value and category_value in VALID_GALLERY_CATEGORY:
            h_item.update_metadata(key='category', value=category_value)
        elif category_value:
            log_w('Unknown manga category:{}'.format(category_value))

        return h_item

    def from_gallery_url(self, g_url):
        """Find gallery download url and puts it in download queue.

        Args:
            g_url: Gallery url.

        Returns:
            Download item
        """
        h_item = HenItem(self._browser.session)
        h_item.download_type = DOWNLOAD_TYPE_OTHER
        h_item.gallery_url = g_url
        # ex/g.e
        log_d("Opening {}".format(g_url))
        dict_metadata = self._get_metadata(g_url=g_url)
        log_d('dict_metadata:\n{}'.format(pformat(dict_metadata)))
        h_item.thumb_url = 'http:' + self._browser.select('.cover img')[0].get('src')
        h_item.fetch_thumb()

        # name
        h_item.gallery_name = dict_metadata['title']
        # name is the name folder
        h_item.name = dict_metadata['title']

        # get dl link
        log_d("Getting download URL!")
        h_item.download_url = self._get_dl_urls(g_url=g_url)

        h_item = self._set_metadata(h_item=h_item, dict_metadata=dict_metadata)

        old_metadata = h_item.metadata
        h_item = self._set_ehen_metadata(h_item=h_item, dict_metadata=dict_metadata)
        log_d('Old metadata\n{}New metadata\n{}'.format(
            pformat(old_metadata),
            pformat(h_item.metadata)
        ))

        DownloaderObject.add_to_queue(h_item, self._browser.session)
        return h_item
