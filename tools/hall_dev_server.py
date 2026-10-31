#!/usr/bin/env python3
"""Serves the walkable hall locally against a snapshot of the live registry.

    python3 tools/hall_dev_server.py [--port 8790] [--snapshot games.json] [--embed on|off]

The registry and play counts come from https://play.danielstephenson.dev/api/games
(or a saved copy of it, --snapshot), so the hall has the same cabinets in the
same order as the live one, and every cabinet opens the live game. Each game
gets a placeholder version locally only so that it counts as deployed. Any
Host is answered as play.danielstephenson.dev, so http://<this machine>:<port>/hall/
works from a phone on the same network. Standard library only.
"""
import argparse
import json
import os
import sys
import tempfile
import urllib.request

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "src"))

from arcade import server  # noqa: E402
from arcade.store import Store  # noqa: E402

LIVE = "https://play.danielstephenson.dev/api/games"
DOMAIN = "play.danielstephenson.dev"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8790)
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--snapshot")
    ap.add_argument("--embed", default="on", choices=("on", "off"))
    args = ap.parse_args()
    if args.snapshot:
        with open(args.snapshot) as f:
            games = json.load(f)["games"]
    else:
        req = urllib.request.Request(LIVE, headers={"User-Agent": "arcade-hall-dev"})
        games = json.loads(urllib.request.urlopen(req, timeout=30).read())["games"]

    work = tempfile.mkdtemp(prefix="arcade-hall-dev-")
    lines = ["games:"]
    for g in games:
        lines += [
            "  - slug: %s" % g["slug"],
            "    title: %s" % json.dumps(g["title"]),
            "    repo: %s" % g["repo"],
            '    token_sha256: "%s"' % ("0" * 64),
            "    kind: static",
            "    isolation: %s" % ("on" if g.get("isolation") else "off"),
        ]
        if g.get("added"):  # the day it joined, so NEW ribbons match the live hall
            lines.append("    added: %s" % g["added"][:10])
        if g.get("tags"):  # so ?tag= lights the same cabinets as the live hall
            lines.append("    tags: [%s]" % ", ".join(g["tags"]))
        if g.get("engine"):
            lines.append("    engine: %s" % g["engine"])
    registry = os.path.join(work, "games.yaml")
    with open(registry, "w") as f:
        f.write("\n".join(lines) + "\n")
    store = Store(os.path.join(work, "data"))
    for g in games:
        if g.get("current"):
            store.add(
                g["slug"],
                "0.0.0-dev",
                {"index.html": b"placeholder", "version.txt": b"0.0.0-dev\n"},
                static=True,
            )
        path = os.path.join(work, "data", g["slug"], "plays")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write("%d\n" % (g.get("plays") or 0))

    config = server.Config(
        DOMAIN,
        os.path.join(work, "data"),
        registry,
        "https://danielstephenson.dev/play",
        hallEmbed=args.embed,
    )
    arcade = server.Arcade(config)
    handler = server.makeHandler(arcade)

    class Dev(handler):
        def _host(self):
            host = super()._host()
            return host if host.endswith("." + DOMAIN) else DOMAIN

    httpd = server.Server((args.host, args.port), Dev)
    print(
        "hall: http://127.0.0.1:%d/hall/  (%d games, data in %s)" % (args.port, len(games), work), flush=True
    )
    httpd.serve_forever()


if __name__ == "__main__":
    main()
