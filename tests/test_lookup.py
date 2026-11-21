import unittest
import urllib.error
from unittest import mock

from watchlog import lookup

WIKIPEDIA = {"query": {"pages": [
    {"index": 1, "title": "Old (film)", "description": "2021 film by M. Night Shyamalan"},
    {"index": 2, "title": "Old Yeller (film)", "description": "1957 American film"},
    {"index": 3, "title": "2021 in film", "description": ""},
    {"index": 4, "title": "Glass (2019 film)", "description": "Film by M. Night Shyamalan"},
    {"index": 5, "title": "M. Night Shyamalan", "description": "American film director (born 1970)"}]}}
TVMAZE = [{"show": {"name": "Severance", "premiered": "2022-02-18", "webChannel": {"name": "Apple TV"}, "network": None}},
          {"show": {"name": "La Rivière Espérance", "premiered": "1995-09-04", "webChannel": None, "network": {"name": "France 2"}}}]
WIKIDATA = {"search": [{"label": "Severance", "description": "2006 film directed by Christopher Smith"},
                       {"label": "Severance", "description": "film series"},
                       {"label": "Severance Pay", "description": "Wikimedia disambiguation page"}]}


def fake(url):
    if "wikipedia.org" in url:
        return WIKIPEDIA
    if "tvmaze" in url:
        return TVMAZE
    if "wikidata" in url:
        return WIKIDATA
    raise OSError("offline")


class LookupTest(unittest.TestCase):
    def setUp(self):
        lookup._cache.clear()

    def test_search(self):
        with mock.patch.object(lookup, "get_json", fake):
            self.assertEqual([(r["title"], r["kind"], r["year"], r["service"]) for r in lookup.search("sever")],
                             [("Severance", "show", "2022", "Apple TV+"), ("Severance", "movie", "2006", None)])

    def test_wikipedia_movies(self):
        with mock.patch.object(lookup, "get_json", fake):
            self.assertEqual([(r["title"], r["year"], r["where"]) for r in lookup.wiki_movies("old")],
                             [("Old", "2021", "film by M. Night Shyamalan"), ("Old Yeller", "1957", "American film"),
                              ("Glass", "2019", "Film by M. Night Shyamalan")])

    def test_year_in_search(self):
        with mock.patch.object(lookup, "get_json", fake):
            self.assertEqual([(r["title"], r["year"]) for r in lookup.search("old 2021")], [("Old", "2021")])

    def test_rate_limited_source_pauses(self):
        def limited(url):
            if "wikipedia.org" in url:
                raise urllib.error.HTTPError(url, 429, "Too Many Requests", {"Retry-After": "20"}, None)
            return fake(url)
        lookup._paused.clear()
        with mock.patch.object(lookup, "get_json", limited):
            self.assertEqual([r["title"] for r in lookup.search("sever")], ["Severance", "Severance"])
        self.assertIn("wikipedia", lookup._paused)
        calls = []
        with mock.patch.object(lookup, "get_json", lambda url: calls.append(url) or fake(url)):
            lookup.search("severanc")
        self.assertFalse(any("wikipedia.org" in u for u in calls))
        lookup._paused.clear()

    def test_offline_is_empty_and_not_cached(self):
        with mock.patch.object(lookup, "get_json", side_effect=OSError("offline")):
            self.assertEqual(lookup.search("dune"), [])
        self.assertEqual(lookup._cache, {})

    def test_too_short(self):
        self.assertEqual(lookup.search(" d "), [])


if __name__ == "__main__":
    unittest.main()
