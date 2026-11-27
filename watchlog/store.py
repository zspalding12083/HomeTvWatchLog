import csv
import datetime as dt
import io
import json
import re
import sqlite3
import threading

SCHEMA = """
CREATE TABLE IF NOT EXISTS watches (
    id          INTEGER PRIMARY KEY,
    title       TEXT NOT NULL,
    kind        TEXT NOT NULL,           -- 'movie' or 'show'
    episode     TEXT,                    -- shows only, free text: 'S2E3', 'S1 finale'
    service     TEXT NOT NULL,           -- Netflix, Max, ...
    watched_on  TEXT NOT NULL,           -- YYYY-MM-DD
    rating      REAL,                    -- 0.5 to 5 stars, NULL = not rated yet
    missed_end  INTEGER NOT NULL DEFAULT 0,  -- did they see the end: 0 yes, 1 dozed off, 2 out cold
    notes       TEXT,
    created_at  TEXT NOT NULL,
    episode_list TEXT,                   -- shows: JSON list of episodes seen (from imports)
    who         TEXT                     -- p1 / p2 / both (names in settings); NULL = not recorded
);
CREATE INDEX IF NOT EXISTS watches_on ON watches(watched_on);
CREATE TABLE IF NOT EXISTS posters (     -- one per title, shared by its entries
    key     TEXT PRIMARY KEY,            -- poster_key(): 'movie:glass onion a knives out mystery'
    file    TEXT,                        -- in the posters folder; NULL = none found / failed
    status  TEXT NOT NULL,               -- ok / none / error / removed (wrong one, by hand)
    checked TEXT NOT NULL                -- YYYY-MM-DD, or date and time for errors
);
CREATE TABLE IF NOT EXISTS settings (    -- names shown on the dashboard, see Store.settings()
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""
KINDS = ("movie", "show")
SERVICES = ("Netflix", "Max", "Disney+", "Hulu", "Prime Video", "Apple TV+",
            "Peacock", "Paramount+", "YouTube", "Other")
SEASON = re.compile(r"^S(\d+)$")


def norm(title):
    """'Glass Onion: A Knives Out Mystery' and 'glass onion – a knives out mystery' match."""
    return " ".join(re.findall(r"\w+", title.lower().replace("&", "and")))


def poster_key(title, kind):
    return f"{kind}:{norm(title)}"


def episode_label(episodes):
    """'S2: Woe's Hollow' for one episode, 'S1–S3 · 18 episodes' for several."""
    if not episodes:
        return None
    if len(episodes) == 1:
        return episodes[0][:40]
    if any(":" not in e for e in episodes):  # some have no season to go by
        return f"{len(episodes)} episodes"
    seasons = {e.split(":")[0].strip() for e in episodes}
    nums = sorted(int(m[1]) for m in map(SEASON.match, seasons) if m)
    other = sorted(x for x in seasons if not SEASON.match(x))
    if len(other) > 2:  # episode or season names, not worth listing
        other = []
    if nums and nums == list(range(nums[0], nums[-1] + 1)) and len(nums) > 1:
        parts = [f"S{nums[0]}–S{nums[-1]}"]
    else:
        parts = [f"S{n}" for n in nums]
    seasons = ", ".join(parts + other)
    return (f"{seasons} · " if seasons else "") + f"{len(episodes)} episodes"[:40]


FIELDS = ("title", "kind", "episode", "service", "watched_on", "rating", "missed_end", "notes", "who")
WHO = ("p1", "p2", "both")
OLD_WHO = {"p1": "p1", "p2": "p2"}  # before the names were settings (2026-11-27)
DEFAULT_SETTINGS = {"person1": "Person 1", "person2": "Person 2",
                    "end_person": ""}  # whose "saw the end" it is: "", "p1" or "p2"
SAW_END = ("saw the end", "dozed off", "out cold")


def combine_who(a, b):
    """Person 1's profile + person 2's profile = both."""
    return a if not b or a == b else b if not a else "both"


def clean(data: dict) -> dict:
    """Validate a watch from the form; raises ValueError with a readable message."""
    out = {}
    title = str(data.get("title") or "").strip()
    if not title:
        raise ValueError("title is required")
    out["title"] = title[:200]
    kind = data.get("kind") or "movie"
    if kind not in KINDS:
        raise ValueError("kind must be movie or show")
    out["kind"] = kind
    out["episode"] = (str(data.get("episode") or "").strip()[:40] or None) if kind == "show" else None
    service = str(data.get("service") or "").strip()
    if not service:
        raise ValueError("service is required")
    out["service"] = service[:40]
    watched = data.get("watched_on") or dt.date.today().isoformat()
    try:
        out["watched_on"] = dt.date.fromisoformat(str(watched)).isoformat()
    except ValueError:
        raise ValueError("watched_on must be a date (YYYY-MM-DD)") from None
    rating = data.get("rating")
    if rating in (None, "", 0, "0"):
        out["rating"] = None
    else:
        r = float(rating)
        if not 0.5 <= r <= 5 or r * 2 != int(r * 2):
            raise ValueError("rating must be 0.5 to 5 in half stars")
        out["rating"] = r
    missed = data.get("missed_end", data.get("wife_asleep"))  # its name before 2026-11-27
    missed = int(missed or 0)
    if missed not in (0, 1, 2):
        raise ValueError("missed_end must be 0, 1 or 2")
    out["missed_end"] = missed
    out["notes"] = str(data.get("notes") or "").strip()[:2000] or None
    who = data.get("who") or None
    who = OLD_WHO.get(who, who)
    if who not in (None,) + WHO:
        raise ValueError("who must be p1, p2 or both")
    out["who"] = who
    return out


def safe_cell(v):
    """Spreadsheets run cells starting with = + - @ as formulas; a title from a Netflix
    file shouldn't be able to do that. Numbers are left alone."""
    if v is None:
        return ""
    if isinstance(v, (int, float)):
        return v
    v = str(v)
    return "'" + v if v[:1] in ("=", "+", "-", "@", "\t", "\r") else v


class Store:
    def __init__(self, path):
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)
        cols = {r["name"] for r in self.db.execute("PRAGMA table_info(watches)")}
        self.lock = threading.Lock()
        if "wife_asleep" in cols:  # renamed when the names became settings (2026-11-27)
            with self.db:
                self.db.execute("ALTER TABLE watches RENAME COLUMN wife_asleep TO missed_end")
        if "who" not in cols:  # databases from before who-watched (2026-10-27)
            with self.db:
                self.db.execute("ALTER TABLE watches ADD COLUMN who TEXT")
        if "episode_list" not in cols:  # databases from before each title was listed once (2026-10-27)
            with self.db:
                self.db.execute("ALTER TABLE watches ADD COLUMN episode_list TEXT")
            self.merge_duplicates()
        if self.db.execute("SELECT 1 FROM watches WHERE who IN ('p1', 'p2') LIMIT 1").fetchone():
            # names became settings: keep this household's names and whose end it tracks
            with self.db:
                for old, new in OLD_WHO.items():
                    self.db.execute("UPDATE watches SET who = ? WHERE who = ?", (new, old))
                self.db.executemany("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
                                    [("person1", "Person 1"), ("person2", "Person 2"), ("end_person", "p2")])

    def merge_duplicates(self):
        """Collapse entries for the same title into the oldest one: latest date and
        episode, latest rating, the strongest asleep mark, all notes. Returns rows removed."""
        groups = {}
        for r in self.db.execute("SELECT * FROM watches ORDER BY watched_on, id"):
            groups.setdefault((r["title"].lower(), r["kind"]), []).append(dict(r))
        removed = 0
        with self.lock, self.db:
            for rows in groups.values():
                if len(rows) < 2:
                    continue
                keep, last = min(rows, key=lambda r: r["id"]), rows[-1]
                eps = []
                for r in rows:
                    eps += [e for e in json.loads(r["episode_list"] or "[]") if e not in eps]
                rated = [r["rating"] for r in rows if r["rating"] is not None]
                notes = []
                for r in rows:
                    if r["notes"] and r["notes"] not in notes:
                        notes.append(r["notes"])
                self.db.execute(
                    "UPDATE watches SET watched_on = ?, episode = ?, service = ?, rating = ?, missed_end = ?, "
                    "notes = ?, episode_list = ? WHERE id = ?",
                    (last["watched_on"], last["episode"], last["service"], rated[-1] if rated else None,
                     max(r["missed_end"] for r in rows), "\n".join(notes) or None,
                     json.dumps(eps) if eps else None, keep["id"]))
                ids = [r["id"] for r in rows if r["id"] != keep["id"]]
                self.db.execute(f"DELETE FROM watches WHERE id IN ({','.join('?' * len(ids))})", ids)
                removed += len(ids)
        return removed

    def fold_into_show(self, wid, show, episode):
        """Turn a 'movie' that is really an episode into part of its show's entry,
        keeping the rating, asleep mark and notes."""
        with self.lock, self.db:
            w = self.get(wid)
            if not w:
                return
            old = self.find(show, "show")
            if old is None:
                self.db.execute(
                    "UPDATE watches SET title = ?, kind = 'show', episode = ?, episode_list = ? WHERE id = ?",
                    (show, episode[:40], json.dumps([episode]), wid))
                return
            eps = json.loads(old["episode_list"] or "[]")
            if episode not in eps:
                eps.append(episode)
            notes = "\n".join(n for n in (old["notes"], w["notes"]) if n) or None
            self.db.execute(
                "UPDATE watches SET watched_on = ?, episode = ?, rating = ?, missed_end = ?, notes = ?, "
                "episode_list = ?, who = ? WHERE id = ?",
                (max(old["watched_on"], w["watched_on"]), episode_label(eps),
                 old["rating"] if old["rating"] is not None else w["rating"],
                 max(old["missed_end"], w["missed_end"]), notes, json.dumps(eps),
                 combine_who(old["who"], w["who"]), old["id"]))
            self.db.execute("DELETE FROM watches WHERE id = ?", (wid,))

    def version(self, set_to=None):
        """Data upgrades done so far (sqlite user_version)."""
        if set_to is not None:
            with self.lock, self.db:
                self.db.execute(f"PRAGMA user_version = {int(set_to)}")
        return self.db.execute("PRAGMA user_version").fetchone()[0]

    def find(self, title, kind):
        row = self.db.execute("SELECT * FROM watches WHERE title = ? COLLATE NOCASE AND kind = ? ORDER BY id LIMIT 1",
                              (title.strip(), kind)).fetchone()
        return dict(row) if row else None

    def add(self, data):
        """Log a watch. A title already in the log is updated instead (each title is
        listed once): newer date, this episode, and the rating, asleep mark and notes
        if given."""
        w = clean(data)
        now = dt.datetime.now().isoformat(timespec="seconds")
        with self.lock, self.db:
            old = self.find(w["title"], w["kind"])
            if old is None:
                eps = [w["episode"]] if w["episode"] else []
                cur = self.db.execute(
                    f"INSERT INTO watches ({', '.join(FIELDS)}, created_at, episode_list) "
                    f"VALUES ({', '.join('?' * len(FIELDS))}, ?, ?)",
                    [w[f] for f in FIELDS] + [now, json.dumps(eps) if eps else None])
                return self.get(cur.lastrowid)
            eps = json.loads(old["episode_list"] or "[]")
            if w["episode"] and w["episode"] not in eps:
                eps.append(w["episode"])
            self.db.execute(
                "UPDATE watches SET watched_on = ?, episode = ?, service = ?, rating = ?, missed_end = ?, "
                "notes = ?, episode_list = ?, who = ? WHERE id = ?",
                (max(old["watched_on"], w["watched_on"]), w["episode"] or old["episode"], w["service"],
                 w["rating"] if w["rating"] is not None else old["rating"],
                 max(old["missed_end"], w["missed_end"]), w["notes"] or old["notes"],
                 json.dumps(eps) if eps else None, combine_who(old["who"], w["who"]), old["id"]))
        return {**self.get(old["id"]), "merged": True}

    def import_status(self, item):
        """For the import preview: 'new', 'update' (newer date, new episodes or who
        watched) or 'logged'."""
        old = self.find(item["title"], item["kind"])
        if old is None:
            return "new"
        seen = set(json.loads(old["episode_list"] or "[]"))
        if (item["watched_on"] > old["watched_on"] or set(item.get("episodes") or []) - seen
                or combine_who(old["who"], item.get("who")) != old["who"]):
            return "update"
        return "logged"

    def import_many(self, items):
        """Bulk import, one entry per title: new titles are added; titles already
        logged get any new episodes and a newer date, keeping their rating, asleep
        mark and notes. Returns {"added": n, "updated": n}."""
        rows = []
        for d in items:
            eps = [str(e)[:200] for e in d.get("episodes") or []][:5000]
            rows.append((clean({**d, "episode": episode_label(eps)}), eps))
        now = dt.datetime.now().isoformat(timespec="seconds")
        added = updated = 0
        with self.lock, self.db:
            for w, eps in rows:
                old = self.find(w["title"], w["kind"])
                if old is None:
                    self.db.execute(
                        f"INSERT INTO watches ({', '.join(FIELDS)}, created_at, episode_list) "
                        f"VALUES ({', '.join('?' * len(FIELDS))}, ?, ?)",
                        [w[f] for f in FIELDS] + [now, json.dumps(eps) if eps else None])
                    added += 1
                    continue
                seen = json.loads(old["episode_list"] or "[]")
                merged = seen + [e for e in eps if e not in seen]
                newer = w["watched_on"] > old["watched_on"]
                who = combine_who(old["who"], w["who"])
                if not newer and len(merged) == len(seen) and who == old["who"]:
                    continue
                self.db.execute(
                    "UPDATE watches SET watched_on = ?, episode = ?, episode_list = ?, who = ? WHERE id = ?",
                    (max(old["watched_on"], w["watched_on"]), episode_label(merged) or old["episode"],
                     json.dumps(merged) if merged else None, who, old["id"]))
                updated += 1
        return {"added": added, "updated": updated}

    def update(self, wid, data):
        w = clean(data)
        with self.lock, self.db:
            cur = self.db.execute(
                f"UPDATE watches SET {', '.join(f + ' = ?' for f in FIELDS)} WHERE id = ?",
                [w[f] for f in FIELDS] + [wid])
        return self.get(wid) if cur.rowcount else None

    def delete(self, wid):
        with self.lock, self.db:
            return self.db.execute("DELETE FROM watches WHERE id = ?", (wid,)).rowcount > 0

    def get(self, wid):
        row = self.db.execute("SELECT * FROM watches WHERE id = ?", (wid,)).fetchone()
        return dict(row) if row else None

    def all(self):
        rows = [dict(r) for r in self.db.execute("SELECT * FROM watches ORDER BY watched_on DESC, id DESC")]
        files = dict(self.db.execute("SELECT key, file FROM posters WHERE status = 'ok'").fetchall())
        for r in rows:
            r["poster"] = files.get(poster_key(r["title"], r["kind"]))
            r["episodes"] = json.loads(r.pop("episode_list") or "[]")
        return rows

    def poster_todo(self, retry_before):
        """The next (title, kind) that needs a poster lookup, newest watch first: never
        looked up, none found before retry_before, or an error over an hour ago."""
        hour_ago = (dt.datetime.now() - dt.timedelta(hours=1)).isoformat(timespec="minutes")
        known = {k: (s, c) for k, s, c in self.db.execute("SELECT key, status, checked FROM posters")}
        for r in self.db.execute("SELECT title, kind FROM watches ORDER BY watched_on DESC, id DESC"):
            status, checked = known.get(poster_key(r["title"], r["kind"]), (None, None))
            if (status is None or (status == "none" and checked < retry_before)
                    or (status == "error" and checked < hour_ago)):
                return r["title"], r["kind"]
        return None

    def set_poster(self, title, kind, file, failed=False, removed=False):
        status = "removed" if removed else "error" if failed else "ok" if file else "none"
        with self.lock, self.db:
            self.db.execute("INSERT OR REPLACE INTO posters (key, file, status, checked) VALUES (?, ?, ?, ?)",
                            (poster_key(title, kind), file, status,
                             dt.datetime.now().isoformat(timespec="minutes") if failed else dt.date.today().isoformat()))

    def forget_poster(self, title, kind):
        """So the next lookup tries again (the "find poster again" button)."""
        with self.lock, self.db:
            self.db.execute("DELETE FROM posters WHERE key = ?", (poster_key(title, kind),))

    def settings(self):
        stored = dict(self.db.execute("SELECT key, value FROM settings").fetchall())
        return {k: stored.get(k, v) for k, v in DEFAULT_SETTINGS.items()}

    def save_settings(self, data):
        new = self.settings()
        for k in ("person1", "person2"):
            if k in data:
                name = " ".join(str(data[k] or "").split())[:30]
                if not name:
                    raise ValueError("names can't be empty")
                new[k] = name
        if "end_person" in data:
            if data["end_person"] not in ("", "p1", "p2"):
                raise ValueError("end_person must be '', p1 or p2")
            new["end_person"] = data["end_person"]
        with self.lock, self.db:
            self.db.executemany("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", new.items())
        return new

    def export_csv(self):
        """Every entry as CSV, names spelled out, ready for a spreadsheet."""
        st = self.settings()
        names = {"p1": st["person1"], "p2": st["person2"], "both": "Both"}
        out = io.StringIO()
        w = csv.writer(out)
        w.writerow(["Title", "Kind", "Episode", "Episodes seen", "Service", "Watched on", "Rating",
                    "Saw the end", "Who watched", "Notes", "Added"])
        for r in sorted(self.all(), key=lambda r: (r["watched_on"], r["id"])):
            w.writerow([safe_cell(v) for v in (
                r["title"], r["kind"], r["episode"], "; ".join(r["episodes"]), r["service"],
                r["watched_on"], r["rating"], SAW_END[r["missed_end"]], names.get(r["who"], ""),
                r["notes"], r["created_at"])])
        return out.getvalue()

    def titles(self):
        """Distinct titles with their last kind and service, for the form's autocomplete."""
        rows = self.db.execute(
            "SELECT title, kind, service FROM watches w WHERE id = "
            "(SELECT MAX(id) FROM watches WHERE title = w.title) ORDER BY title")
        return [dict(r) for r in rows]

    def stats(self, today=None):
        today = today or dt.date.today()
        rows = self.all()
        month = today.isoformat()[:7]
        rated = [r["rating"] for r in rows if r["rating"] is not None]
        by_service = {}
        for r in rows:
            s = by_service.setdefault(r["service"], {"service": r["service"], "count": 0, "asleep": 0, "ratings": []})
            s["count"] += 1
            s["asleep"] += r["missed_end"] > 0
            if r["rating"] is not None:
                s["ratings"].append(r["rating"])
        services = []
        for s in sorted(by_service.values(), key=lambda s: -s["count"]):
            ratings = s.pop("ratings")
            s["avg_rating"] = round(sum(ratings) / len(ratings), 2) if ratings else None
            services.append(s)
        return {
            "total": len(rows),
            "this_month": sum(r["watched_on"].startswith(month) for r in rows),
            "movies": sum(r["kind"] == "movie" for r in rows),
            "shows": len({r["title"] for r in rows if r["kind"] == "show"}),
            "avg_rating": round(sum(rated) / len(rated), 2) if rated else None,
            "asleep": sum(r["missed_end"] > 0 for r in rows),
            "services": services,
        }
