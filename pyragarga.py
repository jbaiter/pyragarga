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

    def __init__(self, kg_id, imdb_id=None, orig_title=None, aka_title=None,
                 director=None, year=None, country=None, torrent=None,
                 genres=[], source=None, subtitles=None, language=None):
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

    def __repr__(self):
        return "<KGItem \"%s\" with id %d>" % (self.orig_title, self.kg_id)

class Pyragarga(object):
    """ Class that represents the tracker's API."""
    # TODO: Move all tracker-code to a separate TrackerApi class, so that
    #       all this class does is to provide wrappers that decide whether
    #       to get the data locally or from the KG server


    def __init__(self, username, password, db_file=None):
        """ Initialize access to the tracker by logging in. """
        self._database = None
        if db_file:
            self.enable_db(db_file)
        self._session = requests.session()
        self._session.post(kg_url + login_script,
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
                self._session.get(kg_url + details_script,
                    params={'id': item_id, 'filelist':1}
                    ).content)
        item = self._parse_details_page(details_page, item_id)
        if self._database:
            self._database.store(item)
        return item

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
            snatched_pages.append(self._build_tree(
                self._session.get(kg_url + history_script,
                params={'id':user_id, 'rcompsort':1, 'page':current_page}
                ).content))
            current_page += 1
        snatched_items = []
        for num, page in enumerate(snatched_pages):
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
        # FIXME: This fails when some weird characters appear on the page.
        #        Happens mostly in the comments.
        #        Examples: "&#21"
        #        Proposed solution: Pre-process the xml-file to get rid
        #         of these characters.
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

    def _parse_details_page(self, page, kg_id):
        """ Parses a page that contains details for a KG item.
            Returns a KGItem.
        """
        item = KGItem(int(kg_id))
        # TODO: Get filename(s) either from torrent-name or from filelist
        title = page.find(".//title").text.strip()
        h1_rexp = re.compile(r"KG - (.*) \((.*)\)(.*)")
        title = h1_rexp.match(title).groups()[0]
        if " aka " in title:
            (item.orig_title, item.aka_title) = title.split(' aka ')[0:2]
        elif " AKA " in title:
            (item.orig_title, item.aka_title) = title.split(' AKA ')[0:2]
        else:
            item.orig_title = title
        table = list(page.findall(".//table[@width='750']"))[0]
        for row in (x for x in list(table.findall('tr'))[1:]
                if len(x.getchildren()) != 1):
            heading = row.find(".//td[@class='heading']").text.strip()
            if heading == 'Internet Link':
                item.imdb_id = self._get_imdb_id(row)
            elif heading == 'Director / Artist':
                item.director = row.find(".//a").text
            elif heading == 'Year':
                item.year = row.find(".//a").text
            elif heading == 'Genres':
                item.genres = [x.text for x in row.findall(".//a") if x.text]
            elif heading == 'Language':
                item.language = row.find(".//td[@align='left']").text.strip()
            elif heading == 'Subtitles':
                # TODO: Get subtitles. How to handle included/external subs?
                pass
            elif heading == 'Source':
                item.source = row.find(".//td[@align='left']").text.strip()
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
        kg_id_rexp = re.compile(r"^details.php\?id=(\d*)")
        item = KGItem(int(kg_id_rexp.match(
            row.find('td/span/a').get('href')).groups()[0]))
        item.imdb_id = self._get_imdb_id(row)
        title_string = row.find('td/span/a/b').text
        # FIXME: Sometimes, this still fails with an "ValueError"
        if " AKA " in title_string:
            (item.orig_title, item.aka_title) = title_string.split(' AKA ')[0:2]
        else:
            item.orig_title = title_string
        var_links = list(row.findall('td/a'))
        item.director = var_links[0].text
        item.year = var_links[1].text
        genre_rexp = re.compile(r"^.*browse.php\?genre=(\d*).*") 
        item.genres = [x.text for x in var_links
                       if genre_rexp.match(x.get('href'))]
        item.country = row.find('td/a/img').get('alt')
        return item

    def _get_imdb_id(self, row):
        imdb_id_rexp = re.compile(r"^.*http://www.imdb.com/title/tt(\d*).*")
        imdb_link = row.find(".//img[@alt='imdb link']/..")
        if imdb_link:
            imdb_url = imdb_link.get('href')
            if 'http://www.imdb.com/' in imdb_url:
                try:
                    return int(imdb_id_rexp.match(imdb_url).groups()[0])
                except:
                    return None

    def _get_genres(self, links):
        genre_rexp = re.compile(r"^.*browse.php\?genre=(\d*).*") 
        genres = [x.text for x in links
                       if genre_rexp.match(x.get('href'))]
        return genres


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
                    language    text
                );

                create table files (
                    id          integer primary key,
                    path        text,
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
        # FIXME: Convert 'genres' column back to a list first
        return KGItem(*result)

    def store(self, item):
        """ Store given item in database."""
        cursor = self.conn.cursor()
        # Store the item
        if item:
            cursor.execute(*self._build_insert(item, 'items'))
            self.conn.commit()
        # TODO: Store the associated files

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
