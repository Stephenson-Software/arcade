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
    for directive in ("default-src 'none'", "base-uri 'none'", "form-action 'none'"):
        assert directive in landing.CSP
    assert "http" not in landing.CSP


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
    assert '<a href="https://rps.play.example.com/"><span class="title">RPS</span>' in page
    assert '<span class="host">tak.play.example.com</span></a>' in page
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
        '<li><span class="soon"><span class="title">Soon</span><span class="host">Coming soon</span></span></li>'
        in page
    )
    assert '<a href="https://rps.play.example.com/">' in page
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
