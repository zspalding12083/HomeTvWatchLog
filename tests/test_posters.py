import json
import os
import tempfile
import unittest
from unittest import mock

from watchlog import posters
from watchlog.store import Store

WIKI = {"query": {"pages": [
    {"index": 1, "title": "Knives Out (film series)", "thumbnail": {"source": "https://upload.wikimedia.org/series.jpg"}},
    {"index": 2, "title": "Glass Onion: A Knives Out Mystery", "thumbnail": {"source": "https://upload.wikimedia.org/glass.jpg"}},
    {"index": 3, "title": "Mission: Impossible – Dead Reckoning Part One (2023 film)",
     "thumbnail": {"source": "https://upload.wikimedia.org/mi.jpg"}},
    {"index": 4, "title": "Dune (novel)", "thumbnail": {"source": "https://upload.wikimedia.org/novel.jpg"}}]}}
TVMAZE = [{"show": {"name": "The Crown", "image": {"medium": "https://static.tvmaze.com/crown.jpg"}}}]


def fake_get(url):
    if "wikipedia.org/w/api.php" in url:
        return json.dumps(WIKI).encode(), "application/json"
    if "api.tvmaze.com" in url:
        return json.dumps(TVMAZE).encode(), "application/json"
    if url.endswith(".jpg"):
        return b"\xff\xd8 fake jpeg", "image/jpeg"
    raise OSError("offline")


class PosterTest(unittest.TestCase):
    def setUp(self):
        self.store = Store(":memory:")
        self.p = posters.Posters(self.store, tempfile.mkdtemp())
        self.get = mock.patch.object(posters, "get", fake_get)
        self.get.start()

    def tearDown(self):
        self.get.stop()

    def test_matching(self):
        self.assertEqual(posters.movie_image("Glass Onion: A Knives Out Mystery"), "https://upload.wikimedia.org/glass.jpg")
        self.assertEqual(posters.movie_image("Mission: Impossible - Dead Reckoning"), "https://upload.wikimedia.org/mi.jpg")
        self.assertIsNone(posters.movie_image("Dune"))  # only the novel: no poster beats the wrong one
        self.assertEqual(posters.show_image("the crown"), "https://static.tvmaze.com/crown.jpg")
        self.assertIsNone(posters.show_image("The Crowd"))

    def test_fetch_and_cache(self):
        self.store.add({"title": "The Crown", "kind": "show", "service": "Netflix", "watched_on": "2026-10-01"})
        self.store.add({"title": "Dune", "service": "Max", "watched_on": "2026-10-02"})
        self.assertTrue(self.p.run_once())   # Dune first (newest): none found
        self.assertTrue(self.p.run_once())   # The Crown
        self.assertFalse(self.p.run_once())  # nothing left
        got = {w["title"]: w["poster"] for w in self.store.all()}
        self.assertIsNone(got["Dune"])
        name = got["The Crown"]
        self.assertTrue(os.path.exists(self.p.path(name)))
        self.assertIsNone(self.p.path("../../etc/passwd"))

    def test_errors_retry_and_remove(self):
        self.store.add({"title": "The Crown", "kind": "show", "service": "Netflix"})
        with mock.patch.object(posters, "get", side_effect=OSError("offline")):
            self.assertTrue(self.p.run_once())
        self.assertFalse(self.p.run_once())  # an error waits an hour
        self.store.forget_poster("The Crown", "show")
        self.assertTrue(self.p.run_once())
        self.assertIsNotNone(self.store.all()[0]["poster"])
        self.store.set_poster("The Crown", "show", None, removed=True)
        self.assertIsNone(self.store.all()[0]["poster"])
        self.assertIsNone(self.store.poster_todo("9999-12-31"))  # removed: never looked up again


if __name__ == "__main__":
    unittest.main()
