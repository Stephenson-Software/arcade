# @author Daniel McCoy Stephenson
"""Walk replays in the hall (RFC 0030 §3): "the hall today".

A visitor who turns on "Share my walk anonymously" in the hall's settings
(off by default) leaves a coarse outline of one visit: a point every 0.5 s
of walking, rounded to 0.25 m, at most 60 s (120 points), the cabinets
walked up to, and the layout key (hall.layout_key) of the hall it was made
in. The hall uploads it once, when the visitor leaves or opens a game.

What arcade keeps, and nothing else:

  <data>/.hall-walks/<YYYY-MM-DD>.json   {"seen": n, "walks": [walk, ...]}

  walk = {"layout": "<key>", "points": [[x, z], ...], "visits": [{"slug", "at"}]}

  - the UTC day only: no time of day, no session, no IP, no user agent, no
    referrer. The walks of a day are kept shuffled, so their order says
    nothing about when each was left;
  - at most PER_DAY walks a day, a uniform random sample of the day's
    (reservoir sampling, so a flood cannot simply fill the day), and `seen`,
    how many were accepted that day (the reservoir needs it);
  - days older than KEEP_DAYS are deleted on the next write.

Every point is re-clamped here, whatever the page sent: rounded to the grid,
then pushed out of the cabinets, the room's obstacles and the walls by a
port of hall-walk.js's `resolve` (tests/test_walks.py checks the two agree),
so a forged walk can only trace a walkable route through the room.

The rate limit (one walk per client per RATE_WINDOW) holds a keyed hash of
the client's address, in memory only, and forgets it when the window ends.

Standard library only: the server imports it.
"""

import datetime
import hashlib
import json
import math
import os
import random
import re
import secrets
import tempfile
import threading
import time

DT = 0.5  # seconds between points
GRID = 0.25  # metres: points are rounded to this
MAX_POINTS = 120  # ~60 s of walking; longer walks are truncated
MAX_VISITS = 10
MIN_POINTS = 4  # fewer is not a walk worth replaying
MAX_BODY = 16 * 1024  # bytes; a full walk is ~2 KiB
RUN = 4.6  # m/s, hall-walk.js
MAX_STEP = RUN * DT * 1.25 + GRID  # metres between two points, with slack for rounding and timers
ROOM_SLACK = 1.0  # metres outside the room a point may be before the walk is refused
PER_DAY = 200
KEEP_DAYS = 7
K = 10  # fewer walks than this (today, or today and yesterday together) and none are shown
SAMPLE = 12  # walks served per request
RATE_WINDOW = 600  # seconds: one walk per client per window
RATE_CAP = 20000  # clients remembered at once; beyond it, walks are refused until the window turns
RADIUS = 0.28  # hall-walk.js: the visitor, for collisions

_KEY = re.compile(r"^[0-9a-f]{16}$")
_SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
_DAY_FILE = re.compile(r"^(\d{4}-\d{2}-\d{2})\.json$")


class Refused(ValueError):
    """A walk that is not kept; str() says why (sent back as the error)."""


# --------------------------------------------------------------------------
# A port of hall-walk.js's frame / world / resolve. Keep them in step: the
# parity test runs the same points through both.


def _clamp(v, lo, hi):
    return lo if v < lo else (hi if v > hi else v)


def _frame(x, z, angle):
    r = (math.cos(angle), -math.sin(angle))  # its right, on the floor (x, z)
    f = (math.sin(angle), math.cos(angle))  # out of its screen
    return (x, z), r, f


def world(layout):
    """{obstacles, bounds} from a layout (hall.layout / layout.json), as HallWalk.world."""
    fp = layout["cabinet"]["footprint"]
    obstacles = []
    for c in layout["cabinets"]:
        o, r, f = _frame(c["x"], c["z"], c["angle"])
        obstacles.append((o, r, f, fp[0], fp[1], fp[2], fp[3]))
    room = layout["room"]
    for x0, z0, x1, z1 in room.get("obstacles") or ():
        o, r, f = _frame(0, 0, 0)
        obstacles.append((o, r, f, x0, z0, x1, z1))
    return {"obstacles": obstacles, "bounds": (-room["halfWidth"], room["far"], room["halfWidth"], room["near"])}


def resolve(x, z, w, r=RADIUS):
    """(x, z) pushed out of every obstacle and inside the walls, as HallWalk.resolve."""
    for _ in range(4):
        moved = False
        for o, ri, fo, x0, z0, x1, z1 in w["obstacles"]:
            dx, dz = x - o[0], z - o[1]
            lx = dx * ri[0] + dz * ri[1]
            lz = dx * fo[0] + dz * fo[1]
            if lx < x0 - r or lx > x1 + r or lz < z0 - r or lz > z1 + r:
                continue
            cx, cz = _clamp(lx, x0, x1), _clamp(lz, z0, z1)
            ex, ez = lx - cx, lz - cz
            d = math.hypot(ex, ez)
            if d >= r:
                continue
            if d > 1e-6:
                nx, nz = cx + ex / d * r, cz + ez / d * r
            else:
                # Inside: out through the nearest side.
                pl, pr, pb, pf = lx - x0, x1 - lx, lz - z0, z1 - lz
                m = min(pl, pr, pb, pf)
                nx, nz = lx, lz
                if m == pl:
                    nx = x0 - r
                elif m == pr:
                    nx = x1 + r
                elif m == pb:
                    nz = z0 - r
                else:
                    nz = z1 + r
            x = o[0] + nx * ri[0] + nz * fo[0]
            z = o[1] + nx * ri[1] + nz * fo[1]
            moved = True
        b = w["bounds"]
        bx, bz = _clamp(x, b[0] + r, b[2] - r), _clamp(z, b[1] + r, b[3] - r)
        if bx != x or bz != z:
            x, z, moved = bx, bz, True
        if not moved:
            break
    return x, z


# --------------------------------------------------------------------------
# The layouts a walk may have been made in


class Layouts(object):
    """The last few hall layouts arcade has served, by layout key, in memory:
    a walk names the layout it was made in, and is clamped against that one.
    Cabinets move when the play ordering changes, so a walk left by a visitor
    who loaded the hall an hour ago may name an older key than today's."""

    def __init__(self, size=32):
        self.size = size
        self._lock = threading.Lock()
        self._known = {}  # key -> (world, frozenset of slugs), oldest first

    def remember(self, layout):
        key = layout["layoutKey"]
        with self._lock:
            if key in self._known:
                return key
            self._known[key] = (world(layout), frozenset(c["slug"] for c in layout["cabinets"]))
            while len(self._known) > self.size:
                del self._known[next(iter(self._known))]
        return key

    def get(self, key):
        with self._lock:
            return self._known.get(key)


# --------------------------------------------------------------------------
# Checking a walk


def _number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def _grid(v):
    return round(v / GRID) * GRID


def clean(payload, layouts):
    """The walk to keep, from a decoded POST body, or Refused. `layouts` is a
    Layouts (or anything with get(key) -> (world, slugs) | None)."""
    if not isinstance(payload, dict):
        raise Refused("expected a JSON object")
    extra = set(payload) - {"layout", "dt", "points", "visits"}
    if extra:
        raise Refused("unexpected field %s" % sorted(extra)[0])
    key = payload.get("layout")
    if not isinstance(key, str) or not _KEY.match(key):
        raise Refused("layout must be a layout key")
    known = layouts.get(key)
    if known is None:
        raise Refused("not a layout this hall has served")
    w, slugs = known
    if payload.get("dt") != DT:
        raise Refused("dt must be %s" % DT)
    points = payload.get("points")
    if not isinstance(points, list) or len(points) < MIN_POINTS:
        raise Refused("points must be a list of at least %d [x, z] pairs" % MIN_POINTS)
    points = points[:MAX_POINTS]  # longer walks are truncated, not refused
    b = w["bounds"]
    rounded = []
    for p in points:
        if not (isinstance(p, list) and len(p) == 2 and _number(p[0]) and _number(p[1])):
            raise Refused("each point must be [x, z]")
        x, z = p
        if not (b[0] - ROOM_SLACK <= x <= b[2] + ROOM_SLACK and b[1] - ROOM_SLACK <= z <= b[3] + ROOM_SLACK):
            raise Refused("a point is outside the room")
        q = (_grid(x), _grid(z))
        if rounded and math.hypot(q[0] - rounded[-1][0], q[1] - rounded[-1][1]) > MAX_STEP + 1e-9:
            raise Refused("two points are further apart than a run covers in %s s" % DT)
        rounded.append(q)
    visits = payload.get("visits", [])
    if not isinstance(visits, list):
        raise Refused("visits must be a list")
    if len(visits) > MAX_VISITS * 4:
        raise Refused("too many visits")
    kept_visits, last = [], -1
    for v in visits:
        if not (isinstance(v, dict) and set(v) == {"slug", "at"}):
            raise Refused('each visit must be {"slug", "at"}')
        slug, at = v["slug"], v["at"]
        if not isinstance(slug, str) or not _SLUG.match(slug) or slug not in slugs:
            raise Refused("a visit names a cabinet that is not in that layout")
        if not isinstance(at, int) or isinstance(at, bool) or at < 0:
            raise Refused("a visit's at must be a point index")
        if at < last:
            raise Refused("visits must be in walking order")
        last = at
        if at < len(rounded) and len(kept_visits) < MAX_VISITS:
            kept_visits.append({"slug": slug, "at": at})
    clamped = []
    for x, z in rounded:
        x, z = resolve(x, z, w)
        clamped.append([round(x, 2) + 0.0, round(z, 2) + 0.0])
    return {"layout": key, "points": clamped, "visits": kept_visits}


# --------------------------------------------------------------------------
# Keeping them


def today(now=None):
    now = datetime.datetime.now(datetime.timezone.utc) if now is None else now
    return now.date()


class Walks(object):
    """The day files under `root` (<data>/.hall-walks)."""

    def __init__(self, root, per_day=PER_DAY, keep_days=KEEP_DAYS, rng=None):
        self.root = root
        self.per_day = per_day
        self.keep_days = keep_days
        self.rng = rng or random.SystemRandom()
        self._lock = threading.Lock()

    def _path(self, day):
        return os.path.join(self.root, day.isoformat() + ".json")

    def _load(self, day):
        try:
            with open(self._path(day), "r", encoding="utf-8") as f:
                doc = json.load(f)
            if isinstance(doc, dict) and isinstance(doc.get("walks"), list):
                return {"seen": int(doc.get("seen") or len(doc["walks"])), "walks": doc["walks"]}
        except (OSError, ValueError, TypeError):
            pass
        return {"seen": 0, "walks": []}

    def _write(self, day, doc):
        os.makedirs(self.root, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.root, prefix=".tmp-")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(doc, f, separators=(",", ":"))
            os.replace(tmp, self._path(day))
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    def _prune(self, day):
        oldest = day - datetime.timedelta(days=self.keep_days - 1)
        try:
            names = os.listdir(self.root)
        except OSError:
            return
        for name in names:
            match = _DAY_FILE.match(name)
            if not match:
                continue
            try:
                when = datetime.date.fromisoformat(match.group(1))
            except ValueError:
                continue
            if when < oldest:
                try:
                    os.unlink(os.path.join(self.root, name))
                except OSError:
                    pass

    def add(self, walk, day=None):
        """Keep `walk` (from clean()) in the day's sample."""
        day = today() if day is None else day
        with self._lock:
            doc = self._load(day)
            doc["seen"] += 1
            if len(doc["walks"]) < self.per_day:
                doc["walks"].append(walk)
            else:
                j = self.rng.randrange(doc["seen"])
                if j < self.per_day:
                    doc["walks"][j] = walk
            self.rng.shuffle(doc["walks"])
            self._write(day, doc)
            self._prune(day)

    def sample(self, day=None, size=SAMPLE, k=K):
        """Up to `size` walks to play: today's, with yesterday's too when today
        has fewer than k, and none at all when even that is fewer than k, so a
        quiet morning's one visitor is never on show alone."""
        day = today() if day is None else day
        with self._lock:
            pool = list(self._load(day)["walks"])
            if len(pool) < k:
                pool += self._load(day - datetime.timedelta(days=1))["walks"]
        if len(pool) < k:
            return []
        return self.rng.sample(pool, min(size, len(pool)))

    def clear(self, day):
        with self._lock:
            try:
                os.unlink(self._path(day))
                return True
            except OSError:
                return False


class RateLimit(object):
    """One walk per client per window. The client's address is held only as a
    keyed hash (the key is random and lives in this process), in memory,
    until its window ends; nothing about it is ever written down."""

    def __init__(self, window=RATE_WINDOW, cap=RATE_CAP, clock=time.monotonic):
        self.window = window
        self.cap = cap
        self.clock = clock
        self._salt = secrets.token_bytes(16)
        self._lock = threading.Lock()
        self._until = {}

    def allow(self, address):
        now = self.clock()
        tag = hashlib.blake2b(address.encode("utf-8", "replace"), key=self._salt, digest_size=12).digest()
        with self._lock:
            for k in [k for k, until in self._until.items() if until <= now]:
                del self._until[k]
            if tag in self._until or len(self._until) >= self.cap:
                return False
            self._until[tag] = now + self.window
            return True

    def __len__(self):
        with self._lock:
            return len(self._until)
