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
