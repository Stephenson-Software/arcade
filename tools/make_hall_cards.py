#!/usr/bin/env python3
"""Renders the hall's link-preview cards: src/arcade/hall_assets/cards/*.jpg.

A link to https://play.danielstephenson.dev/hall/ unfurls with cards/hall.jpg:
the arcade floor seen from just inside the door, down the centre walkway to
Roam on its stage. A link to one cabinet, /hall/?at=<slug>, unfurls with
cards/<slug>.jpg: that cabinet, its poster on the screen, seen as a visitor
walking up to it sees it. arcade names the right one in the page's og:image
(arcade.hall.share_meta); a game with no card yet gets the hall's.

The scene is the walkable hall's: the floor plan comes from
src/arcade/hall.py (the same arcade.hall.layout() the page draws) and the
geometry, lights and signs from tools/make_hall_media.py's build(). The
screens are the posters the hall itself shows (hall_assets/posters/<slug>.jpg,
from tools/make_hall_posters.py). Everything 3D is drawn by Strata v0.7.0
through its Python binding; Pillow adds the caption and writes the JPEGs.

    python3 -m venv /tmp/hall-venv
    /tmp/hall-venv/bin/pip install pillow \\
        "strata-engine @ git+https://github.com/Preponderous-Software/strata@v0.7.0#subdirectory=bindings/python"
    LIBGL_ALWAYS_SOFTWARE=1 GALLIUM_DRIVER=llvmpipe xvfb-run -a \\
        /tmp/hall-venv/bin/python tools/make_hall_cards.py [--only hall|<slug>,...]

The order of the cabinets (most played nearest the door) is read from the live
registry, like the README picture's. Run it again when a game is added.
"""
import json
import math
import os
import sys

from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from arcade import hall  # noqa: E402
import make_hall_media as media  # noqa: E402

SIZE = (hall.CARD_WIDTH, hall.CARD_HEIGHT)
SUPER = 2  # rendered at twice the size, then scaled down: smooth edges
QUALITY = 80


def load_cabinets(games):
    out = []
    for g in hall.order(games):
        colour = hall.org_colour(g["repo"])
        path = os.path.join(hall.POSTERS, g["slug"] + ".jpg")
        img = Image.open(path).convert("RGB") if os.path.isfile(path) else media.title_card(g, colour)
        out.append({"game": g, "colour": colour, "screen": media.cover(img, hall.SCREEN_TEX),
                    "marquee": media.marquee(g["title"], colour)})
    return out


def door_view(room):
    """Just inside the door, a little above eye height, down the walkway to the stage."""
    stage_z = (room["stage"]["front"] + room["stage"]["back"]) / 2
    return (0.0, 2.15, room["near"] - 0.7), (0.0, 1.25, stage_z + 4.0)


def cabinet_view(placed):
    """A couple of steps out from a cabinet and to its right, looking past it a
    little, so it stands in the right half of the card, clear of the caption."""
    a = placed["angle"]
    f = (math.sin(a), math.cos(a))  # out of the screen
    r = (math.cos(a), -math.sin(a))  # the cabinet's right
    x, y, z = placed["x"], placed["y"], placed["z"]
    eye = (x + 2.7 * f[0] + 0.55 * r[0], y + 1.9, z + 2.7 * f[1] + 0.55 * r[1])
    target = (x - 0.75 * r[0] + 0.3 * f[0], y + 1.38, z - 0.75 * r[1] + 0.3 * f[1])
    return eye, target


def label(img, title, line):
    """The title and one line, bottom left, over a soft dark band."""
    img = img.copy()
    d = ImageDraw.Draw(img, "RGBA")
    w, h = img.size
    for y in range(h - 190, h):  # a gradient so the floor shows through
        k = (y - (h - 190)) / 190
        d.line([(0, y), (w, y)], fill=(8, 6, 16, round(205 * k * k)))
    big = media.fit_text(d, title, w - 96, 58, floor=30)
    small = ImageFont.truetype(media.FONT.replace("-Bold", ""), 26)
    tiny = ImageFont.truetype(media.FONT, 20)
    d.text((48, h - 132), title, font=big, fill=(255, 255, 255), anchor="ls")
    d.text((48, h - 88), line, font=small, fill=(226, 220, 246), anchor="ls")
    d.text((48, h - 44), "play.danielstephenson.dev/hall", font=tiny, fill=(255, 200, 120), anchor="ls")
    d.text((w - 40, h - 44), "Rendered with Strata " + media.RELEASE, font=tiny, fill=(190, 184, 214), anchor="rs")
    return img


def save(img, name):
    os.makedirs(hall.CARDS, exist_ok=True)
    path = os.path.join(hall.CARDS, name + ".jpg")
    img.save(path, quality=QUALITY, optimize=True, progressive=True, subsampling="4:2:0")
    print("wrote %s (%d KiB)" % (os.path.relpath(path, ROOT), os.path.getsize(path) // 1024))


def main():
    only = None
    if "--only" in sys.argv:
        only = set(sys.argv[sys.argv.index("--only") + 1].split(","))
    games = json.loads(media.fetch(media.REGISTRY))["games"]
    cabinets = load_cabinets(games)
    doc = hall.layout([c["game"] for c in cabinets])
    assert [c["slug"] for c in doc["cabinets"]] == [c["game"]["slug"] for c in cabinets]
    lines = hall.blurbs()
    w, h = SIZE[0] * SUPER, SIZE[1] * SUPER
    lib = media.strata.load_release(media.RELEASE)
    with media.strata.Engine(lib, w, h) as engine:
        scene = media.build(engine, cabinets, doc)
        if only is None or "hall" in only:
            eye, target = door_view(doc["room"])
            img = media.render(engine, scene, (w, h), eye, target).resize(SIZE, Image.LANCZOS)
            save(label(img, "The Arcade Hall", "%d browser games, one cabinet each. Walk up and play." % len(cabinets)),
                 "hall")
        for cab, placed in zip(cabinets, doc["cabinets"]):
            slug = placed["slug"]
            if only is not None and slug not in only:
                continue
            eye, target = cabinet_view(placed)
            img = media.render(engine, scene, (w, h), eye, target).resize(SIZE, Image.LANCZOS)
            line = lines.get(slug) or "A cabinet in the arcade hall. Walk up and play."
            save(label(img, placed["title"], hall.trim_blurb(line, 72)), slug)


if __name__ == "__main__":
    main()
