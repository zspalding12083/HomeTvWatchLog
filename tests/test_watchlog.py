import datetime as dt
import http.client
import json
import threading
import unittest
from http.server import ThreadingHTTPServer

from watchlog.server import make_handler
from watchlog.store import SCHEMA, Store, clean, episode_label


class CleanTest(unittest.TestCase):
    def test_defaults(self):
        w = clean({"title": " Dune ", "service": "Max"})
        self.assertEqual(w["title"], "Dune")
        self.assertEqual(w["kind"], "movie")
        self.assertEqual(w["watched_on"], dt.date.today().isoformat())
        self.assertIsNone(w["rating"])
        self.assertEqual(w["wife_asleep"], 0)

    def test_episode_only_for_shows(self):
        self.assertIsNone(clean({"title": "x", "service": "Max", "episode": "S1E1"})["episode"])
        self.assertEqual(clean({"title": "x", "kind": "show", "service": "Max", "episode": "S1E1"})["episode"], "S1E1")

    def test_rejects_bad_input(self):
        for bad in ({"service": "Max"}, {"title": "x"}, {"title": "x", "service": "Max", "rating": 6},
                    {"title": "x", "service": "Max", "rating": 3.3}, {"title": "x", "service": "Max", "wife_asleep": 3},
                    {"title": "x", "service": "Max", "kind": "book"}, {"title": "x", "service": "Max", "watched_on": "soon"}):
            with self.assertRaises(ValueError, msg=bad):
                clean(bad)


class EpisodeLabelTest(unittest.TestCase):
    def test_labels(self):
        self.assertIsNone(episode_label([]))
        self.assertEqual(episode_label(["S2: Woe's Hollow"]), "S2: Woe's Hollow")
        self.assertEqual(episode_label(["S1: a", "S2: b", "S3: c"]), "S1–S3 · 3 episodes")
        self.assertEqual(episode_label(["S1: a", "S3: c"]), "S1, S3 · 2 episodes")
        self.assertEqual(episode_label(["Limited Series: Episode 1", "Limited Series: Episode 2"]),
                         "Limited Series · 2 episodes")


class StoreTest(unittest.TestCase):
    def setUp(self):
        self.s = Store(":memory:")

    def test_crud(self):
        w = self.s.add({"title": "Dune", "service": "Max", "rating": 4.5, "wife_asleep": 2})
        self.assertEqual(self.s.get(w["id"])["rating"], 4.5)
        self.s.update(w["id"], {**w, "rating": 5})
        self.assertEqual(self.s.get(w["id"])["rating"], 5)
        self.assertTrue(self.s.delete(w["id"]))
        self.assertIsNone(self.s.update(w["id"], w))
        self.assertEqual(self.s.all(), [])

    def test_add_existing_title_updates_it(self):
        first = self.s.add({"title": "Severance", "kind": "show", "episode": "S2E3", "service": "Apple TV+",
                            "watched_on": "2026-10-20", "rating": 4, "notes": "creepy"})
        again = self.s.add({"title": "severance", "kind": "show", "episode": "S2E4", "service": "Apple TV+",
                            "watched_on": "2026-10-24", "wife_asleep": 1})
        self.assertTrue(again["merged"])
        self.assertEqual(len(self.s.all()), 1)
        w = self.s.get(first["id"])
        self.assertEqual((w["watched_on"], w["episode"], w["rating"], w["wife_asleep"], w["notes"]),
                         ("2026-10-24", "S2E4", 4, 1, "creepy"))
        # same title as a movie is a different entry
        self.s.add({"title": "Severance", "service": "Max"})
        self.assertEqual(len(self.s.all()), 2)

    def test_old_database_is_merged(self):
        import os, sqlite3, tempfile
        path = os.path.join(tempfile.mkdtemp(), "old.db")
        db = sqlite3.connect(path)
        db.executescript(SCHEMA.replace(",\n    episode_list TEXT", ""))
        rows = [("Dune", "movie", None, "Netflix", "2024-03-01", None, 0, None),
                ("Dune", "movie", None, "Netflix", "2025-01-01", 4.5, 2, "again"),
                ("DS9", "show", "S1 · 3 episodes", "Netflix", "2020-01-01", None, 0, None),
                ("DS9", "show", "S2 · 2 episodes", "Netflix", "2020-02-01", None, 1, None),
                ("Glass Onion", "movie", None, "Netflix", "2023-01-01", None, 0, None)]
        db.executemany("INSERT INTO watches (title, kind, episode, service, watched_on, rating, wife_asleep, notes, "
                       "created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'x')", rows)
        db.commit()
        db.close()
        got = {w["title"]: w for w in Store(path).all()}
        self.assertEqual(sorted(got), ["DS9", "Dune", "Glass Onion"])
        self.assertEqual((got["Dune"]["watched_on"], got["Dune"]["rating"], got["Dune"]["wife_asleep"], got["Dune"]["notes"]),
                         ("2025-01-01", 4.5, 2, "again"))
        self.assertEqual((got["DS9"]["episode"], got["DS9"]["wife_asleep"]), ("S2 · 2 episodes", 1))
        self.assertEqual(len(Store(path).all()), 3)  # runs once; opening again changes nothing

    def test_stats(self):
        today = dt.date(2026, 10, 27)
        self.s.add({"title": "Dune", "service": "Max", "rating": 4, "watched_on": "2026-10-01", "wife_asleep": 1})
        self.s.add({"title": "Severance", "kind": "show", "service": "Apple TV+", "watched_on": "2026-10-02"})
        self.s.add({"title": "Severance", "kind": "show", "service": "Apple TV+", "watched_on": "2026-09-30", "rating": 5})
        st = self.s.stats(today)  # the two Severance watches are one entry
        self.assertEqual((st["total"], st["this_month"], st["movies"], st["shows"], st["asleep"]), (2, 2, 1, 1, 1))
        self.assertEqual(st["avg_rating"], 4.5)
        self.assertIn({"service": "Max", "count": 1, "asleep": 1, "avg_rating": 4.0}, st["services"])
        self.assertEqual([t["title"] for t in self.s.titles()], ["Dune", "Severance"])


class ApiTest(unittest.TestCase):
    def setUp(self):
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(Store(":memory:")))
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()

    def call(self, method, path, body=None):
        c = http.client.HTTPConnection("127.0.0.1", self.httpd.server_port)
        c.request(method, path, body and json.dumps(body), {"Content-Type": "application/json"})
        r = c.getresponse()
        data = r.read()
        return r.status, json.loads(data) if r.headers["Content-Type"] == "application/json" else data

    def test_round_trip(self):
        status, w = self.call("POST", "/api/watches", {"title": "Dune", "service": "Max", "wife_asleep": 2})
        self.assertEqual(status, 201)
        self.assertEqual(self.call("PUT", f"/api/watches/{w['id']}", {**w, "rating": 3})[1]["rating"], 3)
        self.assertEqual(self.call("GET", "/api/summary")[1]["stats"]["asleep"], 1)
        self.assertEqual(self.call("DELETE", f"/api/watches/{w['id']}")[0], 200)
        self.assertEqual(self.call("DELETE", f"/api/watches/{w['id']}")[0], 404)

    def test_errors_and_page(self):
        self.assertEqual(self.call("POST", "/api/watches", {"service": "Max"}), (400, {"error": "title is required"}))
        self.assertEqual(self.call("PUT", "/api/watches/99", {"title": "x", "service": "Max"})[0], 404)
        status, page = self.call("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn(b"Watch Log", page)


if __name__ == "__main__":
    unittest.main()
