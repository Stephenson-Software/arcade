#!/usr/bin/env python3
"""Renders the arcade hall at the top of README.md.

One cabinet stands in the hall for every game the live registry lists at
https://play.danielstephenson.dev/api/games. Each cabinet's screen is that
game's poster image: the still that danielstephenson.dev/play shows before its
trailer plays (https://danielstephenson.dev/trailers/<name>.jpg), or, for a
game with no trailer yet, a picture from the game's own public repository
(SCREEN_OVERRIDES). A game with neither gets a plain title card. The marquee
over each screen carries the game's title. Side panels are coloured by the
GitHub organisation the game lives in. Cabinets nearer the door have more
plays; Roam, the featured game, stands alone at the end of the aisle.

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
slow dolly down the aisle) and docs/media/arcade-hall.sources.json (which
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

from PIL import Image, ImageDraw, ImageFont, ImageStat

try:
    import strata
except ImportError:  # tools/make_hall_posters.py needs only the download helpers
    strata = None

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "src"))

# The hall's layout (order, placements, colours, cabinet parts) is shared with
# the walkable hall at /hall: src/arcade/hall.py.
from arcade import hall  # noqa: E402
from arcade.hall import (  # noqa: E402
    BODY, MARQ, MARQUEE_TEX, SCREEN, SCREEN_TEX, TRIM, placements, poster_urls,
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


def cabinet_body(mb, fr, colour):
    roles = {"body": BODY, "trim": TRIM, "bezel": hall.BEZEL, "side": tuple(hall.SIDE_SHADE * c for c in colour)}
    for lo, hi, role in hall.CABINET_BOXES:
        mb.box(fr, lo, hi, roles[role])


def controls(fr, colour):
    """Joystick and buttons, as Strata primitives."""
    items = [
        strata.RenderItem(strata.PRIMITIVE_CYLINDER, fr.p(-0.22, 1.11, 0.53), (0.025, 0.10, 0.025), (0.1, 0.1, 0.1, 1)),
        strata.RenderItem(strata.PRIMITIVE_SPHERE, fr.p(-0.22, 1.17, 0.53), (0.07, 0.07, 0.07), (0.85, 0.12, 0.12, 1)),
    ]
    for k, c in enumerate([(0.95, 0.85, 0.2), colour, (0.25, 0.75, 0.35)]):
        items.append(strata.RenderItem(strata.PRIMITIVE_CYLINDER, fr.p(0.04 + 0.12 * k, 1.07, 0.52 - 0.03 * k),
                                       (0.07, 0.025, 0.07), tuple(c) + (1,)))
    return items


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


def build(engine, cabinets):
    spots = placements(len(cabinets))
    body = MeshBuilder()
    items, glow, lights = [], [], []
    for cab, (pos, angle) in zip(cabinets, spots):
        fr = Frame(pos, angle)
        cabinet_body(body, fr, cab["colour"])
        items += controls(fr, cab["colour"])
        clamp = strata.TEXTURE_MIPMAPS | strata.TEXTURE_CLAMP_U | strata.TEXTURE_CLAMP_V
        for img, (x0, y0, x1, y1, z) in ((cab["screen"], SCREEN), (cab["marquee"], MARQ)):
            q = MeshBuilder()
            q.quad([fr.p(x0, y0, z), fr.p(x1, y0, z), fr.p(x1, y1, z), fr.p(x0, y1, z)], fr.n(0, 0, 1))
            q.add(engine, texture=tex(engine, img, clamp), flags=strata.MESH_UNLIT)
        avg = tuple(v / 255 for v in ImageStat.Stat(cab["screen"]).mean)
        lift = max(max(avg), 0.2)
        avg = tuple(min(1.0, 0.25 + 0.75 * v / lift) for v in avg)
        cab["glow"] = avg
        glow.append(strata.Point(fr.p(0, 2.35, 0.3), 0.0, 1.0, tuple(cab["colour"]) + (0.12,), strata.POINT_SOFT))
        lights.append(strata.PointLight(fr.p(0, 1.5, 1.0), 2.6, avg, 1.4, 0))
    body.add(engine)

    # Floor, back wall and ceiling strip.
    end_z = spots[0][0][2]
    near, far = 7.0, end_z - 1.2
    floor = MeshBuilder()
    w = 6.0
    reps = (2 * w / 1.6, (near - far) / 1.6)
    floor.quad([(-w, 0, near), (w, 0, near), (w, 0, far), (-w, 0, far)], (0, 1, 0),
               uvs=((0, reps[1]), (reps[0], reps[1]), (reps[0], 0), (0, 0)))
    floor.add(engine, texture=tex(engine, checker()))
    wall = MeshBuilder()
    wall.quad([(-w, 0, far), (w, 0, far), (w, 4.2, far), (-w, 4.2, far)], (0, 0, 1), (0.10, 0.08, 0.15))
    for x in (-w, w):
        s = 1 if x < 0 else -1
        pts = [(x, 0, near), (x, 0, far), (x, 4.2, far), (x, 4.2, near)]
        if s < 0:
            pts = [pts[1], pts[0], pts[3], pts[2]]
        wall.quad(pts, (s, 0, 0), (0.08, 0.065, 0.12))
    wall.add(engine)

    lines = []
    for x in (-0.9, 0.9):
        lines += [strata.LineVertex((x, 3.6, near), (0.75, 0.35, 0.95, 1)),
                  strata.LineVertex((x, 3.6, far), (0.75, 0.35, 0.95, 1))]
    z = near - 3.0
    while z > far:
        glow.append(strata.Point((0.0, 3.55, z), 0.0, 1.2, (0.55, 0.35, 1.0, 0.12), strata.POINT_SOFT))
        z -= 2.4

    lighting = engine.lib.lighting_defaults(strata.LIGHTING_SPACE)
    lighting.legacy_ambient = 0.32
    engine.set_lighting(lighting)
    # Thirty-two lights at most: the nearest cabinets get their own, plus two room fills.
    fills = [strata.PointLight((0.0, 3.4, 2.0), 9.0, (0.7, 0.6, 1.0), 1.2, 0),
             strata.PointLight((0.0, 3.4, end_z + 3.0), 9.0, (0.7, 0.6, 1.0), 1.0, 0)]
    engine.set_point_lights(fills + lights[: strata.MAX_POINT_LIGHTS - len(fills)])
    return items, lines, glow, end_z


def render(engine, scene, size, eye, target):
    items, lines, glow, _ = scene
    w, h = size
    engine.set_camera(engine.lib.look_at(eye, target, fov_y_degrees=52, aspect=w / h, far_plane=120))
    engine.begin_frame(clear_color=(0.02, 0.018, 0.035, 1.0))
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


def dolly_eye(t, end_z):
    """t in [0, 1]: from just inside the door to about a third of the way down."""
    e = 0.5 - 0.5 * math.cos(math.pi * t)
    z = 4.6 - e * 9.5
    return (0.0, 1.75, z), (0.0, 1.35, end_z + 1.0)


def main():
    refresh = "--refresh" in sys.argv
    read_at = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    cabinets = load_games(refresh)
    lib = strata.load_release(RELEASE)
    os.makedirs(MEDIA, exist_ok=True)

    with strata.Engine(lib, 2560, 1280) as engine:
        scene = build(engine, cabinets)
        still = render(engine, scene, (2560, 1280), (0.35, 1.8, 4.4), (-0.1, 1.3, scene[3] + 4.0))
    still = caption(still.resize((1280, 640), Image.LANCZOS), len(cabinets))
    still.quantize(colors=256, method=Image.MEDIANCUT, dither=Image.FLOYDSTEINBERG).save(STILL, optimize=True)

    frames, count = [], 34
    with strata.Engine(lib, 960, 480) as engine:
        scene = build(engine, cabinets)
        for i in range(count):
            # Down the aisle and back, so the loop has no jump.
            t = i / (count // 2) if i < count // 2 else 2 - i / (count // 2)
            eye, target = dolly_eye(t, scene[3])
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
            "order": "featured game first (end of the aisle), then by plays at read_at, most first",
            "cabinets": [{"slug": c["game"]["slug"], "title": c["game"]["title"], "repo": c["game"]["repo"],
                          "plays": c["game"].get("plays"), "screen": c["source"] or "title card"}
                         for c in cabinets],
        }, f, indent=2)
        f.write("\n")
    for path in (STILL, LOOP, SOURCES):
        print(f"wrote {os.path.relpath(path, ROOT)} ({os.path.getsize(path) // 1024} KiB)")


if __name__ == "__main__":
    main()
