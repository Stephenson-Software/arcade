# @author Daniel McCoy Stephenson
"""Versioned bundles on disk (RFC 0006 §4).

    <root>/<slug>/<version>/index.html
    <root>/<slug>/<version>/game.zip
    <root>/<slug>/<version>/version.txt
    <root>/<slug>/<version>/.uploaded     (time.time_ns() at upload, for pruning)
    <root>/<slug>/current                 (the live version's name)
    <root>/<slug>/.added                  (time.time_ns() of the slug's first upload)

A version is written into a temporary directory and renamed into place, and
`current` is replaced atomically, so a crash mid-upload leaves the previous
version live. The last KEEP versions are kept; the current one never goes.
"""

import os
import re
import shutil
import tempfile
import threading
import time

from arcade import precompress

VERSION_PATTERN = re.compile(r"^(?!(?:current|plays)$)[0-9A-Za-z][0-9A-Za-z._+-]{0,63}$")
# "current" (the pointer) and "plays" (the counter) are files beside the
# versions, so neither can be a version: a directory by that name would break
# the slug for good.
BUNDLE_FILES = ("index.html", "game.zip", "version.txt")
DEFAULT_KEEP = 5
_UPLOADED = ".uploaded"
_CURRENT = "current"
_PLAYS = "plays"
_ADDED = ".added"  # a dotfile: never a version name (VERSION_PATTERN)


class VersionExists(Exception):
    pass


class NoSuchVersion(Exception):
    pass


class Store(object):
    def __init__(self, root, keep=DEFAULT_KEEP):
        if keep < 1:
            raise ValueError("keep must be at least 1")
        self.root = root
        self.keep = keep
        self._lock = threading.Lock()
        os.makedirs(root, exist_ok=True)

    def _slugDirectory(self, slug):
        return os.path.join(self.root, slug)

    def versionDirectory(self, slug, version):
        if not VERSION_PATTERN.match(version):
            raise NoSuchVersion(version)
        return os.path.join(self._slugDirectory(slug), version)

    def versions(self, slug):
        """The slug's versions, oldest upload first."""
        directory = self._slugDirectory(slug)
        try:
            names = os.listdir(directory)
        except FileNotFoundError:
            return []
        found = []
        for name in names:
            if not VERSION_PATTERN.match(name) or name == _CURRENT:
                continue
            stamp = os.path.join(directory, name, _UPLOADED)
            try:
                with open(stamp, "r") as stampFile:
                    found.append((int(stampFile.read().strip()), name))
            except (OSError, ValueError):
                continue  # not a complete version directory
        return [name for _, name in sorted(found)]

    def current(self, slug):
        try:
            with open(os.path.join(self._slugDirectory(slug), _CURRENT), "r") as currentFile:
                version = currentFile.read().strip()
        except OSError:
            # Missing, or unreadable for any reason: nothing is live. One
            # game's broken pointer must never take down the whole API.
            return None
        if not VERSION_PATTERN.match(version):
            return None
        if not version or not os.path.isdir(self.versionDirectory(slug, version)):
            return None
        return version

    def filePath(self, slug, version, name):
        if name not in BUNDLE_FILES:
            raise KeyError(name)
        return os.path.join(self.versionDirectory(slug, version), name)

    def sitePath(self, slug, version, relative):
        """The on-disk path of a static bundle's file, or None if the
        relative path is unacceptable or the file is not there."""
        from arcade.bundle import BundleError, checkSitePath

        try:
            relative = checkSitePath(relative)
        except BundleError:
            return None
        if relative == _UPLOADED:
            return None
        root = self.versionDirectory(slug, version)
        path = os.path.join(root, *relative.split("/"))
        # Belt and braces: the joined path must still be inside the version.
        if os.path.commonpath([os.path.realpath(root), os.path.realpath(path)]) != os.path.realpath(root):
            return None
        return path if os.path.isfile(path) else None

    def add(self, slug, version, files, activate=True, static=False):
        """Store a validated bundle. For a tak bundle, files maps each
        BUNDLE_FILES name to bytes; for a static one (static=True), every
        relative path to bytes, index.html and version.txt included."""
        if not VERSION_PATTERN.match(version):
            raise ValueError("bad version %r" % version)
        if static:
            from arcade.bundle import checkSitePath

            for name in files:
                checkSitePath(name)
            if "index.html" not in files or "version.txt" not in files:
                raise ValueError("a static bundle needs index.html and version.txt")
            if _UPLOADED in files:
                raise ValueError("%s is reserved" % _UPLOADED)
        elif sorted(files) != sorted(BUNDLE_FILES):
            raise ValueError("a bundle is exactly %s" % ", ".join(BUNDLE_FILES))
        slugDirectory = self._slugDirectory(slug)
        final = os.path.join(slugDirectory, version)
        if os.path.exists(final):
            raise VersionExists(version)
        os.makedirs(slugDirectory, exist_ok=True)
        # Written and compressed outside the lock: gzipping a multi-MB .wasm
        # at level 9 takes seconds, and the lock also guards play counting.
        staging = tempfile.mkdtemp(prefix=".upload-", dir=slugDirectory)
        try:
            for name, data in files.items():
                target = os.path.join(staging, *name.split("/"))
                os.makedirs(os.path.dirname(target), exist_ok=True)
                with open(target, "wb") as out:
                    out.write(data)
            # Each compressible file's .gz sibling, once, so serving it never
            # compresses anything (arcade.precompress).
            precompress.precompressTree(staging)
            uploaded = time.time_ns()
            with open(os.path.join(staging, _UPLOADED), "w") as stamp:
                stamp.write(str(uploaded))
            with self._lock:
                if os.path.exists(final):
                    raise VersionExists(version)
                self._recordAdded(slug, uploaded)
                os.rename(staging, final)
                if activate:
                    self._writeCurrent(slug, version)
                self._prune(slug)
        except BaseException:
            shutil.rmtree(staging, ignore_errors=True)
            raise

    def added(self, slug):
        """When the slug's first version was uploaded (time.time_ns()), or
        None when that is not known. Recorded in .added at the first upload;
        for a slug uploaded before arcade kept that record, its oldest
        version's upload time, but only while no version has ever been
        pruned (fewer than `keep`), since after that the first is gone."""
        try:
            with open(os.path.join(self._slugDirectory(slug), _ADDED), "r") as stamp:
                return int(stamp.read().strip())
        except (OSError, ValueError):
            pass
        return self._oldestUpload(slug)

    def _oldestUpload(self, slug):
        versions = self.versions(slug)
        if not versions or len(versions) >= self.keep:
            return None
        try:
            with open(os.path.join(self._slugDirectory(slug), versions[0], _UPLOADED), "r") as stamp:
                return int(stamp.read().strip())
        except (OSError, ValueError):
            return None

    def _recordAdded(self, slug, now):
        """Under the lock, before a new version lands: write .added if it is
        missing and the first upload is known (this one, or an old one)."""
        path = os.path.join(self._slugDirectory(slug), _ADDED)
        if os.path.exists(path):
            return
        first = now if not self.versions(slug) else self._oldestUpload(slug)
        if first is None:
            return  # pruned before arcade kept the record: the registry's added: says
        handle, temporary = tempfile.mkstemp(prefix=".added-", dir=self._slugDirectory(slug))
        try:
            with os.fdopen(handle, "w") as out:
                out.write("%d\n" % first)
            os.replace(temporary, path)
        except BaseException:
            try:
                os.unlink(temporary)
            except OSError:
                pass
            raise

    def plays(self, slug):
        """How many times the game's page has been served to a person."""
        try:
            with open(os.path.join(self._slugDirectory(slug), _PLAYS), "r") as counter:
                return max(0, int(counter.read().strip()))
        except (OSError, ValueError):
            return 0

    def addPlay(self, slug):
        """Count one play. Written atomically, so a crash never leaves a
        half-written counter; a counter that cannot be read restarts at 0."""
        with self._lock:
            slugDirectory = self._slugDirectory(slug)
            os.makedirs(slugDirectory, exist_ok=True)
            count = self.plays(slug) + 1
            handle, temporary = tempfile.mkstemp(prefix=".plays-", dir=slugDirectory)
            try:
                with os.fdopen(handle, "w") as out:
                    out.write("%d\n" % count)
                os.replace(temporary, os.path.join(slugDirectory, _PLAYS))
            except BaseException:
                try:
                    os.unlink(temporary)
                except OSError:
                    pass
                raise

    def setCurrent(self, slug, version):
        with self._lock:
            if version not in self.versions(slug):
                raise NoSuchVersion(version)
            self._writeCurrent(slug, version)

    def _writeCurrent(self, slug, version):
        slugDirectory = self._slugDirectory(slug)
        handle, temporary = tempfile.mkstemp(prefix=".current-", dir=slugDirectory)
        try:
            with os.fdopen(handle, "w") as out:
                out.write(version + "\n")
            os.replace(temporary, os.path.join(slugDirectory, _CURRENT))
        except BaseException:
            try:
                os.unlink(temporary)
            except OSError:
                pass
            raise

    def _prune(self, slug):
        versions = self.versions(slug)
        live = self.current(slug)
        excess = len(versions) - self.keep
        for version in versions:
            if excess <= 0:
                break
            if version == live:
                continue
            shutil.rmtree(os.path.join(self._slugDirectory(slug), version), ignore_errors=True)
            excess -= 1
