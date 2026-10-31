"""Filter mode: registry tags and engine, arcade.filters, the landing page's
chips, /halloween, /api/games?tag= and the hall's lit cabinets."""

import json

import pytest

from arcade import filters, hall, landing, registry, seasons
from arcade.filters import Filter
from arcade.registry import Game, Registry
from helpers import TOKEN_SHA, game, registryText
from test_hall import get, running  # noqa: F401  (the fixture)

DOMAIN = "play.example.com"


# ------------------------------------------------------------ registry


def test_tags_and_engine_parse_and_default():
    loaded = registry.loads(
        registryText(
            [
                game("familiar", kind="static", tags=["halloween", "story"], engine="strata"),
                game("tidewater", tags=["story", "puzzle"]),
                game("rps", kind="static"),
            ]
        )
    )
    familiar, tidewater, rps = loaded.get("familiar"), loaded.get("tidewater"), loaded.get("rps")
    assert familiar.tags == ("halloween", "story") and familiar.engine == "strata"
    assert familiar.org == "Stephenson-Software"
    # A tak game is tak's console runtime; a static game without one is "other".
    assert tidewater.engine == "tak" and tidewater.tags == ("story", "puzzle")
    assert rps.engine == "other" and rps.tags == ()
    # An empty list is allowed.
    assert registry.loads(registryText([game("a1", tags=[])])).get("a1").tags == ()


@pytest.mark.parametrize(
    "extra, message",
    [
        (dict(tags=["Halloween"]), "must be short and lowercase"),
        (dict(tags=["x"]), "must be short and lowercase"),
        (dict(tags=["has space"]), "must be short and lowercase"),
        (dict(tags=["a" * 25]), "must be short and lowercase"),
        (dict(tags=["story", "story"]), "lists a tag twice"),
        (dict(tags=["t1", "t2", "t3", "t4", "t5", "t6", "t7"]), "at most 6"),
        (dict(kind="static", engine="unity"), "must be one of strata, tak, sdl, other"),
        (dict(engine="strata"), "is a tak game"),
    ],
)
def test_bad_tags_and_engines_are_refused_naming_the_line(extra, message):
    with pytest.raises(registry.RegistryError) as raised:
        registry.loads(registryText([game("tidewater", **extra)]))
    assert message in str(raised.value) and "line " in str(raised.value)


def test_tags_must_be_a_flow_list():
    text = registryText([game("tidewater")]) + "    tags: halloween\n"
    with pytest.raises(registry.RegistryError, match="expected a \\[flow, list\\]"):
        registry.loads(text)


def test_a_tak_game_may_say_its_engine_is_tak():
    assert registry.loads(registryText([game("tidewater", engine="tak")])).get("tidewater").engine == "tak"


# ------------------------------------------------------------- filters

GAMES = [
    {"slug": "familiar", "title": "Familiar", "repo": "Preponderous-Software/familiar",
     "tags": ["halloween", "story"], "engine": "strata", "plays": 5, "added": "2026-10-24T00:00:00Z"},
    {"slug": "tidewater", "title": "Tidewater", "repo": "Stephenson-Software/Tidewater",
     "tags": ["story", "puzzle"], "engine": "tak", "plays": 50, "added": "2026-10-01T00:00:00Z"},
    {"slug": "apex", "title": "Apex", "repo": "Preponderous-Software/apex",
     "tags": ["sim"], "engine": "other", "plays": 9, "added": None},
]


def slugs(games):
    return [g["slug"] for g in games]


def test_parse_reads_each_facet_and_ignores_the_rest():
    f = Filter.parse("tag=Halloween&org=Preponderous-Software&engine=STRATA&sort=plays&at=familiar")
    assert (f.tag, f.org, f.engine, f.sort) == ("halloween", "Preponderous-Software", "strata", "plays")
    assert f.active
    empty = Filter.parse("")
    assert not empty.active and empty.sort == "name"
    assert Filter.parse("sort=sideways").sort == "name"
    # An absurdly long value is dropped, not echoed.
    assert Filter.parse("tag=" + "a" * 200).tag is None


def test_matching_and_order():
    assert slugs(Filter.parse("tag=halloween").apply(GAMES)) == ["familiar"]
    assert slugs(Filter.parse("tag=story").apply(GAMES)) == ["familiar", "tidewater"]
    assert slugs(Filter.parse("org=preponderous-software").apply(GAMES)) == ["apex", "familiar"]
    assert slugs(Filter.parse("tag=story&engine=tak").apply(GAMES)) == ["tidewater"]
    assert slugs(Filter.parse("tag=nothing-yet").apply(GAMES)) == []
    assert slugs(Filter.parse("sort=plays").apply(GAMES)) == ["tidewater", "apex", "familiar"]
    # Newest first; a game whose day is unknown goes last.
    assert slugs(Filter.parse("sort=newest").apply(GAMES)) == ["familiar", "tidewater", "apex"]


def test_query_building_and_toggling():
    f = Filter.parse("engine=strata&tag=halloween&sort=plays")
    # A fixed order, whatever order the query came in.
    assert f.query() == "tag=halloween&engine=strata&sort=plays"
    assert f.toggled("tag", "halloween") == "engine=strata&sort=plays"
    assert f.toggled("tag", "story") == "tag=story&engine=strata&sort=plays"
    assert f.query(sort="name") == "tag=halloween&engine=strata"
    assert f.summary() == "Halloween, Strata 3D"


def test_facets_count_each_value():
    got = filters.facets(GAMES)
    assert got["tag"][0] == ("story", 2)
    assert dict(got["tag"]) == {"story": 2, "halloween": 1, "puzzle": 1, "sim": 1}
    assert got["org"] == [("Preponderous-Software", 2), ("Stephenson-Software", 1)]
    assert [e for e, _ in got["engine"]] == ["strata", "tak", "other"]


# ------------------------------------------------------------- landing


def tagged():
    return Registry(
        [
            Game("familiar", "Familiar", "Preponderous-Software/familiar", "0" * 64, kind="static",
                 tags=["halloween", "story"], engine="strata"),
            Game("tidewater", "Tidewater", "Stephenson-Software/Tidewater", "0" * 64, tags=["story", "puzzle"]),
            Game("apex", "Apex", "Preponderous-Software/apex", "0" * 64, kind="static", tags=["sim"]),
        ]
    )


def render(query="", theme=None, plays=None):
    return landing.render(
        tagged(), DOMAIN, "https://example.com/play", plays=(plays or {}).get if plays else (lambda s: 0),
        query=query, theme=theme,
    ).decode("utf-8")


def listed(page):
    """The titles in the games list, in order."""
    body = page.split('id="games-h"', 1)[1]
    return [part.split("<", 1)[0] for part in body.split('<span class="title">')[1:]]


def test_the_landing_page_has_chips_for_every_facet_and_order():
    page = render()
    assert listed(page) == ["Apex", "Familiar", "Tidewater"]
    for href, label in (
        ("/?tag=halloween", "Halloween"),
        ("/?tag=story", "Story"),
        ("/?org=Preponderous-Software", "Preponderous-Software"),
        ("/?engine=strata", "Strata 3D"),
        ("/?engine=tak", "tak console"),
        ("/?sort=plays", "Most played"),
        ("/?sort=newest", "Newest"),
    ):
        assert '<a class="chip" href="%s">%s' % (href, label) in page, href
    # A–Z is the order in force: marked current; no filter is, so nothing to clear.
    assert '<a class="chip" href="/" aria-current="true">A–Z</a>' in page
    assert "Clear filters" not in page
    assert '<span class="facet-name" id="facet-tag">Theme</span>' in page
    assert 'role="group" aria-labelledby="facet-engine"' in page


def test_the_filter_panel_is_folded_away_so_the_games_come_first():
    for query in ("", "tag=halloween", "sort=plays"):
        page = render(query)
        # A closed <details>: the chips are one tap away, not in front of the games.
        assert '<details class="filters"><summary>' in page, query
        assert "<details class=\"filters\" open" not in page, query
        assert page.index('<details class="filters">') < page.index('id="games-h"'), query
    # The folded summary says what is applied, and Clear filters stays outside the fold.
    page = render("tag=halloween&sort=plays")
    assert '<span id="filters-h">Filter and sort</span> <span class="applied">Halloween, Most played</span>' in page
    assert page.index("</details>") < page.index('<a class="clear" href="/">Clear filters</a>')
    assert '<span class="applied">' not in render()


def test_the_server_renders_the_filtered_list_without_script():
    page = render("tag=halloween")
    assert listed(page) == ["Familiar"]
    assert "Halloween (1 of 3)" in page
    # The chip that is on is marked, and links to the list without it.
    assert '<a class="chip" href="/" aria-current="true">Halloween <span class="n">1</span>' in page
    assert '<a class="clear" href="/">Clear filters</a>' in page
    # The hall link and each cabinet link carry the filter.
    assert 'href="/hall/?tag=halloween"' in page
    assert 'href="/hall/?at=familiar&amp;tag=halloween"' in page
    assert "<script" not in page
    assert listed(render("tag=story&engine=tak")) == ["Tidewater"]
    assert listed(render("sort=plays", plays={"apex": 3, "tidewater": 9, "familiar": 1})) == [
        "Tidewater", "Apex", "Familiar"]


def test_an_unknown_value_shows_nothing_and_is_escaped():
    page = render('org=<b>"x"')
    assert listed(page) == []
    assert "No games match these filters." in page
    assert "<b>" not in page and "&lt;b&gt;" in page


def test_each_game_shows_its_tags_and_engine():
    assert '<span class="meta">Halloween · Story · Strata 3D</span>' in render()


def test_the_halloween_page_is_the_tag_in_the_seasons_colours():
    assert "halloween" in landing.THEMES
    page = render(theme="halloween")
    assert listed(page) == ["Familiar"]
    assert "<h1>Halloween games</h1>" in page
    assert '<link rel="canonical" href="https://play.example.com/halloween">' in page
    assert '<a class="browse" href="/hall/?tag=halloween">' in page
    assert 'href="/?tag=halloween"' in page
    # Its colours are the Halloween season's page palette.
    for colour in seasons.BY_NAME["halloween"].page.values():
        assert colour in page
    # No chips: it is one theme's page.
    assert 'class="chip"' not in page
    # A query cannot widen it to other tags.
    assert listed(render("tag=story", theme="halloween")) == ["Familiar"]


# -------------------------------------------------------------- server

ENTRIES = [
    game("familiar", kind="static", tags=["halloween", "story"], engine="strata",
         repo="Preponderous-Software/familiar"),
    game("tidewater", tags=["story", "puzzle"]),
    game("rps", token_sha256=TOKEN_SHA, kind="static", tags=["classic"]),
]


def test_api_games_reports_tags_org_and_engine_and_filters(running):  # noqa: F811
    port = running(entries=ENTRIES)
    doc = json.loads(get(port, "/api/games")[1])
    by = {g["slug"]: g for g in doc["games"]}
    assert by["familiar"]["tags"] == ["halloween", "story"]
    assert by["familiar"]["engine"] == "strata" and by["familiar"]["org"] == "Preponderous-Software"
    assert by["tidewater"]["engine"] == "tak" and by["rps"]["engine"] == "other"
    only = json.loads(get(port, "/api/games?tag=halloween")[1])
    assert [g["slug"] for g in only["games"]] == ["familiar"]
    one = json.loads(get(port, "/api/games/familiar")[1])
    assert one["tags"] == ["halloween", "story"]


@pytest.mark.parametrize("path", ["/halloween", "/halloween/"])
def test_the_halloween_page_is_served(running, path):  # noqa: F811
    port = running(entries=ENTRIES)
    res, body = get(port, path)
    page = body.decode("utf-8")
    assert res.status == 200 and res.getheader("Content-Type").startswith("text/html")
    assert res.getheader("Content-Security-Policy") == landing.CSP
    assert "<h1>Halloween games</h1>" in page and "Familiar" in page and "Tidewater" not in page.split("games-h")[1]


def test_the_landing_page_reads_the_query(running):  # noqa: F811
    port = running(entries=ENTRIES)
    page = get(port, "/?tag=classic")[1].decode("utf-8")
    assert listed(page) == ["Rps"]


def test_a_filtered_hall_lights_only_the_matches_and_moves_nothing(running):  # noqa: F811
    port = running(entries=ENTRIES)
    plain = json.loads(get(port, "/hall/layout.json")[1])
    assert plain["filter"] is None and all(c["lit"] for c in plain["cabinets"])
    doc = json.loads(get(port, "/hall/layout.json?tag=halloween&season=none")[1])
    assert {c["slug"]: c["lit"] for c in doc["cabinets"]} == {"familiar": True, "tidewater": False, "rps": False}
    assert doc["filter"] == {"query": "tag=halloween", "summary": "Halloween", "lit": 1, "of": 3}
    # Same places, same room.
    where = lambda d: [(c["slug"], c["x"], c["z"], c["angle"]) for c in d["cabinets"]]  # noqa: E731
    unfiltered = json.loads(get(port, "/hall/layout.json?season=none")[1])
    assert where(doc) == where(unfiltered)
    assert doc["room"] == unfiltered["room"]
    assert doc["cabinets"][0]["tags"] is not None


def test_the_hall_page_with_a_filter_and_a_cabinet(running):  # noqa: F811
    port = running(entries=ENTRIES)
    res, body = get(port, "/hall/?at=familiar&tag=halloween")
    assert res.status == 200
    page = body.decode("utf-8")
    assert 'id="filtered"' in page
    # Still unfurls as the cabinet it opens at.
    assert "Familiar" in page


def test_hall_js_darkens_unlit_cabinets_and_keeps_the_filter():
    import os

    with open(os.path.join(hall.ASSETS, "hall.js")) as f:
        js = f.read()
    for needle in ("DIM_SCREEN", "shade(c, DIM_LIGHT)", "layout.cabinets.filter(lit)", "showFilter()"):
        assert needle in js, needle
    with open(os.path.join(hall.ASSETS, "hall-share.js")) as f:
        assert '["tag", "org", "engine"]' in f.read()
