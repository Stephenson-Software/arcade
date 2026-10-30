#!/usr/bin/env python3
"""Writes the walkable hall's screen images and side art:
src/arcade/hall_assets/posters/<slug>.jpg and <slug>.side.jpg.

One 512x288 JPEG per game in the live registry, from the same sources the
README picture uses (arcade.hall.poster_urls: the game's trailer poster on
danielstephenson.dev, else a picture from its README). arcade serves them
itself at /hall/posters/<slug>.jpg, same-origin, because the hall draws them
into WebGL textures and danielstephenson.dev sends no CORS header. A game
with no public image gets a title-card poster drawn here (its title, its
blurb from blurbs.json, and where it is played).

Each cabinet's side art (<slug>.side.jpg, the panel's outline at
arcade.hall_model.art_size()) is made from its poster: a tall crop of it
over the top of the panel, fading into diagonal stripes of the poster's
dominant colours over a dark tone of the organisation's colour.

    /path/to/python-with-pillow tools/make_hall_posters.py [--refresh]
    /path/to/python-with-pillow tools/make_hall_posters.py --sides   # side art only, from the posters here (no network)

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

from arcade import hall, hall_model  # noqa: E402
from make_hall_media import FONT, REGISTRY, cached, cover, fetch, fit_text  # noqa: E402  (strata not needed)
from PIL import ImageChops, ImageDraw, ImageFilter, ImageFont  # noqa: E402

OUT = os.path.join(ROOT, "src", "arcade", "hall_assets", "posters")


def main():
    refresh = "--refresh" in sys.argv
    os.makedirs(OUT, exist_ok=True)
    if "--sides" in sys.argv:
        # Each game's repository (for its organisation's colour), from the README picture's record.
        with open(os.path.join(ROOT, "docs", "media", "arcade-hall.sources.json")) as f:
            repos = {c["slug"]: c["repo"] for c in json.load(f)["cabinets"]}
        for name in sorted(os.listdir(OUT)):
            if name.endswith(".jpg") and not name.endswith(".side.jpg"):
                slug = name[:-4]
                write_side(slug, Image.open(os.path.join(OUT, name)).convert("RGB"), repos.get(slug))
        return
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
            img = title_poster(game)
            img.save(path, quality=86, optimize=True, progressive=True)
            print("%s <- title-card poster (no public image) (%d KiB)" % (os.path.relpath(path, ROOT),
                                                                           os.path.getsize(path) // 1024))
        write_side(game["slug"], img, game["repo"])


def write_side(slug, poster, repo):
    path = os.path.join(OUT, slug + ".side.jpg")
    side_art(poster, hall.org_colour(repo) if repo else None).save(path, quality=84, optimize=True)
    print("%s <- side art (%d KiB)" % (os.path.relpath(path, ROOT), os.path.getsize(path) // 1024))


def dominant(img, count=3):
    """The poster's `count` most common colours, most first, skipping near-black
    and near-grey ones while there are enough others, brightened for a panel."""
    small = img.resize((96, 54))
    pal = small.quantize(colors=8, method=Image.MEDIANCUT)
    flat = pal.getpalette()
    found = []
    for n, k in sorted(pal.getcolors(), reverse=True):
        r, g, b = flat[3 * k: 3 * k + 3]
        hi, lo = max(r, g, b), min(r, g, b)
        found.append(((hi > 60 and hi - lo > 40), n, (r, g, b)))
    vivid = [c for ok, _, c in found if ok]
    rest = [c for ok, _, c in found if not ok]
    out = (vivid + rest)[:count]
    while len(out) < count:
        out.append(out[-1] if out else (128, 128, 128))
    def lift(c):
        hi = max(max(c), 1)
        k = max(1.0, 170 / hi)
        return tuple(min(255, round(v * k)) for v in c)
    return [lift(c) for c in out]


def side_art(poster, org):
    """A cabinet's side art from its poster: see the module docstring. The
    panel's outline crops it (arcade.hall_model.art_mask()); the art is drawn
    to read well through either panel's outline."""
    w, h = hall_model.art_size()
    org = org or (0.55, 0.55, 0.6)
    # Washed-out colours (a text adventure's grey) give way to tones of the organisation's.
    colours = []
    for k, c in enumerate(dominant(poster)):
        hi, lo = max(c), min(c)
        if hi - lo < 0.3 * hi:
            c = tuple(min(255, round(255 * (0.30 + 0.25 * k + 0.75 * v))) for v in org)
        colours.append(c)
    base = tuple(round(255 * (0.05 + 0.20 * c)) for c in org)
    img = Image.new("RGB", (w, h), base)
    # The poster: a tall crop, over the top of the panel.
    top_h = round(h * 0.56)
    crop = cover(poster, (w, top_h))
    fade = Image.linear_gradient("L").resize((w, top_h))  # 0 at the top, 255 at the bottom
    fade = fade.point(lambda v: 255 if v < 150 else round(255 * (255 - v) / 105))
    img.paste(crop, (0, 0), fade)
    # Stripes of the poster's colours, sweeping up across the lower panel.
    stripes = Image.new("RGB", (w, h), base)
    d = ImageDraw.Draw(stripes)
    band, slope = 18, 0.55
    y0 = round(h * 0.54)
    for k, c in enumerate(colours):
        off = y0 + k * (band + 6)
        d.polygon([(0, off + w * slope), (w, off), (w, off + band), (0, off + band + w * slope)], fill=c)
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).rectangle([0, round(h * 0.50), w, h], fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(6))
    img = Image.composite(stripes, img, mask)
    # A soft shine down the middle, so the panel reads as glossy.
    shine = Image.new("L", (w, h), 0)
    ImageDraw.Draw(shine).polygon([(w * 0.18, h), (w * 0.38, h), (w * 0.86, 0), (w * 0.66, 0)], fill=34)
    img = Image.composite(Image.new("RGB", (w, h), (255, 255, 255)), img, shine.filter(ImageFilter.GaussianBlur(10)))
    return img


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
