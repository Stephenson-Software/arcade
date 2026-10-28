# @author Daniel McCoy Stephenson
"""Pre-compressed copies of a game's files, and serving files in chunks.

A Strata game ships multi-MB .wasm and .js files. Compressing them on every
request (the gateway's Traefik used to) costs memory per response; reading a
whole file to answer one request (arcade used to) costs its size. Instead:

  - every compressible file gets a gzip sibling, `<name>.gz`, written once at
    level 9 - at upload for new versions, and lazily (in one background
    thread, one file at a time) for versions stored before this existed;
  - a bundle's own `<name>.br` or `<name>.gz` (dotnet and Emscripten builds
    ship them) is used as is - brotli is not in the standard library, so a
    `.br` is served only when the bundle brings one;
  - a request is answered from the variant its Accept-Encoding prefers, with
    Content-Encoding set, so the proxy in front passes it through untouched;
  - every file is sent in CHUNK_BYTES pieces, never read whole.
"""

import gzip
import mimetypes
import os
import queue
import shutil
import sys
import tempfile
import threading

CHUNK_BYTES = 64 * 1024
# Below this the gzip header and the extra request are not worth it (Traefik's
# compress middleware uses the same floor).
MIN_BYTES = 1024
# The content types the gateway's game-compress middleware compressed.
COMPRESSIBLE_TYPES = frozenset(
    (
        "application/wasm",
        "text/html",
        "text/javascript",
        "application/javascript",
        "text/css",
        "text/plain",
        "application/json",
        "application/manifest+json",
        "image/svg+xml",
    )
)
mimetypes.add_type("text/javascript", ".js")
mimetypes.add_type("text/javascript", ".mjs")
mimetypes.add_type("text/css", ".css")
# application/wasm is what lets a browser compile a module while it streams,
# and it still does when the response carries Content-Encoding.
mimetypes.add_type("application/wasm", ".wasm")
mimetypes.add_type("application/json", ".json")
mimetypes.add_type("application/octet-stream", ".data")
mimetypes.add_type("application/octet-stream", ".apk")


def guessType(name):
    """A file's Content-Type by its name, as arcade serves it."""
    return mimetypes.guess_type(name)[0] or "application/octet-stream"


# Preferred first when the client weighs them equally: br is the smaller.
ENCODINGS = (("br", ".br"), ("gzip", ".gz"))


def log(message):
    print("[arcade] %s" % message, file=sys.stderr, flush=True)


def compressible(contentType):
    return (contentType or "").split(";", 1)[0].strip().lower() in COMPRESSIBLE_TYPES


def parseAcceptEncoding(header):
    """{coding: q} for an Accept-Encoding header. "x-gzip" counts as gzip."""
    weights = {}
    for part in (header or "").split(","):
        fields = part.strip().split(";")
        coding = fields[0].strip().lower()
        if not coding:
            continue
        q = 1.0
        for parameter in fields[1:]:
            name, _, value = parameter.strip().partition("=")
            if name.strip().lower() == "q":
                try:
                    q = float(value.strip())
                except ValueError:
                    q = 0.0
        if coding == "x-gzip":
            coding = "gzip"
        # A coding named twice (gzip and x-gzip) keeps its higher weight.
        weights[coding] = max(q, weights[coding]) if coding in weights else q
    return weights


def acceptable(weights, coding):
    """The q the client gives a coding (0 = refused)."""
    if coding in weights:
        return weights[coding]
    if "*" in weights:
        return weights["*"]
    return 0.0


def choose(path, acceptEncoding):
    """(file to send, Content-Encoding or None) for a request for `path`.
    The variants are siblings named <path>.br and <path>.gz; the identity file
    is the fallback whenever no variant is both present and accepted."""
    weights = parseAcceptEncoding(acceptEncoding)
    best = None
    for coding, suffix in ENCODINGS:
        q = acceptable(weights, coding)
        if q <= 0:
            continue
        variant = path + suffix
        if not os.path.isfile(variant):
            continue
        if best is None or q > best[0]:
            best = (q, variant, coding)
    if best is None:
        return path, None
    return best[1], best[2]


def writeGzip(path):
    """Write <path>.gz beside path, at level 9, atomically: a reader sees the
    whole file or none. Streams, so memory stays flat whatever the size.
    Returns True if it was written (or already there)."""
    target = path + ".gz"
    if os.path.exists(target):
        return True
    directory = os.path.dirname(path) or "."
    handle, temporary = tempfile.mkstemp(prefix=".gz-", dir=directory)
    try:
        with open(path, "rb") as source, os.fdopen(handle, "wb") as raw:
            # mtime=0 and no file name: the same input always gives the same bytes.
            with gzip.GzipFile(filename="", mode="wb", compresslevel=9, fileobj=raw, mtime=0) as out:
                shutil.copyfileobj(source, out, CHUNK_BYTES)
        os.chmod(temporary, 0o644)
        os.replace(temporary, target)
        return True
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def needsGzip(path, contentType):
    """Whether path is a compressible file with no gzip sibling yet."""
    if path.endswith((".gz", ".br")):
        return False  # a variant itself, asked for by name
    if not compressible(contentType) or os.path.exists(path + ".gz"):
        return False
    try:
        return os.path.getsize(path) >= MIN_BYTES
    except OSError:
        return False


def precompressTree(root):
    """Give every compressible file under root a .gz sibling (at upload, in
    the staging directory, before the version goes live)."""
    for directory, _, names in os.walk(root):
        present = set(names)
        for name in names:
            if name.endswith((".gz", ".br")) or name + ".gz" in present:
                continue
            path = os.path.join(directory, name)
            if needsGzip(path, guessType(name)):
                writeGzip(path)


class Backfill(object):
    """Writes missing .gz siblings for files stored before arcade made them,
    the first time each is requested. One background thread, one file at a
    time, so a burst of first requests never compresses in parallel; the
    request that triggers it is answered uncompressed straight away."""

    def __init__(self):
        self._queue = queue.Queue()
        self._lock = threading.Lock()
        self._pending = set()
        self._failed = set()
        self._thread = None

    def request(self, path):
        with self._lock:
            if path in self._pending or path in self._failed:
                return
            self._pending.add(path)
            if self._thread is None:
                self._thread = threading.Thread(target=self._run, name="arcade-gzip", daemon=True)
                self._thread.start()
        self._queue.put(path)

    def _run(self):
        while True:
            path = self._queue.get()
            try:
                writeGzip(path)
            except OSError as e:
                # A pruned version, a read-only volume: do not try again.
                log("could not write %s.gz: %s" % (path, e))
                with self._lock:
                    self._failed.add(path)
            finally:
                with self._lock:
                    self._pending.discard(path)
                self._queue.task_done()

    def wait(self):
        """Block until everything queued so far is written (for tests)."""
        self._queue.join()
