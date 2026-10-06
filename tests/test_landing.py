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
        '<meta name="twitter:card" content="summary">',
        '<meta name="twitter:title" content="Play &mdash;',
        '<meta name="twitter:description" content="Browser games',
    ):
        assert tag in page, tag
    assert "localhost" not in page
    # No image exists to preview, and none is invented.
    assert "og:image" not in page and "twitter:image" not in page


def test_the_share_preview_url_follows_the_configured_domain():
    page = landing.render(Registry([]), "play.danielstephenson.dev", "https://danielstephenson.dev/play").decode("utf-8")
    assert '<meta property="og:url" content="https://play.danielstephenson.dev/">' in page
