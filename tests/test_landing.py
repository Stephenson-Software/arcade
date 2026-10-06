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
        '<meta property="og:image:alt" content="Play: browser games by Daniel McCoy Stephenson',
        '<meta name="twitter:card" content="summary_large_image">',
        '<meta name="twitter:title" content="Play &mdash;',
        '<meta name="twitter:description" content="Browser games',
        '<meta name="twitter:image" content="https://play.example.com/og.png">',
        '<meta name="twitter:image:alt" content="Play: browser games',
    ):
        assert tag in page, tag
    assert "localhost" not in page


def test_the_share_image_is_a_png_of_the_size_the_tags_state():
    data = landing.ogImage()
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    # IHDR follows the signature: big-endian width and height at bytes 16 and 20.
    assert struct.unpack(">II", data[16:24]) == (landing.OG_IMAGE_WIDTH, landing.OG_IMAGE_HEIGHT) == (1200, 630)
    assert len(data) < 150 * 1024


def test_the_share_preview_url_follows_the_configured_domain():
    page = landing.render(Registry([]), "play.danielstephenson.dev", "https://danielstephenson.dev/play").decode("utf-8")
    assert '<meta property="og:url" content="https://play.danielstephenson.dev/">' in page
    assert '<meta property="og:image" content="https://play.danielstephenson.dev/og.png">' in page
