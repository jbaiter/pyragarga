import os
from pyragarga import Pyragarga

class TestPyragarga(object):

    def setup(self):
        self.pyragarga = Pyragarga('user', 'password')

    def teardown(self):
        try:
            os.remove('/tmp/pykg_test.db')
        except:
            pass

    def test_get_item(self):
        result = self.pyragarga.get_item(10593)
        assert result.kg_id == 10593
        assert result.orig_title == u"Chronik der Anna Magdalena Bach"
        assert result.aka_title == u"The Chronicle of Anna Magdalena Bach"
        assert result.genres == ['Arthouse', 'Drama']
        assert ("Jean-Marie Straub(1968)-Chronicle of Anna Magdalena Bach(Chronik der Anna Magdalena Bach)[93.DVD]{Ugo Pi.avi"
                in result.files)
        assert ("Straight.Shooting.(John.Ford, 1917).by.chainsaw[ci-cl].avi"
                in self.pyragarga.get_item(25906).files)
        assert ("Seven.Chances.1925.BluRay.720p.DTS.x264-CHD.mkv"
                in self.pyragarga.get_item(131335).files)
        assert ("Mad Max 3 - Beyond Thunderdome (1985) NTSC DVD5"
                in self.pyragarga.get_item(26763).files)

    def test_search_simple(self):
        result = self.pyragarga.search('Violence.Without.A.Cause.1969.DVDRip.XviD-KG.avi')
        assert result[0].kg_id == 21776

    def test_search_advanced(self):
        result = self.pyragarga.search('John Ford', search_type='director', num_pages=2)
        assert len(result) == 99
        assert result[3].orig_title == "Straight Shooting"

    def test_get_snatched(self):
        result = self.pyragarga.get_snatched(user_id=29027)
        assert result[0].kg_id == 3749
        assert result[1].orig_title == u"Bis ans Ende der Welt"
        assert result[1].imdb_id == 101458
        assert len(result) == 25

    def test_persist_db(self):
        self.pyragarga.enable_db('/tmp/pykg_test.db')
        self.pyragarga.get_item(10593)
        assert self.pyragarga._database.retrieve(10593).orig_title == u"Chronik der Anna Magdalena Bach"
        assert ("Jean-Marie Straub(1968)-Chronicle of Anna Magdalena Bach(Chronik der Anna Magdalena Bach)[93.DVD]{Ugo Pi.avi"
                in self.pyragarga._database.retrieve(10593).files)
        assert len(self.pyragarga._database._run_query(
            """select * from items;""")) == 1
        assert len(self.pyragarga._database._run_query(
            """select * from files;""")) == 1
