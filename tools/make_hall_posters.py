#!/usr/bin/env python3
"""Writes the walkable hall's screen images: src/arcade/hall_assets/posters/<slug>.jpg.

One 512x288 JPEG per game in the live registry, from the same sources the
README picture uses (arcade.hall.poster_urls: the game's trailer poster on
danielstephenson.dev, else a picture from its README). arcade serves them
itself at /hall/posters/<slug>.jpg, same-origin, because the hall draws them
into WebGL textures and danielstephenson.dev sends no CORS header. A game
with no image gets none, and the hall draws it a title card.

    /path/to/python-with-pillow tools/make_hall_posters.py [--refresh]

Shares tools/make_hall_media.py's download cache (~/.cache/arcade-hall).
"""
import io
import json
import os
import sys

from PIL import Image

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from arcade import hall  # noqa: E402
from make_hall_media import REGISTRY, cached, cover, fetch  # noqa: E402  (strata not needed)

OUT = os.path.join(ROOT, "src", "arcade", "hall_assets", "posters")


def main():
    refresh = "--refresh" in sys.argv
    os.makedirs(OUT, exist_ok=True)
    games = json.loads(fetch(REGISTRY))["games"]
    for game in games:
        path = os.path.join(OUT, game["slug"] + ".jpg")
        for url in hall.poster_urls(game):
            data = cached(url, refresh)
            if data:
                img = cover(Image.open(io.BytesIO(data)).convert("RGB"), hall.SCREEN_TEX)
                img.save(path, quality=80, optimize=True, progressive=True)
                print("%s <- %s (%d KiB)" % (os.path.relpath(path, ROOT), url, os.path.getsize(path) // 1024))
                break
        else:
            print("%s: no image; the hall draws a title card" % game["slug"])


if __name__ == "__main__":
    main()
