# arcade

One static host for every browser game. arcade serves each game's page, bundle and kit assets at
`<slug>.play.danielstephenson.dev`, with the cross-origin isolation headers the
[tak](https://github.com/Stephenson-Software/tak) kit needs. A game deploys by uploading a versioned
bundle from its own CI, and rollback is a repoint, not a rebuild.

arcade is designed in **RFC 0006, "A Static Hosting Service for Browser Games"** (Stephenson-Software
RFCs; Accepted, v1.1). The portal that lists the games is <https://danielstephenson.dev/play>.

arcade serves files and runs nothing. Every game runs in the player's own tab, with its saves in
that browser's IndexedDB. The service is standard-library Python with one data volume and no
database.

## How it answers

| Host | What it serves |
|---|---|
| `play.<base>` | the upload API (below); `/` is a landing page listing every game (see below) |
| `<slug>.play.<base>` | the game registered under that slug |
| an alias from the registry | the same game, at an older hostname, so that origin's saves are kept |
| anything else | 404 |

Game routes mirror `tak.web.serve` route for route, so a page built for a per-game container works
unchanged:

| Path | Response |
|---|---|
| `/`, `/play`, `/play/`, `/index.html` | the current version's `index.html` |
| `/web/game.zip`, `/web/version.txt` | the current version's files |
| `/tak/<asset>` | that asset from **the game's own** `game.zip` (`src/tak/web/assets/`), so the kit's Python and JavaScript halves always match (RFC 0006 §5) |
| anything else | 404 |

Every response, errors included, carries `Cross-Origin-Opener-Policy: same-origin`,
`Cross-Origin-Embedder-Policy: require-corp` and `Cross-Origin-Resource-Policy: cross-origin`
(cross-origin so that the portal can embed a game in an iframe). Files
are sent with an `ETag` and `Cache-Control: no-cache`, so a returning player revalidates instead of
downloading again. `/healthz` answers `ok` on any host.

## The registry

`games.yaml` lives in the gateway repository and is mounted read-only at `/config/games.yaml`.
Reserving a slug is a gateway pull request that adds one entry:

```yaml
games:
  - slug: tidewater                      # ^[a-z][a-z0-9-]{1,30}$
    title: Tidewater
    repo: Stephenson-Software/Tidewater
    owner: dmccoystephenson              # optional
    token_sha256: "<64 hex>"             # sha256 of the game's upload token
    aliases: [tidewater.danielstephenson.dev]   # optional
```

The parser is deliberately strict: it accepts only this subset of YAML, and it refuses unknown keys,
duplicate slugs, reserved slugs (`play`, `www`, `api`, `arcade`, `admin`, `static`), malformed
hashes, and aliases under the arcade's own domain, each with its line number. arcade picks up
changes to the file without a restart. A file that stops parsing is logged and ignored, and the
last good registry stays in force.

```sh
python -m arcade check-registry games.yaml
```

### A token for a new game

```sh
python3 -c "import secrets; print(secrets.token_urlsafe(32))" > token.txt
python -m arcade hash-token < token.txt     # → token_sha256 for games.yaml
gh secret set ARCADE_TOKEN -R <owner>/<game> < token.txt
rm token.txt
```

Only the hash is committed. Rotating a token is a registry PR plus a secret update.

### Bundle kinds (RFC 0012)

| `kind` | Upload | Served | `isolation` |
|---|---|---|---|
| `tak` (default) | exactly `index.html`, `game.zip`, `version.txt` | tak's routes; `/tak/` from the game's own `game.zip` | always on; cannot be turned off |
| `static` | any tree with `index.html` and `version.txt` at its root (a pygbag, Emscripten or plain HTML/JS build) | as files; `/` and `…/` serve `index.html`; `.wasm` is `application/wasm` | **off** by default, `on` to opt in |

The `static` kind defaults to no Cross-Origin headers because builds that fetch their runtime from a
CDN without `Cross-Origin-Resource-Policy` (pygbag loads from `pygame-web.github.io`) cannot run
under `require-corp`. Set `isolation: on` for a build that needs `SharedArrayBuffer`, such as
Emscripten with pthreads. A static upload refuses links, absolute paths, `..` and empty segments,
caps the file count at 10,000, and is subject to the same byte cap as a tak upload.

## The landing page

`https://play.<base>/` (and `/index.html`) is a small HTML page generated from the registry on each
request: every game by title, linked to `https://<slug>.play.<base>/` (a game with nothing deployed is
listed as "Coming soon", unlinked), and a prominent "Browse all games" link to `ARCADE_LANDING_URL`.
It has no script and makes no external request (its `Content-Security-Policy` is
`default-src 'none'; style-src 'unsafe-inline'; …`), follows the visitor's light/dark setting, is laid
out for a phone first, and is sent with `Cache-Control: public, max-age=60`. Set
`ARCADE_LANDING_MODE=redirect` to answer `/` with the old 302 to `ARCADE_LANDING_URL` instead.

## The API (on `play.<base>`)

| Method | Path | Does |
|---|---|---|
| `PUT` | `/api/games/<slug>/versions/<version>` | Body: a `.tar` (optionally compressed) or `.zip` holding exactly `index.html`, `game.zip`, `version.txt`. It is validated before anything is written, then stored and made current unless `?activate=false`. Responses: **201**; **409** if the version exists (versions are immutable); **401/403** on a missing or wrong token; **411** without a `Content-Length`; **413** over the size cap; **400** for a missing or extra file, a `version.txt` that disagrees with `<version>`, or a `game.zip` without tak's four assets. |
| `POST` | `/api/games/<slug>/current` | `{"version": "…"}`: repoints the game to a stored version. This is rollback. **404** for a version not on disk. |
| `GET` | `/api/games`, `/api/games/<slug>` | slug, title, repo, url, aliases, kind, isolation, current, versions, **plays** (page loads by people; crawlers and scripts are excluded by User-Agent). Needs no token, never shows hashes, and is readable cross-origin (`Access-Control-Allow-Origin: *`) so the portal can show play counts. |
| `GET` | `/version.json` | `{"version": "<x.y.z>"}`: the version of arcade itself that is running (`arcade.__version__`), with `Cache-Control: no-store`, so a deploy can be verified by the version it reports. Needs no token. Answered on `play.<base>` only: on a game's host `/version.json` is the game's own path. |
| `GET` | `/og.png` | The landing page's share-preview image (`og:image`, `twitter:image`): a 1200x630 PNG, `src/arcade/og.png`, with `Cache-Control: public, max-age=86400`. Needs no token. Answered on `play.<base>` only: on a game's host `/og.png` is the game's own path. |

The token is `Authorization: Bearer <token>`, and each game's token deploys only that game. An
unknown slug and a wrong token both get 403. The last `ARCADE_KEEP_VERSIONS` (5) versions per game
are kept; older ones are pruned on upload, never the current one. A version is written to a
temporary directory and renamed into place, and `current` is replaced atomically, so a crash
mid-upload leaves the previous version live.

```sh
# deploy by hand (CI does this with the arcade-deploy action)
tar -cf bundle.tar -C web index.html game.zip -C .. version.txt
curl -fsS -X PUT -H "Authorization: Bearer $ARCADE_TOKEN" --data-binary @bundle.tar \
  https://play.danielstephenson.dev/api/games/tidewater/versions/$(cat version.txt)

# roll back
curl -fsS -X POST -H "Authorization: Bearer $ARCADE_TOKEN" -d '{"version":"0.1.0"}' \
  https://play.danielstephenson.dev/api/games/tidewater/current
```

## Traefik routers (TLS option B)

TLS-ALPN-01 cannot issue a wildcard certificate, so every host arcade answers gets its own
`Host()` router and certificate. The gateway routes `play.<base>` with ordinary compose labels
(service `arcade`). arcade itself hands Traefik every **game's** routers through Traefik's
[HTTP provider](https://doc.traefik.io/traefik/providers/http/):

```yaml
# traefik.yml (static)
providers:
  http:
    endpoint: "http://arcade:8080/traefik/dynamic.json"
    pollInterval: "10s"
```

`/traefik/dynamic.json` answers only on the internal hostname (`ARCADE_INTERNAL_HOST`, default
`arcade`). No public router sends that `Host`, so the document is never served to the internet. It
contains one router per `<slug>.play.<base>` and per alias. Each router uses `websecure`,
`secure-headers@file` and the `letsencrypt` resolver, and points at `ARCADE_TRAEFIK_SERVICE`
(default `arcade@docker`). Adding a game to `games.yaml` therefore becomes a router and a
certificate within one poll, with no Traefik or compose edit. If arcade is down, Traefik keeps the
routers it last read; this was verified against Traefik v3.5.3.

The same routers are available offline:

```sh
python -m arcade routers --registry games.yaml > arcade.yml       # a file-provider document
python -m arcade routers --registry games.yaml --check arcade.yml  # exit 1 when stale
python -m arcade hosts --registry games.yaml [--games-only]        # one host per line (cert-check)
```

**When migrating a game that already has its own container,** add its alias in the same gateway
change that removes that container's router, or Traefik will see two routers for one host.

## Configuration

| Variable | Default |
|---|---|
| `ARCADE_DOMAIN` | `play.danielstephenson.dev` |
| `ARCADE_DATA` | `/data` (back this up; losing it is recoverable by each game re-running its deploy) |
| `ARCADE_REGISTRY` | `/config/games.yaml` |
| `ARCADE_LANDING_URL` | `https://danielstephenson.dev/play` (the portal: the landing page's "Browse all games" link, or the redirect target) |
| `ARCADE_LANDING_MODE` | `page` (serve the landing page at `/`) or `redirect` (a 302 to `ARCADE_LANDING_URL`, as before 0.6.0) |
| `ARCADE_MAX_UPLOAD_BYTES` | `67108864` (64 MiB, compressed and unpacked) |
| `ARCADE_KEEP_VERSIONS` | `5` |
| `ARCADE_HOST` / `ARCADE_PORT` | `0.0.0.0` / `8080` in the image |
| `ARCADE_TRACE_KEY` | unset (no reporting) |
| `ARCADE_INTERNAL_HOST` | `arcade` (the only host that may read `/traefik/dynamic.json`) |
| `ARCADE_TRAEFIK_SERVICE` | `arcade@docker` |
| `ARCADE_TRAEFIK_MIDDLEWARES` | `secure-headers@file` (comma-separated; the gateway sets a set that lets the portal frame games) |

### Usage reporting

When `ARCADE_TRACE_KEY` is set, arcade reports to [trace](https://trace.danielstephenson.dev) as the
program `arcade` (override with `ARCADE_TRACE_PROGRAM`) using the vendored
[trace-client-python](https://github.com/Stephenson-Software/trace-client-python):
`startup` once, and one `page-served` event tagged with the game's `slug` per game page served.
That is a count of page loads, not of players. Nothing about the visitor is sent: no IP address,
user agent or path beyond the slug. `TRACE_USAGE_REPORTING=off` or `DO_NOT_TRACK=1` turns it off,
as for every trace client.

## Development

```sh
python3 -m pytest              # Python 3.8+, standard library only (pytest to run the tests)
```

Play a real game locally. `*.localhost` resolves to loopback and counts as a secure context, so the
page is cross-origin isolated over plain HTTP:

```sh
ARCADE_DOMAIN=play.localhost ARCADE_DATA=/tmp/arcade ARCADE_REGISTRY=games.yaml \
  ARCADE_HOST=127.0.0.1 PYTHONPATH=src python3 -m arcade serve
# upload as above to http://127.0.0.1:8080 with -H "Host: play.localhost",
# then open http://<slug>.play.localhost:8080/
```

## License

[Stephenson Software Non-Commercial License (Stephenson-NC)](LICENSE). The vendored
`src/arcade/trace_client.py` is MIT, as its header says.
