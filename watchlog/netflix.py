"""Netflix "Viewing activity" CSV (Account > Profile > Viewing activity > Download all).

The file has two columns, Title and Date. Episodes look like
"Show: Season 2: Episode Name"; movies are just the title. The date is in the
account's locale, e.g. 10/24/26 in the US or 24/10/2026 elsewhere.
"""
import csv
import datetime as dt
import io
import re

from . import lookup
from .store import episode_label

# "Show: Season 2: Episode", "Show: Limited Series: Episode", "Show: Part 1: Episode" ...
EPISODE = re.compile(
    r"^(?P<show>.+?): (?P<season>(?:Season|Series|Part|Volume|Book|Chapter|Collection) \d+"
    r"|Limited Series|Miniseries|Season \w+)(?:: (?P<ep>.*))?$")
SEASON_NO = re.compile(r"^(?:Season|Series) (\d+)$")


def parse_dates(raw):
    """Parse every date in the file the same way: day-first only if some first
    field can't be a month."""
    parts = [re.split(r"[/.-]", d.strip()) for d in raw]
    if all(len(p) == 3 and len(p[0]) == 4 for p in parts):
        return [dt.date(int(y), int(m), int(d)) for y, m, d in parts]
    day_first = any(int(p[0]) > 12 for p in parts if len(p) == 3)
    out = []
    for p in parts:
        if len(p) != 3:
            raise ValueError(f"can't read date {'/'.join(p)!r}")
        a, b, y = (int(x) for x in p)
        y += 2000 if y < 100 else 0
        out.append(dt.date(y, b, a) if day_first else dt.date(y, a, b))
    return out


def split_title(title):
    """('Severance', 'show', 'S2: Woe's Hollow') or ('Dune', 'movie', None)."""
    m = EPISODE.match(title)
    if not m:
        return title, "movie", None
    season = m["season"]
    n = SEASON_NO.match(season)
    label = f"S{n[1]}" if n else season
    return m["show"], "show", f"{label}: {m['ep']}" if m["ep"] else label


def find_shows(titles, known_shows=(), is_show=lookup.is_show):
    """Netflix also writes episodes without a season: 'Scrubs: My Last Day',
    'American Horror Story: Murder House: Pilot'. A name that two or more titles
    start with is a show (or one of known_shows). For nested names, the longest
    one TVmaze knows as a show wins ('Star Trek: Prodigy', but 'American Horror
    Story' rather than '...: Murder House'); without TVmaze, the shortest.
    Returns {title: (show, episode)} for the titles that are episodes."""
    titles = {t for t in titles if ": " in t}
    known = {norm_name(s) for s in known_shows}
    count = {}
    for t in titles:
        parts = t.split(": ")
        for k in range(1, len(parts)):
            p = ": ".join(parts[:k])
            count[p] = count.get(p, 0) + 1
    out = {}
    for t in titles:
        parts = t.split(": ")
        if not parts[0].strip():
            continue
        prefixes = [": ".join(parts[:k]) for k in range(len(parts) - 1, 0, -1)]  # longest first
        shows = [p for p in prefixes if count[p] >= 2 or norm_name(p) in known]
        if not shows:
            continue
        pick = next((p for p in shows if norm_name(p) in known), None)
        if pick is None:
            nested = [p for p in shows if ": " in p]
            pick = next((p for p in nested if is_show(p)), shows[-1])
        out[t] = (pick, t[len(pick) + 2:])
    return out


def repair(store):
    """Fold Netflix episodes that were logged as movies (before find_shows existed)
    into their shows. Returns how many entries were folded."""
    rows = store.all()
    shows = [w["title"] for w in rows if w["kind"] == "show"]
    movies = {w["title"]: w["id"] for w in rows if w["kind"] == "movie" and w["service"] == "Netflix"}
    found = find_shows(movies, shows)
    for title, (show, episode) in found.items():
        store.fold_into_show(movies[title], show, episode)
    return len(found)


def norm_name(name):
    return " ".join(re.findall(r"\w+", name.lower()))


def parse(text):
    """One row per title, newest first: its latest date and, for a show, the list
    of episodes watched (Store.import_many merges these into existing entries)."""
    rows = [r for r in csv.reader(io.StringIO(text.lstrip("\ufeff"))) if r and any(c.strip() for c in r)]
    if not rows:
        raise ValueError("the file is empty")
    if [c.strip().lower() for c in rows[0][:2]] != ["title", "date"]:
        raise ValueError("not a Netflix viewing activity file (expected Title and Date columns)")
    rows = rows[1:]
    dates = parse_dates([r[1] for r in rows])
    split = {}
    for r in rows:
        split.setdefault(r[0].strip(), split_title(r[0].strip()))
    known = {t for t, k, _ in split.values() if k == "show"}
    for raw, (show, episode) in find_shows([t for t, (_, k, _) in split.items() if k == "movie"], known).items():
        split[raw] = (show, "show", episode)
    titles = {}
    for r, day in zip(rows, dates):
        title, kind, episode = split[r[0].strip()]
        w = titles.setdefault((title.lower(), kind), {
            "title": title, "kind": kind, "service": "Netflix", "watched_on": "", "episodes": []})
        w["watched_on"] = max(w["watched_on"], day.isoformat())
        if episode and episode not in w["episodes"]:
            w["episodes"].append(episode)
    out = sorted(titles.values(), key=lambda w: w["watched_on"], reverse=True)
    for w in out:
        w["episode"] = episode_label(w["episodes"])
    return out
