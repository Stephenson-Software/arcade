#!/usr/bin/env python3
"""Writes the walkable hall's one-line blurbs: src/arcade/hall_assets/blurbs.json.

One line per game in the live registry: its public GitHub repository's
description, read from the unauthenticated GitHub API (so only public
repositories are ever read), trimmed to BLURB_MAX characters at a word.
The hall shows it on the card that appears at a cabinet. A game whose
repository has no description gets none.

    python3 tools/make_hall_blurbs.py

Standard library only.
"""
import json
import os
import sys
import urllib.error
import urllib.request

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "src"))

from arcade import hall  # noqa: E402

REGISTRY = "https://play.danielstephenson.dev/api/games"
API = "https://api.github.com/repos/{}"


def get_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": "arcade-hall-blurbs", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def main():
    games = get_json(REGISTRY)["games"]
    out = {}
    for game in sorted(games, key=lambda g: g["slug"]):
        try:
            repo = get_json(API.format(game["repo"]))
        except urllib.error.HTTPError as e:
            print("%s: %s %s, no blurb" % (game["slug"], game["repo"], e.code))
            continue
        if repo.get("private"):
            continue
        text = hall.trim_blurb(repo.get("description") or "")
        if text:
            out[game["slug"]] = text
            print("%s: %s" % (game["slug"], text))
    with open(hall.BLURBS, "w") as f:
        json.dump(out, f, indent=1, sort_keys=True, ensure_ascii=False)
        f.write("\n")
    print("wrote %s (%d blurbs)" % (os.path.relpath(hall.BLURBS, ROOT), len(out)))


if __name__ == "__main__":
    main()
