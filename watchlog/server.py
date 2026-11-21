"""Watch log dashboard (port 9280), stdlib only."""
import http.server
import json
import logging
import os
import re
import urllib.parse

from . import lookup, netflix
from .store import KINDS, SERVICES

log = logging.getLogger("watchlog")
IMPORT_LIMIT = 10 * 1024 * 1024  # years of Netflix history is well under 1 MB
STATIC = os.path.join(os.path.dirname(__file__), "static")
WATCH_ID = re.compile(r"^/api/watches/(\d+)$")
POSTER_AGAIN = re.compile(r"^/api/watches/(\d+)/poster$")
IMAGE_TYPES = {"jpg": "image/jpeg", "png": "image/png", "webp": "image/webp"}


def make_handler(store, posters=None):
    def changed():
        """New or renamed titles: let the poster thread look them up now."""
        if posters:
            posters.wake.set()

    class Handler(http.server.BaseHTTPRequestHandler):
        server_version = "watchlog"

        def log_message(self, fmt, *args):
            log.debug("%s %s", self.address_string(), fmt % args)

        def send_json(self, obj, status=200):
            body = json.dumps(obj).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def read_json(self, limit=64 * 1024):
            n = int(self.headers.get("Content-Length") or 0)
            if n > limit:
                raise ValueError("request too large")
            return json.loads(self.rfile.read(n) or b"{}")

        def do_GET(self):
            path = self.path.split("?", 1)[0]
            if path in ("/", "/index.html"):
                with open(os.path.join(STATIC, "index.html"), "rb") as f:
                    body = f.read()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            elif path.startswith("/posters/") and posters:
                file = posters.path(path[len("/posters/"):])
                if not file or not os.path.exists(file):
                    return self.send_json({"error": "not found"}, 404)
                with open(file, "rb") as f:
                    body = f.read()
                self.send_response(200)
                self.send_header("Content-Type", IMAGE_TYPES[file.rsplit(".", 1)[1]])
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "max-age=86400")
                self.end_headers()
                self.wfile.write(body)
            elif path == "/api/watches":
                self.send_json(store.all())
            elif path == "/api/search":
                q = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query).get("q", [""])[0]
                self.send_json(lookup.search(q))
            elif path == "/api/summary":
                self.send_json({"stats": store.stats(), "titles": store.titles(),
                                "kinds": KINDS, "services": SERVICES})
            else:
                self.send_json({"error": "not found"}, 404)

        def do_POST(self):
            try:
                again = POSTER_AGAIN.match(self.path)
                if self.path == "/api/watches":
                    self.send_json(store.add(self.read_json()), 201)
                    changed()
                elif again:
                    w = store.get(int(again.group(1)))
                    if not w:
                        return self.send_json({"error": "not found"}, 404)
                    if self.read_json().get("remove"):  # wrong poster: drop it for good
                        store.set_poster(w["title"], w["kind"], None, removed=True)
                    else:
                        store.forget_poster(w["title"], w["kind"])
                        changed()
                    self.send_json({"ok": True})
                elif self.path == "/api/import/netflix":
                    # preview only: the page shows these and posts the chosen ones to /api/import
                    body = self.read_json(IMPORT_LIMIT)
                    rows = netflix.parse(str(body.get("csv") or ""))
                    who = body.get("who") or None  # whose Netflix profile the file is from
                    for r in rows:
                        r["who"] = who
                        r["status"] = store.import_status(r)
                    self.send_json(rows)
                elif self.path == "/api/import":
                    self.send_json(store.import_many(self.read_json(IMPORT_LIMIT).get("watches") or []))
                    changed()
                else:
                    self.send_json({"error": "not found"}, 404)
            except (ValueError, TypeError, AttributeError) as e:
                self.send_json({"error": str(e)}, 400)

        def do_PUT(self):
            m = WATCH_ID.match(self.path)
            if not m:
                return self.send_json({"error": "not found"}, 404)
            try:
                w = store.update(int(m.group(1)), self.read_json())
            except (ValueError, TypeError) as e:
                return self.send_json({"error": str(e)}, 400)
            self.send_json(w) if w else self.send_json({"error": "not found"}, 404)
            changed()

        def do_DELETE(self):
            m = WATCH_ID.match(self.path)
            if m and store.delete(int(m.group(1))):
                self.send_json({"ok": True})
            else:
                self.send_json({"error": "not found"}, 404)

    return Handler


def serve(store, bind="0.0.0.0", port=9280, posters=None):
    if posters:
        posters.start()
    httpd = http.server.ThreadingHTTPServer((bind, port), make_handler(store, posters))
    log.info("watchlog on http://%s:%d", bind, port)
    httpd.serve_forever()
