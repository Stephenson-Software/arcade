# Changelog

All notable changes to this project are documented in this file. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.0.0/), and the project uses semantic versioning.

## [Unreleased]

### Added

- "Share this spot" in the hall's bar: copies a link to where the visitor stands (with a short note to say
  so), or opens the share sheet on a phone (Web Share API). At a cabinet the link is `/hall/?at=<slug>`,
  elsewhere `/hall/#p=<place>`. On a phone the bar's controls are a little tighter so none wraps.

- The landing page links each deployed game to its cabinet in the hall ("Visit its cabinet in the hall",
  `/hall/?at=<slug>`), under the link to the game itself.

- Link previews for the hall: `/hall/` names a 1200x630 card (`og:image`, `twitter:image`) of the arcade
  floor seen from the door, and `/hall/?at=<slug>` names that game's own card (its cabinet, poster on the
  screen) with its title and blurb. The cards are rendered with Strata by `tools/make_hall_cards.py` from
  the hall's own layout and posters, committed under `src/arcade/hall_assets/cards/`, and served at
  `/hall/cards/<name>.jpg`; a game with no card yet unfurls with the hall's.

- The walkable hall at `https://play.<base>/hall/`: the README's arcade hall, live in the browser on
  Strata's web kit. Walk with WASD/arrows and mouse look, or a stick and tap-to-walk on a phone; walk up
  to a cabinet and press E (or tap) to play. Games open in a frame over the hall with "Back to the hall"
  (`ARCADE_HALL_EMBED=on`; the hall serves itself isolated or not to match each game) or as their own page
  (the default), and the visitor's place is kept. `GET /hall/layout.json` serves the layout, which
  `src/arcade/hall.py` now shares with `tools/make_hall_media.py`. The landing page links to it.

- Pre-compressed files: every compressible file in an upload (`application/wasm`, HTML, JavaScript,
  CSS, plain text, JSON, web manifests, SVG; 1 KiB or more) gets a `<name>.gz` sibling at gzip level
  9, and a bundle's own `<name>.br` / `<name>.gz` are used as shipped. A request is answered from
  the variant its `Accept-Encoding` prefers, with `Content-Encoding`, `Vary: Accept-Encoding` and a
  per-variant `ETag`, so a compressing proxy in front no longer compresses multi-MB `.wasm` on every
  response. Versions stored before this are backfilled lazily, one file at a time in a background
  thread, the first time each file is requested.
- Share-preview metadata on the landing page: `og:type`, `og:site_name`, `og:title`,
  `og:description`, `og:url` (`https://play.<base>/`) and a `twitter:card` with its title and
  description, so a shared link to `play.<base>` unfurls with a title and description.
- A share-preview image: `og:image` and `twitter:image` (`https://play.<base>/og.png`) with
  `og:image:type`, `og:image:width` (1200), `og:image:height` (630) and alt text, and the Twitter
  card is now `summary_large_image`. The image, `src/arcade/og.png`, is a 1200x630 PNG of the
  page's name, description and domain in its dark colours. `GET /og.png` serves it as `image/png` on
  the API host only, never on a game's host, so it cannot shadow a static game's own `/og.png`.
- `GET /robots.txt` on `play.<base>`: `User-agent: *` / `Allow: /` as `text/plain`. Like
  `/version.json`, it is answered on the API host only, never on a game's host, so it cannot shadow
  a static game's own `/robots.txt`.

- Optional `canonical:` registry field: the game's main public page, as an https URL. When it is set,
  every HTML response for the game, on its slug host and on its aliases, carries
  `Link: <url>; rel="canonical"`. Search engines then index one address for the game instead of
  splitting it across `<slug>.play.<base>`, old alias hosts and the portal page that frames it.
  Non-HTML files and games without the field send no Link header.
- `GET /version.json` on `play.<base>`: `{"version": "<arcade.__version__>"}` with
  `Content-Type: application/json` and `Cache-Control: no-store`, so a deploy can be verified by the
  version it reports. It is answered on the API host only, never on a game's host, so it cannot
  shadow a static game's own `/version.json`.

- The hall's cabinets are real arcade cabinets (`src/arcade/hall_model.py`, shared by the page and the
  README picture): bevelled side panels with a T-molding edge in the organisation's colour, a sloped
  control deck, a coin door with glowing coin slots, a bevelled bezel and a speaker grille. Each side
  panel carries side art made from the game's poster (`posters/<slug>.side.jpg`, by
  `tools/make_hall_posters.py`). Cabinets further than about 8 m are drawn as simple stand-ins, swapped
  by the engine (`hall_set_lods`), so the economy tier keeps 60 fps on a software renderer.
- The hall's room: a patterned arcade carpet, a suspended ceiling with framed light panels, a neon
  ARCADE sign over the door, stools under some cabinets' decks (with their own colliders) and plush
  prizes on the prize shelves.

### Changed

- Files are streamed in 64 KiB chunks instead of being read whole into memory for each response.
  Ten parallel downloads of an 18 MB file peaked at 180 MB RSS before and 25 MB after.

- The share-preview image, `src/arcade/og.png`, is redrawn as a 3D scene: rows of arcade cabinets
  on a checkered floor at night, each screen glowing a different colour, rendered with
  [Strata](https://github.com/Preponderous-Software/strata), with the title and play domain over
  it. Its alt text now describes the picture. It is drawn from `og-card/card.json` by
  community-site-kit's `tools/og-card` as a 256-colour PNG (61 KB, under the 150 KB the tests
  allow) and is pre-rendered, so nothing 3D runs on the landing page.

### Fixed

- A registry file that does not exist or cannot be read is reported by `routers`, `hosts`,
  `check-registry` and `serve` as one `arcade: <message>` line on stderr (exit status 1, as before)
  instead of a Python traceback, the same way an invalid registry already was.
- `--help` for `routers`, `hosts` and `check-registry` now describes the registry argument and
  `--domain` (naming its default, `play.danielstephenson.dev`) instead of listing them bare.

## [0.6.0] - 2026-10-03

### Added

- A landing page at `https://play.<base>/` (and `/index.html`) instead of the 302 to the portal: a
  small static HTML page generated from the registry, listing every game by title and linking it to
  `https://<slug>.play.<base>/` (a game with nothing deployed is listed as "Coming soon", unlinked),
  with a prominent "Browse all games" link to `ARCADE_LANDING_URL`. No script and no external request
  (enforced by its CSP), light and dark, phone-first; `Cache-Control: public, max-age=60`.
- `ARCADE_LANDING_MODE`: `page` (default) or `redirect`, which keeps the old 302 to
  `ARCADE_LANDING_URL`. Any other value refuses to start. The API is unchanged.

## [0.5.0] - 2026-10-02

### Changed

- Game responses send `Cross-Origin-Resource-Policy: cross-origin` (was `same-origin`), so the
  portal can embed a game in an iframe: a cross-origin-isolated parent page may only load a child
  document whose CORP allows it. Measured in Chromium: with `same-origin` the embedded tak game was
  blocked, and with `cross-origin` it booted isolated. COOP/COEP, which give a game its isolation,
  are unchanged, and every file served is public.

### Added

- `ARCADE_TRAEFIK_MIDDLEWARES` (comma-separated, default `secure-headers@file`): the middlewares on
  every generated game router. The gateway uses a framing-allowing set for games.

## [0.4.0] - 2026-10-02

### Added

- Play counts: each time a person loads a game's page (a GET of its index; crawlers, link
  previewers and scripts are excluded by User-Agent), arcade adds one to an atomically written
  counter beside that game's versions. `GET /api/games…` reports it as `plays`. Nothing about the
  visitor is stored.
- `GET /api/games` and `GET /api/games/<slug>` send `Access-Control-Allow-Origin: *`, so the
  portal can show play counts from the browser. Uploads and rollback stay same-origin.
- `plays`, like `current`, can no longer be used as a version name.

## [0.3.1] - 2026-10-02

### Fixed

- A version named `current` is refused. It used to collide with the pointer file and leave that
  game, and `GET /api/games` for every game, failing. An unreadable pointer now reads as "nothing
  deployed" instead of raising.
- A static upload holding a top-level `.uploaded`, or a path that is both a file and a directory,
  gets a 400 instead of a dropped connection. Any storage error is answered as a 400.
- Static ETags hash the file path, so names with quotes or non-Latin-1 characters are served.

## [0.3.0] - 2026-10-01

### Added

- Bundle kinds (RFC 0012): `kind: static` in `games.yaml` serves any uploaded tree with
  `index.html` and `version.txt` at its root as files (pygbag, Emscripten, plain HTML/JS). Uploads
  are validated before anything is written: no links, absolute paths, `..` or empty segments; at
  most 10,000 files.
- `isolation: on|off` per game: off by default for static games, so a build that loads a CDN
  runtime without CORP works; tak games must keep it on. It is decided for each request, never
  carried over a kept-alive connection. Verified with a real pygbag 0.9.3 build served through
  arcade in Chromium.
- `kind` and `isolation` in `GET /api/games…`; `.wasm`/`.mjs`/`.data`/`.apk` content types.

## [0.2.0] - 2026-10-01

### Added

- `GET /traefik/dynamic.json` on the internal hostname (`ARCADE_INTERNAL_HOST`, default `arcade`)
  only: the games' routers as a Traefik HTTP-provider document, without `play.<base>`, which the
  gateway routes with compose labels. A `games.yaml` change becomes routers and certificates
  within one poll. Verified against Traefik v3.5.3, including that Traefik keeps the routers while
  arcade is down.
- `ARCADE_TRAEFIK_SERVICE` (default `arcade@docker`) and `hosts --games-only`.

## [0.1.0] - 2026-10-01

### Added

- The arcade server (RFC 0006 v1.1). It serves `<slug>.play.<base>` and registry aliases with tak's
  exact routes and the three cross-origin isolation headers on every response, and serves `/tak/`
  from each game's own `game.zip`.
- An upload API with a bearer token per game (only its SHA-256 is stored), validation before any
  write, immutable versions, `?activate=false`, rollback via `POST …/current`, pruning to the last 5
  versions (never the current one), and atomic writes.
- A strict, stdlib-only parser for `games.yaml` that reports errors by line and hot-reloads, keeping
  the last good registry on error.
- `python -m arcade routers|hosts|check-registry|hash-token`: generated Traefik routers, one per
  host (TLS option B), with `--check` for CI.
- Optional trace reporting (`page-served` per slug) through the vendored trace-client-python 0.3.0.
- A Dockerfile with a `/healthz` health check, and CI on Python 3.8 and 3.12 plus an image smoke test.
