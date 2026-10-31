# @author Daniel McCoy Stephenson
"""The arcade HTTP server (RFC 0006 §4).

One process answers two kinds of host:

  play.<base>               the upload API, and / a page listing every game
                            (or, with ARCADE_LANDING_MODE=redirect, a 302 to
                            the portal), /version.json: the running arcade's
                            own version, {"version": "<x.y.z>"}, and the
                            landing page's /robots.txt and /og.png
  play.<base>/halloween     the landing page for one theme tag (landing.THEMES)
  <slug>.play.<base>        a game, served the way tak.web.serve serves one
  <alias>                   a game's old hostname (registry `aliases`)

Game routes mirror tak.web.serve exactly, so a page built for a per-game
container works unchanged here:

  /  /play  /play/  /index.html  -> the current version's index.html
  /web/game.zip  /web/version.txt
  /tak/<asset>                   -> from the current version's own game.zip
  everything else                -> 404

A `static` game (RFC 0012) is served as a tree of files instead: / and any
path ending in / serve that directory's index.html.

Every response - errors included - carries the three Cross-Origin headers the
kit requires; without them the page is not cross-origin isolated and
SharedArrayBuffer does not exist. The one exception is a `static` game with
isolation off, whose responses carry none of the three.
"""

import datetime
import hashlib
import hmac
import http.server
import json
import os
import re
import sys
import threading
from urllib.parse import parse_qs, unquote, urlparse

from arcade import __version__, activity, bundle, filters, hall, landing, precompress, registry as registryModule, routers, walks
from arcade.store import VERSION_PATTERN, NoSuchVersion, Store, VersionExists

INDEX_PATHS = ("/", "/play", "/play/", "/index.html")
WEB_FILES = {"/web/game.zip": "game.zip", "/web/version.txt": "version.txt"}
ISOLATION_HEADERS = (
    ("Cross-Origin-Opener-Policy", "same-origin"),
    ("Cross-Origin-Embedder-Policy", "require-corp"),
    # cross-origin, not same-origin: the portal (another origin) embeds games
    # in an iframe, and a cross-origin-isolated parent may only load a child
    # document whose CORP allows it. Measured in Chromium: with same-origin
    # the embedded tak game is blocked; with cross-origin it boots isolated.
    # Every file here is public, so letting other origins load them costs
    # nothing; COOP and COEP, which give the game its isolation, are unchanged.
    ("Cross-Origin-Resource-Policy", "cross-origin"),
)
LANDING_MODES = ("page", "redirect")
DEFAULT_MAX_UPLOAD_BYTES = 64 * 1024 * 1024
# User agents that are not a person opening a game: crawlers, link-preview
# fetchers and scripts. Their page loads are not counted as plays.
_NOT_A_PERSON = re.compile(
    r"bot|crawl|spider|slurp|preview|facebookexternalhit|embedly|curl|wget|python|"
    r"go-http-client|java/|okhttp|headless|lighthouse|monitor|uptime",
    re.I,
)
_API_GAME = re.compile(r"^/api/games/([a-z0-9-]+)$")
_API_VERSION = re.compile(r"^/api/games/([a-z0-9-]+)/versions/([^/]+)$")
_API_CURRENT = re.compile(r"^/api/games/([a-z0-9-]+)/current$")

# The Content-Types arcade adds to mimetypes (.wasm, .js, .data, ...) are
# registered in arcade.precompress, which the store shares.


def log(message):
    print("[arcade] %s" % message, file=sys.stderr, flush=True)


class Config(object):
    """Everything the server needs, normally read from the environment."""

    def __init__(
        self,
        domain,
        dataDirectory,
        registryPath,
        landingUrl,
        maxUploadBytes=DEFAULT_MAX_UPLOAD_BYTES,
        keep=5,
        internalHost="arcade",
        traefikService="arcade@docker",
        traefikMiddlewares=("secure-headers@file",),
        landingMode="page",
        hallEmbed="off",
    ):
        self.domain = domain.lower().strip(".")
        self.dataDirectory = dataDirectory
        self.registryPath = registryPath
        # The portal: where `/` redirects in "redirect" mode, and what the
        # landing page's "Browse all games" links to in "page" mode.
        self.landingUrl = landingUrl
        landingMode = (landingMode or "page").strip().lower()
        if landingMode not in LANDING_MODES:
            raise ValueError("ARCADE_LANDING_MODE must be one of %s, not %r" % ("/".join(LANDING_MODES), landingMode))
        self.landingMode = landingMode
        hallEmbed = (hallEmbed or "off").strip().lower()
        if hallEmbed not in hall.EMBED_MODES:
            raise ValueError("ARCADE_HALL_EMBED must be on or off, not %r" % hallEmbed)
        # on: the hall plays a game in a frame over itself. Every game's host
        # must then let play.<base> frame it (the gateway's frame-ancestors).
        self.hallEmbed = hallEmbed == "on"
        self.maxUploadBytes = maxUploadBytes
        self.keep = keep
        # The name other containers reach arcade by. Only a request addressed
        # to it may read /traefik/dynamic.json; no public router sends that Host.
        self.internalHost = internalHost.lower()
        self.traefikService = traefikService
        self.traefikMiddlewares = tuple(traefikMiddlewares)

    @classmethod
    def fromEnvironment(cls, environ=None):
        environ = os.environ if environ is None else environ
        return cls(
            domain=environ.get("ARCADE_DOMAIN", "play.danielstephenson.dev"),
            dataDirectory=environ.get("ARCADE_DATA", "/data"),
            registryPath=environ.get("ARCADE_REGISTRY", "/config/games.yaml"),
            landingUrl=environ.get("ARCADE_LANDING_URL", "https://danielstephenson.dev/play"),
            landingMode=environ.get("ARCADE_LANDING_MODE", "page"),
            hallEmbed=environ.get("ARCADE_HALL_EMBED", "off"),
            maxUploadBytes=int(environ.get("ARCADE_MAX_UPLOAD_BYTES", DEFAULT_MAX_UPLOAD_BYTES)),
            keep=int(environ.get("ARCADE_KEEP_VERSIONS", "5")),
            internalHost=environ.get("ARCADE_INTERNAL_HOST", "arcade"),
            traefikService=environ.get("ARCADE_TRAEFIK_SERVICE", "arcade@docker"),
            traefikMiddlewares=tuple(
                name.strip()
                for name in environ.get("ARCADE_TRAEFIK_MIDDLEWARES", "secure-headers@file").split(",")
                if name.strip()
            ),
        )


class RegistryHolder(object):
    """The registry, reloaded when its file changes. A file that no longer
    parses is logged and the last good registry stays in force."""

    def __init__(self, path, domain):
        self.path = path
        self.domain = domain
        self._lock = threading.Lock()
        self._mtime = None
        self._registry = registryModule.Registry([])
        self.refresh(initial=True)

    def refresh(self, initial=False):
        try:
            mtime = os.stat(self.path).st_mtime_ns
        except OSError as e:
            if initial:
                raise
            log("registry unreadable, keeping the last good one: %s" % e)
            return
        with self._lock:
            if mtime == self._mtime:
                return
            try:
                loaded = registryModule.load(self.path, domain=self.domain)
            except (registryModule.RegistryError, OSError) as e:
                if initial:
                    raise
                log("registry invalid, keeping the last good one: %s" % e)
                self._mtime = mtime
                return
            self._registry = loaded
            self._mtime = mtime
            log("registry loaded: %d game(s): %s" % (len(loaded), ", ".join(g.slug for g in loaded)))

    @property
    def registry(self):
        self.refresh()
        return self._registry


def addedOf(game, store):
    """When the game joined the arcade, as an ISO 8601 UTC time ("...Z"), or
    None: the registry's `added:` day if given, else its first upload."""
    if game.added is not None:
        return game.added.isoformat() + "T00:00:00Z"
    stamp = store.added(game.slug)
    if stamp is None:
        return None
    moment = datetime.datetime.fromtimestamp(stamp / 1e9, datetime.timezone.utc)
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def hashToken(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class Arcade(object):
    """The state one server process shares across requests."""

    def __init__(self, config, reporter=None):
        self.config = config
        self.registry = RegistryHolder(config.registryPath, config.domain)
        self.store = Store(config.dataDirectory, keep=config.keep)
        self.reporter = reporter
        # Versions stored before arcade wrote .gz siblings get theirs the
        # first time each file is asked for, one file at a time.
        self.backfill = precompress.Backfill()
        # Walk replays (RFC 0030 §3, opt-in in the hall): kept per UTC day
        # beside the games (a dot name, so never a slug); the layouts a walk
        # may name, and the per-client rate limit, in memory only.
        self.walks = walks.Walks(os.path.join(config.dataDirectory, ".hall-walks"))
        self.layouts = walks.Layouts()
        self.walkLimit = walks.RateLimit()

    def gameForHost(self, host):
        """The Game a request's Host header names, or None."""
        registry = self.registry.registry
        suffix = "." + self.config.domain
        if host.endswith(suffix):
            label = host[: -len(suffix)]
            if "." not in label:
                return registry.get(label)
            return None
        return registry.forAlias(host)

    def report(self, name, slug):
        if self.reporter is not None:
            self.reporter.report(name, tags={"slug": slug})

    def played(self, slug, userAgent):
        """A person loaded the game's page: count it, and report it to trace."""
        if not userAgent or _NOT_A_PERSON.search(userAgent):
            return
        try:
            self.store.addPlay(slug)
        except OSError as e:
            log("could not count a play of %s: %s" % (slug, e))
        self.report("page-served", slug)


def makeHandler(arcade):
    config = arcade.config

    class Handler(http.server.BaseHTTPRequestHandler):
        server_version = "arcade/" + __version__
        sys_version = ""
        protocol_version = "HTTP/1.1"

        # --- plumbing -------------------------------------------------------

        def _host(self):
            host = (self.headers.get("Host") or "").strip().lower()
            if host.startswith("["):
                return host
            return host.split(":", 1)[0].rstrip(".")

        # Per response: a static game with isolation off sends no
        # Cross-Origin headers (RFC 0012); everything else does.
        isolate = True
        # Per response: the game's canonical page, sent as a Link header on
        # HTML so search engines index one address for it, not every host.
        canonical = None

        def end_headers(self):
            if self.isolate:
                for name, value in ISOLATION_HEADERS:
                    self.send_header(name, value)
            super().end_headers()

        def _send(self, status, body=b"", contentType="text/plain; charset=utf-8", headers=()):
            self.send_response(status)
            self.send_header("Content-Type", contentType)
            self.send_header("Content-Length", str(len(body)))
            for name, value in headers:
                self.send_header(name, value)
            if self.canonical and contentType.startswith("text/html"):
                self.send_header("Link", '<%s>; rel="canonical"' % self.canonical)
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def _text(self, status, message):
            self._send(status, (message + "\n").encode("utf-8"))

        def _json(self, status, payload, public=False, cache=None):
            body = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")
            # Public reads (the game list, with play counts) may be fetched by
            # the portal from another origin; writes never are.
            headers = (("Access-Control-Allow-Origin", "*"),) if public else ()
            if cache:
                headers += (("Cache-Control", cache),)
            self._send(status, body, "application/json", headers)

        def log_message(self, *args):
            pass  # the API logs what matters itself; game traffic is not logged

        def _path(self):
            return unquote(urlparse(self.path).path)

        # --- verbs ----------------------------------------------------------

        def do_GET(self):
            self._dispatch(read=True)

        def do_HEAD(self):
            self._dispatch(read=True)

        def do_PUT(self):
            self._dispatch(read=False)

        def do_POST(self):
            self._dispatch(read=False)

        def _dispatch(self, read):
            # Reset every request: one handler serves a whole keep-alive
            # connection, and a proxy may reuse it across hosts.
            self.isolate = True
            self.canonical = None
            path = self._path()
            if path == "/healthz" and read:
                self._text(200, "ok")
                return
            host = self._host()
            if host == config.internalHost:
                if read and path == "/traefik/dynamic.json":
                    document = routers.providerDocument(
                        arcade.registry.registry,
                        config.domain,
                        service=config.traefikService,
                        middlewares=config.traefikMiddlewares,
                    )
                    self._json(200, document)
                else:
                    self._text(404, "Not found")
                return
            if host == config.domain:
                self._api(path, read)
                return
            game = arcade.gameForHost(host)
            if game is None:
                self._text(404, "No game is served at this address.")
                return
            if not read:
                self._text(405, "Games are read-only; uploads go to https://%s/api/" % config.domain)
                return
            self._game(game, path)

        # --- games ----------------------------------------------------------

        def _game(self, game, path):
            self.isolate = game.isolation
            self.canonical = game.canonical
            version = arcade.store.current(game.slug)
            if version is None:
                self._text(404, "%s has not been deployed yet." % game.title)
                return
            if game.kind == "static":
                self._static(game, version, path)
                return
            if path in INDEX_PATHS:
                self._file(game.slug, version, "index.html", "text/html; charset=utf-8")
                if self.command == "GET":
                    arcade.played(game.slug, self.headers.get("User-Agent"))
                return
            if path in WEB_FILES:
                name = WEB_FILES[path]
                contentType = "application/zip" if name == "game.zip" else "text/plain; charset=utf-8"
                self._file(game.slug, version, name, contentType)
                return
            if path.startswith("/tak/"):
                name = path[len("/tak/") :]
                data = bundle.readAsset(arcade.store.filePath(game.slug, version, "game.zip"), name)
                if data is None:
                    self._text(404, "Not found")
                    return
                contentType = precompress.guessType(name)
                self._cached(data, contentType, '"%s-%s"' % (version, name))
                return
            self._text(404, "Not found")

        def _static(self, game, version, path):
            relative = path.lstrip("/")
            if relative == "" or relative.endswith("/"):
                relative += "index.html"
            stored = arcade.store.sitePath(game.slug, version, relative)
            if stored is None:
                self._text(404, "Not found")
                return
            contentType = precompress.guessType(relative)
            if contentType.startswith("text/") and "charset" not in contentType:
                contentType += "; charset=utf-8"
            # The path is hashed, not quoted: a file name may hold a quote or
            # characters a Latin-1 header cannot carry.
            tag = hashlib.sha256(relative.encode("utf-8")).hexdigest()[:16]
            if not self._stream(stored, contentType, '"%s-%s"' % (version, tag)):
                return
            if relative == "index.html" and self.command == "GET":
                arcade.played(game.slug, self.headers.get("User-Agent"))

        def _file(self, slug, version, name, contentType):
            self._stream(arcade.store.filePath(slug, version, name), contentType, '"%s-%s"' % (version, name))

        def _stream(self, path, contentType, etag, extra=(), backfill=True):
            """Send a stored file - or its .br/.gz sibling, if the client
            accepts it - in chunks, never read whole. False if it is missing
            (a 404 has been sent)."""
            canCompress = precompress.compressible(contentType)
            # The hall's files ship in the image, read-only: their .gz copies
            # are made by hall3d/build.sh, never at run time.
            if backfill and canCompress and precompress.needsGzip(path, contentType):
                arcade.backfill.request(path)
            chosen, encoding = precompress.choose(path, self.headers.get("Accept-Encoding"))
            try:
                served = open(chosen, "rb")
            except OSError:
                if encoding is None:
                    self._text(404, "Not found")
                    return False
                # The variant vanished between the check and the open.
                chosen, encoding = path, None
                try:
                    served = open(chosen, "rb")
                except OSError:
                    self._text(404, "Not found")
                    return False
            with served:
                size = os.fstat(served.fileno()).st_size
                headers = []
                if encoding is not None:
                    # Each variant is its own representation, so its own tag.
                    etag = etag[:-1] + ("-br" if encoding == "br" else "-gz") + '"'
                    headers.append(("Content-Encoding", encoding))
                if canCompress or encoding is not None or self._hasVariant(path):
                    headers.append(("Vary", "Accept-Encoding"))
                headers += [("ETag", etag), ("Cache-Control", "no-cache")]
                headers += list(extra)
                if self.headers.get("If-None-Match") == etag:
                    self._notModified(headers)
                    return True
                self.send_response(200)
                self.send_header("Content-Type", contentType)
                self.send_header("Content-Length", str(size))
                for name, value in headers:
                    self.send_header(name, value)
                if self.canonical and contentType.startswith("text/html"):
                    self.send_header("Link", '<%s>; rel="canonical"' % self.canonical)
                self.end_headers()
                if self.command != "HEAD":
                    while True:
                        chunk = served.read(precompress.CHUNK_BYTES)
                        if not chunk:
                            break
                        self.wfile.write(chunk)
            return True

        @staticmethod
        def _hasVariant(path):
            return any(os.path.isfile(path + suffix) for _, suffix in precompress.ENCODINGS)

        def _notModified(self, headers):
            self.send_response(304)
            for name, value in headers:
                self.send_header(name, value)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def _cached(self, data, contentType, etag):
            # The URLs are not versioned, so every response is revalidated;
            # the ETag makes an unchanged file a 304 instead of a download.
            headers = (("ETag", etag), ("Cache-Control", "no-cache"))
            if self.headers.get("If-None-Match") == etag:
                self._notModified(headers)
                return
            self._send(200, data, contentType, headers)

        # --- API ------------------------------------------------------------

        def _api(self, path, read):
            if read and path in ("/", "/index.html"):
                self._landing()
                return
            if read and path.startswith("/") and path.strip("/") in landing.THEMES:
                # /halloween: the landing page for one theme tag (?tag=halloween), in its colours.
                self._landing(theme=path.strip("/"))
                return
            if read and path == "/version.json":
                self._version()
                return
            if read and (path == "/hall" or path.startswith("/hall/")):
                self._hall(path)
                return
            if read and path == "/robots.txt":
                # API host only, like /version.json: on a game's host the path
                # belongs to the game.
                self._send(200, landing.ROBOTS.encode("utf-8"), headers=(("Cache-Control", "public, max-age=3600"),))
                return
            if read and path == landing.OG_IMAGE_PATH:
                # The landing page's share card. API host only, like robots.txt:
                # on a game's host the path belongs to the game.
                headers = (("Cache-Control", "public, max-age=86400"),)
                self._send(200, landing.ogImage(), "image/png", headers=headers)
                return
            if read and path == "/api/games":
                # ?tag=, ?org=, ?engine= narrow the list and ?sort= orders it, as on the landing page.
                chosen = filters.Filter.parse(urlparse(self.path).query)
                described = [self._describe(game) for game in arcade.registry.registry]
                if chosen.active:
                    described = [game for game in described if chosen.matches(game)]
                if chosen.sort != "name":
                    described = chosen.order(described)
                self._json(200, {"games": described}, public=True)
                return
            if read and path == "/api/activity":
                # The hall's ghosts: a 0..4 level per game, never a count (RFC 0030 §2.2).
                doc = activity.document(
                    [game.slug for game in arcade.registry.registry],
                    lambda slug: arcade.store.recentPlays(slug, activity.WINDOW_DAYS),
                )
                body = (json.dumps(doc, indent=2, sort_keys=True) + "\n").encode("utf-8")
                maxAge = activity.maxAge(datetime.datetime.now(datetime.timezone.utc))
                headers = (
                    ("Access-Control-Allow-Origin", "*"),
                    ("Cache-Control", "public, max-age=%d" % maxAge),
                )
                self._send(200, body, "application/json", headers=headers)
            if path == "/api/walks" and self.command == "POST":
                self._leaveWalk()
                return
            if read and path == "/api/walks/today":
                self._json(200, {"dt": walks.DT, "walks": arcade.walks.sample()}, cache="public, max-age=60")
                return
            match = _API_GAME.match(path)
            if match and read:
                game = arcade.registry.registry.get(match.group(1))
                if game is None:
                    self._json(404, {"error": "no such game"})
                    return
                self._json(200, self._describe(game), public=True)
                return
            match = _API_VERSION.match(path)
            if match and self.command == "PUT":
                self._upload(match.group(1), match.group(2))
                return
            match = _API_CURRENT.match(path)
            if match and self.command == "POST":
                self._rollback(match.group(1))
                return
            self._json(404, {"error": "not found"})

        # --- the walkable hall -------------------------------------------

        def _hall(self, path):
            query = urlparse(self.path).query
            if path == "/hall":
                # Relative URLs in the page resolve under /hall/.
                self._send(301, b"", headers=(("Location", "/hall/" + ("?" + query if query else "")),))
                return
            name = path[len("/hall/") :]
            if name in ("", "index.html"):
                # Cross-origin isolated only when asked (?isolated=1): an
                # isolated hall can frame a tak or Roam build, which needs
                # SharedArrayBuffer; a plain one can frame every other game.
                params = parse_qs(query)
                self.isolate = params.get("isolated", [""])[0] == "1"
                # A link to one cabinet (?at=<slug>) unfurls with that game's
                # title and card; anything else with the hall's.
                game = arcade.registry.registry.get(params.get("at", [""])[0])
                body = hall.page(config.domain, game.slug, game.title) if game else hall.page(config.domain)
                tag = '"hall-page-%s-%s"' % (
                    hashlib.sha256(body).hexdigest()[:16],
                    "iso" if self.isolate else "plain",
                )
                headers = (
                    ("ETag", tag),
                    ("Cache-Control", "no-cache"),
                    ("Content-Security-Policy", hall.csp(config.domain)),
                    ("X-Content-Type-Options", "nosniff"),
                    ("Referrer-Policy", "strict-origin-when-cross-origin"),
                )
                if self.headers.get("If-None-Match") == tag:
                    self._notModified(headers)
                    return
                self._send(200, body, "text/html; charset=utf-8", headers=headers)
                return
            if name == "layout.json":
                registry = arcade.registry.registry
                games = [self._describe(game) for game in registry]
                # ?season=halloween (or none) shows a season's decor on any date, for testing.
                season = parse_qs(query).get("season", [None])[0]
                # ?tag=halloween (and org, engine): the cabinets that match stay lit, the rest go dark.
                doc = hall.served_layout(
                    games, config.hallEmbed, season=season, chosen=filters.Filter.parse(query)
                )
                if season is None:
                    # A walk left in this hall is clamped against this room (a
                    # filter moves nothing; ?season= is for testing only).
                    arcade.layouts.remember(doc)
                body = (json.dumps(doc, indent=1) + "\n").encode("utf-8")
                self._send(200, body, "application/json", headers=(("Cache-Control", "no-cache"),))
                return
            stored = hall.asset_path(name)
            if stored is None:
                self._text(404, "Not found")
                return
            self._stream(stored, precompress.guessType(name), '"%s"' % hall.etag(stored), backfill=False)

        # --- walk replays (RFC 0030 §3) ----------------------------------

        def _client(self):
            # Behind Traefik the client is the last address it appended; held
            # only by the rate limit, hashed, in memory, for one window.
            forwarded = [a.strip() for a in (self.headers.get("X-Forwarded-For") or "").split(",") if a.strip()]
            return forwarded[-1] if forwarded else self.client_address[0]

        def _currentLayout(self):
            games = [self._describe(game) for game in arcade.registry.registry]
            return hall.served_layout(games, config.hallEmbed)

        def _leaveWalk(self):
            length = self._contentLength()
            if length is None:
                self.close_connection = True
                self._json(411, {"error": "Content-Length is required"})
                return
            if length > walks.MAX_BODY:
                self.close_connection = True
                self._json(413, {"error": "a walk is at most %d bytes" % walks.MAX_BODY})
                return
            data = self.rfile.read(length)
            try:
                payload = json.loads(data.decode("utf-8"))
            except (UnicodeDecodeError, ValueError):
                self._json(400, {"error": "expected a JSON walk"})
                return
            key = payload.get("layout") if isinstance(payload, dict) else None
            if isinstance(key, str) and arcade.layouts.get(key) is None:
                # Not served since this process started: today's hall may be it.
                arcade.layouts.remember(self._currentLayout())
            try:
                walk = walks.clean(payload, arcade.layouts)
            except walks.Refused as e:
                self._json(400, {"error": str(e)})
                return
            if not arcade.walkLimit.allow(self._client()):
                self._json(429, {"error": "one walk per visitor every %d minutes" % (walks.RATE_WINDOW // 60)})
                return
            try:
                arcade.walks.add(walk)
            except OSError as e:
                log("could not keep a walk: %s" % e)
                self._json(503, {"error": "the walk could not be kept"})
                return
            self._json(202, {"kept": True})

        def _version(self):
            # The version of the code this process is running, so a deploy can
            # be verified by the version it reports. Only on the API host: on a
            # game's host /version.json belongs to the game (a static site may
            # ship its own), so it is never answered there.
            body = json.dumps({"version": __version__}).encode("utf-8")
            self._send(200, body, "application/json", headers=(("Cache-Control", "no-store"),))

        def _landing(self, theme=None):
            if config.landingMode == "redirect" and theme is None:
                self._send(302, b"", headers=(("Location", config.landingUrl),))
                return
            body = landing.render(
                arcade.registry.registry,
                config.domain,
                config.landingUrl,
                deployed=lambda slug: arcade.store.current(slug) is not None,
                plays=arcade.store.plays,
                added=lambda game: addedOf(game, arcade.store),
                query=urlparse(self.path).query,
                theme=theme,
            )
            self._send(
                200,
                body,
                "text/html; charset=utf-8",
                headers=(
                    ("Content-Security-Policy", landing.CSP),
                    ("X-Content-Type-Options", "nosniff"),
                    ("Referrer-Policy", "strict-origin-when-cross-origin"),
                    # Generated from the registry, which can change at any time.
                    ("Cache-Control", "public, max-age=60"),
                ),
            )

        def _describe(self, game):
            return {
                "slug": game.slug,
                "title": game.title,
                "repo": game.repo,
                "url": "https://%s.%s/" % (game.slug, config.domain),
                "aliases": list(game.aliases),
                "kind": game.kind,
                "isolation": game.isolation,
                "current": arcade.store.current(game.slug),
                "versions": arcade.store.versions(game.slug),
                "plays": arcade.store.plays(game.slug),
                "added": addedOf(game, arcade.store),
                "tags": list(game.tags),
                "org": game.org,
                "engine": game.engine,
            }

        def _authorise(self, slug):
            """The Game if the bearer token is right for it; otherwise None,
            with the error already sent."""
            game = arcade.registry.registry.get(slug)
            header = self.headers.get("Authorization") or ""
            if not header.startswith("Bearer ") or not header[7:].strip():
                self._drain()
                self._json(401, {"error": "an Authorization: Bearer <token> header is required"})
                return None
            presented = hashToken(header[7:].strip())
            expected = game.tokenSha256 if game else "0" * 64
            if game is None or not hmac.compare_digest(presented, expected):
                self._drain()
                # Unknown slug and wrong token look the same from outside.
                self._json(403, {"error": "this token cannot deploy that game"})
                return None
            return game

        def _drain(self):
            # Read (and discard) a small body so the connection stays usable;
            # a large one is not worth reading - close instead.
            length = self._contentLength()
            if length is not None and 0 < length <= 1024 * 1024:
                self.rfile.read(length)
            elif length:
                self.close_connection = True

        def _contentLength(self):
            try:
                return int(self.headers.get("Content-Length", ""))
            except ValueError:
                return None

        def _upload(self, slug, version):
            game = self._authorise(slug)
            if game is None:
                return
            if not VERSION_PATTERN.match(version):
                self._drain()
                self._json(400, {"error": "bad version %r" % version})
                return
            length = self._contentLength()
            if length is None:
                self.close_connection = True
                self._json(411, {"error": "Content-Length is required"})
                return
            if length > config.maxUploadBytes:
                self.close_connection = True
                self._json(413, {"error": "uploads are capped at %d bytes" % config.maxUploadBytes})
                return
            data = self.rfile.read(length)
            static = game.kind == "static"
            try:
                if static:
                    files = bundle.unpackStatic(data, version, config.maxUploadBytes)
                else:
                    files = bundle.unpack(data, version, config.maxUploadBytes)
            except bundle.BundleTooLarge as e:
                self._json(413, {"error": str(e)})
                return
            except bundle.BundleError as e:
                self._json(400, {"error": str(e)})
                return
            activate = parse_qs(urlparse(self.path).query).get("activate", ["true"])[0] != "false"
            try:
                arcade.store.add(slug, version, files, activate=activate, static=static)
            except VersionExists:
                self._json(409, {"error": "version %s already exists; versions are immutable" % version})
                return
            except (ValueError, OSError) as e:
                # Validation should have caught it; if not, still answer.
                log("%s %s upload could not be stored: %s" % (slug, version, e))
                self._json(400, {"error": "the bundle could not be stored: %s" % e})
                return
            log("%s %s uploaded (%d bytes)%s" % (slug, version, length, " and made current" if activate else ""))
            self._json(201, self._describe(game))

        def _rollback(self, slug):
            game = self._authorise(slug)
            if game is None:
                return
            length = self._contentLength() or 0
            if length > 4096:
                self.close_connection = True
                self._json(413, {"error": "body too large"})
                return
            try:
                payload = json.loads(self.rfile.read(length) or b"{}")
                version = payload["version"]
                if not isinstance(version, str):
                    raise TypeError
            except (ValueError, KeyError, TypeError):
                self._json(400, {"error": 'expected a JSON body {"version": "<version>"}'})
                return
            try:
                arcade.store.setCurrent(slug, version)
            except NoSuchVersion:
                self._json(404, {"error": "version %r is not on disk" % version})
                return
            log("%s current set to %s" % (slug, version))
            self._json(200, self._describe(game))

    return Handler


class Server(http.server.ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True


def makeServer(arcade, host="0.0.0.0", port=8080):
    return Server((host, port), makeHandler(arcade))
