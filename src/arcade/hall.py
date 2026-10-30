# @author Daniel McCoy Stephenson
"""The arcade hall: one cabinet per game, as in the README picture.

This module is the one source of the hall's layout. tools/make_hall_media.py
(the README still and GIF, drawn with Strata's Python binding) and the
walkable hall at https://play.<base>/hall (drawn with Strata's web kit) both
read it, so the picture and the walk always show the same hall:

  - the featured game (Roam) stands alone at the end of the aisle;
  - the rest are ordered by plays, most first, nearest the door;
  - side panels are coloured by the GitHub organisation the game lives in;
  - each screen is the game's poster (https://danielstephenson.dev/trailers/
    <name>.jpg), or a picture from its README (SCREEN_OVERRIDES), or a title
    card.

Coordinates are metres. The door is at +z and the aisle runs towards -z, one
wall of cabinets on each side. A cabinet's front faces (sin a, 0, cos a).

Standard library only: the server imports it.
"""

import math
import os
import re

FEATURED = "roam"
POSTER = "https://danielstephenson.dev/trailers/{}.jpg"
RAW = "https://raw.githubusercontent.com/{repo}/HEAD/{path}"
# Games with no trailer poster yet: a picture from the game's own README.
SCREEN_OVERRIDES = {
    "viron-strata": "docs/media/web-public.png",
}

ORG_COLOURS = {
    "Preponderous-Software": (0.48, 0.32, 0.95),
    "Stephenson-Software": (0.07, 0.66, 0.74),
    "dmccoystephenson": (0.98, 0.62, 0.05),
}
OTHER_COLOUR = (0.7, 0.7, 0.7)
BODY = (0.075, 0.075, 0.10)
TRIM = (0.035, 0.035, 0.05)
BEZEL = (0.01, 0.01, 0.015)

SCREEN_TEX = (512, 288)
MARQUEE_TEX = (512, 112)

SPACING = 1.42  # metres between cabinets along a wall
WALL_X = 2.0  # distance of each wall's cabinets from the aisle's centre line
TURN = math.radians(48)  # how far each cabinet turns from the wall towards the door

# The room: half its width, its height, how far the door wall is past z = 0,
# and how far the back wall is behind the featured cabinet.
HALL_HALF_WIDTH = 6.0
HALL_HEIGHT = 4.2
HALL_NEAR = 7.0
HALL_BACK = 1.2

# A cabinet in its own frame (x to its right, y up, z out of its screen):
# (low corner, high corner, colour role). Roles: body, trim, bezel, side.
CABINET_BOXES = (
    ((-0.5, 0.0, -0.45), (0.5, 1.0, 0.36), "body"),  # pedestal
    ((-0.5, 0.94, 0.36), (0.5, 1.06, 0.70), "trim"),  # control deck
    ((-0.5, 1.06, -0.45), (0.5, 2.0, 0.30), "body"),  # screen housing
    ((-0.5, 2.0, -0.45), (0.5, 2.27, 0.40), "trim"),  # marquee box
    ((-0.47, 1.13, 0.295), (0.47, 1.75, 0.30), "bezel"),  # bezel
    ((-0.54, 0.0, -0.47), (-0.50, 2.30, 0.72), "side"),  # left side art
    ((0.50, 0.0, -0.47), (0.54, 2.30, 0.72), "side"),  # right side art
    ((-0.5, 0.0, 0.36), (0.5, 0.1, 0.40), "side"),  # kick plate
)
SIDE_SHADE = 0.85  # side art is the org colour times this
# The footprint a visitor collides with, in the cabinet's frame: x0, z0, x1, z1.
FOOTPRINT = (-0.54, -0.47, 0.54, 0.72)
SCREEN = (-0.42, 1.20, 0.42, 1.68, 0.305)  # x0, y0, x1, y1, z
MARQ = (-0.47, 2.03, 0.47, 2.23, 0.405)


def poster_name(repo):
    """danielstephenson.dev names a trailer after the repository, in kebab case."""
    name = repo.split("/")[1]
    return re.sub(r"(?<=[a-z])([A-Z])", r"-\1", name).lower()


def poster_urls(game):
    """Where a game's screen image may be, best first."""
    urls = [POSTER.format(poster_name(game["repo"])), POSTER.format(game["slug"])]
    if game["slug"] in SCREEN_OVERRIDES:
        urls.append(RAW.format(repo=game["repo"], path=SCREEN_OVERRIDES[game["slug"]]))
    return urls


def org_colour(repo):
    return ORG_COLOURS.get(repo.split("/")[0], OTHER_COLOUR)


def order(games):
    """The featured game first (end of the aisle), then by plays, most first."""
    featured = [g for g in games if g["slug"] == FEATURED]
    rest = sorted(
        (g for g in games if g["slug"] != FEATURED), key=lambda g: (-(g.get("plays") or 0), g["slug"])
    )
    return featured + rest


def placements(count):
    """(position, facing angle) for the featured cabinet then the rest."""
    if count <= 0:
        return []
    rest = count - 1
    left = (rest + 1) // 2
    end_z = -(left - 1) * SPACING - 2.1
    out = [((0.0, 0.0, end_z), 0.0)]
    for i in range(rest):
        k = i // 2
        side = -1 if i % 2 == 0 else 1
        z = -k * SPACING - (0.0 if side < 0 else SPACING / 2)
        out.append(((side * WALL_X, 0.0, z), -side * (math.pi / 2 - TURN)))
    return out


def layout(games):
    """The hall as plain data (JSON-ready): the room and one entry per
    cabinet, in placement order. `games` are /api/games entries."""
    ordered = order(games)
    spots = placements(len(ordered))
    end_z = spots[0][0][2] if spots else -2.1
    cabinets = []
    for game, (pos, angle) in zip(ordered, spots):
        cabinets.append(
            {
                "slug": game["slug"],
                "title": game.get("title") or game["slug"],
                "repo": game["repo"],
                "url": game.get("url"),
                "isolation": bool(game.get("isolation")),
                "deployed": game.get("current") is not None,
                "plays": game.get("plays") or 0,
                "colour": list(org_colour(game["repo"])),
                "x": round(pos[0], 4),
                "z": round(pos[2], 4),
                "angle": round(angle, 6),
                "featured": game["slug"] == FEATURED,
            }
        )
    return {
        "room": {
            "halfWidth": HALL_HALF_WIDTH,
            "height": HALL_HEIGHT,
            "near": HALL_NEAR,
            "far": round(end_z - HALL_BACK, 4),
        },
        "cabinet": {
            "boxes": [[list(lo), list(hi), role] for lo, hi, role in CABINET_BOXES],
            "footprint": list(FOOTPRINT),
            "screen": list(SCREEN),
            "marquee": list(MARQ),
            "body": list(BODY),
            "trim": list(TRIM),
            "bezel": list(BEZEL),
            "sideShade": SIDE_SHADE,
        },
        "cabinets": cabinets,
    }


# --------------------------------------------------------------------------
# Serving the walkable hall (https://play.<base>/hall/)

ASSETS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "hall_assets")
POSTERS = os.path.join(ASSETS, "posters")
_ASSET_NAME = re.compile(r"^(?:posters/)?[a-z0-9][a-z0-9._-]{0,80}$")
EMBED_MODES = ("on", "off")


def csp(domain):
    """The hall page's Content-Security-Policy: everything from this origin,
    WebAssembly compiled from it, and frames only from a game's own host."""
    return (
        "default-src 'self'; script-src 'self' 'wasm-unsafe-eval'; style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data: blob:; connect-src 'self'; frame-src https://*.%s; base-uri 'none'; "
        "form-action 'none'; object-src 'none'" % domain
    )


def etag(path):
    """A file's tag: its size and modification time, so a rebuilt file is
    fetched again and an unchanged one answers 304."""
    st = os.stat(path)
    return "hall-%x-%x" % (st.st_size, st.st_mtime_ns)


def asset_path(name):
    """The file for /hall/<name>, or None. Only plain names (and posters/<name>)."""
    if not _ASSET_NAME.match(name) or ".." in name:
        return None
    path = os.path.join(ASSETS, *name.split("/"))
    return path if os.path.isfile(path) else None


def served_layout(games, embed):
    """layout.json: the layout, plus each cabinet's poster when arcade has
    one, and whether games are played in a frame (embed) and whether the hall
    may reload itself to match a game's isolation (modes)."""
    doc = layout(games)
    for cabinet in doc["cabinets"]:
        has = os.path.isfile(os.path.join(POSTERS, cabinet["slug"] + ".jpg"))
        cabinet["poster"] = "posters/%s.jpg" % cabinet["slug"] if has else None
    doc["embed"] = bool(embed)
    doc["modes"] = True
    return doc
