# Watch log status (2026-11-27)

Running on the Pi at <http://10.0.0.10:9280> as the `watchlog` systemd service.
The code on GitHub (`watchlog` and `HomeTvWatchLog`) is the same as what runs on the Pi.

## What works

- **Logging by hand:** title, movie or show, episode, service, date watched, a rating
  with half stars, whether they saw the end (saw the end / dozed off / out cold),
  who watched (person 1, person 2 or both), and notes.
- **Settings (⚙):** the two people's names, and whose "saw the end" is tracked: one person
  or whoever's watching. On the Pi: Person 1 and Person 2, tracking Person 2.
- **Title search while typing:** your own titles come first, then TVmaze for shows and
  Wikipedia/Wikidata for movies. Typing a year narrows the results ("old 2021").
- **Netflix import:** from the viewing-activity CSV, with a preview before anything is
  saved. Each title is listed once, even across both profiles. Episodes are grouped
  under their show, even when Netflix leaves out the season.
- **Export CSV:** every entry as a download, with the names spelled out and
  formula-looking cells made safe for spreadsheets.
- **Posters:** cached on the Pi, fetched in the background. A wrong poster can be removed.
- **History:** search ("did we watch…?"), filters for service, kind, rating, saw the end
  and who watched, plus sort (newest watched first by default).
- **Totals:** a per-service breakdown, the average rating, and how often the end got missed.
- **Phones:** the header wraps on narrow screens, so all the buttons fit.

## Numbers on the Pi (2026-11-27)

- 1,198 entries
- 917 have a poster
- 1,173 not rated yet
- who watched filled in on only 23 entries

## Recent changes

- **2026-11-27:** names became settings and CSV export was added. Old `p1` / `p2`
  values were converted to `p1` / `p2` on the Pi, and the counts matched before and after.
  Backup taken first: `backups/watchlog-20261127-1230.db`.
  The `wife_asleep` column was renamed to `missed_end`, in the database and the API.
  Old databases rename it on start, and the API still accepts `wife_asleep`.
- **2026-11-26:** security review and fixes, deployed. See [SECURITY.md](SECURITY.md).
  There's no login, on purpose (it's for the home network). The server refuses requests
  that other web pages send, DNS rebinding, malformed bodies and being loaded in a frame.

## To do

- **Re-import both Netflix files** with Person 1 or Person 2 picked, to fill in who watched.
  Ratings and marks you've set are kept.
- **Rate the 1,173 unrated entries.** Filter "Rated or not" → "Not rated yet" and tap
  through them.
- **Fix or delete 16 entries titled ": Episode N".** Netflix left out the show name for
  these, so they can't be matched to a show.
- **Max, Paramount+, Peacock and Apple TV** have no history download, so those entries are
  typed in by hand.

## Deploying

- Tests: `python3 -m unittest discover -s tests -t .` (40 tests, all passing)
- `deploy/sync.sh backup` snapshots the database into `backups/`, which git ignores.
- `deploy/sync.sh push` runs the tests, copies the code to the Pi and restarts the service.
- Push to both remotes: `git push origin main` (watchlog) and `git push hometv main` (HomeTvWatchLog).
