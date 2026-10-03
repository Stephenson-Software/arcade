# Changelog

All notable changes to this project are documented in this file. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.0.0/), and the project uses semantic versioning.

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
