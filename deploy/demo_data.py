#!/usr/bin/env python3
"""Fill a database with made-up titles, for trying the dashboard or taking screenshots
without showing anyone's real watch history.

    python3 deploy/demo_data.py /tmp/demo.db
    python3 -m watchlog --db /tmp/demo.db --no-posters
"""
import datetime
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from watchlog.store import Store  # noqa: E402

# (title, kind, episode, service, days ago, rating, did not see the end, who, notes)
DEMO = [
    ("The Lighthouse Keepers", "show", "S2 · 8 episodes", "Netflix", 1, 4.5, 0, "both", "Finale was worth it"),
    ("Midnight at the Diner", "movie", None, "Max", 2, 3.5, 1, "both", None),
    ("Orbit of Small Things", "movie", None, "Apple TV+", 4, 5, 0, "both", "Watch again with the kids"),
    ("Cold Case Kitchen", "show", "S1 · 6 episodes", "Peacock", 6, 3, 0, "p2", None),
    ("Paper Moon Harbor", "movie", None, "Paramount+", 9, 2.5, 2, "both", "Too slow"),
    ("Station Eleven Below", "show", "S1–S2 · 14 episodes", "Max", 12, 4, 0, "both", None),
    ("The Quiet Heist", "movie", None, "Netflix", 15, 4, 1, "both", None),
    ("Backyard Astronomers", "show", "S3: The Comet", "Disney+", 18, 3.5, 0, "p1", None),
    ("Summer of the Red Kite", "movie", None, "Prime Video", 21, None, 0, "both", None),
    ("Iron Valley", "show", "S1 · 10 episodes", "Netflix", 25, 4.5, 0, "both", "Season 2 when it's out"),
    ("A Very Long Weekend", "movie", None, "Hulu", 30, 3, 2, "both", None),
    ("The Glass Orchard", "movie", None, "Apple TV+", 34, 4, 0, "p2", None),
    ("Tides of Marrow Bay", "show", "S1 · 4 episodes", "Peacock", 40, None, 1, "both", None),
    ("Last Train to Fairhaven", "movie", None, "Max", 46, 5, 0, "both", None),
    ("Weekend Mechanics", "show", "S5 · 12 episodes", "YouTube", 52, 3.5, 0, "p1", None),
    ("The Velvet Static", "movie", None, "Netflix", 60, 2, 2, "both", "Fell flat"),
]


def main(path):
    if os.path.exists(path):
        sys.exit(f"{path} already exists; pick a new file so nothing real is overwritten")
    store, today = Store(path), datetime.date.today()
    for title, kind, episode, service, ago, rating, sleep, who, notes in DEMO:
        store.add({"title": title, "kind": kind, "episode": episode, "service": service,
                   "watched_on": (today - datetime.timedelta(days=ago)).isoformat(), "rating": rating,
                   "wife_asleep": sleep, "who": who, "notes": notes})
    print(f"{len(DEMO)} made-up entries in {path}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "demo.db")
