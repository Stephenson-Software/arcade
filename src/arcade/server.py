# @author Daniel McCoy Stephenson
"""The arcade HTTP server (RFC 0006 §4).

One process answers two kinds of host:

  play.<base>               the upload API, and / redirecting to the portal
  <slug>.play.<base>        a game, served the way tak.web.serve serves one
  <alias>                   a game's old hostname (registry `aliases`)

Game routes mirror tak.web.serve exactly, so a page built for a per-game
container works unchanged here:

  /  /play  /play/  /index.html  -> the current version's index.html
  /web/game.zip  /web/version.txt
  /tak/<asset>                   -> from the current version's own game.zip
  everything else                -> 404

Every response - errors included - carries the three Cross-Origin headers the
kit requires; without them the page is not cross-origin isolated and
SharedArrayBuffer does not exist.
"""

import hashlib
import hmac
import http.server
import json
import mimetypes
import os
import re
import sys
import threading
from urllib.parse import parse_qs, unquote, urlparse

from arcade import __version__, bundle, registry as registryModule, routers
from arcade.store import VERSION_PATTERN, NoSuchVersion, Store, VersionExists

INDEX_PATHS = ("/", "/play", "/play/", "/index.html")
WEB_FILES = {"/web/game.zip": "game.zip", "/web/version.txt": "version.txt"}
ISOLATION_HEADERS = (
    ("Cross-Origin-Opener-Policy", "same-origin"),
    ("Cross-Origin-Embedder-Policy", "require-corp"),
    ("Cross-Origin-Resource-Policy", "same-origin"),
)
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

mimetypes.add_type("text/javascript", ".js")
mimetypes.add_type("text/javascript", ".mjs")
mimetypes.add_type("text/css", ".css")
# application/wasm is what lets a browser compile a module while it streams.
mimetypes.add_type("application/wasm", ".wasm")
mimetypes.add_type("application/json", ".json")
mimetypes.add_type("application/octet-stream", ".data")
mimetypes.add_type("application/octet-stream", ".apk")


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
    ):
        self.domain = domain.lower().strip(".")
        self.dataDirectory = dataDirectory
        self.registryPath = registryPath
        self.landingUrl = landingUrl
        self.maxUploadBytes = maxUploadBytes
        self.keep = keep
        # The name other containers reach arcade by. Only a request addressed
        # to it may read /traefik/dynamic.json; no public router sends that Host.
        self.internalHost = internalHost.lower()
        self.traefikService = traefikService

    @classmethod
    def fromEnvironment(cls, environ=None):
        environ = os.environ if environ is None else environ
        return cls(
            domain=environ.get("ARCADE_DOMAIN", "play.danielstephenson.dev"),
            dataDirectory=environ.get("ARCADE_DATA", "/data"),
            registryPath=environ.get("ARCADE_REGISTRY", "/config/games.yaml"),
            landingUrl=environ.get("ARCADE_LANDING_URL", "https://danielstephenson.dev/play"),
            maxUploadBytes=int(environ.get("ARCADE_MAX_UPLOAD_BYTES", DEFAULT_MAX_UPLOAD_BYTES)),
            keep=int(environ.get("ARCADE_KEEP_VERSIONS", "5")),
            internalHost=environ.get("ARCADE_INTERNAL_HOST", "arcade"),
            traefikService=environ.get("ARCADE_TRAEFIK_SERVICE", "arcade@docker"),
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


def hashToken(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class Arcade(object):
    """The state one server process shares across requests."""

    def __init__(self, config, reporter=None):
        self.config = config
        self.registry = RegistryHolder(config.registryPath, config.domain)
        self.store = Store(config.dataDirectory, keep=config.keep)
        self.reporter = reporter

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
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def _text(self, status, message):
            self._send(status, (message + "\n").encode("utf-8"))

        def _json(self, status, payload, public=False):
            body = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")
            # Public reads (the game list, with play counts) may be fetched by
            # the portal from another origin; writes never are.
            headers = (("Access-Control-Allow-Origin", "*"),) if public else ()
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
            path = self._path()
            if path == "/healthz" and read:
                self._text(200, "ok")
                return
            host = self._host()
            if host == config.internalHost:
                if read and path == "/traefik/dynamic.json":
                    document = routers.providerDocument(
                        arcade.registry.registry, config.domain, service=config.traefikService
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
                contentType = mimetypes.guess_type(name)[0] or "application/octet-stream"
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
            try:
                with open(stored, "rb") as served:
                    data = served.read()
            except OSError:
                self._text(404, "Not found")
                return
            contentType = mimetypes.guess_type(relative)[0] or "application/octet-stream"
            if contentType.startswith("text/") and "charset" not in contentType:
                contentType += "; charset=utf-8"
            # The path is hashed, not quoted: a file name may hold a quote or
            # characters a Latin-1 header cannot carry.
            tag = hashlib.sha256(relative.encode("utf-8")).hexdigest()[:16]
            self._cached(data, contentType, '"%s-%s"' % (version, tag))
            if relative == "index.html" and self.command == "GET":
                arcade.played(game.slug, self.headers.get("User-Agent"))

        def _file(self, slug, version, name, contentType):
            try:
                with open(arcade.store.filePath(slug, version, name), "rb") as stored:
                    data = stored.read()
            except OSError:
                self._text(404, "Not found")
                return
            self._cached(data, contentType, '"%s-%s"' % (version, name))

        def _cached(self, data, contentType, etag):
            # The URLs are not versioned, so every response is revalidated;
            # the ETag makes an unchanged file a 304 instead of a download.
            headers = (("ETag", etag), ("Cache-Control", "no-cache"))
            if self.headers.get("If-None-Match") == etag:
                self.send_response(304)
                for name, value in headers:
                    self.send_header(name, value)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            self._send(200, data, contentType, headers)

        # --- API ------------------------------------------------------------

        def _api(self, path, read):
            if read and path in ("/", "/index.html"):
                self._send(302, b"", headers=(("Location", config.landingUrl),))
                return
            if read and path == "/api/games":
                registry = arcade.registry.registry
                self._json(200, {"games": [self._describe(game) for game in registry]}, public=True)
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
