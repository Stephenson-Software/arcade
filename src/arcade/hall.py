# @author Daniel McCoy Stephenson
"""The arcade hall: one cabinet per game, as in the README picture.

This module is the one source of the hall's layout. tools/make_hall_media.py
(the README still and GIF, drawn with Strata's Python binding) and the
walkable hall at https://play.<base>/hall (drawn with Strata's web kit) both
read it, so the picture and the walk always show the same hall:

  - a roughly square arcade floor: islands of back-to-back cabinets either
    side of a centre walkway, a change and prize counter by the door;
  - the featured game (Roam) stands alone on a raised, lit stage at the back
    wall, in sight from the door;
  - the rest are ordered by plays, most first, in the island nearest the door;
  - side panels are coloured by the GitHub organisation the game lives in;
  - each screen is the game's poster (https://danielstephenson.dev/trailers/
    <name>.jpg), or a picture from its README (SCREEN_OVERRIDES), or a title
    card.

Coordinates are metres. The door is at +z and the room runs towards -z. A
cabinet stands at (x, y, z) (y is above the floor only on the stage) and its
front faces (sin a, 0, cos a).

Standard library only: the server imports it.
"""

import hashlib
import html
import json
import math
import os
import re
from urllib.parse import quote

from arcade import seasons

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

# The floor: a roughly square room, laid out like a real arcade. The door is
# in the middle of the near wall (+z), with a change and prize counter beside
# it. Short "islands" of cabinets stand back to back across the room, split
# by a wide centre walkway that runs from the door to a raised stage at the
# back wall, where the featured game stands alone. Walkways (across the room
# between islands, down the middle and along the sides) are at least 2.5 m.
ROW_PITCH = 1.16  # metres between cabinet centres along a row
BACK_GAP = 0.04  # between the backs of two back-to-back cabinets
CENTRE_WALK = 3.2  # the walkway from the door to the stage
SIDE_WALK = 2.6  # between the outer cabinets and the side walls
AISLE = 2.8  # between one island's back row and the next island's front row
ENTRY = 5.0  # from the door wall to the first island's front
STAGE_GAP = 2.8  # from the last island's back row to the stage
STAGE_HEIGHT = 0.45
STAGE_HALF_WIDTH = 3.0
STAGE_DEPTH = 2.9
HALL_HEIGHT = 4.2
DOOR_HALF_WIDTH = 0.9
DOOR_HEIGHT = 2.5
MAX_PER_HALF_ROW = 6

# How it is lit: warm and bright, with lit panels in the ceiling.
STYLE = {
    "ambient": 0.58,
    "clear": [0.10, 0.08, 0.10],
    "wall": [0.42, 0.30, 0.34],
    "wainscot": [0.24, 0.16, 0.22],
    "ceiling": [0.20, 0.17, 0.19],
    "carpet": [0.26, 0.27, 0.52],  # mid blue, with confetti (carpet_dots)
    "carpetDots": [[0.98, 0.42, 0.66], [0.99, 0.84, 0.30], [0.36, 0.86, 0.92], [0.62, 0.48, 1.0]],
    "panel": [1.0, 0.94, 0.80],
    "light": [1.0, 0.82, 0.60],
}

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
    """The featured game first (on the stage), then by plays, most first."""
    featured = [g for g in games if g["slug"] == FEATURED]
    rest = sorted(
        (g for g in games if g["slug"] != FEATURED), key=lambda g: (-(g.get("plays") or 0), g["slug"])
    )
    return featured + rest


def carpet_dots(size=256, count=110, seed=7):
    """The carpet's confetti, the same in the README picture and the page:
    (x, y, radius, colour index) in a size x size tile, from a small LCG."""
    out, state = [], seed
    for _ in range(count):
        vals = []
        for _ in range(4):
            state = (state * 1103515245 + 12345) % 2147483648
            vals.append(state / 2147483648)
        out.append([round(vals[0] * size, 2), round(vals[1] * size, 2), round(1.6 + vals[2] * 2.2, 2),
                    int(vals[3] * len(STYLE["carpetDots"]))])
    return out


def floor_plan(rest):
    """(islands, cabinets per half row) for `rest` non-featured cabinets: up
    to four islands of two back-to-back rows, each row split in two by the
    centre walkway, so a hall of 30 is two islands of rows of four a side."""
    if rest <= 0:
        return 0, 0
    islands = min(4, max(1, -(-rest // 16)))
    per = -(-rest // (islands * 4))
    while per > MAX_PER_HALF_ROW and islands < 4:
        islands += 1
        per = -(-rest // (islands * 4))
    return islands, per


def _island_centre(j):
    """z of island j's spine (between its back-to-back rows)."""
    half = BACK_GAP / 2 + -FOOTPRINT[1]  # spine to a cabinet's origin
    depth = 2 * (half + FOOTPRINT[3])  # front face to front face
    return -(half + FOOTPRINT[3]) - j * (depth + AISLE)


def _row_offset():
    return BACK_GAP / 2 + -FOOTPRINT[1]


def placements(count):
    """(position, facing angle) for the featured cabinet then the rest, most
    played first. The rest fill the island nearest the door first, its front
    row (facing the door) then its back row, each row from the centre
    walkway outwards, alternating left and right."""
    if count <= 0:
        return []
    rest = count - 1
    islands, per = floor_plan(rest)
    spots = []
    for j in range(islands):
        zc = _island_centre(j)
        for facing in (1, -1):  # front row faces the door (+z), back row the stage
            z = zc + facing * _row_offset()
            angle = 0.0 if facing > 0 else math.pi
            for k in range(per):
                x = CENTRE_WALK / 2 + FOOTPRINT[2] + k * ROW_PITCH
                for side in (-1, 1):
                    spots.append(((side * x, 0.0, z), angle))
    stage = _stage(islands)
    out = [((0.0, STAGE_HEIGHT, stage["cabinetZ"]), 0.0)]
    return out + spots[:rest]


def _stage(islands):
    """Where the stage and the back wall are, for a floor of `islands`."""
    last = _island_centre(max(islands, 1) - 1)
    back_face = last - _row_offset() - FOOTPRINT[3]
    front = back_face - STAGE_GAP
    back_wall = front - STAGE_DEPTH - 0.2
    return {"front": front, "back": back_wall + 0.2, "wall": back_wall,
            "cabinetZ": front - FOOTPRINT[3] - 0.7}


def _box(lo, hi, colour, unlit=False):
    return {"lo": [round(v, 4) for v in lo], "hi": [round(v, 4) for v in hi],
            "colour": [round(v, 4) for v in colour], "unlit": unlit}


def room_for(count, style=None):
    """The room around `count` cabinets: its size, props (plain boxes, drawn
    by both the README tool and the page), signs, lights, the obstacles a
    visitor collides with besides the cabinets, and where a visitor starts.
    `style` replaces STYLE (a season's tint: arcade.seasons.style)."""
    st = style or STYLE
    islands, per = floor_plan(max(count - 1, 0))
    half_width = CENTRE_WALK / 2 + max(per, 2) * ROW_PITCH + SIDE_WALK
    stage = _stage(islands)
    near, far, h = ENTRY, stage["wall"], HALL_HEIGHT
    # Square it up a little: never much narrower than it is deep.
    half_width = round(max(half_width, (near - far) * 0.42), 4)
    props, signs, lights, obstacles = [], [], [], []

    # The stage: a raised, lit platform for the featured game, with a curtain behind.
    sx = STAGE_HALF_WIDTH
    props.append(_box((-sx, 0, stage["back"]), (sx, STAGE_HEIGHT, stage["front"]), (0.36, 0.17, 0.12)))
    props.append(_box((-sx, STAGE_HEIGHT - 0.06, stage["front"]), (sx, STAGE_HEIGHT - 0.02, stage["front"] + 0.03),
                      (1.0, 0.72, 0.30), unlit=True))
    props.append(_box((-sx - 0.4, 0, far + 0.02), (sx + 0.4, 3.6, far + 0.12), (0.46, 0.08, 0.12)))
    obstacles.append([-sx, far - 1.0, sx, stage["front"]])  # to (and past) the wall: no way round behind
    signs.append({"text": "FEATURED", "x": 0.0, "y": 3.25, "z": far + 0.14, "w": 2.6, "h": 0.5,
                  "facing": 1, "colour": [1.0, 0.78, 0.36]})

    # The change and prize counter, left of the door, with a prize wall behind it.
    cx0, cx1 = -DOOR_HALF_WIDTH - 5.2, -DOOR_HALF_WIDTH - 1.4
    cz0, cz1 = near - 2.0, near - 1.25
    props.append(_box((cx0, 0, cz0), (cx1, 1.0, cz1), (0.55, 0.12, 0.20)))
    props.append(_box((cx0 - 0.03, 1.0, cz0 - 0.03), (cx1 + 0.03, 1.06, cz1 + 0.03), (0.93, 0.80, 0.58)))
    props.append(_box((cx0, 0.94, cz0 - 0.02), (cx1, 0.97, cz0), (1.0, 0.76, 0.32), unlit=True))
    props.append(_box((cx1, 0, cz1), (cx1 + 0.05, 1.0, near), (0.55, 0.12, 0.20)))  # its end, to the wall
    props.append(_box((cx0, 0, near - 0.45), (cx1, 2.3, near), (0.30, 0.20, 0.16)))  # prize shelves
    prize = [(0.98, 0.36, 0.52), (0.99, 0.80, 0.25), (0.35, 0.80, 0.95), (0.55, 0.90, 0.40), (0.72, 0.50, 1.0)]
    for row, y in enumerate((0.75, 1.3, 1.85)):
        x, k = cx0 + 0.25, row
        while x < cx1 - 0.3:
            w = 0.22 + 0.08 * ((k * 7) % 3)
            props.append(_box((x, y, near - 0.62), (x + w, y + 0.18 + 0.06 * (k % 2), near - 0.45),
                              prize[k % len(prize)]))
            x += w + 0.12
            k += 1
    for y in (0.72, 1.27, 1.82):
        props.append(_box((cx0, y - 0.04, near - 0.66), (cx1, y, near - 0.45), (0.40, 0.27, 0.20)))
    obstacles.append([cx0, cz0, cx1 + 0.05, near])
    signs.append({"text": "CHANGE \u00b7 PRIZES", "x": (cx0 + cx1) / 2, "y": 2.75, "z": near - 0.44, "w": 3.2,
                  "h": 0.55, "facing": -1, "colour": [1.0, 0.80, 0.30]})

    # The door, lit, and a welcome mat.
    props.append(_box((-DOOR_HALF_WIDTH - 0.12, 0, near - 0.06), (DOOR_HALF_WIDTH + 0.12, DOOR_HEIGHT + 0.12, near),
                      (0.85, 0.62, 0.30)))
    props.append(_box((-DOOR_HALF_WIDTH, 0, near - 0.08), (DOOR_HALF_WIDTH, DOOR_HEIGHT, near - 0.06),
                      (0.98, 0.86, 0.62), unlit=True))
    props.append(_box((-1.2, 0, near - 2.2), (1.2, 0.012, near - 0.1), (0.50, 0.12, 0.16)))
    signs.append({"text": "ARCADE", "x": 0.0, "y": DOOR_HEIGHT + 0.5, "z": near - 0.08, "w": 2.2, "h": 0.5,
                  "facing": -1, "colour": [0.66, 0.54, 1.0]})

    # The ceiling: lit panels in a grid, a warm light under each other one.
    xs = []
    x = -half_width + 2.0
    while x <= half_width - 1.9:
        xs.append(round(x, 4))
        x += 3.2
    zs = []
    z = near - 1.6
    while z >= far + 1.4:
        zs.append(round(z, 4))
        z -= 3.0
    for i, z in enumerate(zs):
        for k, x in enumerate(xs):
            props.append(_box((x - 0.7, h - 0.04, z - 0.35), (x + 0.7, h - 0.01, z + 0.35), st["panel"], unlit=True))
            if (i + k) % 2 == 0:
                lights.append([x, h - 0.5, z, 6.5] + st["light"] + [0.9])
    # Two broad fills first (always kept, whatever the light budget), then
    # the stage's spotlights, then the panels.
    fills = [[0.0, h - 0.4, near - 4.0, 16.0] + st["light"] + [0.8],
             [0.0, h - 0.4, (near + far) / 2 - 2.0, 16.0] + st["light"] + [0.8]]
    spots = [[x, 3.4, stage["cabinetZ"] + 1.6, 5.0, 1.0, 0.85, 0.62, 2.2] for x in (-1.4, 1.4)]
    lights = fills + spots + lights
    return {
        "halfWidth": half_width,
        "height": h,
        "near": near,
        "far": round(far, 4),
        "door": [-DOOR_HALF_WIDTH, DOOR_HALF_WIDTH, DOOR_HEIGHT],
        "stage": {"halfWidth": STAGE_HALF_WIDTH, "height": STAGE_HEIGHT,
                  "front": round(stage["front"], 4), "back": round(stage["back"], 4)},
        "spawn": {"x": 0.0, "z": round(near - 1.4, 4), "yaw": round(math.pi / 2, 6)},
        "props": props,
        "signs": signs,
        "lights": [[round(v, 4) for v in l] for l in lights],
        "obstacles": [[round(v, 4) for v in o] for o in obstacles],
        "style": dict(st, dots=carpet_dots()),
    }


def layout(games, style=None):
    """The hall as plain data (JSON-ready): the room and one entry per
    cabinet, in placement order. `games` are /api/games entries; `style`
    is passed to room_for."""
    ordered = order(games)
    spots = placements(len(ordered))
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
                "y": round(pos[1], 4),
                "z": round(pos[2], 4),
                "angle": round(angle, 6),
                "featured": game["slug"] == FEATURED,
            }
        )
    return {
        "room": room_for(len(ordered), style),
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
# Link-preview cards (tools/make_hall_cards.py): cards/hall.jpg for the hall,
# cards/<slug>.jpg for /hall/?at=<slug>.
CARDS = os.path.join(ASSETS, "cards")
CARD_WIDTH, CARD_HEIGHT = 1200, 630
_ASSET_NAME = re.compile(r"^(?:posters/|cards/)?[a-z0-9][a-z0-9._-]{0,80}$")
EMBED_MODES = ("on", "off")
# One line per game for the card at a cabinet (tools/make_hall_blurbs.py).
BLURBS = os.path.join(ASSETS, "blurbs.json")
BLURB_MAX = 140


def trim_blurb(text, limit=BLURB_MAX):
    """One line, at most `limit` characters, cut at a word with an ellipsis."""
    text = " ".join(str(text).split())
    if len(text) <= limit:
        return text
    cut = text[: limit - 1].rsplit(" ", 1)[0].rstrip(",;:.-")
    return cut + "\u2026"


_blurbs = {"mtime": None, "data": {}}


def blurbs():
    """slug -> blurb, from blurbs.json (re-read when it changes; {} if absent or unreadable)."""
    try:
        mtime = os.stat(BLURBS).st_mtime_ns
    except OSError:
        return {}
    if _blurbs["mtime"] != mtime:
        try:
            with open(BLURBS, encoding="utf-8") as f:
                data = json.load(f)
            _blurbs["data"] = {k: trim_blurb(v) for k, v in data.items() if isinstance(v, str)}
        except (OSError, ValueError):
            _blurbs["data"] = {}
        _blurbs["mtime"] = mtime
    return _blurbs["data"]


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
    """The file for /hall/<name>, or None. Only plain names (and posters/<name>, cards/<name>)."""
    if not _ASSET_NAME.match(name) or ".." in name:
        return None
    path = os.path.join(ASSETS, *name.split("/"))
    return path if os.path.isfile(path) else None


def served_layout(games, embed, season=None, now=None):
    """layout.json: the layout, plus each cabinet's poster when arcade has
    one, and whether games are played in a frame (embed) and whether the hall
    may reload itself to match a game's isolation (modes). The season in
    force at `now` in Denver (or the one `season` names: ?season=) tints the
    lights and adds its decor (arcade.seasons)."""
    which = seasons.pick(now, season)
    doc = layout(games, seasons.style(which, STYLE))
    lines = blurbs()
    for cabinet in doc["cabinets"]:
        cabinet["org"] = cabinet["repo"].split("/")[0]
        cabinet["blurb"] = lines.get(cabinet["slug"])
        has = os.path.isfile(os.path.join(POSTERS, cabinet["slug"] + ".jpg"))
        cabinet["poster"] = "posters/%s.jpg" % cabinet["slug"] if has else None
    doc["embed"] = bool(embed)
    doc["modes"] = True
    return seasons.dress(doc, which)


# --------------------------------------------------------------------------
# The page, with its link-preview tags

SHARE_MARK = "<!--share-meta-->"
TITLE = "Arcade Hall"
DESCRIPTION = (
    "Walk the arcade: one cabinet per browser game on play.danielstephenson.dev. Walk up to one and play it."
)
HALL_CARD_ALT = (
    "The arcade hall seen from its door: islands of lit arcade cabinets on a confetti carpet, each screen "
    "showing a game, and Roam on a stage at the back, rendered in 3D with Strata. Over it: The Arcade Hall "
    "and play.danielstephenson.dev/hall."
)
_files = {}


def _read(path):
    """A file's bytes and a short hash of them, re-read when it changes."""
    st = os.stat(path)
    key = (st.st_size, st.st_mtime_ns)
    cached = _files.get(path)
    if cached is None or cached[0] != key:
        with open(path, "rb") as f:
            data = f.read()
        cached = (key, data, hashlib.sha256(data).hexdigest()[:12])
        _files[path] = cached
    return cached[1], cached[2]


def card(slug=None):
    """(path under /hall/, short hash) of the card for a cabinet, or of the
    hall's when the cabinet has none (or no slug is given)."""
    name = "%s.jpg" % slug if slug and _ASSET_NAME.match(slug) else None
    if name is None or not os.path.isfile(os.path.join(CARDS, name)):
        name = "hall.jpg"
    return "cards/" + name, _read(os.path.join(CARDS, name))[1]


def share_meta(domain, slug=None, title=None):
    """The og:* and twitter:* tags for /hall/, or for /hall/?at=<slug> when a
    game is named (its title, its blurb, its own card if it has one)."""
    escape = html.escape
    base = "https://%s/hall/" % domain
    if slug:
        name = title or slug
        page_title = "%s, in the Arcade Hall" % name
        blurb = trim_blurb(blurbs().get(slug) or "%s has a cabinet in the arcade." % name, 100)
        if not blurb.endswith((".", "!", "?", "\u2026")):
            blurb += "."
        description = blurb + " Walk up to its cabinet in the arcade hall and play it."
        url = base + "?at=" + quote(slug)
    else:
        page_title, description, url = TITLE, DESCRIPTION, base
    path, version = card(slug)
    if path == "cards/hall.jpg":
        alt = HALL_CARD_ALT
    else:
        alt = "The %s arcade cabinet in the hall, its screen showing the game, rendered in 3D with Strata." % name
    image = "%s%s?v=%s" % (base, path, version)
    values = {k: escape(v) for k, v in (("title", page_title), ("description", description), ("url", url),
                                        ("image", image), ("alt", alt))}
    values.update(width=CARD_WIDTH, height=CARD_HEIGHT)
    return (
        '<meta property="og:type" content="website">\n'
        '<meta property="og:site_name" content="Play">\n'
        '<meta property="og:title" content="%(title)s">\n'
        '<meta property="og:description" content="%(description)s">\n'
        '<meta property="og:url" content="%(url)s">\n'
        '<meta property="og:image" content="%(image)s">\n'
        '<meta property="og:image:type" content="image/jpeg">\n'
        '<meta property="og:image:width" content="%(width)d">\n'
        '<meta property="og:image:height" content="%(height)d">\n'
        '<meta property="og:image:alt" content="%(alt)s">\n'
        '<meta name="twitter:card" content="summary_large_image">\n'
        '<meta name="twitter:title" content="%(title)s">\n'
        '<meta name="twitter:description" content="%(description)s">\n'
        '<meta name="twitter:image" content="%(image)s">\n'
        '<meta name="twitter:image:alt" content="%(alt)s">'
    ) % values


def page(domain, slug=None, title=None):
    """index.html as UTF-8 bytes, its link-preview tags filled in."""
    text = _read(os.path.join(ASSETS, "index.html"))[0].decode("utf-8")
    return text.replace(SHARE_MARK, share_meta(domain, slug, title), 1).encode("utf-8")
