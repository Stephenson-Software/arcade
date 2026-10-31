# @author Daniel McCoy Stephenson
"""Filters over the games: by theme tag, by organisation, by engine, and an order.

One query string drives every view, so any combination is a link to share:

    /?tag=halloween&org=Preponderous-Software&engine=strata&sort=plays
    /hall/?tag=halloween&at=familiar

  tag     a theme tag from the registry's `tags:` (halloween, story, sim, ...)
  org     the GitHub organisation, the part of `repo` before the slash
  engine  strata, tak, sdl or other (the registry's `engine:`, see below)
  sort    name (the default), plays (most played first) or newest (by `added`)

One value per facet; a game matches when it matches every facet given. Values
are compared without regard to case. An unknown value is kept (it matches
nothing), so a link to a tag that no game carries yet says so rather than
quietly showing everything.

The landing page, the hall and /api/games all read the query through
Filter.parse, so the three always agree on what matches.

Standard library only: the server imports it.
"""

from urllib.parse import parse_qs, urlencode

from arcade.registry import ENGINES, default_engine, org_of  # noqa: F401  (re-exported)

# The engine a game runs on, as the registry's `engine:` names it. A `tak`
# game is always tak's console runtime; a `static` game is `other` unless its
# entry says which engine its build is (a static bundle does not say so itself:
# a Strata build and an SDL build are both an Emscripten index.html).
ENGINE_LABELS = {
    "strata": "Strata 3D",
    "tak": "tak console",
    "sdl": "SDL",
    "other": "Other",
}
FACETS = ("tag", "org", "engine")
SORTS = ("name", "plays", "newest")
SORT_LABELS = {"name": "A–Z", "plays": "Most played", "newest": "Newest"}
# Longest value kept from a query: anything longer cannot be a tag, an
# organisation or an engine, and is not echoed back into a page.
MAX_VALUE = 64


def tag_label(tag):
    """A tag as a chip shows it: halloween -> Halloween, first-programs -> First programs."""
    text = tag.replace("-", " ")
    return text[:1].upper() + text[1:]


def label_for(facet, value):
    if facet == "engine":
        return ENGINE_LABELS.get(value, value)
    if facet == "tag":
        return tag_label(value)
    return value


class Filter(object):
    """The facets and the order a query asks for."""

    __slots__ = ("tag", "org", "engine", "sort")

    def __init__(self, tag=None, org=None, engine=None, sort="name"):
        self.tag = tag
        self.org = org
        self.engine = engine
        self.sort = sort if sort in SORTS else "name"

    @classmethod
    def parse(cls, query):
        """From a query string (`tag=halloween&sort=plays`) or a parse_qs dict."""
        params = parse_qs(query or "") if not isinstance(query, dict) else query

        def first(name):
            values = params.get(name) or [""]
            value = (values[0] or "").strip()
            if not value or len(value) > MAX_VALUE:
                return None
            return value

        tag = first("tag")
        engine = first("engine")
        return cls(
            tag=tag.lower() if tag else None,
            org=first("org"),
            engine=engine.lower() if engine else None,
            sort=(first("sort") or "name").lower(),
        )

    @property
    def active(self):
        return any(getattr(self, facet) for facet in FACETS)

    def get(self, facet):
        return getattr(self, facet)

    def matches(self, game):
        """Whether a game matches. `game` is a dict with `tags`, `org` (or
        `repo`) and `engine`, as /api/games describes one."""
        if self.tag and self.tag not in [t.lower() for t in game.get("tags") or ()]:
            return False
        if self.org and self.org.lower() != (game.get("org") or org_of(game.get("repo"))).lower():
            return False
        if self.engine and self.engine != (game.get("engine") or "other").lower():
            return False
        return True

    def order(self, games):
        """`games` (dicts) in this filter's order. Ties, and the default, go by title."""
        byName = sorted(games, key=lambda g: ((g.get("title") or g["slug"]).lower(), g["slug"]))
        if self.sort == "plays":
            return sorted(byName, key=lambda g: -(g.get("plays") or 0))
        if self.sort == "newest":
            # An unknown day sorts last.
            return sorted(byName, key=lambda g: g.get("added") or "", reverse=True)
        return byName

    def apply(self, games):
        return self.order([g for g in games if self.matches(g)])

    def pairs(self, **changes):
        """The query's (name, value) pairs, in a fixed order, with `changes`
        applied (None removes a facet; sort=name is the default and left out)."""
        values = {name: getattr(self, name) for name in FACETS + ("sort",)}
        values.update(changes)
        out = [(name, values[name]) for name in FACETS if values[name]]
        if values["sort"] and values["sort"] != "name":
            out.append(("sort", values["sort"]))
        return out

    def query(self, **changes):
        """The query string for this filter with `changes`, '' when empty."""
        return urlencode(self.pairs(**changes))

    def toggled(self, facet, value):
        """The query with `facet` set to `value`, or cleared if it is already that."""
        current = getattr(self, facet)
        same = current is not None and current.lower() == value.lower()
        return self.query(**{facet: None if same else value})

    def summary(self):
        """Words for what is shown: "Halloween, Strata 3D", '' when nothing is filtered."""
        return ", ".join(label_for(facet, getattr(self, facet)) for facet in FACETS if getattr(self, facet))


def facets(games):
    """The values each facet takes over `games`, with counts, for the chips:
    {"tag": [(value, count), ...], "org": [...], "engine": [...]}, tags by
    count then name, orgs by name, engines in ENGINES order."""
    counts = {facet: {} for facet in FACETS}
    for game in games:
        for tag in game.get("tags") or ():
            counts["tag"][tag] = counts["tag"].get(tag, 0) + 1
        org = game.get("org") or org_of(game.get("repo"))
        counts["org"][org] = counts["org"].get(org, 0) + 1
        engine = game.get("engine") or "other"
        counts["engine"][engine] = counts["engine"].get(engine, 0) + 1
    rank = {name: k for k, name in enumerate(ENGINES)}
    return {
        "tag": sorted(counts["tag"].items(), key=lambda kv: (-kv[1], kv[0])),
        "org": sorted(counts["org"].items(), key=lambda kv: kv[0].lower()),
        "engine": sorted(counts["engine"].items(), key=lambda kv: (rank.get(kv[0], len(ENGINES)), kv[0])),
    }
