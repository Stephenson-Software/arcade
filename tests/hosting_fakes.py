"""Test doubles for the hosting core's ports (arcade.hosting.ports). Each one
passes the same contract test as its production adapter
(test_hosting_contracts.py)."""

from arcade import registry
from arcade.hosting.ports import NoSuchVersion, VersionExists


class FakeCatalog(object):
    def __init__(self, text="games: []\n", domain=None):
        self._registry = registry.loads(text, domain=domain)

    def games(self):
        return self._registry


class FakeStore(object):
    """VersionStore and PlayCounter in memory."""

    def __init__(self, now=1_700_000_000_000_000_000):
        self.now = now
        self.stored = {}  # slug -> {version: files}, in upload order
        self.currents = {}
        self.firsts = {}
        self.counts = {}
        self.failPlays = False

    def current(self, slug):
        return self.currents.get(slug)

    def versions(self, slug):
        return list(self.stored.get(slug, {}))

    def added(self, slug):
        return self.firsts.get(slug)

    def add(self, slug, version, files, activate=True, static=False):
        versions = self.stored.setdefault(slug, {})
        if version in versions:
            raise VersionExists(version)
        versions[version] = dict(files)
        self.firsts.setdefault(slug, self.now)
        if activate:
            self.currents[slug] = version

    def setCurrent(self, slug, version):
        if version not in self.stored.get(slug, {}):
            raise NoSuchVersion(version)
        self.currents[slug] = version

    def plays(self, slug):
        return self.counts.get(slug, 0)

    def addPlay(self, slug):
        if self.failPlays:
            raise OSError("disk full")
        self.counts[slug] = self.counts.get(slug, 0) + 1


class Recorder(object):
    """EventReporter that keeps what it was told."""

    def __init__(self):
        self.events = []

    def report(self, name, tags=None):
        self.events.append((name, tags))


class FakeNotes(object):
    """ReleaseNotes from a dict: (slug, current) -> notes."""

    def __init__(self, known=None):
        self.known = dict(known or {})

    def notes(self, slug, repo, current):
        return self.known.get((slug, current))


class FakeVisits(object):
    """Every visit is the visitor's first today, unless `seen` says not."""

    def __init__(self):
        self.seen = set()

    def first(self, slug, client, userAgent):
        key = (slug, client, userAgent)
        if key in self.seen:
            return False
        self.seen.add(key)
        return True
