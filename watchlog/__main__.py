import argparse
import logging
import os
import threading

from . import netflix, server
from .posters import Posters
from .store import Store


def main():
    p = argparse.ArgumentParser(prog="watchlog", description="Movie and show watch log")
    p.add_argument("--db", default="watchlog.db")
    p.add_argument("--bind", default="0.0.0.0")
    p.add_argument("--port", type=int, default=9280)
    p.add_argument("--posters", help="poster cache folder (default: 'posters' next to the database)")
    p.add_argument("--no-posters", action="store_true", help="don't look up posters")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args()
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(levelname)s %(name)s: %(message)s")
    store = Store(args.db)
    if store.version() < 1:
        def fix_episodes():  # in the background: TVmaze lookups can take a minute or two
            log = logging.getLogger("watchlog")
            log.info("data upgrade: looking for Netflix episodes logged as movies")
            n = netflix.repair(store)
            store.version(1)
            log.info("data upgrade: folded %d episodes into their shows", n)
        threading.Thread(target=fix_episodes, name="upgrade", daemon=True).start()
    folder = args.posters or os.path.join(os.path.dirname(os.path.abspath(args.db)), "posters")
    server.serve(store, args.bind, args.port, None if args.no_posters else Posters(store, folder))


if __name__ == "__main__":
    main()
