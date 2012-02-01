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
        assert "Jean-Marie Straub(1968)-Chronicle of Anna Magdalena Bach (Chronik der Anna Magdalena Bach)[93.DVD]{Ugo Pi.avi" in result.files

    def test_search_simple(self):
        result = self.pyragarga.search('Violence.Without.A.Cause.1969.DVDRip.XviD-KG.avi')
        assert result[0].kg_id == 21776

    def test_get_snatched(self):
        result = self.pyragarga.get_snatched(user_id=29027)
        assert result[3].kg_id == 3749
        assert result[5].orig_title == u"Bis ans Ende der Welt"
        assert len(result) == 52

    def test_persist_db(self):
        self.pyragarga.enable_db('/tmp/pykg_test.db')
        self.pyragarga.get_snatched(user_id=29027)
        self.pyragarga.get_item(10593)
        assert len(self.pyragarga._database._run_query(
            """select * from items;""").fetchall()) == 53
