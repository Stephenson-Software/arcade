#!/usr/bin/env python3
"""Renders the arcade hall at the top of README.md.

One cabinet stands in the hall for every game the live registry lists at
https://play.danielstephenson.dev/api/games. Each cabinet's screen is that
game's poster image: the still that danielstephenson.dev/play shows before its
trailer plays (https://danielstephenson.dev/trailers/<name>.jpg), or, for a
game with no trailer yet, a picture from the game's own public repository
(SCREEN_OVERRIDES). A game with neither gets a plain title card. The marquee
over each screen carries the game's title. Side panels are coloured by the
GitHub organisation the game lives in. The floor is laid out like a real
arcade (src/arcade/hall.py): islands of back-to-back cabinets, the most played
nearest the door, a change counter by the entrance, and Roam, the featured
game, alone on a lit stage at the back wall.

Everything 3D, the screens and marquees included, is drawn by Strata v0.7.0
through its Python binding, which fetches the released library and checks it
against its pinned SHA-256. Pillow is used to decode the posters, to draw the
marquee and title-card textures before they are uploaded, and to write the
image files. Only public URLs are read.

    python3 -m venv /tmp/hall-venv
    /tmp/hall-venv/bin/pip install pillow \\
        "strata-engine @ git+https://github.com/Preponderous-Software/strata@v0.7.0#subdirectory=bindings/python"
    LIBGL_ALWAYS_SOFTWARE=1 GALLIUM_DRIVER=llvmpipe xvfb-run -a \\
        /tmp/hall-venv/bin/python tools/make_hall_media.py

Writes docs/media/arcade-hall.png (the still), docs/media/arcade-hall.gif (a
slow dolly from the door towards the stage) and docs/media/arcade-hall.sources.json (which
image went on which screen, and when the registry was read). Downloaded
images are cached in ~/.cache/arcade-hall; pass --refresh to fetch them again.
"""
import datetime
import io
import json
import math
import os
import re
import sys
import urllib.error
import urllib.request

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageStat

try:
    import strata
except ImportError:  # tools/make_hall_posters.py needs only the download helpers
    strata = None

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "src"))

# The hall's layout (order, placements, colours, cabinet parts) is shared with
# the walkable hall at /hall: src/arcade/hall.py.
from arcade import hall, hall_model  # noqa: E402
from arcade.hall import (  # noqa: E402
    MARQ, MARQUEE_TEX, SCREEN, SCREEN_TEX, poster_urls,
)
MEDIA = os.path.join(ROOT, "docs", "media")
STILL = os.path.join(MEDIA, "arcade-hall.png")
LOOP = os.path.join(MEDIA, "arcade-hall.gif")
SOURCES = os.path.join(MEDIA, "arcade-hall.sources.json")
CACHE = os.path.join(os.path.expanduser("~"), ".cache", "arcade-hall")
RELEASE = "0.7.0"

REGISTRY = "https://play.danielstephenson.dev/api/games"
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"



# ---------------------------------------------------------------- the games


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "arcade-hall-media"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read()


def cached(url, refresh):
    os.makedirs(CACHE, exist_ok=True)
    path = os.path.join(CACHE, re.sub(r"[^A-Za-z0-9._-]", "_", url))
    if refresh or not os.path.exists(path):
        try:
            data = fetch(url)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            raise
        with open(path, "wb") as f:
            f.write(data)
    with open(path, "rb") as f:
        return f.read()


def screen_image(game, refresh):
    """(PIL image, source URL) for a game's screen, or (None, None)."""
    for url in poster_urls(game):
        data = cached(url, refresh)
        if data:
            return Image.open(io.BytesIO(data)).convert("RGB"), url
    return None, None


def cover(img, size):
    """Scale and centre-crop img to fill size."""
    w, h = size
    s = max(w / img.width, h / img.height)
    img = img.resize((max(w, round(img.width * s)), max(h, round(img.height * s))), Image.LANCZOS)
    x, y = (img.width - w) // 2, (img.height - h) // 2
    return img.crop((x, y, x + w, y + h))


def fit_text(draw, text, box_w, start, floor=14):
    size = start
    while size > floor:
        font = ImageFont.truetype(FONT, size)
        if draw.textlength(text, font=font) <= box_w:
            return font
        size -= 2
    return ImageFont.truetype(FONT, floor)


def title_card(game, colour):
    w, h = SCREEN_TEX
    img = Image.new("RGB", (w, h), tuple(round(40 * c) for c in colour))
    d = ImageDraw.Draw(img)
    for y in range(0, h, 4):  # scanlines
        d.line([(0, y), (w, y)], fill=tuple(round(22 * c) for c in colour))
    font = fit_text(d, game["title"], w - 60, 64)
    d.text((w / 2, h / 2), game["title"], font=font, fill=(255, 255, 255), anchor="mm")
    return img


def marquee(title, colour):
    w, h = MARQUEE_TEX
    img = Image.new("RGB", (w, h), (12, 10, 18))
    d = ImageDraw.Draw(img)
    d.rectangle([3, 3, w - 4, h - 4], outline=tuple(round(255 * c) for c in colour), width=4)
    font = fit_text(d, title.upper(), w - 48, 62)
    glow = tuple(round(255 * (0.55 + 0.45 * c)) for c in colour)
    d.text((w / 2, h / 2 + 2), title.upper(), font=font, fill=glow, anchor="mm")
    return img


def load_games(refresh):
    games = json.loads(fetch(REGISTRY))["games"]
    out = []
    for g in hall.order(games):
        colour = hall.org_colour(g["repo"])
        img, url = screen_image(g, refresh)
        if img is None:
            img, url = title_card(g, colour), None
        out.append({
            "game": g,
            "colour": colour,
            "screen": cover(img, SCREEN_TEX),
            "marquee": marquee(g["title"], colour),
            "source": url,
        })
    return out


# ---------------------------------------------------------------- geometry


class Frame:
    """A cabinet's local frame: x to its right, y up, z out of its screen."""

    def __init__(self, pos, angle):
        self.o = pos
        self.r = (math.cos(angle), 0.0, -math.sin(angle))
        self.f = (math.sin(angle), 0.0, math.cos(angle))

    def p(self, x, y, z):
        return tuple(self.o[i] + x * self.r[i] + z * self.f[i] + (y if i == 1 else 0.0) for i in range(3))

    def n(self, x, y, z):
        return tuple(x * self.r[i] + z * self.f[i] + (y if i == 1 else 0.0) for i in range(3))


class MeshBuilder:
    def __init__(self):
        self.positions, self.normals, self.colors, self.uvs, self.indices = [], [], [], [], []

    def quad(self, corners, normal, colour=(1, 1, 1), uvs=((0, 1), (1, 1), (1, 0), (0, 0))):
        """corners counter-clockwise seen from the side the normal points to,
        starting bottom-left."""
        base = len(self.positions) // 3
        for c, uv in zip(corners, uvs):
            self.positions += c
            self.normals += normal
            self.colors += tuple(colour)
            self.uvs += uv
        self.indices += [base, base + 1, base + 2, base, base + 2, base + 3]

    def box(self, fr, lo, hi, colour):
        x0, y0, z0 = lo
        x1, y1, z1 = hi
        faces = [
            ((0, 0, 1), [(x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)]),
            ((0, 0, -1), [(x1, y0, z0), (x0, y0, z0), (x0, y1, z0), (x1, y1, z0)]),
            ((1, 0, 0), [(x1, y0, z1), (x1, y0, z0), (x1, y1, z0), (x1, y1, z1)]),
            ((-1, 0, 0), [(x0, y0, z0), (x0, y0, z1), (x0, y1, z1), (x0, y1, z0)]),
            ((0, 1, 0), [(x0, y1, z1), (x1, y1, z1), (x1, y1, z0), (x0, y1, z0)]),
            ((0, -1, 0), [(x0, y0, z0), (x1, y0, z0), (x1, y0, z1), (x0, y0, z1)]),
        ]
        for n, cs in faces:
            self.quad([fr.p(*c) for c in cs], fr.n(*n), colour)

    def add(self, engine, **kw):
        return engine.add_mesh(self.positions, self.indices, normals=self.normals, colors=self.colors,
                               uvs=self.uvs if kw.get("texture") else None, **kw)


def add_model(mb, fr, part, colour, uvs=False):
    """A part of the cabinet's model (arcade.hall_model, the same as the page
    draws) into mb, in a cabinet's frame, coloured by role."""
    base = len(mb.positions) // 3
    p, n, roles = part["p"], part["n"], part["r"]
    colours = {}
    for k, role in enumerate(roles):
        mb.positions += fr.p(*p[3 * k: 3 * k + 3])
        mb.normals += fr.n(*n[3 * k: 3 * k + 3])
        if role not in colours:
            colours[role] = tuple(hall_model.role_colour(role, colour)) if role in hall_model.ROLES else (1, 1, 1)
        mb.colors += colours[role]
        mb.uvs += tuple(part["t"][2 * k: 2 * k + 2]) if uvs else (0.0, 0.0)
    mb.indices += [base + i for i in part["i"]]


def side_image(slug, colour):
    """A cabinet's side art (tools/make_hall_posters.py), else its organisation's colour, as the page does."""
    path = os.path.join(hall.POSTERS, slug + ".side.jpg")
    if os.path.isfile(path):
        return Image.open(path).convert("RGB")
    w, h = hall_model.art_size()
    img = Image.new("RGB", (w, h))
    d = ImageDraw.Draw(img)
    for y in range(h):
        k = 150 - 90 * y / h
        d.line([(0, y), (w, y)], fill=tuple(round(k * c) for c in colour))
    return img


def checker(size=256, cells=8):
    img = Image.new("RGB", (size, size))
    d = ImageDraw.Draw(img)
    c = size // cells
    for i in range(cells):
        for j in range(cells):
            d.rectangle([i * c, j * c, i * c + c - 1, j * c + c - 1],
                        fill=(30, 28, 44) if (i + j) % 2 else (12, 11, 20))
    return img


def tex(engine, img, flags=None):
    flags = strata.TEXTURE_MIPMAPS if flags is None else flags
    img = img.convert("RGBA")
    return engine.create_texture_rgba8(img.width, img.height, img.tobytes(), flags)


def _carpet_shape(kind, s):
    """A carpet shape's outline round (0, 0), as hall.js draws it."""
    if kind == 2:
        return [(s * math.cos(k * 2.0944 - 1.5708), s * math.sin(k * 2.0944 - 1.5708)) for k in range(3)]
    if kind == 3:
        return [(s * (k / 4 - 0.5), (1 if k % 2 else -1) * s * 0.16) for k in range(5)]
    return [((s * 0.42 if k % 2 else s) * math.cos(k * math.pi / 4 - math.pi / 2),
             (s * 0.42 if k % 2 else s) * math.sin(k * math.pi / 4 - math.pi / 2)) for k in range(8)]


def carpet(style, size=256):
    """The carpet tile: the same colours and shapes as the page's (hall.carpet_pattern())."""
    img = Image.new("RGB", (size, size), tuple(round(255 * c) for c in style["carpet"]))
    d = ImageDraw.Draw(img)
    for kind, x, y, s, a, k in style["pattern"]:
        fill = tuple(round(255 * c) for c in style["carpetDots"][k])
        ca, sa = math.cos(a), math.sin(a)
        for ox in (-size, 0, size):
            for oy in (-size, 0, size):
                cx, cy = x + ox, y + oy
                if kind in (0, 1):
                    box = [cx - s, cy - s, cx + s, cy + s]
                    d.ellipse(box, fill=fill) if kind == 0 else d.ellipse(box, outline=fill, width=3)
                    continue
                pts = [(cx + px * ca - py * sa, cy + px * sa + py * ca) for px, py in _carpet_shape(kind, s)]
                if kind == 4:
                    d.polygon(pts, fill=fill)
                else:
                    d.line(pts + (pts[:1] if kind == 2 else []), fill=fill, width=3, joint="curve")
    return img


def ceiling(style, size=128):
    """The suspended ceiling's tile (two by two, with T-bars), as the page draws it."""
    img = Image.new("RGB", (size, size), tuple(round(255 * c) for c in style["ceiling"]))
    d = ImageDraw.Draw(img)
    grid = tuple(round(255 * c) for c in style.get("ceilingGrid", style["ceiling"]))
    for at in (0, size // 2):
        d.rectangle([at, 0, at + 2, size], fill=grid)
        d.rectangle([0, at, size, at + 2], fill=grid)
    return img


def neon(sg, style):
    """A neon sign (the ARCADE sign over the door), as the page draws it:
    glowing tubes for the letters and a border, on a dark board."""
    w, h = 512, round(512 * sg["h"] / sg["w"])
    img = Image.new("RGB", (w, h), (14, 8, 20))

    def tube(draw_fn, colour, width):
        c = tuple(round(255 * v) for v in colour)
        for blur, lw, col, k in ((18, width * 2.2, c, 0.55), (6, width, c, 1.0),
                                 (0, width * 0.38, tuple(round(255 * (0.75 + 0.25 * v)) for v in colour), 1.0)):
            mask = Image.new("L", (w, h), 0)
            draw_fn(ImageDraw.Draw(mask), max(1, round(lw)))
            if blur:
                glow = mask.filter(ImageFilter.GaussianBlur(blur / 2))
                img.paste(Image.new("RGB", (w, h), c), (0, 0), glow.point(lambda v: round(v * k)))
            img.paste(Image.new("RGB", (w, h), col), (0, 0), mask.point(lambda v: round(v * k)))

    m = 14
    tube(lambda d, lw: d.rounded_rectangle([m, m, w - m, h - m], radius=18, outline=255, width=lw),
         style.get("neon", (1, 0.36, 0.72)), 4)
    font = fit_text(ImageDraw.Draw(img), sg["text"], w - 90, round(h * 0.6))
    tube(lambda d, lw: d.text((w / 2, h / 2 + 3), sg["text"], font=font, fill=0, anchor="mm", stroke_width=lw,
                              stroke_fill=255), sg["colour"], 3)
    return img


def sign(sg):
    """A lit sign (the counter's, the stage's, the door's), as the page draws it."""
    w, h = 512, round(512 * sg["h"] / sg["w"])
    img = Image.new("RGB", (w, h), (20, 12, 18))
    d = ImageDraw.Draw(img)
    d.rectangle([4, 4, w - 5, h - 5], outline=tuple(round(255 * c) for c in sg["colour"]), width=5)
    font = fit_text(d, sg["text"], w - 56, round(h * 0.62))
    d.text((w / 2, h / 2 + 2), sg["text"], font=font, fill=tuple(round(255 * (0.6 + 0.4 * c)) for c in sg["colour"]),
           anchor="mm")
    return img


class Flat:
    """The room's own frame: world coordinates."""

    @staticmethod
    def p(x, y, z):
        return (x, y, z)

    @staticmethod
    def n(x, y, z):
        return (x, y, z)


CARPET_TILE = 1.6  # metres per carpet tile (hall.js)


def build(engine, cabinets, doc):
    """doc: arcade.hall.layout() for these cabinets, the same data the page draws."""
    room, style = doc["room"], doc["room"]["style"]
    body, accent = MeshBuilder(), MeshBuilder()
    items, glow, lights = [], [], []
    clamp = strata.TEXTURE_MIPMAPS | strata.TEXTURE_CLAMP_U | strata.TEXTURE_CLAMP_V
    model = doc["cabinet"]["model"]
    for cab, placed in zip(cabinets, doc["cabinets"]):
        fr = Frame((placed["x"], placed["y"], placed["z"]), placed["angle"])
        add_model(body, fr, model["detail"], cab["colour"])
        add_model(accent, fr, model["accent"], cab["colour"])
        art = MeshBuilder()
        add_model(art, fr, model["art"], cab["colour"], uvs=True)
        art.add(engine, texture=tex(engine, side_image(placed["slug"], cab["colour"]), clamp))
        for img, (x0, y0, x1, y1, z) in ((cab["screen"], SCREEN), (cab["marquee"], MARQ)):
            q = MeshBuilder()
            q.quad([fr.p(x0, y0, z), fr.p(x1, y0, z), fr.p(x1, y1, z), fr.p(x0, y1, z)], fr.n(0, 0, 1))
            q.add(engine, texture=tex(engine, img, clamp), flags=strata.MESH_UNLIT)
        avg = tuple(v / 255 for v in ImageStat.Stat(cab["screen"]).mean)
        lift = max(max(avg), 0.2)
        avg = tuple(min(1.0, 0.25 + 0.75 * v / lift) for v in avg)
        cab["glow"] = avg
        colour = tuple(0.4 + 0.6 * c for c in cab["colour"])
        glow.append(strata.Point(fr.p(0, 2.15, 0.45), 0.0, 1.3, colour + (0.16,), strata.POINT_SOFT))
        lights.append(strata.PointLight(fr.p(0, 1.5, 1.0), 2.6, avg, 1.2, 0))
    body.add(engine)
    accent.add(engine, flags=strata.MESH_UNLIT)

    # The room (hall.js buildRoom()): carpet, walls, ceiling, props and signs.
    w, near, far, h = room["halfWidth"], room["near"], room["far"], room["height"]
    floor = MeshBuilder()
    reps = (2 * w / CARPET_TILE, (near - far) / CARPET_TILE)
    floor.quad([(-w, 0, near), (w, 0, near), (w, 0, far), (-w, 0, far)], (0, 1, 0),
               uvs=((0, reps[1]), (reps[0], reps[1]), (reps[0], 0), (0, 0)))
    floor.add(engine, texture=tex(engine, carpet(style)))
    walls, lit = MeshBuilder(), MeshBuilder()

    def wall(a, b, n):
        walls.quad([(a[0], 0, a[1]), (b[0], 0, b[1]), (b[0], 1.1, b[1]), (a[0], 1.1, a[1])], n, style["wainscot"])
        walls.quad([(a[0], 1.1, a[1]), (b[0], 1.1, b[1]), (b[0], h, b[1]), (a[0], h, a[1])], n, style["wall"])

    wall((-w, far), (w, far), (0, 0, 1))
    wall((-w, near), (-w, far), (1, 0, 0))
    wall((w, far), (w, near), (-1, 0, 0))
    wall((w, near), (-w, near), (0, 0, -1))
    ceil, ct = MeshBuilder(), room["ceilingTile"]
    cr = (2 * w / ct, (near - far) / ct)
    ceil.quad([(-w, h, far), (w, h, far), (w, h, near), (-w, h, near)], (0, -1, 0),
              uvs=((0, 0), (cr[0], 0), (cr[0], cr[1]), (0, cr[1])))
    ceil.add(engine, texture=tex(engine, ceiling(style)))
    for b in room["props"]:
        (lit if b["unlit"] else walls).box(Flat, b["lo"], b["hi"], b["colour"])
    for t in room["things"]:
        add_model(walls, Frame((t["x"], t["y"], t["z"]), t["angle"]), room["thingParts"][t["part"]],
                  t.get("colour", (1, 1, 1)))
    walls.add(engine)
    lit.add(engine, flags=strata.MESH_UNLIT)
    for sg in room["signs"]:
        f = sg["facing"]
        x0, x1 = sg["x"] - sg["w"] / 2 * f, sg["x"] + sg["w"] / 2 * f
        y0, y1 = sg["y"] - sg["h"] / 2, sg["y"] + sg["h"] / 2
        q = MeshBuilder()
        q.quad([(x0, y0, sg["z"]), (x1, y0, sg["z"]), (x1, y1, sg["z"]), (x0, y1, sg["z"])], (0, 0, f))
        q.add(engine, texture=tex(engine, neon(sg, style) if sg.get("neon") else sign(sg), clamp),
              flags=strata.MESH_UNLIT)
        glow.append(strata.Point((sg["x"], sg["y"], sg["z"] + 0.15 * f), 0.0, sg["w"] * (1.2 if sg.get("neon") else 0.9),
                                 tuple(sg["colour"]) + (0.16 if sg.get("neon") else 0.10,), strata.POINT_SOFT))
    for l in room["lights"][2:]:
        glow.append(strata.Point((l[0], l[1] + 0.4, l[2]), 0.0, 1.5, tuple(style["panel"]) + (0.18,), strata.POINT_SOFT))

    lighting = engine.lib.lighting_defaults(strata.LIGHTING_SPACE)
    lighting.legacy_ambient = style["ambient"]
    engine.set_lighting(lighting)
    # The room's lights first (its two fills, the stage's spots, the ceiling),
    # then as many cabinets' own as fit.
    room_lights = [strata.PointLight(tuple(l[:3]), l[3], tuple(l[4:7]), l[7], 0) for l in room["lights"]]
    room_lights = room_lights[: strata.MAX_POINT_LIGHTS - 8]
    engine.set_point_lights(room_lights + lights[: strata.MAX_POINT_LIGHTS - len(room_lights)])
    return items, [], glow, room


def render(engine, scene, size, eye, target):
    items, lines, glow, _ = scene
    w, h = size
    engine.set_camera(engine.lib.look_at(eye, target, fov_y_degrees=56, aspect=w / h, far_plane=120))
    engine.begin_frame(clear_color=tuple(scene[3]["style"]["clear"]) + (1.0,))
    if lines:
        engine.submit_lines(lines)
    engine.submit_primitives(items)
    engine.submit_points(glow)
    engine.end_frame()
    rgba, rw, rh = engine.read_pixels()
    return Image.frombytes("RGBA", (rw, rh), rgba).convert("RGB")


def caption(img, count):
    """A small caption, drawn after the render, in the bottom-left corner."""
    img = img.copy()
    d = ImageDraw.Draw(img, "RGBA")
    s = img.width / 1280
    big = ImageFont.truetype(FONT, round(30 * s))
    small = ImageFont.truetype(FONT.replace("-Bold", ""), round(17 * s))
    x, y = round(28 * s), img.height - round(78 * s)
    d.rounded_rectangle([x - 14 * s, y - 12 * s, x + 470 * s, y + 62 * s], radius=10 * s, fill=(8, 6, 16, 170))
    d.text((x, y), "play.danielstephenson.dev", font=big, fill=(255, 255, 255))
    d.text((x, y + 38 * s), f"{count} browser games, one cabinet each. Rendered with Strata {RELEASE}.",
           font=small, fill=(200, 196, 230))
    return img


def dolly_eye(t, room):
    """t in [0, 1]: from just inside the door, down the centre walkway towards
    the stage, looking at the featured cabinet."""
    e = 0.5 - 0.5 * math.cos(math.pi * t)
    z0, z1 = room["near"] - 0.6, room["stage"]["front"] + 5.0
    stage_z = (room["stage"]["front"] + room["stage"]["back"]) / 2
    return (0.0, 1.8, z0 + (z1 - z0) * e), (0.0, 1.5, stage_z)


def main():
    refresh = "--refresh" in sys.argv
    read_at = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    cabinets = load_games(refresh)
    doc = hall.layout([c["game"] for c in cabinets])
    assert [c["slug"] for c in doc["cabinets"]] == [c["game"]["slug"] for c in cabinets]
    lib = strata.load_release(RELEASE)
    os.makedirs(MEDIA, exist_ok=True)

    with strata.Engine(lib, 2560, 1280) as engine:
        scene = build(engine, cabinets, doc)
        room = doc["room"]
        # From the entrance's right-hand corner, across the floor to the stage.
        eye = (room["halfWidth"] - 1.2, 3.2, room["near"] - 0.5)
        target = (-1.6, 0.9, (room["stage"]["front"] + room["near"]) / 2 - 2.5)
        still = render(engine, scene, (2560, 1280), eye, target)
    still = caption(still.resize((1280, 640), Image.LANCZOS), len(cabinets))
    still.quantize(colors=256, method=Image.MEDIANCUT, dither=Image.FLOYDSTEINBERG).save(STILL, optimize=True)

    frames, count = [], 34
    with strata.Engine(lib, 960, 480) as engine:
        scene = build(engine, cabinets, doc)
        for i in range(count):
            # Down the aisle and back, so the loop has no jump.
            t = i / (count // 2) if i < count // 2 else 2 - i / (count // 2)
            eye, target = dolly_eye(t, doc["room"])
            frames.append(render(engine, scene, (960, 480), eye, target).resize((440, 220), Image.LANCZOS))
    w, h = frames[0].size
    sample = Image.new("RGB", (w, h * 4))
    for k in range(4):
        sample.paste(frames[k * count // 8], (0, h * k))
    palette = sample.quantize(colors=96, method=Image.MEDIANCUT, dither=Image.NONE)
    gif = [f.quantize(palette=palette, dither=Image.NONE) for f in frames]
    gif[0].save(LOOP, save_all=True, append_images=gif[1:], duration=130, loop=0, optimize=True)

    with open(SOURCES, "w") as f:
        json.dump({
            "registry": REGISTRY,
            "read_at": read_at,
            "strata": RELEASE,
            "order": "featured game first (on the stage), then by plays at read_at, most first (nearest the door)",
            "cabinets": [{"slug": c["game"]["slug"], "title": c["game"]["title"], "repo": c["game"]["repo"],
                          "plays": c["game"].get("plays"), "screen": c["source"] or "title card"}
                         for c in cabinets],
        }, f, indent=2)
        f.write("\n")
    for path in (STILL, LOOP, SOURCES):
        print(f"wrote {os.path.relpath(path, ROOT)} ({os.path.getsize(path) // 1024} KiB)")


if __name__ == "__main__":
    main()
