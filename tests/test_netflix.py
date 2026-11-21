import unittest
from unittest import mock

from watchlog import netflix
from watchlog.store import Store

US = '''﻿Title,Date
"Severance: Season 2: Woe's Hollow","10/24/26"
"Severance: Season 2: Who Is Alive?","10/24/26"
"Severance: Season 1: Good News About Hell","10/23/26"
"Mission: Impossible - Dead Reckoning","10/20/26"
"Baby Reindeer: Limited Series: Episode 1","10/19/26"
"Glass Onion: A Knives Out Mystery","9/28/26"
"Glass Onion: A Knives Out Mystery","1/2/23"
'''
# the other profile: one shared episode, one of her own, and a newer Glass Onion rewatch
WIFE = '''Title,Date
"Severance: Season 2: Who Is Alive?","10/24/26"
"Severance: Season 2: Cold Harbor","10/26/26"
"Glass Onion: A Knives Out Mystery","10/25/26"
'''


class ParseTest(unittest.TestCase):
    def test_split_title(self):
        self.assertEqual(netflix.split_title("Severance: Season 2: Woe's Hollow"), ("Severance", "show", "S2: Woe's Hollow"))
        self.assertEqual(netflix.split_title("Baby Reindeer: Limited Series: Episode 1"),
                         ("Baby Reindeer", "show", "Limited Series: Episode 1"))
        self.assertEqual(netflix.split_title("Mission: Impossible - Dead Reckoning"),
                         ("Mission: Impossible - Dead Reckoning", "movie", None))

    def test_one_row_per_title(self):
        rows = netflix.parse(US)
        self.assertEqual([(r["title"], r["watched_on"]) for r in rows], [
            ("Severance", "2026-10-24"), ("Mission: Impossible - Dead Reckoning", "2026-10-20"),
            ("Baby Reindeer", "2026-10-19"), ("Glass Onion: A Knives Out Mystery", "2026-09-28")])
        self.assertEqual(rows[0]["episode"], "S1–S2 · 3 episodes")
        self.assertEqual(rows[2]["episode"], "Limited Series: Episode 1")
        self.assertTrue(all(r["service"] == "Netflix" for r in rows))

    def test_dates(self):
        self.assertEqual([d.isoformat() for d in netflix.parse_dates(["24/10/2026", "3/10/2026"])], ["2026-10-24", "2026-10-03"])
        self.assertEqual([d.isoformat() for d in netflix.parse_dates(["3/10/26"])], ["2026-03-10"])
        self.assertEqual([d.isoformat() for d in netflix.parse_dates(["2026-10-03"])], ["2026-10-03"])

    def test_wrong_file(self):
        for bad in ("", "Name,When\nx,1/1/26\n"):
            with self.assertRaises(ValueError):
                netflix.parse(bad)


class FindShowsTest(unittest.TestCase):
    TVMAZE = {"star trek prodigy", "american horror story"}

    def is_show(self, name):
        return netflix.norm_name(name) in self.TVMAZE

    def test_episodes_without_seasons(self):
        found = netflix.find_shows([
            "Scrubs: My Last Day", "Scrubs: My Old Man", "Star Trek: Prodigy: Mindwalk", "Star Trek: Prodigy: Supernova",
            "American Horror Story: Murder House: Pilot", "American Horror Story: 1984: Red Dawn",
            "Doctor Who: Blink", "Glass Onion: A Knives Out Mystery", ": Episode 9", ": Episode 5"],
            known_shows=["Doctor Who"], is_show=self.is_show)
        self.assertEqual(found, {
            "Scrubs: My Last Day": ("Scrubs", "My Last Day"), "Scrubs: My Old Man": ("Scrubs", "My Old Man"),
            "Star Trek: Prodigy: Mindwalk": ("Star Trek: Prodigy", "Mindwalk"),
            "Star Trek: Prodigy: Supernova": ("Star Trek: Prodigy", "Supernova"),
            "American Horror Story: Murder House: Pilot": ("American Horror Story", "Murder House: Pilot"),
            "American Horror Story: 1984: Red Dawn": ("American Horror Story", "1984: Red Dawn"),
            "Doctor Who: Blink": ("Doctor Who", "Blink")})

    def test_parse_uses_it(self):
        rows = netflix.parse('Title,Date\n"Scrubs: My Last Day","1/2/24"\n"Scrubs: Season 2: My Overkill","1/1/24"\n'
                             '"Scrubs: My Old Man","1/3/24"\n"Dune","1/1/24"\n')
        self.assertEqual([(r["title"], r["kind"], r["episode"]) for r in rows],
                         [("Scrubs", "show", "3 episodes"), ("Dune", "movie", None)])

    def test_repair(self):
        s = Store(":memory:")
        s.add({"title": "Scrubs", "kind": "show", "service": "Netflix", "episode": "S2: My Overkill", "watched_on": "2024-01-01"})
        s.add({"title": "Scrubs: My Last Day", "service": "Netflix", "watched_on": "2024-01-05", "rating": 4, "wife_asleep": 2})
        s.add({"title": "Tiger King: Playing with Fire", "service": "Netflix", "watched_on": "2024-02-01"})
        s.add({"title": "Tiger King: The Noble Thing", "service": "Netflix", "watched_on": "2024-02-02", "notes": "wild"})
        s.add({"title": "Mission: Impossible - Dead Reckoning", "service": "Netflix"})
        self.assertEqual(netflix.repair(s), 3)
        got = {w["title"]: w for w in s.all()}
        self.assertEqual(sorted(got), ["Mission: Impossible - Dead Reckoning", "Scrubs", "Tiger King"])
        self.assertEqual((got["Scrubs"]["rating"], got["Scrubs"]["wife_asleep"], got["Scrubs"]["watched_on"]), (4, 2, "2024-01-05"))
        self.assertEqual((got["Tiger King"]["kind"], got["Tiger King"]["notes"], got["Tiger King"]["episode"]),
                         ("show", "wild", "2 episodes"))
        self.assertEqual(netflix.repair(s), 0)


class WhoTest(unittest.TestCase):
    def test_profiles_combine(self):
        s = Store(":memory:")
        mine = [{**r, "who": "p1"} for r in netflix.parse(US)]
        hers = [{**r, "who": "p2"} for r in netflix.parse(WIFE)]
        s.import_many(mine)
        self.assertEqual([s.import_status(r) for r in hers], ["update", "update"])
        s.import_many(hers)
        who = {w["title"]: w["who"] for w in s.all()}
        self.assertEqual(who["Severance"], "both")
        self.assertEqual(who["Glass Onion: A Knives Out Mystery"], "both")
        self.assertEqual(who["Baby Reindeer"], "p1")
        # re-importing just to record whose profile: an update even with nothing else new
        s2 = Store(":memory:")
        s2.import_many(netflix.parse(WIFE))
        self.assertEqual([s2.import_status(r) for r in hers], ["update", "update"])
        s2.import_many(hers)
        self.assertEqual({w["who"] for w in s2.all()}, {"p2"})

    def test_manual(self):
        s = Store(":memory:")
        s.add({"title": "Dune", "service": "Max", "who": "p2"})
        self.assertEqual(s.add({"title": "Dune", "service": "Max", "who": "p1"})["who"], "both")
        with self.assertRaises(ValueError):
            s.add({"title": "x", "service": "Max", "who": "bob"})


class ImportTest(unittest.TestCase):
    def test_two_profiles_merge(self):
        s = Store(":memory:")
        s.add({"title": "severance", "service": "Netflix", "kind": "show", "watched_on": "2026-10-01", "rating": 5})
        self.assertEqual(s.import_many(netflix.parse(US)), {"added": 3, "updated": 1})
        self.assertEqual(s.import_many(netflix.parse(US)), {"added": 0, "updated": 0})
        wife = netflix.parse(WIFE)
        self.assertEqual([s.import_status(r) for r in wife], ["update", "update"])
        self.assertEqual(s.import_many(wife), {"added": 0, "updated": 2})
        got = {w["title"]: w for w in s.all()}
        self.assertEqual(len(got), 4)
        sev = got["severance"]
        self.assertEqual((sev["watched_on"], sev["episode"], sev["rating"]), ("2026-10-26", "S1–S2 · 4 episodes", 5))
        self.assertEqual(got["Glass Onion: A Knives Out Mystery"]["watched_on"], "2026-10-25")
        self.assertEqual([s.import_status(r) for r in wife], ["logged", "logged"])


if __name__ == "__main__":
    unittest.main()
