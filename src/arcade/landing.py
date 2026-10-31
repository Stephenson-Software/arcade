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

Filters (arcade.filters) are links, not a form: chips for each theme tag,
organisation and engine, and an order, all in the query string
(/?tag=halloween&engine=strata&sort=plays), so the page needs no script and
any view is a link to share. /halloween is the page for one theme tag
(THEMES), in the colours of the hall's season of the same name.
"""

import html
import os
from urllib.parse import quote

from arcade import filters, seasons

CSP = "default-src 'none'; style-src 'unsafe-inline'; img-src data:; base-uri 'none'; form-action 'none'"

# Already HTML-escaped; shared by <title>, the description and the share-preview
# tags (og:* and twitter:*).
TITLE = "Play &mdash; browser games by Daniel McCoy Stephenson"
DESCRIPTION = "Browser games by Daniel McCoy Stephenson, served by arcade. Nothing to install."

# The link-preview card named by og:image and twitter:image: og.png beside this
# module, a 1200x630 picture of arcade cabinets rendered in 3D with Strata, with
# the page's name and the play domain over it. It is drawn from og-card/card.json
# (see og-card/README.md), and OG_IMAGE_ALT is that spec's alt text, word for
# word: tests/test_landing.py fails if the two drift apart. It is served at
# /og.png on the API host only (a game's host never answers it, like
# /robots.txt). The page itself never loads it, so the CSP's "img-src data:" is
# unaffected. If the image is redrawn at another size, change the dimensions
# here with it.
OG_IMAGE_PATH = "/og.png"
OG_IMAGE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "og.png")
OG_IMAGE_WIDTH = 1200
OG_IMAGE_HEIGHT = 630
OG_IMAGE_ALT = (
    "Rows of arcade cabinets on a checkered floor at night, each screen glowing a different colour, "
    "rendered in 3D with Strata. Over it: the title Play, the line \u201cBrowser games. Nothing to install.\u201d, "
    "and the address play.danielstephenson.dev."
)
_ogImage = []


# The pages for one theme tag: /<tag>, in the colours of the hall's season of
# that name (arcade.seasons Season.page). Each is the list at /?tag=<tag>.
THEMES = {
    season.name: {
        "tag": season.name,
        "heading": "%s games" % filters.tag_label(season.name),
        "intro": (
            "Games for Halloween night, all in the browser: a cat in a New England town, lanterns, pumpkins "
            "and things that go bump. Nothing to install."
        ),
        "colours": season.page,
    }
    for season in seasons.SEASONS
    if season.page
}


def ogImage():
    """The PNG bytes of the share card, read once and kept."""
    if not _ogImage:
        with open(OG_IMAGE_FILE, "rb") as handle:
            _ogImage.append(handle.read())
    return _ogImage[0]


# Served at /robots.txt on the API host only. A game's host never answers it:
# a static game may ship its own robots.txt and must not be shadowed.
ROBOTS = "User-agent: *\nAllow: /\n"

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
.hall { display: block; margin: -1.25rem 0 2rem; color: var(--accent); font-weight: 600; }
.hall:focus-visible, .browse:focus-visible, li a:focus-visible { outline: 3px solid var(--accent); outline-offset: 3px; }
h2 { font-size: 1.15rem; margin: 0 0 .75rem; }
ul { list-style: none; margin: 0; padding: 0; display: grid; gap: .6rem; }
li { background: var(--card); border: 1px solid var(--line); border-radius: .6rem; min-width: 0; }
li a, li span.soon { display: block; padding: .8rem 1rem; color: inherit; text-decoration: none;
  overflow-wrap: anywhere; }
li a:hover .title { text-decoration: underline; }
li a.cab { padding: 0 1rem .75rem; margin-top: -.4rem; font-size: .85rem; color: var(--accent); }
li a.cab:hover { text-decoration: underline; }
.title { display: block; font-weight: 600; color: var(--accent); }
.host { display: block; font-size: .85rem; color: var(--muted); }
span.soon .title { color: var(--fg); }
footer { margin-top: 2.5rem; font-size: .85rem; color: var(--muted); }
footer a { color: inherit; }
.sr-only { position: absolute; width: 1px; height: 1px; margin: -1px; overflow: hidden; clip: rect(0 0 0 0);
  white-space: nowrap; border: 0; }
.filters { margin: 0 0 1.75rem; }
.facet { margin: 0 0 .9rem; }
.facet-name { display: block; font-size: .8rem; font-weight: 600; letter-spacing: .04em; text-transform: uppercase;
  color: var(--muted); margin: 0 0 .35rem; }
ul.chips { display: flex; flex-wrap: wrap; gap: .45rem; }
ul.chips li { background: none; border: 0; border-radius: 0; }
a.chip { display: inline-flex; align-items: center; gap: .4rem; min-height: 44px; padding: .45rem .9rem;
  border: 1px solid var(--line); border-radius: 999px; background: var(--card); color: var(--fg);
  text-decoration: none; font-size: .95rem; overflow-wrap: anywhere; }
a.chip:hover { border-color: var(--accent); }
a.chip .n { font-size: .8rem; color: var(--muted); }
a.chip[aria-current="true"] { background: var(--accent); border-color: var(--accent); color: var(--accent-fg);
  font-weight: 600; }
a.chip[aria-current="true"] .n { color: inherit; }
a.chip[aria-current="true"]::before { content: "\2713"; }
a.chip:focus-visible, a.clear:focus-visible, .shown a:focus-visible { outline: 3px solid var(--accent);
  outline-offset: 3px; }
a.clear { display: inline-flex; align-items: center; min-height: 44px; color: var(--accent); font-weight: 600; }
.meta { display: block; font-size: .8rem; color: var(--muted); margin-top: .15rem; }
.shown { color: var(--muted); }
.shown a { color: var(--accent); }
"""


def gameUrl(game, domain):
    return "https://%s.%s/" % (game.slug, domain)


def cabinetUrl(game, chosen=None):
    """The game's cabinet in the walkable hall, on this host: the hall opens in
    front of it, with the same filter (if any) lighting the matching cabinets."""
    url = "/hall/?at=%s" % quote(game.slug)
    extra = chosen.query(sort=None) if chosen is not None else ""
    return url + ("&" + extra if extra else "")


def hallUrl(chosen=None):
    extra = chosen.query(sort=None) if chosen is not None else ""
    return "/hall/" + ("?" + extra if extra else "")


def _here(query):
    return "/?" + query if query else "/"


def _chips(escape, name, label, values, chosen):
    items = []
    for value, count in values:
        current = chosen.get(name) is not None and chosen.get(name).lower() == value.lower()
        items.append(
            '<li class="c"><a class="chip" href="%s"%s>%s <span class="n">%d</span></a></li>'
            % (
                escape(_here(chosen.toggled(name, value))),
                ' aria-current="true"' if current else "",
                escape(filters.label_for(name, value)),
                count,
            )
        )
    return (
        '<div class="facet" role="group" aria-labelledby="facet-%s"><span class="facet-name" id="facet-%s">%s</span>'
        '<ul class="chips">%s</ul></div>' % (name, name, label, "".join(items))
    )


def _filterPanel(escape, facetValues, chosen):
    groups = [
        _chips(escape, "tag", "Theme", facetValues["tag"], chosen),
        _chips(escape, "org", "Organisation", facetValues["org"], chosen),
        _chips(escape, "engine", "Engine", facetValues["engine"], chosen),
    ]
    sorts = []
    for name in filters.SORTS:
        sorts.append(
            '<li class="c"><a class="chip" href="%s"%s>%s</a></li>'
            % (
                escape(_here(chosen.query(sort=name))),
                ' aria-current="true"' if chosen.sort == name else "",
                filters.SORT_LABELS[name],
            )
        )
    groups.append(
        '<div class="facet" role="group" aria-labelledby="facet-sort"><span class="facet-name" id="facet-sort">'
        'Order</span><ul class="chips">%s</ul></div>' % "".join(sorts)
    )
    clear = '<a class="clear" href="/">Clear filters</a>' if chosen.active or chosen.sort != "name" else ""
    return (
        '<section class="filters" aria-labelledby="filters-h"><h2 class="sr-only" id="filters-h">Filter and sort '
        "the games</h2>%s%s</section>" % ("".join(groups), clear)
    )


def _palette(colours):
    """A theme's colours as the page's custom properties, the same in light and dark."""
    names = (("bg", "--bg"), ("fg", "--fg"), ("muted", "--muted"), ("card", "--card"), ("line", "--line"),
             ("accent", "--accent"), ("accentFg", "--accent-fg"))
    rules = "; ".join("%s: %s" % (prop, colours[key]) for key, prop in names if key in colours)
    return ":root, :root:not(#x) { color-scheme: dark; %s; }\n" % rules


def render(registry, domain, portalUrl, deployed=lambda slug: True, plays=lambda slug: 0,
           added=lambda game: None, query="", theme=None):
    """The page as UTF-8 bytes. `deployed(slug)` says whether a game has a
    current version (only those are linked), `plays(slug)` how often it has
    been played and `added(game)` when it joined (ISO 8601), for ?sort=.
    `query` is the request's query string (arcade.filters). `theme`, a key of
    THEMES, renders that theme's page: the games with its tag, its heading
    and colours, and no other filters."""
    escape = html.escape
    themed = THEMES.get(theme) if theme else None
    chosen = filters.Filter.parse(query)
    if themed:
        chosen = filters.Filter(tag=themed["tag"], sort=chosen.sort)
    byDict = {}
    everything = []
    for game in registry:
        entry = {
            "slug": game.slug,
            "title": game.title or game.slug,
            "repo": game.repo,
            "tags": list(getattr(game, "tags", ())),
            "org": filters.org_of(game.repo),
            "engine": getattr(game, "engine", None) or filters.default_engine(game.kind),
            "plays": plays(game.slug) or 0,
            "added": added(game),
        }
        byDict[game.slug] = game
        everything.append(entry)
    shown = chosen.apply(everything)
    items = []
    for entry in shown:
        game = byDict[entry["slug"]]
        title = escape(entry["title"])
        host = escape("%s.%s" % (game.slug, domain))
        meta = " · ".join(
            [filters.tag_label(tag) for tag in entry["tags"]] + [filters.ENGINE_LABELS.get(entry["engine"], "")]
        )
        metaLine = '<span class="meta">%s</span>' % escape(meta) if meta else ""
        if deployed(game.slug):
            items.append(
                '<li><a href="%s"><span class="title">%s</span><span class="host">%s</span>%s</a>'
                '<a class="cab" href="%s">Visit its cabinet in the hall &rarr;</a></li>'
                % (escape(gameUrl(game, domain)), title, host, metaLine, escape(cabinetUrl(game, chosen)))
            )
        else:
            items.append(
                '<li><span class="soon"><span class="title">%s</span>'
                '<span class="host">Coming soon</span>%s</span></li>' % (title, metaLine)
            )
    if items:
        listing = "\n".join(items)
    elif everything:
        listing = '<li><span class="soon">No games match these filters. <a href="/">Show every game</a></span></li>'
    else:
        listing = "<li><span class=\"soon\">No games yet.</span></li>"
    portal = escape(portalUrl)
    portalLabel = escape(portalUrl.split("://", 1)[-1].rstrip("/"))
    if chosen.active:
        heading = "%s (%d of %d)" % (escape(chosen.summary()), len(shown), len(everything))
    else:
        heading = "Games served here (%d)" % len(everything)
    if themed:
        title = "%s &mdash; Play" % escape(themed["heading"])
        description = escape(themed["intro"])
        canonical = "https://%s/%s" % (escape(domain), escape(theme))
        intro = (
            '<h1>%s</h1>\n<p>%s</p>\n'
            '<a class="browse" href="%s">Walk the hall with these cabinets lit &rarr;</a>\n'
            '<a class="hall" href="%s">Filter or sort them further, or see every game &rarr;</a>\n'
            % (escape(themed["heading"]), description, escape(hallUrl(chosen)), escape(_here(chosen.query())))
        )
        panel = ""
        style = _STYLE + _palette(themed["colours"])
        heading = "%s (%d)" % (escape(themed["heading"]), len(shown))
    else:
        title = TITLE
        description = DESCRIPTION
        canonical = "https://%s/" % escape(domain)
        hallLabel = (
            "Walk the hall &rarr; these games lit up as arcade cabinets, in 3D"
            if chosen.active
            else "Walk the hall &rarr; every game as an arcade cabinet, in 3D"
        )
        intro = (
            '<h1>Play</h1>\n<p>Browser games by Daniel McCoy Stephenson. Nothing to install: pick one and it runs '
            'in this tab.</p>\n<a class="browse" href="%s">Browse all games &rarr; %s</a>\n'
            '<a class="hall" href="%s">%s</a>\n' % (portal, portalLabel, escape(hallUrl(chosen)), hallLabel)
        )
        panel = _filterPanel(escape, filters.facets(everything), chosen)
        style = _STYLE
    document = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>%(title)s</title>
<meta name="description" content="%(description)s">
<link rel="canonical" href="%(canonical)s">
<meta property="og:type" content="website">
<meta property="og:site_name" content="Play">
<meta property="og:title" content="%(title)s">
<meta property="og:description" content="%(description)s">
<meta property="og:url" content="%(canonical)s">
<meta property="og:image" content="https://%(domain)s%(ogImage)s">
<meta property="og:image:type" content="image/png">
<meta property="og:image:width" content="%(ogImageWidth)d">
<meta property="og:image:height" content="%(ogImageHeight)d">
<meta property="og:image:alt" content="%(ogImageAlt)s">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="%(title)s">
<meta name="twitter:description" content="%(description)s">
<meta name="twitter:image" content="https://%(domain)s%(ogImage)s">
<meta name="twitter:image:alt" content="%(ogImageAlt)s">
<link rel="icon" href="data:,">
<style>%(style)s</style>
</head>
<body>
<main>
%(intro)s%(panel)s
<h2 class="shown" id="games-h" aria-live="polite">%(heading)s</h2>
<ul aria-labelledby="games-h">
%(listing)s
</ul>
<footer>Served by <a href="https://github.com/Stephenson-Software/arcade">arcade</a>. Likes, scores and
details for each game are on <a href="%(portal)s">%(portalLabel)s</a>.</footer>
</main>
</body>
</html>
""" % {
        "domain": escape(domain),
        "title": title,
        "description": description,
        "canonical": canonical,
        "ogImage": OG_IMAGE_PATH,
        "ogImageWidth": OG_IMAGE_WIDTH,
        "ogImageHeight": OG_IMAGE_HEIGHT,
        "ogImageAlt": escape(OG_IMAGE_ALT),
        "style": style,
        "intro": intro,
        "panel": panel,
        "heading": heading,
        "portal": portal,
        "portalLabel": portalLabel,
        "listing": listing,
    }
    return document.encode("utf-8")
