""" pyragarga.py
Python module to access karagarga.net.
Useful to obtain metadata for downloaded films, grab torrent-files for
bookmarked items, etc.
"""


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

KG_URL = 'https://karagarga.net/'
LOGIN_SCRIPT = 'takelogin.php'
BROWSE_SCRIPT = 'browse.php'
DETAILS_SCRIPT = 'details.php'
HISTORY_SCRIPT = 'history.php'
BOOKMARKS_SCRIPT = 'bookmarks.php'

KG_ID_REXP = re.compile(r"^details.php\?id=(\d*)")
PAGE_REXP = re.compile(r"^.*\.php\?.*page=(\d*).*")
H1_REXP = re.compile(r"KG - (.*) \((.*)\)(.*)")
GENRE_REXP = re.compile(r"^.*browse.php\?genre=(\d*).*") 
IMDB_ID_REXP = re.compile(r"^.*http://www.imdb.com/title/tt(\d*).*")
FILENAME_REXP = re.compile(r"(.*\.avi|AVI|mkv|MKV)\.torrent$")

class KGItem(object):

    def __init__(self, kg_id, imdb_id=None, orig_title=None, aka_title=None,
                 director=None, year=None, country=None, torrent=None,
                 genres=[], source=None, subtitles=None, language=None,
                 media_type=None):
        """ Initialize object with the item's Karagarga ID. """
        self.kg_id = int(kg_id)
        self.imdb_id = imdb_id
        
        self.orig_title = orig_title
        self.aka_title = aka_title
        self.director = director
        self.year = year
        self.country = country
        self.genres = genres
        self.files = []
        self.torrent = torrent
        self.source = source
        self.subtitles = subtitles
        self.language = language
        self.media_type = type

    def __repr__(self):
        return "<KGItem \"%s\" with id %d>" % (self.orig_title, self.kg_id)

class Pyragarga(object):
    """ Class that represents the tracker's API."""
    # TODO: Move all tracker-code to a separate TrackerApi class, so that
    #       all this class does is to provide wrappers that decide whether
    #       to get the data locally or from the KG server
    #       Rationale: Makes API more extensible, e.g. to add support for
    #                  other trackers
    #       Problems:  The whole API revolves around 'KGItem'-objects.
    #                  What would a more abstract type look like?
    # TODO: Make the API movie-only, i.e. filter out ebooks and music from
    #       search results, raise an exception if details for one are
    #       requested.
    #       Rationale: Makes API simpler, no need to worry about corner-
    #                  cases


    def __init__(self, username, password, db_file=None):
        """ Initialize access to the tracker by logging in. """
        self._database = None
        if db_file:
            self.enable_db(db_file)
        self._session = requests.session()
        self._session.post(KG_URL + LOGIN_SCRIPT,
                data={'username':username, 'password':password})
        self.user_id = self._session.cookies['uid']

    def enable_db(self, db_file):
        if not self._database:
            self._database = LocalDatabase(db_file)
    
    def get_item(self, item_id):
        """ Returns the item with the given id. """
        if self._database:
            try:
                return self._database.retrieve(item_id)
            except PyragargaError:
                pass
        details_page = self._build_tree(
                self._session.get(KG_URL + DETAILS_SCRIPT,
                    params={'id': item_id, 'filelist':1}
                    ).content)
        item = self._parse_details_page(details_page, item_id)
        if self._database:
            self._database.store(item)
        return item

    def search(self, query, search_type='torrent', num_pages=1,
            movies_only=True):
        """ Execute a search query for torrents of type `search_type` and
            present the results retreived from `num_pages`.
        """
        result_pages = []
        result_pages.append(self._do_search(query,
            options={'search_type':search_type}))
        if num_pages > 1:
            print "More than one page, yay!"
            page_num = 1
            while page_num < (num_pages):
                result_pages.append(self._do_search(query,
                    options={'search_type':search_type, 'page':page_num}))
                page_num += 1
        result_items = []
        for page in result_pages:
            result_items += self._parse_result_page(page)
        if movies_only:
            result_items = [x for x in result_items
                            if x.media_type == 'Movie']
        return result_items
    
    def get_snatched(self, user_id=None, movies_only=True):
        """ Returns a list with all items on the tracker snatched by the user.
        """
        if not user_id:
            user_id = self.user_id
        current_page = 0
        snatched_pages = []
        snatched_pages.append(self._build_tree(
                self._session.get(KG_URL + HISTORY_SCRIPT,
                    params={'id': user_id, 'rcompsort':1, 'page':current_page}
                    ).content))
        current_page += 1
        last_page = self._get_max_pagenum(snatched_pages[0])
        while current_page <= last_page:
            snatched_pages.append(self._build_tree(
                self._session.get(KG_URL + HISTORY_SCRIPT,
                params={'id':user_id, 'rcompsort':1, 'page':current_page}
                ).content))
            current_page += 1
        snatched_items = []
        for page in snatched_pages:
            snatched_items += self._parse_result_page(page)
        if movies_only:
            snatched_items = [x for x in snatched_items
                              if x.media_type == 'Movie']
        return snatched_items

    def get_bookmarks(self, snatched=False):
        """ Returns a list with all items bookmarked on the tracker by the
            user, by default excluding any item already snatched.
        """
        # TODO: Implement this properly
        #       Idea:
        #           - Get first page of bookmarks
        #           - Determine number of last page ('_get_max_pagenum')
        #           - Go through all bookmarks pages, parsing them for
        #             KGItems ('_parse_result_page')
        #start_page = self._build_tree(
        #    self._session.get(KG_URL + BOOKMARKS_SCRIPT,
        #        params={'page':0}).content)
        raise NotImplementedError

    def _build_tree(self, markup):
        """ Helper method that builds a XML element tree from the markup
            it gets passed, tidying it beforehand.
        """
        clean_markup = tidy_document(markup,
                                     options={'numeric-entities':1,
                                              'output-xml':1,
                                              'output-encoding':'utf8'})[0]
        # Small fix for a cornercase involving invalid characters...
        clean_markup = clean_markup.replace('\x15', '_')
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
        page_nums = [int(PAGE_REXP.match(x).groups()[0]) for x in browse_links]
        page_nums.sort(reverse=True)
        max_pagenum = page_nums[0]
        return max_pagenum

    def _do_search(self, query, options=None):
        default_options = {'incldead':0}
        options.update(default_options)
        # Add the search query
        options.update({'search':query})
        result_tree = self._build_tree(
                self._session.get(KG_URL + BROWSE_SCRIPT,
                    params=options).content
                )
        return result_tree

    def _parse_details_page(self, page, kg_id):
        """ Parses a page that contains details for a KG item.
            Returns a KGItem.
            FIXME: A little too b
        """
        item = KGItem(int(kg_id))
        title = page.find(".//title").text.strip()
        title = H1_REXP.match(title).groups()[0]
        if " aka " in title:
            (item.orig_title, item.aka_title) = title.split(' aka ')[0:2]
        elif " AKA " in title:
            (item.orig_title, item.aka_title) = title.split(' AKA ')[0:2]
        else:
            item.orig_title = title
        table = list(page.findall(".//table[@width='750']"))[0]
        for row in (x for x in list(table.findall('tr'))
                if len(x.getchildren()) != 1):
            rowhead = row.find(".//td[@class='rowhead']")
            # For some reason 'bool(rowhead)' evaluates to 'False' even if
            # it is not 'None'... Don't ask me why :-/
            if rowhead != None:
                torrent_link = row.findall(".//a")[0]
                torrent_name = torrent_link.text.strip()
                torrent_url = torrent_link.get('href')
            else:
                heading = row.find(".//td[@class='heading']").text.strip()
                if heading == 'Internet Link':
                    item.imdb_id = self._get_imdb_id(row)
                elif heading == 'Director / Artist':
                    item.director = row.find(".//a").text
                elif heading == 'Year':
                    item.year = row.find(".//a").text
                elif heading == 'Genres':
                    item.genres = [x.text for x in row.findall(".//a")
                                   if x.text]
                elif heading == 'Language':
                    item.language = row.find(
                            ".//td[@align='left']").text.strip()
                elif heading == 'Subtitles':
                    # TODO: Get subtitles. How to handle included/external subs?
                    pass
                elif heading == 'Source':
                    item.source = row.find(".//td[@align='left']").text.strip()

        file_table = table.find("./tr/td[@align='left']/table[@class='main']")
        if file_table:
            for row in file_table[1:]:
                item.files.append(row.find('td').text.strip())
        elif FILENAME_REXP.match(torrent_name):
            item.files = [FILENAME_REXP.match(torrent_name).groups()[0]]
        else:
            torrent = self._session.get(KG_URL + torrent_url).content
            item.files = self._get_files_from_torrent(torrent)

        return item


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
        item = KGItem(int(KG_ID_REXP.match(
            row.find('td/span/a').get('href')).groups()[0]))
        item.imdb_id = self._get_imdb_id(row)
        title_string = row.find('td/span/a/b').text
        if " AKA " in title_string:
            (item.orig_title, item.aka_title) = title_string.split(' AKA ')[0:2]
        else:
            item.orig_title = title_string
        var_links = list(row.findall('td/a'))
        item.director = var_links[0].text
        item.year = var_links[1].text
        item.genres = [x.text for x in var_links
                       if GENRE_REXP.match(x.get('href'))]
        item.media_type = row.find("td/div/a/img[@width='40']").get(
                'title').split(':')[0]
        item.country = row.find('td/a/img').get('alt')
        return item

    def _get_imdb_id(self, row):
        imdb_link = row.find(".//img[@alt='imdb link']/..")
        if imdb_link:
            imdb_url = imdb_link.get('href')
            if 'http://www.imdb.com/' in imdb_url:
                try:
                    return int(IMDB_ID_REXP.match(imdb_url).groups()[0])
                except:
                    return None

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



class LocalDatabase(object):
    """ Manages items stored locally, to ease load on the KG-Server and make
        querying faster.
    """

    schema = """
                create table items (
                    kg_id       integer primary key,
                    imdb_id     integer,
                    orig_title  text,
                    aka_title   text,
                    director    text,
                    year        text,
                    country     text,
                    torrent     blob,
                    genres      text,
                    source      text,
                    subtitles   text,
                    language    text,
                    media_type  text
                );

                create table files (
                    id          integer primary key,
                    filename    text,
                    item_id     integer not null references items(kg_id)
                );
            """

    def __init__(self, db_file):
        db_exists = os.path.exists(db_file)
        self.conn = sqlite3.connect(db_file)
        if not db_exists:
            self.conn.executescript(LocalDatabase.schema)

    def retrieve(self, kg_id):
        """ Retrieve item with the given KG-ID from the database. """
        cursor = self.conn.cursor()
        cursor.execute("""select * from items where kg_id = ?;""", (kg_id,))
        result = cursor.fetchone()
        if not result:
            raise PyragargaError("No item found.")
        item = KGItem(*result)
        cursor.execute("""select * from files where item_id = ?;""", (kg_id,))
        item.files = [x[1] for x in cursor.fetchall()]
        # FIXME: Convert 'genres' column back to a list first
        return item

    def store(self, item):
        """ Store given item in database."""
        cursor = self.conn.cursor()
        # Store the item
        if item:
            cursor.execute(*self._build_insert(item, 'items'))
        for file_ in item.files:
            cursor.execute("""insert into files (filename, item_id)
                values (?, ?)""", (file_, item.kg_id))
        self.conn.commit()

    def _run_query(self, query):
        """ Run a query on the database. """
        cursor = self.conn.cursor()
        cursor.execute(query)
        return cursor.fetchall()

    def _build_insert(self, item, table):
        # FIXME: Huge security gap, as this makes the application vulnerable
        #        to SQL injection. I don't know how to construct queries with
        #        a varying number of keys safely, though :-/
        #        On top of that, the code is butt-ugly, but well...
        keys = tuple(x for x in item.__dict__
                if item.__dict__[x] and x != 'files')
        values = tuple(unicode(item.__dict__[x]) for x in keys)
        query = "insert into %s (%s) values (%s)" % (
                    table, ', '.join(keys), ', '.join('?'*len(keys)))
        return (query, values)


class PyragargaError(Exception):

    pass
