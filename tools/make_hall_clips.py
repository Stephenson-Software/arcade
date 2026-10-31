#!/usr/bin/env python3
"""Writes the walkable hall's trailer clips: src/arcade/hall_assets/clips/<slug>.mp4.

One short, silent H.264 clip per game in the live registry that has a trailer
on danielstephenson.dev (arcade.hall.clip_urls: /trailers/<repo>.mp4, else
/trailers/<slug>.mp4). The hall plays a clip on a cabinet's screen while a
visitor stands near it, drawn into the screen's WebGL texture, so arcade
serves the clips itself, same-origin: danielstephenson.dev sends no CORS
header, and a cross-origin video would taint the canvas it is drawn through.

Each clip is re-encoded for the screen it plays on (16:9, cropped to fill,
SIZE pixels, FPS frames a second, no sound track, the index at the front) by
ffmpeg: the one on PATH, or $FFMPEG (needed: the hall sizes the screen's
texture by the clip, so every clip must be 16:9).

    python3 tools/make_hall_clips.py [--refresh]

Shares tools/make_hall_media.py's download cache (~/.cache/arcade-hall).
Standard library only (and ffmpeg).
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from arcade import hall  # noqa: E402
from make_hall_media import REGISTRY, cached, fetch  # noqa: E402

OUT = hall.CLIPS
SIZE = (384, 216)
FPS = 15


def ffmpeg():
    return os.environ.get("FFMPEG") or shutil.which("ffmpeg")


def encode(exe, data, path):
    """`data` (an mp4) re-encoded for a screen, written to `path`."""
    w, h = SIZE
    with tempfile.TemporaryDirectory() as tmp:
        src = os.path.join(tmp, "in.mp4")
        with open(src, "wb") as f:
            f.write(data)
        subprocess.run(
            [exe, "-v", "error", "-y", "-i", src, "-an",
             "-vf", "scale=%d:%d:force_original_aspect_ratio=increase,crop=%d:%d,setsar=1,fps=%d" % (w, h, w, h, FPS),
             "-c:v", "libx264", "-profile:v", "main", "-pix_fmt", "yuv420p", "-crf", "30", "-preset", "slow",
             "-movflags", "+faststart", "-map_metadata", "-1", "-fflags", "+bitexact", "-flags:v", "+bitexact",
             path],
            check=True,
        )


def main():
    refresh = "--refresh" in sys.argv
    os.makedirs(OUT, exist_ok=True)
    exe = ffmpeg()
    if not exe:
        sys.exit("make_hall_clips: needs ffmpeg (on PATH, or $FFMPEG)")
    games = json.loads(fetch(REGISTRY))["games"]
    for game in games:
        path = os.path.join(OUT, game["slug"] + ".mp4")
        for url in hall.clip_urls(game):
            data = cached(url, refresh)
            if not data:
                continue
            encode(exe, data, path)
            print("%s <- %s (%d KiB)" % (os.path.relpath(path, ROOT), url, os.path.getsize(path) // 1024))
            break
        else:
            print("%s: no trailer" % game["slug"])


if __name__ == "__main__":
    main()
