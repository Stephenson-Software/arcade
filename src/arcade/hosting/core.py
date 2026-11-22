# @author Daniel McCoy Stephenson
"""The hosting core: which game a host names, what the API says about a
game, who may deploy it, and what counts as a play. Pure policy over the
ports in arcade.hosting.ports; it does no I/O of its own."""

import datetime
import hashlib
import hmac
import re

from arcade import bundle
from arcade.hosting.model import Denied, Deployed, Rejected
from arcade.hosting.ports.version_store import VERSION_PATTERN, NoSuchVersion, VersionExists

# User agents that are not a person opening a game: crawlers, link-preview
# fetchers and scripts. Their page loads are not counted as plays.
# `arcade-watch` is the nightly health check's own marker: it appends it to
# every browser profile's User-Agent (its iPhone profile is otherwise a plain
# Safari string), so its loads never count.
_NOT_A_PERSON = re.compile(
    r"bot|crawl|spider|slurp|preview|facebookexternalhit|embedly|curl|wget|python|"
    r"go-http-client|java/|okhttp|headless|lighthouse|monitor|uptime|arcade-watch",
    re.I,
)


def hashToken(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def addedOf(game, store):
    """When the game joined the arcade, as an ISO 8601 UTC time ("...Z"), or
    None: the registry's `added:` (a day, as its midnight UTC, or a time) if
    given, else its first upload."""
    if isinstance(game.added, datetime.datetime):
        return game.added.astimezone(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    if game.added is not None:
        return game.added.isoformat() + "T00:00:00Z"
    stamp = store.added(game.slug)
    if stamp is None:
        return None
    moment = datetime.datetime.fromtimestamp(stamp / 1e9, datetime.timezone.utc)
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


class Hosting(object):
    """The policy one arcade process applies to every request.

    catalog   GameCatalog     the registered games
    versions  VersionStore    each game's versions and current one
    counter   PlayCounter     each game's plays
    reporter  EventReporter   trace
    notes     ReleaseNotes    "what's new" per current version
    visits    arcade.visits.Visits (in memory: who has played today)
    log       a callable taking one line for the server's log
    """

    def __init__(self, domain, catalog, versions, counter, reporter, notes, visits, maxUploadBytes, log):
        self.domain = domain
        self.catalog = catalog
        self.versions = versions
        self.counter = counter
        self.reporter = reporter
        self.notes = notes
        self.visits = visits
        self.maxUploadBytes = maxUploadBytes
        self._log = log

    def games(self):
        return self.catalog.games()

    # --- reading ------------------------------------------------------------

    def gameForHost(self, host):
        """The Game a request's Host header names, or None."""
        registry = self.catalog.games()
        suffix = "." + self.domain
        if host.endswith(suffix):
            label = host[: -len(suffix)]
            if "." not in label:
                return registry.get(label)
            return None
        return registry.forAlias(host)

    def notesFor(self, game):
        """"What's new" for the game's current version, or None (arcade.remote)."""
        return self.notes.notes(game.slug, game.repo, self.versions.current(game.slug))

    def describe(self, game):
        return {
            "slug": game.slug,
            "title": game.title,
            "repo": game.repo,
            "url": "https://%s.%s/" % (game.slug, self.domain),
            "aliases": list(game.aliases),
            "kind": game.kind,
            "isolation": game.isolation,
            "current": self.versions.current(game.slug),
            "versions": self.versions.versions(game.slug),
            "plays": self.counter.plays(game.slug),
            "added": addedOf(game, self.versions),
            "tags": list(game.tags),
            "org": game.org,
            "engine": game.engine,
            # Its place among the featured games (1 first), or None.
            "featured": game.featured,
            # "What's new" in the current version: the GitHub release's
            # notes, once arcade has looked them up (arcade.remote).
            "notes": self.notesFor(game),
        }

    # --- plays --------------------------------------------------------------

    def played(self, slug, userAgent, client=None):
        """A person loaded the game's page: count it, and report it to trace,
        once per visitor (`client`, the address, with `userAgent`) per game
        per UTC day (arcade.visits). Reloads and later visits that day are
        not plays."""
        if not userAgent or _NOT_A_PERSON.search(userAgent):
            return
        if not self.visits.first(slug, client or "", userAgent):
            return
        try:
            self.counter.addPlay(slug)
        except OSError as e:
            self._log("could not count a play of %s: %s" % (slug, e))
        self.reporter.report("page-served", tags={"slug": slug})

    # --- deploying ----------------------------------------------------------

    def authorise(self, slug, authorization):
        """The Game if the Authorization header's bearer token is right for
        it; otherwise Denied."""
        game = self.catalog.games().get(slug)
        header = authorization or ""
        if not header.startswith("Bearer ") or not header[7:].strip():
            return Denied(401, "an Authorization: Bearer <token> header is required")
        presented = hashToken(header[7:].strip())
        expected = game.tokenSha256 if game else "0" * 64
        if game is None or not hmac.compare_digest(presented, expected):
            # Unknown slug and wrong token look the same from outside.
            return Denied(403, "this token cannot deploy that game")
        return game

    @staticmethod
    def checkVersion(version):
        """Rejected if `version` cannot name a version; otherwise None."""
        if not VERSION_PATTERN.match(version):
            return Rejected(400, "bad version %r" % version)
        return None

    def deploy(self, game, version, data, activate, length):
        """Unpack an uploaded bundle (`data`, the request body, which declared
        `length` bytes) and store it as `version`: Deployed(201) or Rejected."""
        slug = game.slug
        static = game.kind == "static"
        try:
            if static:
                files = bundle.unpackStatic(data, version, self.maxUploadBytes)
            else:
                files = bundle.unpack(data, version, self.maxUploadBytes)
        except bundle.BundleTooLarge as e:
            return Rejected(413, str(e))
        except bundle.BundleError as e:
            return Rejected(400, str(e))
        try:
            self.versions.add(slug, version, files, activate=activate, static=static)
        except VersionExists:
            return Rejected(409, "version %s already exists; versions are immutable" % version)
        except (ValueError, OSError) as e:
            # Validation should have caught it; if not, still answer.
            self._log("%s %s upload could not be stored: %s" % (slug, version, e))
            return Rejected(400, "the bundle could not be stored: %s" % e)
        self._log(
            "%s %s uploaded (%d bytes)%s" % (slug, version, length, " and made current" if activate else "")
        )
        return Deployed(201, game=game)

    def rollback(self, game, version):
        """Make a stored version current: Deployed(200) or Rejected(404)."""
        try:
            self.versions.setCurrent(game.slug, version)
        except NoSuchVersion:
            return Rejected(404, "version %r is not on disk" % version)
        self._log("%s current set to %s" % (game.slug, version))
        return Deployed(200, game=game)
