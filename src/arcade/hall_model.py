# @author Daniel McCoy Stephenson
"""The hall's arcade cabinet, as a mesh: one source for the walkable hall
(hall_assets/hall.js) and the README picture (tools/make_hall_media.py).

The cabinet is built in its own frame (x to its right, y up, z out of its
screen, metres; the floor at y 0) from extruded side profiles, so its edges
can be bevelled and its control deck sloped:

  - two side panels with the classic profile (a hood over the screen, a
    control deck jutting out), edged with a T-molding strip in the cabinet's
    organisation colour; their outer faces are the side art (`art`), drawn
    as one textured mesh for the whole hall;
  - the body between them: a kick plate, a coin door with two glowing coin
    slots, a sloped control deck with a joystick and buttons, a bevelled
    bezel round the screen, a speaker grille above it and the marquee box;
  - a low-detail stand-in (`lod`): the same silhouette as a few faces, inside
    the detailed cabinet; hall3d/main.cpp draws the detail within about 8 m
    of the visitor and the stand-in beyond.

Parts are plain data: positions, normals and indices, and a colour role per
vertex (`ROLES`: a fixed colour, or the organisation colour scaled), so the
page and the README tool colour them the same way. The footprint, screen
and marquee rectangles are unchanged (arcade.hall), so walking, picking and
the move into a game are untouched.

Standard library only: the server imports it.
"""

import math

# Colour roles: [r, g, b], or {"org": [k, add]} for organisation colour * k + add.
ROLES = {
    "body": [0.075, 0.075, 0.10],
    "trim": [0.035, 0.035, 0.05],
    "bezel": [0.012, 0.012, 0.018],
    "inner": {"org": [0.30, 0.02]},  # the inside faces of the side panels
    "molding": {"org": [0.70, 0.30]},  # the T-molding, bright
    "kick": {"org": [0.80, 0.0]},
    "deck": {"org": [0.42, 0.05]},  # the control panel's top
    "door": [0.22, 0.22, 0.25],
    "doordark": [0.05, 0.05, 0.06],
    "grillepanel": [0.14, 0.14, 0.17],
    "grille": [0.01, 0.01, 0.012],
    "stick": [0.10, 0.10, 0.10],
    "ball": [0.85, 0.12, 0.12],
    "button1": [0.95, 0.85, 0.20],
    "button2": {"org": [0.80, 0.20]},
    "button3": [0.25, 0.75, 0.35],
    "start": [0.90, 0.90, 0.94],
    # Unlit (the "accent" part): the coin slots glow.
    "slot": [1.0, 0.60, 0.16],
    "slotdark": [0.30, 0.07, 0.02],
}

# The side panel's outline, (z, y), round the outside from the back bottom.
SIDE_PROFILE = (
    (-0.47, 0.00), (0.42, 0.00), (0.42, 0.88), (0.70, 0.93), (0.72, 0.96), (0.72, 1.00), (0.69, 1.03),
    (0.36, 1.12), (0.36, 1.80), (0.44, 2.00), (0.44, 2.26), (0.40, 2.30), (-0.43, 2.30), (-0.47, 2.26),
)
SIDE_X = (0.50, 0.54)  # inner and outer face of the right panel (the left is mirrored)
# The body between the panels, (z, y): the pedestal, the screen housing, the
# speaker slope and the marquee box.
BODY_PROFILE = (
    (-0.45, 0.00), (0.40, 0.00), (0.40, 0.92), (0.30, 0.92), (0.30, 1.80), (0.38, 1.96), (0.40, 1.99),
    (0.40, 2.25), (0.37, 2.28), (-0.45, 2.28),
)
# The parts of a side panel's inner face the body and deck do not cover, as
# small convex pieces (z, y): beside the screen, the hood, the marquee, the
# pedestal's front, and round the deck. (Long thin triangles cost a software
# renderer far more than their pixels, so the panel is not one ring.)
INNER_FACES = (
    ((0.30, 1.115), (0.36, 1.12), (0.36, 1.80), (0.30, 1.80)),
    ((0.30, 1.80), (0.36, 1.80), (0.44, 2.00), (0.40, 1.99), (0.38, 1.96)),
    ((0.40, 1.99), (0.44, 2.00), (0.44, 2.26), (0.40, 2.30)),
    ((0.40, 0.00), (0.42, 0.00), (0.42, 0.88), (0.40, 0.9266)),
    ((0.40, 0.9266), (0.42, 0.88), (0.70, 0.93), (0.68, 0.945)),
    ((0.68, 0.945), (0.70, 0.93), (0.72, 0.96), (0.70, 0.965)),
    ((0.70, 0.965), (0.72, 0.96), (0.72, 1.00), (0.70, 0.995)),
    ((0.70, 0.995), (0.72, 1.00), (0.69, 1.03), (0.68, 1.02)),
    ((0.30, 1.115), (0.68, 1.02), (0.69, 1.03), (0.36, 1.12)),
)
# Inside the side profile, from where every edge of it is in sight: its
# faces are fans from here (no long slivers).
SIDE_CENTRE = (0.05, 1.10)
# The control deck: its top slopes down towards the player.
DECK_PROFILE = (
    (0.30, 0.92), (0.68, 0.945), (0.70, 0.965), (0.70, 0.995), (0.68, 1.02), (0.30, 1.115),
)
DECK_ROLES = ("trim", "trim", "trim", "trim", "deck", None)
# The low-detail stand-in's outline: inside the body, deck and panels everywhere.
LOD_PROFILE = (
    (-0.44, 0.01), (0.39, 0.01), (0.39, 0.93), (0.69, 0.955), (0.69, 1.005), (0.30, 1.10), (0.29, 1.10),
    (0.29, 1.80), (0.37, 1.96), (0.39, 1.99), (0.39, 2.27), (-0.44, 2.27),
)
LOD_X = 0.53
LOD_DISTANCE = 8.0  # metres: further than this, a cabinet is drawn as its stand-in

RIM_NORMALS = ((0, -1, 0), (1, 0, 0), (0, 1, 0), (-1, 0, 0))  # the bezel's outer rim: bottom, right, top, left
MOLDING_OUT = 0.008  # how far the T-molding stands off the panel's edge
MOLDING_IN = 0.006  # how far its lips reach over the panel's faces
MOLDING_LIP = 0.004  # how far its lips stand off the panel's faces

DIGITS = 4


def deck_y(z):
    """The control deck's top at z (on its slope)."""
    (z0, y0), (z1, y1) = DECK_PROFILE[4], DECK_PROFILE[5]
    return y0 + (z - z0) * (y1 - y0) / (z1 - z0)


# ------------------------------------------------------------------ meshes


def _sub(a, b):
    return [a[i] - b[i] for i in range(3)]


def _cross(a, b):
    return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]


def _dot(a, b):
    return sum(a[i] * b[i] for i in range(3))


def _norm(v):
    m = math.sqrt(_dot(v, v)) or 1.0
    return [c / m for c in v]


class Part:
    """An indexed mesh with a colour role per vertex (and uvs, for the art)."""

    def __init__(self, uvs=False):
        self.p, self.n, self.r, self.i = [], [], [], []
        self.t = [] if uvs else None

    def vertex(self, pos, normal, role, uv=None):
        self.p.append([float(v) for v in pos])
        self.n.append([float(v) for v in normal])
        self.r.append(role)
        if self.t is not None:
            self.t.append(list(uv or (0.0, 0.0)))
        return len(self.p) - 1

    def face(self, corners, normal, role, uvs=None):
        """A flat convex face (3+ corners in order round it, either way): it is
        wound counter-clockwise seen from the side `normal` points to."""
        base = len(self.p)
        for k, c in enumerate(corners):
            self.vertex(c, normal, role, uvs[k] if uvs else None)
        n = len(corners)
        a, b, c = corners[0], corners[1], corners[2]
        flip = _dot(_cross(_sub(b, a), _sub(c, a)), normal) < 0
        for k in range(1, n - 1):
            tri = (base, base + k, base + k + 1)
            self.i += [tri[0], tri[2], tri[1]] if flip else list(tri)

    def fan(self, corners, centre, normal, role, uvs=None, centre_uv=None):
        """A flat polygon that is star-shaped about `centre`, as a fan of
        triangles from there (no long slivers, unlike ear-clipping)."""
        mid = self.vertex(centre, normal, role, centre_uv)
        base = len(self.p)
        for k, c in enumerate(corners):
            self.vertex(c, normal, role, uvs[k] if uvs else None)
        n = len(corners)
        for k in range(n):
            a, b = base + k, base + (k + 1) % n
            pa, pb = corners[k], corners[(k + 1) % n]
            if _dot(_cross(_sub(pa, centre), _sub(pb, centre)), normal) < 0:
                a, b = b, a
            self.i += [mid, a, b]

    def box(self, lo, hi, role, skip=()):
        x0, y0, z0 = lo
        x1, y1, z1 = hi
        faces = {
            "+z": ([0, 0, 1], [(x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)]),
            "-z": ([0, 0, -1], [(x1, y0, z0), (x0, y0, z0), (x0, y1, z0), (x1, y1, z0)]),
            "+x": ([1, 0, 0], [(x1, y0, z1), (x1, y0, z0), (x1, y1, z0), (x1, y1, z1)]),
            "-x": ([-1, 0, 0], [(x0, y0, z0), (x0, y0, z1), (x0, y1, z1), (x0, y1, z0)]),
            "+y": ([0, 1, 0], [(x0, y1, z1), (x1, y1, z1), (x1, y1, z0), (x0, y1, z0)]),
            "-y": ([0, -1, 0], [(x0, y0, z0), (x1, y0, z0), (x1, y0, z1), (x0, y0, z1)]),
        }
        for key, (n, cs) in faces.items():
            if key not in skip:
                self.face(cs, n, role)

    def cylinder(self, centre, d, h, role, sides=8):
        """Upright, smooth-sided, with a top (no bottom: it stands on something)."""
        x, y, z = centre
        r, y0, y1 = d / 2, y - h / 2, y + h / 2
        ring = []
        for k in range(sides + 1):
            a = 2 * math.pi * k / sides
            c, s = math.cos(a), math.sin(a)
            lo = self.vertex((x + r * c, y0, z + r * s), (c, 0, s), role)
            hi = self.vertex((x + r * c, y1, z + r * s), (c, 0, s), role)
            ring.append((lo, hi))
        for k in range(sides):
            (a0, a1), (b0, b1) = ring[k], ring[k + 1]
            self.i += [a0, a1, b1, a0, b1, b0]
        top = [(x + r * math.cos(2 * math.pi * k / sides), y1, z + r * math.sin(2 * math.pi * k / sides))
               for k in range(sides)]
        self.face(top, (0, 1, 0), role)

    def sphere(self, centre, d, role, rings=5, sides=8):
        x, y, z = centre
        r = d / 2
        grid = []
        for i in range(rings + 1):
            th = math.pi * i / rings
            row = []
            for k in range(sides + 1):
                ph = 2 * math.pi * k / sides
                n = (math.sin(th) * math.cos(ph), math.cos(th), math.sin(th) * math.sin(ph))
                row.append(self.vertex((x + r * n[0], y + r * n[1], z + r * n[2]), n, role))
            grid.append(row)
        for i in range(rings):
            for k in range(sides):
                a, b, c, e = grid[i][k], grid[i + 1][k], grid[i + 1][k + 1], grid[i][k + 1]
                self.i += [a, e, c, a, c, b]

    def data(self):
        out = {
            "p": [round(v, DIGITS) for p in self.p for v in p],
            "n": [round(v, 3) for n in self.n for v in n],
            "r": list(self.r),
            "i": list(self.i),
        }
        if self.t is not None:
            out["t"] = [round(v, DIGITS) for t in self.t for v in t]
        return out


def _outward(profile):
    """Unit outward normals (in z, y) of each edge of a closed profile."""
    area = sum(profile[k][0] * profile[(k + 1) % len(profile)][1] - profile[(k + 1) % len(profile)][0] * profile[k][1]
               for k in range(len(profile)))
    out = []
    for k in range(len(profile)):
        (z0, y0), (z1, y1) = profile[k], profile[(k + 1) % len(profile)]
        dz, dy = z1 - z0, y1 - y0
        m = math.hypot(dz, dy)
        # Counter-clockwise in (z, y): outward is (dy, -dz).
        nz, ny = (dy / m, -dz / m) if area > 0 else (-dy / m, dz / m)
        out.append((nz, ny))
    return out


def _prism_edges(part, profile, x0, x1, roles):
    """The faces round an extruded profile (no caps). roles: one per edge (None: skipped)."""
    normals = _outward(profile)
    for k, role in enumerate(roles):
        if role is None:
            continue
        (za, ya), (zb, yb) = profile[k], profile[(k + 1) % len(profile)]
        nz, ny = normals[k]
        part.face([(x0, ya, za), (x1, ya, za), (x1, yb, zb), (x0, yb, zb)], (0, ny, nz), role)


def _offset_chain(profile, normals, first, last, d):
    """The profile's vertices first..last (round the outline, wrapping), moved
    d along the mitred outward normals of the edges between them."""
    n = len(profile)
    out = []
    count = (last - first) % n + 1
    for j in range(count):
        k = (first + j) % n
        z, y = profile[k]
        e_in = normals[(k - 1) % n] if j > 0 else None
        e_out = normals[k] if j < count - 1 else None
        if e_in and e_out:
            mz, my = e_in[0] + e_out[0], e_in[1] + e_out[1]
            m = math.hypot(mz, my) or 1.0
            mz, my = mz / m, my / m
            scale = d / max(0.3, mz * e_out[0] + my * e_out[1])
            out.append((z + mz * scale, y + my * scale))
        else:
            e = e_in or e_out
            out.append((z + e[0] * d, y + e[1] * d))
    return out


def _side_panel(part, side):
    """One side panel (side +1 right, -1 left): its edges, its inner face and
    its T-molding. Its outer face is the side art (art_part())."""
    xi, xo = side * SIDE_X[0], side * SIDE_X[1]
    prof = SIDE_PROFILE
    _prism_edges(part, prof, xi, xo, [None] + ["inner"] * (len(prof) - 1))
    # Its inner face, only where the body does not hide it.
    for piece in INNER_FACES:
        part.face([(xi, y, z) for z, y in piece], (-side, 0, 0), "inner")
    # The T-molding: round every edge but the bottom (vertex 1 round to vertex 0).
    normals = _outward(prof)
    outer = _offset_chain(prof, normals, 1, 0, MOLDING_OUT)
    inner = _offset_chain(prof, normals, 1, 0, -MOLDING_IN)
    xa, xb = xi, xo + side * MOLDING_LIP
    for j in range(len(outer) - 1):
        k = (1 + j) % len(prof)
        nz, ny = normals[k]
        (oz0, oy0), (oz1, oy1) = outer[j], outer[j + 1]
        (iz0, iy0), (iz1, iy1) = inner[j], inner[j + 1]
        part.face([(xa, oy0, oz0), (xb, oy0, oz0), (xb, oy1, oz1), (xa, oy1, oz1)], (0, ny, nz), "molding")
        # Its outer lip (the inner one faces into the cabinet, out of sight).
        part.face([(xb, iy0, iz0), (xb, oy0, oz0), (xb, oy1, oz1), (xb, iy1, iz1)], (side, 0, 0), "molding")


def _on_slope(a, b, s, t, offset):
    """A point on the slope from a to b ((z, y)): s along it (metres), lifted offset off it."""
    (za, ya), (zb, yb) = a, b
    m = math.hypot(zb - za, yb - ya)
    dz, dy = (zb - za) / m, (yb - ya) / m
    return za + dz * s + dy * offset, ya + dy * s - dz * offset, (dy, -dz)


def detail_part():
    """The detailed cabinet (lit)."""
    part = Part()
    # Bottom, pedestal front, under the deck, screen face, speaker slope, chamfer,
    # marquee front, chamfer, top, back.
    body_roles = [None, "body", None, "body", "body", "trim", "trim", "trim", "body", "body"]
    _prism_edges(part, BODY_PROFILE, -SIDE_X[0], SIDE_X[0], body_roles)
    _prism_edges(part, DECK_PROFILE, -SIDE_X[0], SIDE_X[0], DECK_ROLES)
    # The kick plate, in front of the pedestal.
    part.box((-0.5, 0.0, 0.40), (0.5, 0.10, 0.412), "kick", skip=("-z", "-y", "+x", "-x"))
    # The coin door, its two coin returns and its lock.
    part.box((-0.16, 0.34, 0.40), (0.16, 0.78, 0.414), "door", skip=("-z",))
    # (Plates a few millimetres proud: their edges are too thin to see.)
    flat = ("-z", "+x", "-x", "+y", "-y")
    for x in (-0.065, 0.065):
        part.box((x - 0.028, 0.47, 0.414), (x + 0.028, 0.53, 0.420), "doordark", skip=flat)
        part.box((x - 0.026, 0.645, 0.414), (x + 0.026, 0.745, 0.418), "doordark", skip=flat)
    part.box((-0.012, 0.385, 0.414), (0.012, 0.415, 0.419), "doordark", skip=flat)  # the lock
    # The bezel: a bevelled frame sloping in to the screen.
    o, i = (-0.475, 1.125, 0.475, 1.765, 0.335), (-0.425, 1.195, 0.425, 1.685, 0.301)
    ring = lambda r: [(r[0], r[1], r[4]), (r[2], r[1], r[4]), (r[2], r[3], r[4]), (r[0], r[3], r[4])]  # noqa: E731
    outer, inner = ring(o), ring(i)
    back = [(x, y, 0.30) for x, y, _ in outer]
    for k in range(4):
        a, b = outer[k], outer[(k + 1) % 4]
        ia, ib = inner[k], inner[(k + 1) % 4]
        n = _norm(_cross(_sub(b, a), _sub(ia, a)))
        if _dot(n, [0, 0, 1]) < 0:
            n = [-c for c in n]
        part.face([a, b, ib, ia], n, "bezel")
        part.face([a, b, back[(k + 1) % 4], back[k]], RIM_NORMALS[k], "trim")
    # The speaker grilles, on the slope above the screen.
    a, b = BODY_PROFILE[4], BODY_PROFILE[5]
    for x0, x1 in ((-0.42, -0.06), (0.06, 0.42)):
        z0, y0, n = _on_slope(a, b, 0.025, 0, 0.002)
        z1, y1, _ = _on_slope(a, b, 0.155, 0, 0.002)
        part.face([(x0, y0, z0), (x1, y0, z0), (x1, y1, z1), (x0, y1, z1)], (0, n[1], n[0]), "grille")
        for k in range(6):
            s = 0.035 + k * 0.021
            za, ya, _ = _on_slope(a, b, s, 0, 0.003)
            zb, yb, _ = _on_slope(a, b, s + 0.010, 0, 0.003)
            part.face([(x0 + 0.01, ya, za), (x1 - 0.01, ya, za), (x1 - 0.01, yb, zb), (x0 + 0.01, yb, zb)],
                      (0, n[1], n[0]), "grillepanel")
    # The controls, standing on the deck's slope.
    part.cylinder((-0.22, deck_y(0.53) + 0.05, 0.53), 0.022, 0.10, "stick", sides=6)
    part.sphere((-0.22, deck_y(0.53) + 0.11, 0.53), 0.065, "ball", rings=4, sides=7)
    for k, role in enumerate(("button1", "button2", "button3")):
        z = 0.53 - 0.03 * k
        part.cylinder((0.04 + 0.12 * k, deck_y(z) + 0.008, z), 0.062, 0.03, role, sides=7)
    for x in (-0.05, 0.05):
        part.cylinder((x, deck_y(0.40) + 0.006, 0.40), 0.03, 0.02, "start", sides=6)
    # The panels last: drawn after the body in front of them, most of their
    # hidden pixels fail the depth test before they are shaded.
    for side in (1, -1):
        _side_panel(part, side)
    return part


def accent_part():
    """The cabinet's unlit parts: the coin slots' glow."""
    part = Part()
    for x in (-0.065, 0.065):
        part.face([(x - 0.017, 0.66, 0.4185), (x + 0.017, 0.66, 0.4185), (x + 0.017, 0.73, 0.4185),
                   (x - 0.017, 0.73, 0.4185)], (0, 0, 1), "slot")
        part.face([(x - 0.003, 0.672, 0.419), (x + 0.003, 0.672, 0.419), (x + 0.003, 0.718, 0.419),
                   (x - 0.003, 0.718, 0.419)], (0, 0, 1), "slotdark")
    return part


def lod_part():
    """The stand-in: the silhouette, inside the detailed cabinet everywhere."""
    part = Part()
    roles = [None] + ["body"] * (len(LOD_PROFILE) - 1)
    roles[4] = "deck"
    _prism_edges(part, LOD_PROFILE, -LOD_X, LOD_X, roles)
    return part


def art_part():
    """The side panels' outer faces, textured with the side art: u across the
    panel (the front edge at 0 on the right panel and at 1 on the left, so
    the art reads the same way round, unmirrored, on both), v down it."""
    zs = [z for z, _ in SIDE_PROFILE]
    z0, z1 = min(zs), max(zs)
    top = max(y for _, y in SIDE_PROFILE)
    part = Part(uvs=True)
    def uv(z, y, side):
        u = (z - z0) / (z1 - z0)
        return (1 - u if side > 0 else u, 1 - y / top)

    cz, cy = SIDE_CENTRE
    for side in (1, -1):
        x = side * SIDE_X[1]
        corners = [(x, y, z) for z, y in SIDE_PROFILE]
        part.fan(corners, (x, cy, cz), (side, 0, 0), "art", [uv(z, y, side) for z, y in SIDE_PROFILE],
                 uv(cz, cy, side))
    return part


def art_size():
    """The side art's pixel size: the panel's outline, at 135 px a metre."""
    zs = [z for z, _ in SIDE_PROFILE]
    top = max(y for _, y in SIDE_PROFILE)
    return [int(round((max(zs) - min(zs)) * 135)), int(round(top * 135))]


def art_mask():
    """The panel's outline in the art's pixels, as the right panel shows it
    (its front at the left), for tools that draw the art; the left panel
    shows the art through the mirror image of this outline."""
    w, h = art_size()
    zs = [z for z, _ in SIDE_PROFILE]
    z0, z1 = min(zs), max(zs)
    top = max(y for _, y in SIDE_PROFILE)
    return [(round((1 - (z - z0) / (z1 - z0)) * w, 1), round((1 - y / top) * h, 1)) for z, y in SIDE_PROFILE]


_cache = {}


def model():
    """The cabinet's parts, JSON-ready (cached: it never changes)."""
    if "m" not in _cache:
        _cache["m"] = {
            "roles": ROLES,
            "detail": detail_part().data(),
            "accent": accent_part().data(),
            "lod": lod_part().data(),
            "art": art_part().data(),
            "artSize": art_size(),
            "lodDistance": LOD_DISTANCE,
        }
    return _cache["m"]


def role_colour(role, org):
    """A role's colour for a cabinet of organisation colour `org`."""
    spec = ROLES[role]
    if isinstance(spec, dict):
        k, add = spec["org"]
        return [min(1.0, k * c + add) for c in org]
    return list(spec)
