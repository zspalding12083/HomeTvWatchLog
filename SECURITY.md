# Security status (2026-11-27)

Reviewed and fixed 2026-11-26. Re-tested 2026-11-27 against the live Pi, after the
settings and CSV export were added: every check below passed.

Watch log has **no login, on purpose**. It runs on the home network (on a Pi, port 9280),
and anyone on that network can view and edit it. That's the intended
trust model, so this review asked a narrower question: *can anything off the home
network read or change the log?*

The main risk without a login is your own browser. Any web page you open on a phone or
laptop at home could send requests to the Pi. The fixes below shut that off.

## Results

| # | Check | Before | Now |
|---|---|---|---|
| 1 | **Cross-site writes (CSRF).** Another site's page posts `text/plain` JSON to `/api/watches` or `/api/import`. Browsers send this kind of request without asking first. | **Vulnerable:** entry created | Blocked (415 / 403), also for `PUT /api/settings` |
| 2 | **DNS rebinding.** An outside domain that resolves to the Pi's address lets another site read the whole history. | **Vulnerable:** any `Host` accepted | Blocked (421), also for `/api/export.csv` |
| 3 | **Negative `Content-Length`.** | **Vulnerable:** the request thread hung for good | 400 |
| 4 | **JSON list instead of an object** (`PUT /api/watches/1` with `[1]`). | **Vulnerable:** handler crashed, connection dropped | 400 |
| 5 | **Clickjacking.** The dashboard loads in a hidden frame on another site, and a click deletes an entry. | No frame protection | `X-Frame-Options: DENY`, CSP `frame-ancestors 'none'` |
| 6 | **Slow clients** holding a thread open. | No timeout | 30 s socket timeout |
| 7 | **Version disclosure** in the `Server` header (`Python/3.x`). | Shown | Removed |
| 8 | **Path traversal** on `/posters/` (`../../etc/passwd`). | Safe: names must match `^[0-9a-f]{20}\.(jpg\|png\|webp)$` | Unchanged |
| 9 | **SQL injection.** | Safe: every query uses parameters | Unchanged |
| 10 | **Stored XSS** through titles, notes or imported CSV rows. | Safe: the page only uses `textContent` and DOM nodes, never `innerHTML` | Unchanged, plus CSP |
| 11 | **SSRF via posters.** | Safe: image URLs must be on Wikimedia or TVmaze, max 3 MB, image types only | Unchanged |
| 12 | **Oversized uploads.** | Safe: 64 KB per request, 10 MB for a Netflix import | Unchanged |
| 13 | **Spreadsheet formulas in the CSV export.** A title from an imported Netflix file like `=HYPERLINK(...)` runs when the export is opened in Excel or Sheets. | New feature (2026-11-27) | Cells starting with `=` `+` `-` `@` get a leading `'` |
| 14 | **Settings input.** Names shown on every page. | New feature (2026-11-27) | Max 30 characters, can't be empty, `end_person` must be `""`, `p1` or `p2`; shown with `textContent` only |
| 15 | **Personal data in the public repo.** | Our first names were in the code, screenshots, commit messages and history | Removed from the files and from every commit; the names live only in the Pi's database |

## How the fixes work (`watchlog/server.py`)

- **Host check:** a request is only answered if its `Host` is an IP address, `localhost`,
  a bare name (`raspberrypi`), or a home-network name (`.local`, `.lan`, `.home`,
  `.home.arpa`, `.internal`). A rebinding attack needs a real outside domain, so it gets 421.
- **Writes** (`POST`, `PUT`, `DELETE`) are refused when:
  - `Origin` is a different site, or
  - `Sec-Fetch-Site` says `cross-site` or `same-site`, or
  - for `POST`/`PUT`, `Content-Type` isn't `application/json`. A browser has to ask
    first (a CORS preflight) before sending that type across sites, and the server never
    says yes.
- **Headers on every response:** `Content-Security-Policy` (only this server's own
  scripts, styles, images and API), `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`,
  `Referrer-Policy: no-referrer`.
- **Request bodies:** a negative length or a non-object JSON body gets 400.
- **CSV export** (`watchlog/store.py`, `safe_cell`): formula-looking cells are escaped, and
  the response is `no-store` with `Content-Disposition: attachment`, so it downloads
  rather than opening in the browser.

`curl` and scripts on the home network still work as before. They just need
`-H 'Content-Type: application/json'` on writes, and they send no `Origin` header.

## Privacy

- Real watch data and the names are only in the Pi's database (`/var/lib/watchlog/`) and the
  local `backups/` folder, which git ignores. The repo's screenshots and demo data are made up.
- 2026-11-27: the first names were removed from every commit and both GitHub repos were
  force-pushed. GitHub may keep the old commits reachable by direct link until GitHub
  Support purges them, and clones made before then still have the old history.
- The CSV export holds the whole history with names, so treat downloaded copies like the backups.

## Still open (accepted for a home network)

- **Anyone on the Wi-Fi can edit or delete entries.** That's how it's meant to work. Guests on
  the main network have the same access, so put guests on a guest network.
  `deploy/sync.sh backup` is the undo.
- **Plain HTTP:** someone on the same network could watch the traffic. The data is only
  movie titles and ratings.
- **No rate limit on `/api/search`.** Someone on the home network could make the Pi send
  many lookups to TVmaze and Wikipedia. The lookups are cached, and TVmaze "too many
  requests" replies pause them.
- **Don't forward port 9280 on the router.** Nothing here is built to face the internet.

## Tests

`tests/test_watchlog.py`:

- `SecurityTest`: cross-site writes, rebinding hosts, bad bodies and response headers.
- `SettingsExportTest`: settings validation, and formula escaping in the CSV export.

All 39 tests pass: `python3 -m unittest discover -s tests -t .`

Live re-test on the Pi (2026-11-27). Writes were refused before anything was saved:

| Request | Result |
|---|---|
| cross-site `POST /api/watches` (text/plain) | 403 |
| cross-site `PUT /api/settings` | 403 |
| `PUT /api/settings` as text/plain | 415 |
| cross-site `DELETE`, and `Sec-Fetch-Site: cross-site` import | 403 |
| foreign `Host` on `/api/watches` and `/api/export.csv` | 421 |
| negative `Content-Length`, list body on settings | 400 |
| `/posters/../../etc/passwd` | 404 |
