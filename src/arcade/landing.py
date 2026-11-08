# @author Daniel McCoy Stephenson
"""The landing page at https://play.<base>/: every game in the registry.

One small, self-contained HTML document, generated from the registry on each
request (the registry is reloaded when its file changes, so the page follows
it): no stylesheet, font, image or script fetched from anywhere, light and
dark from the visitor's own setting, and laid out for a phone first. Its
Content-Security-Policy (CSP below) forbids every external request, so a
mistake here cannot add one silently; the one inline script (SCRIPT) runs
only because the CSP names its hash.

Everything works without script: the search box is a form the server answers
(/?q=cat), "Random game" is a link to /random (a 302 to a game picked by the
server), and "Most played this week" is rendered here. The script adds the
rest: the list narrows as you type, "Random game" picks among what is shown,
and "Continue playing" lists the games this browser opened last (their slugs
in this browser's localStorage, RECENT_KEY, which the hall writes too; never
sent anywhere). Without storage that row simply stays hidden.

A game with nothing deployed yet is listed without a link, since its address
would only answer 404.

Filters (arcade.filters) are links, not a form: chips for each theme tag,
organisation and engine, and an order, all in the query string
(/?tag=halloween&engine=strata&sort=plays), so the page needs no script and
any view is a link to share. /halloween is the page for one theme tag
(THEMES), in the colours of the hall's season of the same name.
"""

import base64
import datetime
import hashlib
import html
import json
import os
from urllib.parse import quote

from arcade import filters, seasons

# The page's one script, inline. Standard ES5 plus closest(); every storage
# access is in a try, so blocked storage (private windows, previews) only
# hides "Continue playing".
RECENT_KEY = "arcade.recent"
RECENT_MAX = 6
SCRIPT = r"""
(function () {
  "use strict";
  var KEY = "%(key)s", MAX = %(max)d;
  function read() {
    try {
      var list = JSON.parse(window.localStorage.getItem(KEY) || "[]");
      return Array.isArray(list) ? list.filter(function (s) { return typeof s === "string"; }) : [];
    } catch (e) { return []; }
  }
  function remember(slug) {
    try {
      var list = read().filter(function (s) { return s !== slug; });
      list.unshift(slug);
      window.localStorage.setItem(KEY, JSON.stringify(list.slice(0, MAX)));
    } catch (e) { /* storage blocked: nothing is remembered */ }
  }
  var games = {};
  try { games = JSON.parse(document.getElementById("arcade-games").textContent) || {}; } catch (e) { games = {}; }
  document.addEventListener("click", function (e) {
    var a = e.target && e.target.closest ? e.target.closest("a[data-play]") : null;
    if (a) remember(a.getAttribute("data-play"));
  });
  var recent = document.getElementById("recent");
  if (recent) {
    var row = recent.querySelector("ul"), count = 0;
    read().forEach(function (slug) {
      var g = games[slug];
      if (!g) return;
      var li = document.createElement("li"), a = document.createElement("a"), t = document.createElement("span");
      a.href = g[1]; a.setAttribute("data-play", slug); t.className = "title"; t.textContent = g[0];
      a.appendChild(t); li.appendChild(a); row.appendChild(li); count++;
    });
    if (count) recent.hidden = false;
  }
  var tiles = document.querySelectorAll("#games li[data-slug]");
  var random = document.getElementById("random");
  if (random) random.addEventListener("click", function (e) {
    var pool = [];
    for (var i = 0; i < tiles.length; i++) {
      var slug = tiles[i].getAttribute("data-slug");
      if (!tiles[i].hidden && games[slug]) pool.push(slug);
    }
    if (!pool.length) return;
    e.preventDefault();
    var pick = pool[Math.floor(Math.random() * pool.length)];
    remember(pick);
    window.location.assign(games[pick][1]);
  });
  var q = document.getElementById("q"), heading = document.getElementById("games-h"), none = document.getElementById("no-match");
  if (!q || !heading) return;
  var total = heading.getAttribute("data-total") || "0", facets = heading.getAttribute("data-facets") || "";
  function apply() {
    var words = q.value.toLowerCase().split(/\s+/).filter(Boolean), n = 0;
    for (var i = 0; i < tiles.length; i++) {
      var text = tiles[i].getAttribute("data-search") || "", hit = true;
      for (var k = 0; k < words.length; k++) if (text.indexOf(words[k]) < 0) { hit = false; break; }
      tiles[i].hidden = !hit;
      if (hit) n++;
    }
    if (none) none.hidden = n > 0 || !tiles.length;
    document.body.classList.toggle("searching", words.length > 0);
    var parts = facets ? [facets] : [];
    if (words.length) parts.push("matching \u201c" + words.join(" ") + "\u201d");
    var text = parts.join(", ");
    if (text.indexOf("matching") === 0) text = "M" + text.slice(1);
    heading.textContent = text ? text + " (" + n + " of " + total + ")" : "Games served here (" + total + ")";
    try {
      var url = new URL(window.location.href);
      if (words.length) url.searchParams.set("q", words.join(" ")); else url.searchParams.delete("q");
      window.history.replaceState(window.history.state, "", url.pathname + url.search + url.hash);
    } catch (e) { /* the address just stays as it was */ }
  }
  q.addEventListener("input", apply);
  q.form.addEventListener("submit", function (e) { e.preventDefault(); apply(); q.blur(); });
})();
""" % {"key": RECENT_KEY, "max": RECENT_MAX}
SCRIPT_HASH = "sha256-" + base64.b64encode(hashlib.sha256(SCRIPT.encode("utf-8")).digest()).decode("ascii")
CSP = (
    "default-src 'none'; style-src 'unsafe-inline'; img-src data:; script-src '%s'; base-uri 'none'; "
    "form-action 'self'" % SCRIPT_HASH
)

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
li a.cab { display: flex; align-items: center; min-height: 44px; padding: 0 1rem; margin-top: -.4rem;
  font-size: .85rem; color: var(--accent); }
li a.cab:hover { text-decoration: underline; }
.title { font-weight: 600; color: var(--accent); }
.host { display: block; font-size: .85rem; color: var(--muted); }
span.soon .title { color: var(--fg); }
footer { margin-top: 2.5rem; font-size: .85rem; color: var(--muted); }
footer a { color: inherit; }
.sr-only { position: absolute; width: 1px; height: 1px; margin: -1px; overflow: hidden; clip: rect(0 0 0 0);
  white-space: nowrap; border: 0; }
.filterbar { display: flex; flex-wrap: wrap; align-items: flex-start; gap: .25rem 1rem; margin: 0 0 1.25rem; }
.filters { flex: 1 1 18rem; min-width: 0; }
.filters summary { display: flex; flex-wrap: wrap; align-items: center; gap: .5rem; min-height: 44px; cursor: pointer;
  color: var(--accent); font-weight: 600; list-style: none; }
.filters summary::-webkit-details-marker { display: none; }
.filters summary::before { content: "\\25B8"; display: inline-block; transition: transform .15s; }
.filters[open] summary::before { transform: rotate(90deg); }
.filters[open] summary { margin-bottom: .6rem; }
.filters summary:focus-visible { outline: 3px solid var(--accent); outline-offset: 3px; }
.filters .applied { color: var(--muted); font-weight: 400; }
@media (prefers-reduced-motion: reduce) { .filters summary::before { transition: none; } }
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
a.chip[aria-current="true"]::before { content: "\\2713"; }
a.chip:focus-visible, a.clear:focus-visible, .shown a:focus-visible { outline: 3px solid var(--accent);
  outline-offset: 3px; }
a.clear { display: inline-flex; align-items: center; min-height: 44px; color: var(--accent); font-weight: 600; }
.meta { display: block; font-size: .8rem; color: var(--muted); margin-top: .15rem; }
.badge { display: inline-block; margin-left: .4rem; padding: 0 .45rem; border-radius: 999px; background: var(--accent);
  color: var(--accent-fg); font-size: .7rem; font-weight: 700; letter-spacing: .04em; text-transform: uppercase;
  vertical-align: .15em; }
.tools { display: flex; flex-wrap: wrap; gap: .5rem; margin: 0 0 1rem; }
form.search { display: flex; flex: 1 1 16rem; min-width: 0; gap: .5rem; margin: 0; }
form.search input { flex: 1 1 auto; min-width: 0; min-height: 44px; padding: .5rem .8rem; border: 1px solid var(--line);
  border-radius: .6rem; background: var(--card); color: var(--fg); font: inherit; }
form.search input:focus-visible { outline: 3px solid var(--accent); outline-offset: 1px; }
form.search button, a.random { display: inline-flex; align-items: center; justify-content: center; min-height: 44px;
  min-width: 44px; padding: .5rem .9rem; border: 1px solid var(--accent); border-radius: .6rem; background: var(--card);
  color: var(--accent); font: inherit; font-weight: 600; text-decoration: none; cursor: pointer; }
form.search button:focus-visible, a.random:focus-visible { outline: 3px solid var(--accent); outline-offset: 3px; }
.strip { margin: 0 0 1.5rem; }
.searching .strip { display: none; }
ul.row { grid-template-columns: repeat(auto-fill, minmax(9.5rem, 1fr)); }
ul.row li a { display: flex; flex-direction: column; justify-content: center; min-height: 44px; padding: .55rem .8rem; }
ul.row .title { font-size: .95rem; }
details.notes { padding: 0 1rem .75rem; font-size: .9rem; }
details.notes summary { display: flex; align-items: center; min-height: 44px; cursor: pointer; color: var(--accent);
  font-weight: 600; }
details.notes summary:focus-visible { outline: 3px solid var(--accent); outline-offset: 3px; }
details.notes p { margin: 0 0 .5rem; color: var(--fg); white-space: pre-line; overflow-wrap: anywhere; }
details.notes a { display: inline-flex; align-items: center; min-height: 44px; color: var(--accent); }
[hidden] { display: none !important; }
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
    # Collapsed by default so the games come first; the summary says what is
    # applied, and "Clear filters" stays outside the fold so it is always one tap.
    applied = chosen.summary()
    if chosen.sort != "name":
        applied = ", ".join(x for x in (applied, filters.SORT_LABELS[chosen.sort]) if x)
    note = ' <span class="applied">%s</span>' % escape(applied) if applied else ""
    return (
        '<div class="filterbar"><details class="filters"><summary><span id="filters-h">Filter and sort</span>%s'
        "</summary>%s</details>%s</div>" % (note, "".join(groups), clear)
    )


def _palette(colours):
    """A theme's colours as the page's custom properties, the same in light and dark."""
    names = (("bg", "--bg"), ("fg", "--fg"), ("muted", "--muted"), ("card", "--card"), ("line", "--line"),
             ("accent", "--accent"), ("accentFg", "--accent-fg"))
    rules = "; ".join("%s: %s" % (prop, colours[key]) for key, prop in names if key in colours)
    return ":root, :root:not(#x) { color-scheme: dark; %s; }\n" % rules


def _searchForm(escape, chosen):
    """The search box: a GET form the server answers (?q=), which the script
    turns into a filter as you type. The chips in force ride along."""
    kept = "".join(
        '<input type="hidden" name="%s" value="%s">' % (escape(name), escape(value))
        for name, value in chosen.pairs(q=None)
    )
    return (
        '<form class="search" role="search" action="/" method="get">'
        '<label class="sr-only" for="q">Search games</label>'
        '<input id="q" name="q" type="search" value="%s" placeholder="Search title, theme or engine" '
        'autocomplete="off" enterkeyhint="search" maxlength="%d">%s'
        '<button type="submit">Search</button></form>'
        % (escape(chosen.q or ""), filters.MAX_VALUE, kept)
    )


def randomUrl(chosen=None):
    """/random, with the chips in force: a 302 to one deployed game among them."""
    extra = chosen.query(sort=None, q=None) if chosen is not None else ""
    return "/random" + ("?" + extra if extra else "")


def _strip(escape, ident, heading, entries, domain, hidden=False):
    items = "".join(
        '<li><a href="%s" data-play="%s"><span class="title">%s</span></a></li>'
        % (escape(gameUrl(game, domain)), escape(game.slug), escape(title))
        for game, title in entries
    )
    return (
        '<section class="strip" id="%s" aria-labelledby="%s-h"%s><h2 id="%s-h">%s</h2>'
        '<ul class="row">%s</ul></section>\n' % (ident, ident, " hidden" if hidden else "", ident, heading, items)
    )


# "Most played this week": at most this many games, each with at least
# activity.K plays over the seven complete UTC days before today (the same
# floor the hall's ghosts keep), in order, and never a count.
WEEKLY_MAX = 5


def _isNew(added, now):
    from arcade import hall

    return hall.is_new(added, now)


def _notes(escape, notes):
    if not notes or not notes.get("text"):
        return ""
    more = (
        '<a href="%s">Full release notes</a>' % escape(notes["url"])
        if notes.get("url", "") and str(notes["url"]).startswith("https://github.com/")
        else ""
    )
    return '<details class="notes"><summary>What&rsquo;s new in %s</summary><p>%s</p>%s</details>' % (
        escape(notes["version"]),
        escape(notes["text"]),
        more,
    )


def render(registry, domain, portalUrl, deployed=lambda slug: True, plays=lambda slug: 0,
           added=lambda game: None, query="", theme=None, weekly=lambda slug: 0, notes=lambda game: None,
           now=None):
    """The page as UTF-8 bytes. `deployed(slug)` says whether a game has a
    current version (only those are linked), `plays(slug)` how often it has
    been played and `added(game)` when it joined (ISO 8601), for ?sort= and
    the New badge. `weekly(slug)` is its plays over the last seven complete
    UTC days ("Most played this week") and `notes(game)` its release notes
    ({"version", "text", "url"} or None, "What's new").
    `query` is the request's query string (arcade.filters). `theme`, a key of
    THEMES, renders that theme's page: the games with its tag, its heading
    and colours, and no other filters."""
    escape = html.escape
    themed = THEMES.get(theme) if theme else None
    chosen = filters.Filter.parse(query)
    if themed:
        chosen = filters.Filter(tag=themed["tag"], sort=chosen.sort, q=chosen.q)
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
    # Every game the chips allow is in the list; a search only hides the ones
    # it does not find, so the script can widen it again as the words change.
    facetsOnly = filters.Filter(tag=chosen.tag, org=chosen.org, engine=chosen.engine, sort=chosen.sort)
    candidates = facetsOnly.apply(everything)
    items = []
    found = 0
    live = {}
    for entry in candidates:
        game = byDict[entry["slug"]]
        title = escape(entry["title"])
        host = escape("%s.%s" % (game.slug, domain))
        meta = " · ".join(
            [filters.tag_label(tag) for tag in entry["tags"]] + [filters.ENGINE_LABELS.get(entry["engine"], "")]
        )
        metaLine = '<span class="meta">%s</span>' % escape(meta) if meta else ""
        hit = chosen.found(entry) if chosen.q else True
        found += hit
        attrs = ' data-slug="%s" data-search="%s"%s' % (
            escape(game.slug), escape(filters.search_text(entry)), "" if hit else " hidden"
        )
        badge = '<span class="badge">New</span>' if _isNew(entry["added"], now) else ""
        if deployed(game.slug):
            live[game.slug] = [entry["title"], gameUrl(game, domain)]
            items.append(
                '<li%s><a href="%s" data-play="%s"><span class="title">%s</span>%s<span class="host">%s</span>%s</a>'
                '<a class="cab" href="%s">Visit its cabinet in the hall &rarr;</a>%s</li>'
                % (attrs, escape(gameUrl(game, domain)), escape(game.slug), title, badge, host, metaLine,
                   escape(cabinetUrl(game, chosen)), _notes(escape, notes(game)))
            )
        else:
            items.append(
                '<li%s><span class="soon"><span class="title">%s</span>%s'
                '<span class="host">Coming soon</span>%s</span></li>' % (attrs, title, badge, metaLine)
            )
    if items:
        noMatch = (
            '<li id="no-match"%s><span class="soon">No games match. <a href="/">Show every game</a></span></li>'
            % ("" if not found else " hidden")
        )
        listing = "\n".join(items + [noMatch])
    elif everything:
        listing = '<li><span class="soon">No games match these filters. <a href="/">Show every game</a></span></li>'
    else:
        listing = "<li><span class=\"soon\">No games yet.</span></li>"
    portal = escape(portalUrl)
    portalLabel = escape(portalUrl.split("://", 1)[-1].rstrip("/"))
    if chosen.active:
        heading = "%s (%d of %d)" % (escape(chosen.summary()), found, len(everything))
    else:
        heading = "Games served here (%d)" % len(everything)
    facetWords = escape(chosen.summary(search=False))
    search = '<div class="tools">%s<a class="random" id="random" href="%s">Random game</a></div>\n' % (
        _searchForm(escape, chosen), escape(randomUrl(chosen))
    )
    strips = ""
    if themed:
        title = "%s &mdash; Play" % escape(themed["heading"])
        description = escape(themed["intro"])
        canonical = "https://%s/%s" % (escape(domain), escape(theme))
        intro = (
            '<h1>%s</h1>\n<p>%s</p>\n'
            '<a class="browse" href="%s">Walk the hall with these cabinets lit &rarr;</a>\n'
            '<a class="hall" href="%s">Filter or sort them further, or see every game &rarr;</a>\n'
            % (escape(themed["heading"]), description, escape(hallUrl(chosen)),
               escape(_here(chosen.query(q=None))))
        )
        panel = ""
        search = '<div class="tools"><a class="random" id="random" href="%s">Random game</a></div>\n' % escape(
            randomUrl(chosen)
        )
        style = _STYLE + _palette(themed["colours"])
        heading = "%s (%d)" % (escape(themed["heading"]), len(candidates))
        facetWords = escape(themed["heading"])
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
        # Filled in by the script from this browser's own storage; hidden until then.
        strips = _strip(escape, "recent", "Continue playing", [], domain, hidden=True)
        if not chosen.facetsActive:
            from arcade import activity

            busy = sorted(
                ((weekly(slug) or 0, entry) for slug, entry in ((e["slug"], e) for e in everything)
                 if slug in live),
                key=lambda pair: (-pair[0], pair[1]["title"].lower()),
            )
            top = [(byDict[e["slug"]], e["title"]) for n, e in busy if n >= activity.K][:WEEKLY_MAX]
            if top:
                strips += _strip(escape, "weekly", "Most played this week", top, domain)
    data = json.dumps(live, sort_keys=True).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
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
%(intro)s%(search)s%(panel)s
%(strips)s<h2 class="shown" id="games-h" aria-live="polite" data-total="%(total)d" data-facets="%(facetWords)s">%(heading)s</h2>
<ul id="games" aria-labelledby="games-h">
%(listing)s
</ul>
<footer>Served by <a href="https://github.com/Stephenson-Software/arcade">arcade</a>. Likes, scores and
details for each game are on <a href="%(portal)s">%(portalLabel)s</a>.</footer>
</main>
<script type="application/json" id="arcade-games">%(data)s</script>
<script>%(script)s</script>
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
        "search": search,
        "panel": panel,
        "strips": strips,
        "heading": heading,
        "total": len(everything) if not themed else len(candidates),
        "facetWords": facetWords,
        "portal": portal,
        "portalLabel": portalLabel,
        "listing": listing,
        "data": data,
        "script": SCRIPT,
    }
    return document.encode("utf-8")
