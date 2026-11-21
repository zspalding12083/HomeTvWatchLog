"""Poster images, cached on disk: Wikipedia (movies) and TVmaze (shows).

A background thread works through titles that have no poster yet, newest
watches first, one lookup at a time so both sites see a gentle trickle. Only
an exact title match is accepted: no poster beats the wrong one. Titles with
none found are retried after RETRY_DAYS.
"""
import datetime as dt
import hashlib
import json
import logging
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from .store import norm, poster_key

log = logging.getLogger("watchlog")
UA = "watchlog/1.0 (home watch log dashboard)"
TIMEOUT = 10
MAX_BYTES = 3 * 1024 * 1024
IMAGE_HOSTS = ("upload.wikimedia.org", "thumb.wikimedia.org", "static.tvmaze.com")
PAUSE = 1.5          # seconds between titles
BACKOFF = 120        # after "too many requests" / "unavailable"
RETRY_DAYS = 30
FILENAME = re.compile(r"^[0-9a-f]{20}\.(jpg|png|webp)$")


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return r.read(MAX_BYTES + 1), r.headers.get("Content-Type", "")


def get_json(url):
    return json.loads(get(url)[0])


def movie_image(title):
    q = urllib.parse.urlencode({
        "action": "query", "format": "json", "formatversion": 2, "generator": "search",
        "gsrsearch": f"{title} film", "gsrlimit": 5, "prop": "pageimages", "piprop": "thumbnail",
        "pithumbsize": 342, "pilicense": "any"})
    pages = sorted(get_json("https://en.wikipedia.org/w/api.php?" + q).get("query", {}).get("pages", []),
                   key=lambda p: p.get("index", 99))
    want = norm(title)
    films = []
    for p in pages:
        # "Dune (2021 film)" -> "Dune"; skip "(franchise)", "(film series)", "(novel)" ...
        name, paren = re.match(r"^(.*?)(?: \(([^)]*)\))?$", p["title"]).groups()
        if (paren is None or re.fullmatch(r"(\d{4} )?(\w+ )?film", paren)) and p.get("thumbnail"):
            films.append((norm(name), p["thumbnail"]["source"]))
    for name, src in films:
        if name == want:
            return src
    # Netflix sometimes drops a subtitle: "...Dead Reckoning" is "...Dead Reckoning Part One"
    for name, src in films:
        if name.startswith(want + " ") and len(name.split()) - len(want.split()) <= 3:
            return src
    return None


def show_image(title):
    want = norm(title)
    for r in get_json("https://api.tvmaze.com/search/shows?q=" + urllib.parse.quote(title))[:5]:
        s = r["show"]
        if norm(s["name"]) == want and s.get("image"):
            return s["image"].get("medium") or s["image"].get("original")
    return None


class Posters:
    def __init__(self, store, folder):
        self.store, self.folder = store, folder
        os.makedirs(folder, exist_ok=True)
        self.wake = threading.Event()

    def path(self, name):
        return os.path.join(self.folder, name) if FILENAME.match(name) else None

    def fetch(self, title, kind):
        """Look up and save one poster; returns the file name or None."""
        url = (show_image if kind == "show" else movie_image)(title)
        if not url:
            return None
        host = urllib.parse.urlsplit(url).hostname
        if host not in IMAGE_HOSTS:
            log.warning("poster for %r is on an unexpected host %s; skipped", title, host)
            return None
        data, ctype = get(url)
        ext = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}.get(ctype.split(";")[0].strip())
        if not ext or len(data) > MAX_BYTES:
            return None
        name = hashlib.sha1(poster_key(title, kind).encode()).hexdigest()[:20] + "." + ext
        tmp = os.path.join(self.folder, name + ".part")
        with open(tmp, "wb") as f:
            f.write(data)
        os.replace(tmp, os.path.join(self.folder, name))
        return name

    def run_once(self):
        """Fetch the next missing poster. Returns False when there's nothing to do."""
        retry = (dt.date.today() - dt.timedelta(days=RETRY_DAYS)).isoformat()
        todo = self.store.poster_todo(retry)
        if not todo:
            return False
        title, kind = todo
        try:
            name = self.fetch(title, kind)
        except urllib.error.HTTPError as e:
            if e.code in (429, 503):  # the site wants a break: pause, then this same title again
                log.info("poster lookups paused %ds (%s)", BACKOFF, e)
                return "backoff"
            log.warning("poster for %r failed: %s", title, e)
            self.store.set_poster(title, kind, None, failed=True)
            return True
        except Exception as e:  # offline or a site hiccup: try again in an hour
            log.warning("poster for %r failed: %s", title, e)
            self.store.set_poster(title, kind, None, failed=True)
            return True
        self.store.set_poster(title, kind, name)
        log.info("poster for %r: %s", title, name or "none found")
        return True

    def loop(self):
        while True:
            try:
                busy = self.run_once()
            except Exception:
                log.exception("poster loop")
                busy = False
            if busy == "backoff":
                time.sleep(BACKOFF)
            elif busy:
                time.sleep(PAUSE)
            else:
                self.wake.wait(3600)
                self.wake.clear()

    def start(self):
        threading.Thread(target=self.loop, name="posters", daemon=True).start()
