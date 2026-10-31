# @author Daniel McCoy Stephenson
"""Seasonal decor for the walkable hall.

A season is a date range in the arcade's own time zone (America/Denver),
a warmer or cooler tint for the hall's lights, and a decor builder that
places things in the room hall.py lays out. The hall page asks for
layout.json; arcade adds the season in force (or the one named by
`?season=`, for testing) as `layout["season"]`, and hall.js draws it.

Decor never moves a cabinet and never narrows a walkway: it sits on the
counter, against a wall, in a ceiling corner or above head height. Anything
a visitor could walk into (a jack-o'-lantern by the door) is added to the
room's obstacles, so the walk goes round it rather than through it.

To add a season: write its decor builder, add a Season to SEASONS, and give
hall.js anything new it has to draw. A season with `ready=False` is only
ever shown when asked for by name, so one can be built up over several
changes without appearing on its dates.

Standard library only, and Python 3.8 (no zoneinfo): the Denver offset is
worked out from the US daylight-saving rule.
"""

import datetime

TIME_ZONE = "America/Denver"
OFF = ("none", "off")


def _nth_sunday(year, month, n):
    first = datetime.date(year, month, 1)
    return first + datetime.timedelta(days=(6 - first.weekday()) % 7 + 7 * (n - 1))


def denver(now):
    """`now` (an aware datetime, or naive UTC) as a naive Denver wall-clock
    time: UTC-7, or UTC-6 from 02:00 on the second Sunday of March to 02:00
    on the first Sunday of November (the US rule since 2007)."""
    if now.tzinfo is not None:
        now = now.astimezone(datetime.timezone.utc).replace(tzinfo=None)
    year = now.year
    # 02:00 MST is 09:00 UTC; 02:00 MDT is 08:00 UTC.
    start = datetime.datetime.combine(_nth_sunday(year, 3, 2), datetime.time(9))
    end = datetime.datetime.combine(_nth_sunday(year, 11, 1), datetime.time(8))
    offset = -6 if start <= now < end else -7
    return now + datetime.timedelta(hours=offset)


class Season(object):
    """first and last are (month, day), both included; a range may wrap the
    new year (last before first)."""

    def __init__(self, name, first, last, light, panel, decor, ready=True, page=None):
        self.name = name
        self.first = first
        self.last = last
        self.light = light
        self.panel = panel
        self.decor = decor
        self.ready = ready
        # The colours of the season's own landing page (/halloween, arcade.landing):
        # CSS colours by role, or None for a season without one.
        self.page = page

    def covers(self, day):
        md = (day.month, day.day)
        if self.first <= self.last:
            return self.first <= md <= self.last
        return md >= self.first or md <= self.last


# --------------------------------------------------------------- Halloween

LANTERN = 0.42  # a jack-o'-lantern's width, metres
FAMILIAR = "familiar"


def _halloween(doc):
    room = doc["room"]
    near, w, h = room["near"], room["halfWidth"], room["height"]
    d0, d1 = room["door"][0], room["door"][1]
    lanterns = []
    obstacles = []
    # By the door, one each side against the wall (and a little one beside
    # the right-hand one), all facing into the hall.
    for x, size in ((d0 - 0.5, LANTERN), (d1 + 0.5, LANTERN), (d1 + 0.95, LANTERN * 0.7)):
        z = near - 0.06 - size / 2 - 0.04
        lanterns.append({"x": round(x, 4), "y": 0.0, "z": round(z, 4), "size": round(size, 4),
                         "angle": 3.141593})
        r = size / 2
        obstacles.append([round(x - r, 4), round(z - r, 4), round(x + r, 4), round(near, 4)])
    # On the change counter (hall.py room_for): its top, out of reach.
    counter = _counter(room)
    if counter:
        x0, z0, x1, z1, top = counter
        zc = z0 + 0.22
        for k, size in enumerate((LANTERN * 0.8, LANTERN * 0.6, LANTERN * 0.75)):
            x = x0 + (x1 - x0) * (0.18 + 0.32 * k)
            lanterns.append({"x": round(x, 4), "y": round(top, 4), "z": round(zc, 4), "size": round(size, 4),
                             "angle": 3.141593})
    # Cobwebs in the four ceiling corners: (x, z) of the corner and the
    # directions back into the room.
    webs = [{"x": sx * w, "z": z, "dx": -sx, "dz": dz, "size": 1.0}
            for sx in (-1, 1) for z, dz in ((near, -1), (room["far"], 1))]
    # A warm, flickering light at each group of lanterns (not drawn in the
    # economy tier, which has no point lights: the lanterns' glow stays).
    flame = [1.0, 0.55, 0.16]
    lights = [[0.0, 0.55, round(near - 0.7, 4), 3.2] + flame + [1.1]]
    if counter:
        lights.append([round((x0 + x1) / 2, 4), round(top + 0.45, 4), round(z0 - 0.3, 4), 3.0] + flame + [1.0])
    out = {"lanterns": lanterns, "cobwebs": webs, "obstacles": obstacles, "lights": lights}
    # Familiar (the Halloween cat game) on a banner hung over the walkway
    # in from the door, in sight from where a visitor starts.
    familiar = next((c for c in doc["cabinets"] if c["slug"] == FAMILIAR), None)
    if familiar is not None:
        out["banner"] = {
            "slug": FAMILIAR,
            "title": "Happy Halloween",
            "line": "%s \u00b7 the Halloween cat game" % familiar["title"],
            "poster": familiar.get("poster"),
            "x": 0.0, "y": 3.0, "z": round(near - 7.0, 4), "w": 2.4, "h": 0.8, "facing": 1,
            "colour": [1.0, 0.55, 0.12],
            "ceiling": h,
        }
        lights.append([0.0, 2.3, round(near - 6.0, 4), 3.5, 1.0, 0.62, 0.30, 0.9])
    return out


# /halloween's colours: night purple, candle-lit text, and the banner's orange
# (the "Happy Halloween" banner's colour above) for links and the chips.
HALLOWEEN_PAGE = {
    "bg": "#140d1c",
    "fg": "#f7efe4",
    "muted": "#d2bfae",
    "card": "#21162c",
    "line": "#3d2b4c",
    "accent": "#ff8c1f",
    "accentFg": "#1a0e04",
}


def _counter(room):
    """The change counter's top, (x0, z0, x1, z1, y), found as the prop that
    hall.py puts just above 1 m: None if the room has none."""
    for b in room["props"]:
        lo, hi = b["lo"], b["hi"]
        if abs(lo[1] - 1.0) < 1e-6 and abs(hi[1] - 1.06) < 1e-6:
            return lo[0], lo[2], hi[0], hi[2], hi[1]
    return None


# ------------------------------------------------------------------ winter


def _winter(doc):
    # A stub, so the next season has its place: no decor yet.
    return {"lanterns": [], "cobwebs": [], "obstacles": [], "lights": []}


SEASONS = (
    Season("halloween", (10, 20), (11, 1), light=[1.0, 0.70, 0.42], panel=[1.0, 0.86, 0.62], decor=_halloween,
           page=HALLOWEEN_PAGE),
    Season("winter", (12, 1), (1, 6), light=[0.92, 0.90, 1.0], panel=[0.94, 0.96, 1.0], decor=_winter,
           ready=False),
)
BY_NAME = {s.name: s for s in SEASONS}


def pick(now=None, override=None):
    """The Season in force at `now` (default: this moment) in Denver, or
    the one `override` names; None when there is none. An override of
    "none" or "off" turns decor off; an unknown one is ignored."""
    if override:
        override = override.strip().lower()
        if override in OFF:
            return None
        if override in BY_NAME:
            return BY_NAME[override]
    if now is None:
        now = datetime.datetime.now(datetime.timezone.utc)
    day = denver(now).date()
    for season in SEASONS:
        if season.ready and season.covers(day):
            return season
    return None


def style(season, base):
    """The hall's STYLE with the season's tint (base itself when none)."""
    if season is None:
        return base
    return dict(base, light=list(season.light), panel=list(season.panel))


def dress(doc, season):
    """Add the season's decor to a layout (hall.layout()): doc["season"],
    and any obstacles it brings to the room's. Returns doc."""
    if season is None:
        doc["season"] = None
        return doc
    decor = season.decor(doc)
    doc["room"]["obstacles"] = doc["room"]["obstacles"] + decor.pop("obstacles", [])
    decor["name"] = season.name
    decor["light"] = list(season.light)
    doc["season"] = decor
    return doc
