"""Title search for the add form: TVmaze for shows; Wikipedia and Wikidata for
movies (Wikipedia's search finds whole words like "old", Wikidata's finds
half-typed ones like "dune par"). All free, no API key. Failures just mean
fewer suggestions. A year in the search ("old 2021") picks that year's titles."""
import concurrent.futures
import json
import logging
import re
import time
import urllib.error
import urllib.parse
import urllib.request

log = logging.getLogger("watchlog")
UA = "watchlog/1.0 (home watch log dashboard)"
TIMEOUT = 4
# Wikidata descriptions like "2021 film directed by Denis Villeneuve" or
# "2023 American comedy-drama film"; not "film series" or "film director"
FILM = re.compile(r"^(\d{4})\b.*\bfilm\b(?! series)")
# Wikipedia page titles like "Old (film)" or "Dune (2021 film)"; descriptions like
# "2021 film by M. Night Shyamalan" or "Film by James Bobin" (not "film director")
PAGE = re.compile(r"^(.*?)(?: \((?:(\d{4}) )?(?:[\w-]+ )?film\))?$")
WIKI_FILM = re.compile(r"\bfilm\b(?! (?:series|director|producer|critic|studio|festival|award|score))", re.I)
YEAR = re.compile(r"\b(19\d{2}|20\d{2})\b")
# TVmaze network / web channel name -> our service names
SERVICES = {
    "netflix": "Netflix", "hbo": "Max", "hbo max": "Max", "max": "Max",
    "apple tv": "Apple TV+", "apple tv+": "Apple TV+", "peacock": "Peacock",
    "paramount+": "Paramount+", "paramount plus": "Paramount+", "hulu": "Hulu",
    "disney+": "Disney+", "prime video": "Prime Video", "amazon prime video": "Prime Video",
    "amazon": "Prime Video", "youtube": "YouTube", "youtube premium": "YouTube",
}
_cache = {}
_paused = {}  # source -> time.time() it may be asked again, after "too many requests"


def get_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return json.load(r)


def shows(q):
    out = []
    for r in get_json("https://api.tvmaze.com/search/shows?q=" + urllib.parse.quote(q))[:6]:
        s = r["show"]
        channel = (s.get("webChannel") or s.get("network") or {}).get("name") or ""
        out.append({"title": s["name"], "kind": "show", "year": (s.get("premiered") or "")[:4] or None,
                    "service": SERVICES.get(channel.lower()), "where": channel or None})
    return out


def wiki_movies(q):
    """Wikipedia full-text search; q may include a year."""
    url = "https://en.wikipedia.org/w/api.php?" + urllib.parse.urlencode({
        "action": "query", "format": "json", "formatversion": 2, "generator": "search",
        "gsrsearch": q + " film", "gsrlimit": 15, "prop": "description"})
    out = []
    for p in sorted(get_json(url).get("query", {}).get("pages", []), key=lambda p: p.get("index", 99)):
        desc = p.get("description") or ""
        name, paren_year = PAGE.match(p["title"]).groups()
        if "(" in name or not WIKI_FILM.search(desc):  # "(novel)", "(band)", people, "2021 in film" ...
            continue
        year = paren_year or (YEAR.search(desc) or [None])[0]
        out.append({"title": name, "kind": "movie", "year": year, "service": None,
                    "where": YEAR.sub("", desc, count=1).strip() or None})
    return out[:8]


def movies(q):
    url = ("https://www.wikidata.org/w/api.php?action=wbsearchentities&type=item&language=en"
           "&uselang=en&limit=20&format=json&search=" + urllib.parse.quote(q))
    out = []
    for r in get_json(url).get("search", []):
        m = FILM.match(r.get("description") or "")
        if m and r.get("label"):
            out.append({"title": r["label"], "kind": "movie", "year": m[1], "service": None,
                        "where": r["description"][len(m[1]):].strip()})
    return out[:6]


_shows = {}


def is_show(name):
    """Does TVmaze have a show with exactly this name? Cached; False when offline.
    Paced to stay inside TVmaze's 20 calls per 10 seconds."""
    key = " ".join(re.findall(r"\w+", name.lower()))
    if key not in _shows:
        try:
            time.sleep(0.6)
            found = get_json("https://api.tvmaze.com/search/shows?q=" + urllib.parse.quote(name))[:5]
            _shows[key] = any(" ".join(re.findall(r"\w+", r["show"]["name"].lower())) == key for r in found)
        except Exception as e:
            log.warning("TVmaze lookup for %r failed: %s", name, e)
            return False
    return _shows[key]


def norm(title):
    return " ".join(re.findall(r"\w+", title.lower()))


def search(q):
    q = " ".join(q.split())[:100]
    if len(q) < 2:
        return []
    key = q.lower()
    if key in _cache:
        return _cache[key]
    year = (YEAR.search(q) or [None])[0]
    words_q = " ".join(YEAR.sub(" ", q).split()) or q  # the title part, for TVmaze and Wikidata
    sources = (("shows", shows, words_q), ("wikipedia", wiki_movies, q), ("wikidata", movies, words_q))
    results = {name: [] for name, _, _ in sources}
    live = [(name, fn, arg) for name, fn, arg in sources if _paused.get(name, 0) <= time.time()]
    ok = len(live) == len(sources)
    with concurrent.futures.ThreadPoolExecutor(3) as pool:
        futures = {pool.submit(fn, arg): name for name, fn, arg in live}
        for f in concurrent.futures.as_completed(futures):
            name = futures[f]
            try:
                results[name] = f.result()
            except urllib.error.HTTPError as e:
                if e.code == 429:  # rate limited: leave this source alone for as long as it asks
                    after = str(e.headers.get("Retry-After") or "")
                    _paused[name] = time.time() + (int(after) if after.isdigit() else 60)
                log.warning("title search (%s) failed: %s", name, e)
                ok = False
            except Exception as e:  # offline, slow, or the API changed
                log.warning("title search (%s) failed: %s", name, e)
                ok = False
    seen, film_rows = set(), []
    for r in results["wikipedia"] + results["wikidata"]:
        if (norm(r["title"]), r["year"]) not in seen:
            seen.add((norm(r["title"]), r["year"]))
            film_rows.append(r)
    results = {"shows": results["shows"], "movies": film_rows}
    # all three are fuzzy; keep titles whose words start with what was typed,
    # unless that leaves nothing at all (then a typo still finds something)
    words = re.findall(r"\w+", words_q.lower())
    close = {name: [r for r in rows
                    if all(any(t.startswith(w) for t in re.findall(r"\w+", r["title"].lower())) for w in words)]
             for name, rows in results.items()}
    if any(close.values()):
        results = close
    if year:  # "old 2021": that year's titles, if there are any
        same = {name: [r for r in rows if r["year"] == year] for name, rows in results.items()}
        if any(same.values()):
            results = same
    results = {name: rows[:6] for name, rows in results.items()}
    # interleave so both kinds show up near the top
    merged = [x for pair in zip(results["shows"], results["movies"]) for x in pair]
    n = min(len(results["shows"]), len(results["movies"]))
    merged += results["shows"][n:] + results["movies"][n:]
    if ok:
        if len(_cache) > 500:
            _cache.clear()
        _cache[key] = merged
    return merged
