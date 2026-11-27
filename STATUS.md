# Watch log status (2026-11-27)

Running on the Pi at <http://10.0.0.10:9280> as the `watchlog` systemd service.

## What works

- **Logging by hand:** title, movie or show, episode, service, date watched, a rating
  with half stars, whether Person 2 saw the end (saw the end / dozed off / out cold),
  who watched (Person 1, Person 2 or both), and notes.
- **Title search while typing:** your own titles come first, then TVmaze for shows and
  Wikipedia/Wikidata for movies. Typing a year narrows the results ("old 2021").
- **Netflix import:** from the viewing-activity CSV, with a preview before anything is
  saved. Each title is listed once, even across both profiles. Episodes are grouped
  under their show, even when Netflix leaves out the season.
- **Posters:** cached on the Pi, fetched in the background. A wrong poster can be removed.
- **History:** search ("did we watch…?"), filters for service, kind, rating, saw the end
  and who watched, plus sort (newest watched first by default).
- **Settings (⚙):** the two names and whose "saw the end" is tracked are settings now,
  not code. On the Pi they're Person 1, Person 2 and Person 2, set by the upgrade on first start.
- **Export CSV:** every entry as a CSV download, from the button up top.
- **Totals:** a per-service breakdown, the average rating, and how often Person 2 didn't
  see the end.

## Numbers on the Pi

- 1,194 entries
- 912 posters cached
- 1,175 entries not rated yet
- who watched filled in on only 16 entries

## To do

- **Re-import both Netflix files** with Person 1 or Person 2 picked, to fill in who watched.
  Ratings and marks you've set are kept.
- **Fix or delete 16 entries titled ": Episode N".** Netflix left out the show name for
  these, so they can't be matched to a show.
- **Max, Paramount+, Peacock and Apple TV** have no history download, so those entries are
  typed in by hand.

## Security

- Reviewed 2026-11-26; see [SECURITY.md](SECURITY.md). There's no login (it's for the home network).
  The server now refuses requests that other web pages send, DNS rebinding,
  malformed bodies and framing. **Deploy with `deploy/sync.sh push`** to put this on the Pi.

## Deploying

- Tests: `python3 -m unittest discover -s tests -t .` (39 tests, all passing)
- `deploy/sync.sh backup` snapshots the database into `backups/`, which git ignores.
- `deploy/sync.sh push` copies the code to the Pi and restarts the service.
