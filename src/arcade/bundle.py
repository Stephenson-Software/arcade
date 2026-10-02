# @author Daniel McCoy Stephenson
"""Unpack and validate an uploaded bundle before anything is written (RFC 0006 §4).

An upload is a .tar (optionally compressed) or .zip holding exactly
index.html, game.zip and version.txt, at its top level (a leading "./" is
fine). version.txt must agree with the version in the URL, and game.zip must
be a zip carrying tak's four browser assets - arcade serves /tak/ out of each
game's own bundle (RFC 0006 §5, decided v1.1), so a bundle without them would
be a blank page.
"""

import io
import posixpath
import tarfile
import zipfile

from arcade.store import BUNDLE_FILES

TAK_ASSET_DIRECTORY = "src/tak/web/assets/"
TAK_ASSETS = ("boot.js", "client.css", "client.js", "game-worker.js")


class BundleError(ValueError):
    """The upload is not an acceptable bundle; the message says why (sent as a 400)."""


class BundleTooLarge(BundleError):
    """The upload unpacks to more than the size cap (sent as a 413)."""


def _normalise(name):
    name = name.replace("\\", "/")
    while name.startswith("./"):
        name = name[2:]
    return name


def _checkName(name):
    if name not in BUNDLE_FILES:
        raise BundleError(
            "unexpected file %r in the bundle; it must hold exactly %s at its top level"
            % (name, ", ".join(BUNDLE_FILES))
        )


def _fromZip(data, maxBytes):
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise BundleError("the upload is not a readable zip")
    files = {}
    total = 0
    for info in archive.infolist():
        name = _normalise(info.filename)
        if not name or name.endswith("/"):
            continue  # directory entries
        _checkName(name)
        if name in files:
            raise BundleError("%s appears twice" % name)
        total += info.file_size
        if total > maxBytes:
            raise BundleTooLarge("the bundle unpacks to more than %d bytes" % maxBytes)
        files[name] = archive.read(info)
    return files


def _fromTar(data, maxBytes):
    try:
        archive = tarfile.open(fileobj=io.BytesIO(data), mode="r:*")
    except (tarfile.TarError, EOFError, OSError):
        raise BundleError("the upload is neither a zip nor a readable tar")
    files = {}
    total = 0
    with archive:
        for member in archive:
            name = _normalise(member.name)
            if member.isdir() and name in ("", "."):
                continue
            if not member.isfile():
                raise BundleError("%r is not a regular file; links and directories are refused" % member.name)
            _checkName(name)
            if name in files:
                raise BundleError("%s appears twice" % name)
            total += member.size
            if total > maxBytes:
                raise BundleTooLarge("the bundle unpacks to more than %d bytes" % maxBytes)
            extracted = archive.extractfile(member)
            files[name] = extracted.read() if extracted else b""
    return files


def unpack(data, version, maxBytes):
    """Return {name: bytes} for a valid bundle, or raise BundleError."""
    if data[:4] == b"PK\x03\x04":
        files = _fromZip(data, maxBytes)
    else:
        files = _fromTar(data, maxBytes)
    missing = [name for name in BUNDLE_FILES if name not in files]
    if missing:
        raise BundleError("the bundle is missing %s" % ", ".join(missing))
    try:
        stated = files["version.txt"].decode("utf-8").strip()
    except UnicodeDecodeError:
        raise BundleError("version.txt is not UTF-8 text")
    if stated != version:
        raise BundleError(
            "version.txt says %r but the upload is for version %r" % (stated, version)
        )
    try:
        game = zipfile.ZipFile(io.BytesIO(files["game.zip"]))
        names = set(game.namelist())
    except zipfile.BadZipFile:
        raise BundleError("game.zip is not a readable zip")
    absent = [asset for asset in TAK_ASSETS if TAK_ASSET_DIRECTORY + asset not in names]
    if absent:
        raise BundleError(
            "game.zip has no %s under %s; arcade serves /tak/ from the game's own bundle"
            % (", ".join(absent), TAK_ASSET_DIRECTORY)
        )
    return files


def readAsset(gameZipPath, name):
    """The bytes of one flat tak asset from a stored game.zip, or None."""
    if not name or posixpath.basename(name) != name or name.startswith("."):
        return None
    try:
        with zipfile.ZipFile(gameZipPath) as game:
            return game.read(TAK_ASSET_DIRECTORY + name)
    except (KeyError, OSError, zipfile.BadZipFile):
        return None
