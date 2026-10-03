# @author Daniel McCoy Stephenson
"""The landing page at https://play.<base>/: every game in the registry.

One small, self-contained HTML document, generated from the registry on each
request (the registry is reloaded when its file changes, so the page follows
it): no script, no stylesheet, font or image fetched from anywhere, light and
dark from the visitor's own setting, and laid out for a phone first. Its
Content-Security-Policy (CSP below) forbids every external request, so a
mistake here cannot add one silently.

A game with nothing deployed yet is listed without a link, since its address
would only answer 404.
"""

import html

CSP = "default-src 'none'; style-src 'unsafe-inline'; img-src data:; base-uri 'none'; form-action 'none'"

_STYLE = """
:root { color-scheme: light dark; --bg: #f6f7f9; --fg: #1a1c20; --muted: #5b616b; --card: #ffffff;
  --line: #dde1e7; --accent: #3758d6; --accent-fg: #ffffff; }
@media (prefers-color-scheme: dark) {
  :root { --bg: #121418; --fg: #eceef2; --muted: #a2a8b3; --card: #1b1e24; --line: #2c3139;
    --accent: #7d98ff; --accent-fg: #0d1020; }
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--fg);
  font: 16px/1.5 system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; }
main { max-width: 44rem; margin: 0 auto; padding: 2rem 16px 3rem; }
h1 { font-size: 2rem; line-height: 1.2; margin: 0 0 .5rem; }
p { margin: 0 0 1.25rem; color: var(--muted); }
.browse { display: inline-block; margin: 0 0 2rem; padding: .8rem 1.2rem; border-radius: .6rem;
  background: var(--accent); color: var(--accent-fg); font-weight: 600; text-decoration: none; }
.browse:focus-visible, li a:focus-visible { outline: 3px solid var(--accent); outline-offset: 3px; }
h2 { font-size: 1.15rem; margin: 0 0 .75rem; }
ul { list-style: none; margin: 0; padding: 0; display: grid; gap: .6rem; }
li { background: var(--card); border: 1px solid var(--line); border-radius: .6rem; min-width: 0; }
li a, li span.soon { display: block; padding: .8rem 1rem; color: inherit; text-decoration: none;
  overflow-wrap: anywhere; }
li a:hover .title { text-decoration: underline; }
.title { display: block; font-weight: 600; color: var(--accent); }
.host { display: block; font-size: .85rem; color: var(--muted); }
span.soon .title { color: var(--fg); }
footer { margin-top: 2.5rem; font-size: .85rem; color: var(--muted); }
footer a { color: inherit; }
"""


def gameUrl(game, domain):
    return "https://%s.%s/" % (game.slug, domain)


def render(registry, domain, portalUrl, deployed=lambda slug: True):
    """The page as UTF-8 bytes. `deployed(slug)` says whether a game has a
    current version (only those are linked)."""
    escape = html.escape
    games = sorted(registry, key=lambda game: ((game.title or game.slug).lower(), game.slug))
    items = []
    for game in games:
        title = escape(game.title or game.slug)
        host = escape("%s.%s" % (game.slug, domain))
        if deployed(game.slug):
            items.append(
                '<li><a href="%s"><span class="title">%s</span><span class="host">%s</span></a></li>'
                % (escape(gameUrl(game, domain)), title, host)
            )
        else:
            items.append(
                '<li><span class="soon"><span class="title">%s</span>'
                '<span class="host">Coming soon</span></span></li>' % title
            )
    listing = "\n".join(items) if items else "<li><span class=\"soon\">No games yet.</span></li>"
    portal = escape(portalUrl)
    portalLabel = escape(portalUrl.split("://", 1)[-1].rstrip("/"))
    document = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Play &mdash; browser games by Daniel McCoy Stephenson</title>
<meta name="description" content="Browser games by Daniel McCoy Stephenson, served by arcade. Nothing to install.">
<link rel="canonical" href="https://%(domain)s/">
<link rel="icon" href="data:,">
<style>%(style)s</style>
</head>
<body>
<main>
<h1>Play</h1>
<p>Browser games by Daniel McCoy Stephenson. Nothing to install: pick one and it runs in this tab.</p>
<a class="browse" href="%(portal)s">Browse all games &rarr; %(portalLabel)s</a>
<h2>Games served here (%(count)d)</h2>
<ul>
%(listing)s
</ul>
<footer>Served by <a href="https://github.com/Stephenson-Software/arcade">arcade</a>. Likes, scores and
details for each game are on <a href="%(portal)s">%(portalLabel)s</a>.</footer>
</main>
</body>
</html>
""" % {
        "domain": escape(domain),
        "style": _STYLE,
        "portal": portal,
        "portalLabel": portalLabel,
        "count": len(games),
        "listing": listing,
    }
    return document.encode("utf-8")
