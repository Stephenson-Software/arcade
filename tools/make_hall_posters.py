#!/usr/bin/env python3
"""Writes the walkable hall's screen images: src/arcade/hall_assets/posters/<slug>.jpg.

One 512x288 JPEG per game in the live registry, from the same sources the
README picture uses (arcade.hall.poster_urls: the game's trailer poster on
danielstephenson.dev, else a picture from its README). arcade serves them
itself at /hall/posters/<slug>.jpg, same-origin, because the hall draws them
into WebGL textures and danielstephenson.dev sends no CORS header. A game
with no public image gets a title-card poster drawn here (its title, its
blurb from blurbs.json, and where it is played).

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
from make_hall_media import FONT, REGISTRY, cached, cover, fetch, fit_text  # noqa: E402  (strata not needed)
from PIL import ImageChops, ImageDraw, ImageFilter, ImageFont  # noqa: E402

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
            title_poster(game).save(path, quality=86, optimize=True, progressive=True)
            print("%s <- title-card poster (no public image) (%d KiB)" % (os.path.relpath(path, ROOT),
                                                                           os.path.getsize(path) // 1024))


def wrap(draw, text, font, width, lines=2):
    """At most `lines` lines of text that fit `width`, the last cut with an ellipsis."""
    words, out, line = text.split(), [], ""
    for w in words:
        trial = (line + " " + w).strip()
        if draw.textlength(trial, font=font) <= width:
            line = trial
            continue
        out.append(line)
        line = w
        if len(out) == lines:
            break
    if len(out) < lines and line:
        out.append(line)
    if len(out) == lines and " ".join(out) != " ".join(words):
        while out[-1] and draw.textlength(out[-1] + "\u2026", font=font) > width:
            out[-1] = out[-1].rsplit(" ", 1)[0] if " " in out[-1] else out[-1][:-1]
        out[-1] += "\u2026"
    return out


def title_poster(game):
    """A poster for a game with no public picture: its title over a dark
    gradient of its organisation's colour, its blurb, and where it is played."""
    w, h = hall.SCREEN_TEX
    c = hall.org_colour(game["repo"])
    img = Image.new("RGB", (w, h))
    d = ImageDraw.Draw(img)
    for y in range(h):
        k = 0.42 - 0.34 * y / h
        d.line([(0, y), (w, y)], fill=tuple(round(255 * (0.03 + k * v)) for v in c))
    glow = Image.new("RGB", (w, h))  # a soft glow behind the title
    ImageDraw.Draw(glow).ellipse([w * 0.12, h * 0.2, w * 0.88, h * 0.64],
                                 fill=tuple(round(255 * 0.5 * v) for v in c))
    img = ImageChops.add(img, glow.filter(ImageFilter.GaussianBlur(34)))
    d = ImageDraw.Draw(img)
    font = fit_text(d, game["title"], w - 70, 74)
    d.text((w / 2 + 2, h * 0.42 + 3), game["title"], font=font, fill=(0, 0, 0), anchor="mm")
    d.text((w / 2, h * 0.42), game["title"], font=font, fill=(255, 255, 255), anchor="mm")
    blurb = hall.blurbs().get(game["slug"])
    small = ImageFont.truetype(FONT.replace("-Bold", ""), 17)
    if blurb:
        for k, line in enumerate(wrap(d, blurb, small, w - 70)):
            d.text((w / 2, h * 0.68 + k * 22), line, font=small, fill=(232, 226, 245), anchor="mm")
    tiny = ImageFont.truetype(FONT, 13)
    d.text((w / 2, h - 18), "%s.play.danielstephenson.dev" % game["slug"], font=tiny,
           fill=tuple(round(255 * (0.55 + 0.45 * v)) for v in c), anchor="mm")
    return img


if __name__ == "__main__":
    main()
