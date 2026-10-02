# @author Daniel McCoy Stephenson
"""Versioned bundles on disk (RFC 0006 §4).

    <root>/<slug>/<version>/index.html
    <root>/<slug>/<version>/game.zip
    <root>/<slug>/<version>/version.txt
    <root>/<slug>/<version>/.uploaded     (time.time_ns() at upload, for pruning)
    <root>/<slug>/current                 (the live version's name)

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

VERSION_PATTERN = re.compile(r"^(?!current$)[0-9A-Za-z][0-9A-Za-z._+-]{0,63}$")
# "current" is the name of the pointer file beside the versions, so it can
# never be a version: a directory by that name would break the slug for good.
BUNDLE_FILES = ("index.html", "game.zip", "version.txt")
DEFAULT_KEEP = 5
_UPLOADED = ".uploaded"
_CURRENT = "current"


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
        with self._lock:
            slugDirectory = self._slugDirectory(slug)
            os.makedirs(slugDirectory, exist_ok=True)
            final = os.path.join(slugDirectory, version)
            if os.path.exists(final):
                raise VersionExists(version)
            staging = tempfile.mkdtemp(prefix=".upload-", dir=slugDirectory)
            try:
                for name, data in files.items():
                    target = os.path.join(staging, *name.split("/"))
                    os.makedirs(os.path.dirname(target), exist_ok=True)
                    with open(target, "wb") as out:
                        out.write(data)
                with open(os.path.join(staging, _UPLOADED), "w") as stamp:
                    stamp.write(str(time.time_ns()))
                os.rename(staging, final)
            except BaseException:
                shutil.rmtree(staging, ignore_errors=True)
                raise
            if activate:
                self._writeCurrent(slug, version)
            self._prune(slug)

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
