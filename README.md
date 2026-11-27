<p align="left">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="assets/brand/zs-logo-horizontal-dark-bg.svg">
    <img alt="ZS Tech | Zachary Spalding Technology Services" src="assets/brand/zs-logo-horizontal-light-bg.svg" height="64">
  </picture>
</p>

# Watch log

A self-hosted log of the movies and shows two people watch on the streaming services,
made for a Raspberry Pi (or any small Linux box) on the home network. Python 3.10 standard
library and SQLite, with no dependencies to install.

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/screenshots/overview-dark.png">
  <img alt="Watch Log dashboard: totals, a per-service breakdown and the watch history" src="docs/screenshots/overview-light.png" width="720">
</picture>

The screenshots use made-up titles and names from `deploy/demo_data.py`. Real watch data
stays in the database on the Pi, which is never committed.

## Features

- **Log a watch:** title, movie or show, episode, service, date, a star rating (half stars
  allowed), who watched, whether they saw the end (saw the end / dozed off / out cold),
  and notes. Tap an entry to edit or delete it.
- **Title search while typing:** your own past titles first, then TVmaze for shows (it also
  fills in the network or streamer) and Wikipedia/Wikidata for movies. Add a year to narrow
  it ("old 2021"). Free and keyless; the server does the lookups and caches them.
- **Netflix import:** on netflix.com, Account → your profile → Viewing activity →
  **Download all**, then **Import** on the dashboard. You get a preview first. Each title
  is listed once and episodes are grouped under their show, even when Netflix leaves out
  the season. Titles already logged just get the new episodes and a newer date. Afterwards
  the unrated ones are listed so you can tap through and rate them.
- **Two people:** pick whose Netflix profile a file came from; a title in both profiles
  becomes "Both".
- **Settings (⚙):** the two names, and whose "saw the end" to track: one person ("Did Sam
  see the end?") or whoever's watching ("Did you see the end?"). Names are stored in the
  database, so changing them relabels every entry.
- **Export CSV:** every entry as a spreadsheet-ready file, with names spelled out. Cells
  that a spreadsheet would run as a formula (`=`, `+`, `-`, `@`) get a leading `'`.
- **Posters:** looked up in the background (newest first, about one a second) from
  Wikipedia and TVmaze and cached on disk. A wrong one can be removed and won't come back.
- **Dashboard:** totals, the average rating, how often the end got missed, a per-service
  breakdown, and a searchable history with filters (service, kind, rating, saw the end,
  who watched) and sorting. Light and dark themes, and it works on a phone.

Max, Disney+, Paramount+, Peacock and Apple TV have no watch-history download, so those
entries are typed in by hand.

## Try it

```bash
python3 deploy/demo_data.py /tmp/demo.db
python3 -m watchlog --db /tmp/demo.db --port 9280 --no-posters
```

Then open <http://localhost:9280>. For a real log, point `--db` at a new file.

| Option | Default | What |
|---|---|---|
| `--db` | `watchlog.db` | SQLite database (created if missing) |
| `--bind` | `0.0.0.0` | address to listen on |
| `--port` | `9280` | port |
| `--posters` | `posters/` next to the database | poster cache folder |
| `--no-posters` | | don't look up posters |
| `-v` | | debug logging |

Tests: `python3 -m unittest discover -s tests -t .`

## Security

There's **no login, on purpose**: anyone on the home network can view and edit the log.
What it does protect against is other web pages using it through your browser. It refuses
cross-site writes, DNS rebinding, being loaded in a frame, and malformed requests, and it
sends a strict Content-Security-Policy. The CSV export escapes cells a spreadsheet would
run as formulas. Details, and the latest test results, in [SECURITY.md](SECURITY.md).

- **Don't forward the port on your router.** It isn't built to face the internet.
- Scripts that write to the API need `-H 'Content-Type: application/json'`.
- **Your data stays on your Pi.** The log, the names and the backups are never committed
  (`backups/` is git-ignored). A CSV export holds your whole history with names, so keep
  downloaded copies somewhere private.

## Running it on a Pi

`deploy/` has the scripts for a Pi reached over SSH. They default to `spalding@10.0.0.10`;
set `PI=user@host` to use your own.

```bash
PI=pi@192.168.1.50 deploy/install.sh
```

`install.sh` runs once and asks for the Pi's sudo password once. It creates a `watchlog`
system user, copies the code to `/opt/watchlog`, installs `deploy/watchlog.service`
(port 9280, database in `/var/lib/watchlog/`, private to the `watchlog` group), adds your
login to that group so backups can read the database, adds a passwordless rule for
restarting the service, and starts it.

After that:

```bash
PI=pi@192.168.1.50 deploy/sync.sh push
```

| Command | What |
|---|---|
| `deploy/sync.sh push` | run the tests, copy the code to the Pi, restart, check it's up |
| `deploy/sync.sh backup` | snapshot the Pi's database and service file into `backups/` (git ignores it; keeps 30) |
| `deploy/sync.sh check` | show anything that differs between here and the Pi |

## API

JSON in and out. Writes need `Content-Type: application/json`.

| Method and path | What |
|---|---|
| `GET /api/watches` | every entry, newest first |
| `POST /api/watches` | add an entry (an existing title is updated instead) |
| `PUT /api/watches/<id>` | edit an entry |
| `DELETE /api/watches/<id>` | delete an entry |
| `POST /api/watches/<id>/poster` | look for the poster again; `{"remove": true}` drops a wrong one for good |
| `GET /api/summary` | totals, titles, services and settings |
| `GET /api/search?q=` | title suggestions |
| `POST /api/import/netflix` | preview a Netflix CSV: `{"csv": "...", "who": "p1"}` |
| `POST /api/import` | save previewed rows: `{"watches": [...]}` |
| `PUT /api/settings` | `{"person1": "...", "person2": "...", "end_person": "" \| "p1" \| "p2"}` |
| `GET /api/export.csv` | every entry as a CSV download |

An entry: `title`, `kind` (`movie` / `show`), `episode`, `service`, `watched_on`
(YYYY-MM-DD), `rating` (0.5–5 in halves, or null), `missed_end` (0 saw the end, 1 dozed off,
2 out cold), `who` (`p1` / `p2` / `both`, or null) and `notes`.

## Files

| Path | What |
|---|---|
| `watchlog/store.py` | SQLite schema, validation, stats, settings, CSV export |
| `watchlog/server.py` | HTTP server, JSON API and the security checks |
| `watchlog/netflix.py` | Netflix viewing-activity CSV parser |
| `watchlog/lookup.py` | title search (TVmaze, Wikipedia, Wikidata) |
| `watchlog/posters.py` | poster lookups (Wikipedia, TVmaze) and the disk cache |
| `watchlog/static/index.html` | the dashboard (one page, no build step) |
| `deploy/` | install, sync, systemd unit and demo data |
| `tests/` | unit and API tests |
| `STATUS.md` | where things stand and what is left |
| `SECURITY.md` | security review: what's protected and what isn't |

## License

MIT, see [LICENSE](LICENSE). The ZS Tech mark files in `assets/brand/` are not covered by the MIT
License: they are all rights reserved and may be used only to identify ZS Tech (Zachary Spalding Technology Services) and its projects.

---

<img src="assets/brand/zs-mark.svg" alt="" height="20" align="top"> A **ZS Tech** project · Zachary Spalding Technology Services · [zspalding12083](https://github.com/zspalding12083). Systems · Networks · Cloud · Open source.
