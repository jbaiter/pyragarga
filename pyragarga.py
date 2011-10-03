import re
import sys
import os.path
import sqlite3

# ElementTree 1.3 is required for its handling of more advanced XPath
# expressions. As it's only available in the standard library from Python 2.7
# on, we have to use the 3rd party module for earlier versions.
if sys.version_info >= (2, 7):
    from xml.etree import cElementTree as ET
else:
    import cElementTree as ET

import requests
from tidylib import tidy_document
from bencode import bdecode

kg_url = 'https://karagarga.net/'
login_script = 'takelogin.php'
browse_script = 'browse.php'
details_script = 'details.php'
history_script = 'history.php'
bookmarks_script = 'bookmarks.php'

class KGItem(object):

    def __init__(self, kg_id):
        """ Initialize object with the item's Karagarga ID. """
        self.kg_id = None
        self.imdb_id = None
        
        self.title = None
        self.director = None
        self.year = None
        self.country = None
        self.genres = []
        self.files = []
        self.torrent = None

        self.kg_id = int(kg_id)
    
    def update_info(self):
        """ Get the details page from KG and retrieve information
            from there.
        """
        pass

    def __repr__(self):
        return u"<KGItem \"%s\" with id %d>" % (self.title, self.kg_id)

class Pyragarga(object):
    """ Class that represents the tracker's API.
    """

    def __init__(self, username, password):
        """ Initialize access to the tracker by logging in. """
        self._session = requests.session()
        self._session.post(kg_url + login_script,
                data={'username':username, 'password':password})
        self.user_id = requests.utils.dict_from_cookiejar(
                self._session.cookies)['uid']
    
    def get_item(self, item_id):
        """ Returns the item with the given id. """
        pass

    def get_imdb_items(self, imdb_id):
        """ Returns all items listed for a given iMDB-ID. """
        pass

    def search(self, query, search_type='torrent', num_pages=1):
        """ Execute a search query for torrents of type `search_type` and
            present the results retreived from `num_pages`.
        """
        result_pages = []
        result_pages.append(self._do_search(query))
        if num_pages > 1:
            page_num = 1
            while page_num < (num_pages-1):
                result_pages.append(self._do_search(query,
                        options={'page':page_num}))
                page_num += 1
        result_items = []
        for page in result_pages:
            result_items += self._parse_result_page(page)
        # TODO: Somehow trying to get the files during the row parsing step
        #       fails because of bad 'bencode' data...
        for item in result_items:
            try:
                item.files = self._get_files_from_torrent(item.torrent)
            except:
                print "Invalid torrent data for \"%s\"" % item.title
        return result_items
    
    def get_snatched(self, user_id=None):
        """ Returns a list with all items on the tracker snatched by the user.
        """
        if not user_id:
            user_id = self.user_id
        current_page = 0
        snatched_pages = []
        snatched_pages.append(self._build_tree(
                self._session.get(kg_url + history_script,
                    params={'id': user_id, 'rcompsort':1, 'page':current_page}
                    ).content))
        current_page += 1
        last_page = self._get_max_pagenum(snatched_pages[0])
        while current_page <= last_page:
            print "Getting page %d of %d" % (current_page+1, last_page+1)
            snatched_pages.append(self._build_tree(
                self._session.get(kg_url + history_script,
                params={'id':user_id, 'rcompsort':1, 'page':current_page}
                ).content))
            current_page += 1
        snatched_items = []
        for num, page in enumerate(snatched_pages):
            print "Parsing page %d of %d" % (num+1, last_page+1)
            snatched_items += self._parse_result_page(page)
        return snatched_items

    def get_bookmarks(self, snatched=False):
        """ Returns a list with all items bookmarked on the tracker by the
            user, by default excluding any item already snatched.
        """
        start_page = self._build_tree(
            self._session.get(kg_url + bookmarks_script,
                params={'page':0}).content)
        return self._get_max_pagenum(start_page)

    def get_mom_items(self, mom_id):
        """ Returns a list with all the items from a MoM. """
        pass

    def _build_tree(self, markup):
        """ Helper method that builds a XML element tree from the markup
            it gets passed, tidying it beforehand.
        """
        clean_markup = tidy_document(markup,
                                     options={'numeric-entities':1})[0]
        etree = self._fix_treetags(ET.fromstring(clean_markup))
        return etree

    def _fix_treetags(self, tree):
        """ Helper method that removes the namespace prefix from all tags
            in a given XML element tree to facilitate querying.
        """
        for element in tree:
            element.tag = element.tag.split('}')[1]
            if len(element.getchildren()) > 0:
                self._fix_treetags(element)
        return tree
            
    def _get_max_pagenum(self, pagetree):
        """ Gets the last pagenumber that results are available for. """
        browse_links = [x.get('href') for x in
                      pagetree.findall('body/table/tr/td//p/a')]
        #Find the largest value for 'page'
        page_rexp = re.compile(r"^.*\.php\?.*page=(\d*).*")
        page_nums = [int(page_rexp.match(x).groups()[0]) for x in browse_links]
        page_nums.sort(reverse=True)
        max_pagenum = page_nums[0]
        return max_pagenum

    def _do_search(self, query, options=None):
        default_options = {'incldead':0}
        # Some default parameters
        if not options or 'search_type' not in options.keys():
            options = dict(default_options, **{'search_type':'torrent'})
        else:
            options = dict(default_options, **options)
        # Add the search query
        options = dict(options, **{'search':query})
        result_tree = self._build_tree(
                self._session.get(kg_url + browse_script,
                    params=options).content
                )
        return result_tree

    def _parse_result_page(self, page):
        """ Parses a page that contains a table listing KG items. """
        items = []
        table = list(page.findall(".//table[@id='browse']"))[0]
        for row in (x for x in list(table.findall('tr'))[1:]
                    if len(x.getchildren()) != 1):
            item = self._parse_item_row(row)
            items.append(item)
        return items

    def _parse_item_row(self, row):
        """ Parses a row from a table of results and returns a dictionary with
            all relevant information on the item.
        """
        kg_id_rexp = re.compile(r"^details.php\?id=(\d*)")
        item = KGItem(int(kg_id_rexp.match(
            row.find('td/span/a').get('href')).groups()[0]))
        imdb_id_rexp = re.compile(r"^.*http://www.imdb.com/title/tt(\d*).*")
        imdb_link = row.find(".//img[@alt='imdb link']/..")
        if imdb_link:
            imdb_url = imdb_link.get('href')
            if 'http://www.imdb.com/' in imdb_url:
                try:
                    item.imdb_id = imdb_id_rexp.match(imdb_url).groups()[0]
                except:
                    print "Bad URL: %s" % imdb_url
        item.title = row.find('td/span/a/b').text
        var_links = list(row.findall('td/a'))
        item.director = var_links[0].text
        item.year = var_links[1].text
        genre_rexp = re.compile(r"^.*browse.php\?genre=(\d*).*") 
        item.genres = [x.text for x in var_links
                       if genre_rexp.match(x.get('href'))]
        item.country = row.find('td/a/img').get('alt')
        item.torrent = self._session.get(
                kg_url + row.find(".//img[@alt='Download']/..").get('href')
                ).content
        return item

    def _get_files_from_torrent(self, torrent):
        """ Returns a list with all the files contained in a given torrent. """
        files = []
        torrent_data = bdecode(torrent)
        name = torrent_data['info']['name']
        files.append(name)
        if 'files' in torrent_data['info'].keys():
            for file_ in [x['path']
                          for x in torrent_data['info']['files']]:
                # FIXME: Sometimes bdecode seems to give a list of length 1
                #        instead of a plain string for 'path'
                if type(file_) == list:
                    file_ = file_[0]
                files.append(os.path.join(name, file_))
        return files

    def _persist_snatched(self, items, db_file):
        """ Stores all snatched items in a SQLite database to ease the load
            on the server and make queries faster.
        """
        schema = """
                    create table items (
                        kg_id       integer primary key,
                        imdb_id     integer,
                        title       text,
                        director    text,
                        year        text,
                        country     text,
                        torrent     blob,
                        files       integer,
                        genres      text
                    )
                """
        db_is_new = not os.path.exists(db_file)
