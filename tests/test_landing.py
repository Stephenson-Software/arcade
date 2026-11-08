import json
import os
import struct

from arcade import landing
from arcade.registry import Game, Registry


def games(*entries):
    return Registry([Game(slug, title, "https://github.com/x/" + slug, "0" * 64) for slug, title in entries])


def test_titles_are_escaped_and_sorted():
    page = landing.render(games(("zeta", "Zeta"), ("evil", "<script>alert(1)</script>"), ("alpha", "Alpha")),
                          "play.example.com", "https://example.com/play").decode("utf-8")
    assert "<script>alert" not in page
    assert "&lt;script&gt;" in page
    assert page.index("Alpha") < page.index("Zeta")


def test_an_empty_registry_still_renders():
    page = landing.render(Registry([]), "play.example.com", "https://example.com/play").decode("utf-8")
    assert "No games yet." in page
    assert "(0)" in page


def test_the_csp_forbids_external_requests():
    # The search form may submit to this page only; the one script runs by its hash.
    for directive in ("default-src 'none'", "base-uri 'none'", "form-action 'self'", "img-src data:"):
        assert directive in landing.CSP
    assert "http" not in landing.CSP
    assert "'unsafe-inline'" not in landing.CSP.split("script-src", 1)[1]


def test_the_csp_names_the_inline_scripts_hash():
    import base64
    import hashlib

    page = landing.render(games(("rps", "RPS")), "play.example.com", "https://example.com/play").decode("utf-8")
    inline = page.split("<script>", 1)[1].split("</script>", 1)[0]
    digest = base64.b64encode(hashlib.sha256(inline.encode("utf-8")).digest()).decode("ascii")
    assert "script-src 'sha256-%s'" % digest in landing.CSP
    # Exactly one executable script, and nothing loaded from anywhere.
    assert page.count("<script>") == 1 and "<script src" not in page


def test_the_page_carries_share_preview_tags_on_its_own_domain():
    page = landing.render(games(("rps", "RPS")), "play.example.com", "https://example.com/play").decode("utf-8")
    for tag in (
        '<meta name="description" content="Browser games by Daniel McCoy Stephenson',
        '<link rel="canonical" href="https://play.example.com/">',
        '<meta property="og:type" content="website">',
        '<meta property="og:title" content="Play &mdash; browser games by Daniel McCoy Stephenson">',
        '<meta property="og:description" content="Browser games by Daniel McCoy Stephenson',
        '<meta property="og:url" content="https://play.example.com/">',
        '<meta property="og:image" content="https://play.example.com/og.png">',
        '<meta property="og:image:type" content="image/png">',
        '<meta property="og:image:width" content="1200">',
        '<meta property="og:image:height" content="630">',
        '<meta property="og:image:alt" content="Rows of arcade cabinets on a checkered floor at night',
        '<meta name="twitter:card" content="summary_large_image">',
        '<meta name="twitter:title" content="Play &mdash;',
        '<meta name="twitter:description" content="Browser games',
        '<meta name="twitter:image" content="https://play.example.com/og.png">',
        '<meta name="twitter:image:alt" content="Rows of arcade cabinets',
    ):
        assert tag in page, tag
    assert "localhost" not in page


def test_the_share_image_is_a_png_of_the_size_the_tags_state():
    data = landing.ogImage()
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    # IHDR follows the signature: big-endian width and height at bytes 16 and 20.
    assert struct.unpack(">II", data[16:24]) == (landing.OG_IMAGE_WIDTH, landing.OG_IMAGE_HEIGHT) == (1200, 630)
    assert len(data) < 150 * 1024


def test_the_share_image_alt_text_is_its_card_spec_s():
    root = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
    with open(os.path.join(root, "og-card", "card.json"), encoding="utf-8") as handle:
        spec = json.load(handle)
    assert os.path.normpath(os.path.join(root, "og-card", spec["output"])) == os.path.normpath(landing.OG_IMAGE_FILE)
    assert landing.OG_IMAGE_ALT == spec["alt"]


def test_the_share_preview_url_follows_the_configured_domain():
    page = landing.render(Registry([]), "play.danielstephenson.dev", "https://danielstephenson.dev/play").decode("utf-8")
    assert '<meta property="og:url" content="https://play.danielstephenson.dev/">' in page
    assert '<meta property="og:image" content="https://play.danielstephenson.dev/og.png">' in page


def test_every_game_is_linked_at_its_own_host_by_default():
    registry = games(("rps", "RPS"), ("tak", "Tak"))
    page = landing.render(registry, "play.example.com", "https://example.com/play").decode("utf-8")
    assert '<a href="https://rps.play.example.com/" data-play="rps"><span class="title">RPS</span>' in page
    # Then its tags and engine (none here but its engine: a tak game by default).
    assert '<span class="host">tak.play.example.com</span><span class="meta">tak console</span></a>' in page
    assert "Coming soon" not in page
    assert "Games served here (2)" in page


def test_an_undeployed_game_is_listed_without_a_link_or_host():
    asked = []

    def deployed(slug):
        asked.append(slug)
        return slug == "rps"

    page = landing.render(
        games(("rps", "RPS"), ("soon", "Soon")), "play.example.com", "https://example.com/play", deployed
    ).decode("utf-8")
    assert sorted(asked) == ["rps", "soon"]
    assert "soon.play.example.com" not in page
    assert (
        '<li data-slug="soon" data-search="soon soon tak tak console"><span class="soon"><span class="title">Soon'
        '</span><span class="host">Coming soon</span><span class="meta">tak console</span></span></li>'
        in page
    )
    assert '<a href="https://rps.play.example.com/" data-play="rps">' in page
    # Only deployed games are offered to "Continue playing" and "Random game".
    data = json.loads(page.split('<script type="application/json" id="arcade-games">', 1)[1].split("</script>")[0])
    assert data == {"rps": ["RPS", "https://rps.play.example.com/"]}
    # An undeployed game still counts towards the heading.
    assert "Games served here (2)" in page


def test_a_game_without_a_title_is_listed_by_its_slug():
    registry = games(("untitled", None))
    page = landing.render(registry, "play.example.com", "https://example.com/play").decode("utf-8")
    assert '<span class="title">untitled</span>' in page


def test_games_sort_by_title_ignoring_case_then_by_slug():
    page = landing.render(
        games(("b-two", "same"), ("a-one", "Same"), ("zed", "apple"), ("mid", None)),
        "play.example.com",
        "https://example.com/play",
    ).decode("utf-8")
    order = [page.index("https://%s.play.example.com/" % slug) for slug in ("zed", "mid", "a-one", "b-two")]
    assert order == sorted(order)


def test_the_portal_link_is_labelled_without_its_scheme_or_trailing_slash():
    page = landing.render(Registry([]), "play.example.com", "https://example.com/games/").decode("utf-8")
    assert 'class="browse" href="https://example.com/games/">Browse all games &rarr; example.com/games</a>' in page
    assert 'on <a href="https://example.com/games/">example.com/games</a>.' in page


def test_the_portal_url_is_escaped():
    page = landing.render(Registry([]), "play.example.com", 'https://example.com/?a=1&b="2"').decode("utf-8")
    assert 'href="https://example.com/?a=1&amp;b=&quot;2&quot;"' in page
    assert 'b="2"' not in page


def test_the_page_is_utf8_bytes():
    page = landing.render(games(("cafe", "Café")), "play.example.com", "https://example.com/play")
    assert isinstance(page, bytes)
    assert "Café".encode("utf-8") in page
    assert b'<meta charset="utf-8">' in page


def test_game_url_is_the_slug_under_the_domain():
    rps = games(("rps", "RPS")).get("rps")
    assert landing.gameUrl(rps, "play.example.com") == "https://rps.play.example.com/"


def test_every_deployed_game_links_to_its_cabinet_in_the_hall():
    page = landing.render(
        games(("rps", "RPS"), ("soon", "Soon")),
        "play.example.com",
        "https://example.com/play",
        lambda slug: slug == "rps",
    ).decode("utf-8")
    # Same host, so the hall opens in front of that cabinet (and unfurls with its card).
    assert '<a class="cab" href="/hall/?at=rps">Visit its cabinet in the hall &rarr;</a></li>' in page
    # A game not deployed yet has nothing to play at its cabinet.
    assert "?at=soon" not in page


def test_cabinet_links_quote_the_slug():
    assert landing.cabinetUrl(Game("a b", "A", "https://github.com/x/a", "0" * 64)) == "/hall/?at=a%20b"


# --- findability: search, Continue playing, Random game, Most played this week


def tagged():
    return Registry(
        [
            Game("familiar", "Familiar", "Preponderous-Software/familiar", "0" * 64, kind="static",
                 tags=["halloween", "story"], engine="strata"),
            Game("tidewater", "Tidewater", "Stephenson-Software/Tidewater", "0" * 64, tags=["story", "puzzle"]),
            Game("apex", "Apex", "Preponderous-Software/apex", "0" * 64, kind="static", tags=["sim"]),
        ]
    )


def page(query="", **kwargs):
    return landing.render(tagged(), "play.example.com", "https://example.com/play", query=query,
                          **kwargs).decode("utf-8")


def shown(text):
    """Slugs of the tiles a visitor sees (not hidden by a search)."""
    body = text.split('id="games-h"', 1)[1].split("</ul>", 1)[0]
    return [t.split('"', 1)[0] for t in body.split('<li data-slug="')[1:] if " hidden>" not in t.split(">", 1)[0] + ">"]


def test_the_search_box_works_without_script():
    text = page("q=STRATA")
    # A plain GET form back to this page, with the search kept in the box.
    assert '<form class="search" role="search" action="/" method="get">' in text
    assert '<input id="q" name="q" type="search" value="strata"' in text
    assert '<label class="sr-only" for="q">Search games</label>' in text
    assert shown(text) == ["familiar"]
    assert "Matching “strata” (1 of 3)" in text
    # Every word must match, in the title, slug, tags or engine.
    assert shown(page("q=story+tak")) == ["tidewater"]
    assert shown(page("q=halloween")) == ["familiar"]
    assert shown(page("q=ape")) == ["apex"]
    # The other games are still in the page (hidden) so typing can widen the list again.
    assert page("q=strata").count("<li data-slug=") == 3


def test_a_search_with_no_match_says_so_and_keeps_chips_in_the_form():
    text = page("q=zzz&tag=story&sort=plays")
    assert shown(text) == []
    assert '<li id="no-match"><span class="soon">No games match.' in text
    assert '<input type="hidden" name="tag" value="story"><input type="hidden" name="sort" value="plays">' in text
    assert '<li id="no-match" hidden>' in page("q=apex")


def test_the_search_is_escaped():
    text = page('q="><b>x')
    assert "<b>x" not in text and 'value="&quot;&gt;&lt;b&gt;x"' in text


def test_random_game_is_a_link_that_needs_no_script():
    assert '<a class="random" id="random" href="/random">Random game</a>' in page()
    # The chips in force narrow it; the search and the order do not travel.
    assert 'href="/random?tag=halloween"' in page("tag=halloween&sort=plays&q=x")


def test_continue_playing_is_hidden_until_the_browser_has_something():
    text = page()
    assert ('<section class="strip" id="recent" aria-labelledby="recent-h" hidden><h2 id="recent-h">'
            "Continue playing</h2>" in text)
    # The script keeps only slugs, in this browser's storage, behind try/catch.
    assert landing.RECENT_KEY in landing.SCRIPT and "localStorage" in landing.SCRIPT
    for use in landing.SCRIPT.split("localStorage")[1:]:
        assert "catch (e)" in use.split("\n", 3)[-1] or "catch (e)" in use, use[:60]
    assert "fetch(" not in landing.SCRIPT and "XMLHttpRequest" not in landing.SCRIPT


def test_most_played_this_week_ranks_deployed_games_over_k_and_shows_no_counts():
    weekly = {"apex": 40, "tidewater": 120, "familiar": 9}.get
    text = page(weekly=weekly)
    row = text.split('id="weekly"', 1)[1].split("</section>", 1)[0]
    assert "Most played this week" in row
    # familiar is under the k = 10 floor (activity.K), so it is not listed; no count is shown.
    assert row.index("Tidewater") < row.index("Apex") and "Familiar" not in row
    assert "120" not in row and "40" not in row
    # Undeployed games are never in it; nothing over the floor means no row at all.
    text = page(weekly=weekly, deployed=lambda slug: slug == "apex")
    assert "Tidewater" not in text.split('id="weekly"', 1)[1].split("</section>", 1)[0]
    assert 'id="weekly"' not in page(weekly=lambda slug: 3)
    # A filtered list is about the filter, so the row steps aside.
    assert 'id="weekly"' not in page("tag=story", weekly=weekly)


def test_a_new_game_has_a_badge():
    import datetime

    now = datetime.datetime(2026, 11, 8, tzinfo=datetime.timezone.utc)
    added = {"apex": "2026-11-01T04:00:00Z", "tidewater": "2026-10-02T03:31:15Z"}
    text = page(added=lambda game: added.get(game.slug), now=now)
    assert '<span class="title">Apex</span><span class="badge">New</span>' in text
    assert '<span class="title">Tidewater</span><span class="badge">' not in text
    # Newest first is ordered by the same dates.
    assert shown(page("sort=newest", added=lambda game: added.get(game.slug), now=now))[:2] == ["apex", "tidewater"]


def test_whats_new_shows_the_release_notes_on_the_tile():
    notes = {"apex": {"version": "0.3.0", "text": "Line one.\n• <b>bold</b>",
                      "url": "https://github.com/Preponderous-Software/apex/releases/tag/0.3.0"}}
    text = page(notes=lambda game: notes.get(game.slug))
    tile = text.split('<li data-slug="apex"', 1)[1].split("</li>", 1)[0]
    assert "<details class=\"notes\"><summary>What&rsquo;s new in 0.3.0</summary>" in tile
    assert "<p>Line one.\n• &lt;b&gt;bold&lt;/b&gt;</p>" in tile
    assert '<a href="https://github.com/Preponderous-Software/apex/releases/tag/0.3.0">Full release notes</a>' in tile
    assert "<details" not in text.split('<li data-slug="tidewater"', 1)[1].split("</li>", 1)[0]
    # A link anywhere but GitHub is dropped.
    notes["apex"]["url"] = "javascript:alert(1)"
    assert "javascript:" not in page(notes=lambda game: notes.get(game.slug))


def test_the_page_stays_phone_sized():
    css = landing._STYLE
    # Touch targets: the search, its button, Random, the rows, the cabinet link and What's new.
    for rule in ("form.search input {", "form.search button, a.random {", "ul.row li a {", "li a.cab {",
                 "details.notes summary {"):
        assert "min-height: 44px" in css.split(rule, 1)[1].split("}", 1)[0], rule
    # Nothing fixed-width wider than a 320 px screen: the rows and the search shrink.
    assert "min-width: 0" in css.split("form.search {", 1)[1].split("}", 1)[0]
    assert "repeat(auto-fill, minmax(9.5rem, 1fr))" in css
