import gzip
import hashlib
import json
import os
import tracemalloc

import pytest

from arcade import precompress
from arcade.store import Store
from helpers import bundleFiles
from test_server import DOMAIN, arcade, request, tarBundle, upload  # noqa: F401 (arcade is a fixture)

RPS = "rps." + DOMAIN
TIDEWATER = "tidewater." + DOMAIN
# Compressible, and well over precompress.MIN_BYTES.
WASM = b"\0asm\x01\0\0\0" + b"(module (func $f (result i32) i32.const 42))\n" * 2000
SCRIPT = b"export function boot() { return 'hello from the game'; }\n" * 500


def _site(version, extra=None):
    files = {
        "index.html": ("<html>site %s</html>" % version).encode() * 100,
        "version.txt": (version + "\n").encode(),
        "pkg/game.wasm": WASM,
        "tiny.js": b"x()",
        "rps.apk": b"apk" * 1000,
    }
    files.update(extra or {})
    return files


def _deploy(arcade, extra=None, version="0.1"):
    response, data = upload(arcade, slug="rps", version=version, body=tarBundle(_site(version, extra)))
    assert response.status == 201, data
    return arcade.store.versionDirectory("rps", version)


def _get(arcade, path, acceptEncoding=None, method="GET", headers=None):
    allHeaders = dict(headers or {})
    if acceptEncoding is not None:
        allHeaders["Accept-Encoding"] = acceptEncoding
    return request(arcade, method, RPS, path, headers=allHeaders)


# --- Accept-Encoding ------------------------------------------------------


@pytest.mark.parametrize(
    "header, expected",
    [
        ("gzip, deflate, br, zstd", {"gzip": 1.0, "deflate": 1.0, "br": 1.0, "zstd": 1.0}),
        ("br;q=0.5, gzip;q=0.8", {"br": 0.5, "gzip": 0.8}),
        ("GZIP ; Q=0", {"gzip": 0.0}),
        ("x-gzip", {"gzip": 1.0}),
        ("gzip;q=nonsense", {"gzip": 0.0}),
        ("", {}),
        (None, {}),
    ],
)
def test_accept_encoding_is_parsed_with_q_values(header, expected):
    assert precompress.parseAcceptEncoding(header) == expected


def test_choose_prefers_br_then_gzip_and_honours_q(tmp_path):
    path = str(tmp_path / "game.wasm")
    for suffix in ("", ".gz", ".br"):
        open(path + suffix, "wb").close()
    assert precompress.choose(path, "gzip, br") == (path + ".br", "br")
    assert precompress.choose(path, "gzip") == (path + ".gz", "gzip")
    assert precompress.choose(path, "br;q=0.5, gzip") == (path + ".gz", "gzip")
    assert precompress.choose(path, "br;q=0, gzip;q=0") == (path, None)
    assert precompress.choose(path, "*") == (path + ".br", "br")
    assert precompress.choose(path, "*;q=0") == (path, None)
    assert precompress.choose(path, "identity") == (path, None)
    assert precompress.choose(path, None) == (path, None)
    os.unlink(path + ".br")
    assert precompress.choose(path, "br, gzip") == (path + ".gz", "gzip")
    assert precompress.choose(path, "br") == (path, None)


def test_acceptable_falls_back_to_the_wildcard_only_for_an_unnamed_coding():
    weights = precompress.parseAcceptEncoding("gzip;q=0, *;q=0.5")
    assert precompress.acceptable(weights, "gzip") == 0.0  # named, so * does not apply
    assert precompress.acceptable(weights, "br") == 0.5
    assert precompress.acceptable(precompress.parseAcceptEncoding("gzip"), "br") == 0.0
    assert precompress.acceptable({}, "gzip") == 0.0


# --- content types and what is compressible --------------------------------


@pytest.mark.parametrize(
    "name, contentType",
    [
        # The types README's "Compression" section names as compressible.
        ("pkg/game.wasm", "application/wasm"),
        ("index.html", "text/html"),
        ("page.htm", "text/html"),
        ("game.js", "text/javascript"),
        ("module.mjs", "text/javascript"),
        ("style.css", "text/css"),
        ("notes.txt", "text/plain"),
        ("data.json", "application/json"),
        ("manifest.webmanifest", "application/manifest+json"),
        ("icon.svg", "image/svg+xml"),
        ("GAME.WASM", "application/wasm"),
        # Not compressible: binary game data, packages, images, unknowns.
        ("index.data", "application/octet-stream"),
        ("rps.apk", "application/octet-stream"),
        ("icon.png", "image/png"),
        ("Makefile", "application/octet-stream"),
        ("save.unknownext", "application/octet-stream"),
    ],
)
def test_guess_type_names_each_file_as_it_is_served(name, contentType):
    assert precompress.guessType(name) == contentType


def test_only_the_documented_types_are_compressible():
    compressible = [
        "application/wasm",
        "text/html",
        "text/javascript",
        "application/javascript",
        "text/css",
        "text/plain",
        "application/json",
        "application/manifest+json",
        "image/svg+xml",
    ]
    assert all(precompress.compressible(t) for t in compressible)
    # Parameters and case do not matter: the static path adds "; charset=utf-8".
    assert precompress.compressible("text/html; charset=utf-8")
    assert precompress.compressible("TEXT/CSS")
    for contentType in ("application/octet-stream", "image/png", "application/zip", "", None):
        assert not precompress.compressible(contentType), contentType


def test_a_variant_name_is_typed_as_its_original():
    # Characterization: mimetypes reads ".gz" as an encoding, so a variant asked
    # for by name gets its original's type (see the by-name serving test below).
    assert precompress.guessType("pkg/game.wasm.gz") == "application/wasm"
    assert precompress.guessType("game.js.gz") == "text/javascript"


def test_needs_gzip_starts_at_min_bytes(tmp_path):
    under = tmp_path / "under.js"
    under.write_bytes(b"x" * (precompress.MIN_BYTES - 1))
    exact = tmp_path / "exact.js"
    exact.write_bytes(b"x" * precompress.MIN_BYTES)
    assert not precompress.needsGzip(str(under), "text/javascript")
    assert precompress.needsGzip(str(exact), "text/javascript")


def test_needs_gzip_is_false_for_a_variant_an_existing_sibling_a_binary_or_a_missing_file(tmp_path):
    big = b"x" * (precompress.MIN_BYTES * 4)
    for name in ("game.wasm.gz", "game.wasm.br", "done.js", "done.js.gz", "index.data"):
        (tmp_path / name).write_bytes(big)
    assert not precompress.needsGzip(str(tmp_path / "game.wasm.gz"), "application/wasm")
    assert not precompress.needsGzip(str(tmp_path / "game.wasm.br"), "application/wasm")
    assert not precompress.needsGzip(str(tmp_path / "done.js"), "text/javascript")
    assert not precompress.needsGzip(str(tmp_path / "index.data"), "application/octet-stream")
    assert not precompress.needsGzip(str(tmp_path / "gone.js"), "text/javascript")


def test_precompress_tree_walks_subdirectories_and_skips_what_needs_nothing(tmp_path):
    big = b"function f() { return 1; }\n" * 200
    (tmp_path / "pkg" / "deep").mkdir(parents=True)
    (tmp_path / "index.html").write_bytes(big)
    (tmp_path / "pkg" / "deep" / "game.js").write_bytes(big)
    (tmp_path / "pkg" / "tiny.css").write_bytes(b"a{}")
    (tmp_path / "pkg" / "index.data").write_bytes(big)
    (tmp_path / "pkg" / "own.js").write_bytes(big)
    (tmp_path / "pkg" / "own.js.gz").write_bytes(b"the bundle's own")
    precompress.precompressTree(str(tmp_path))
    written = sorted(
        os.path.relpath(os.path.join(directory, name), str(tmp_path))
        for directory, _, names in os.walk(str(tmp_path))
        for name in names
        if name.endswith(".gz")
    )
    assert written == [
        "index.html.gz",
        os.path.join("pkg", "deep", "game.js.gz"),
        os.path.join("pkg", "own.js.gz"),
    ]
    assert (tmp_path / "pkg" / "own.js.gz").read_bytes() == b"the bundle's own"
    assert gzip.decompress((tmp_path / "pkg" / "deep" / "game.js.gz").read_bytes()) == big


def test_write_gzip_is_level_9_deterministic_and_leaves_no_temporary(tmp_path):
    path = tmp_path / "game.wasm"
    path.write_bytes(WASM)
    assert precompress.writeGzip(str(path))
    written = (tmp_path / "game.wasm.gz").read_bytes()
    assert gzip.decompress(written) == WASM
    assert len(written) < len(WASM) // 10
    os.unlink(str(tmp_path / "game.wasm.gz"))
    precompress.writeGzip(str(path))
    assert (tmp_path / "game.wasm.gz").read_bytes() == written
    assert sorted(os.listdir(str(tmp_path))) == ["game.wasm", "game.wasm.gz"]


def test_a_failed_gzip_leaves_no_temporary(tmp_path):
    with pytest.raises(OSError):
        precompress.writeGzip(str(tmp_path / "missing.wasm"))
    assert os.listdir(str(tmp_path)) == []


# --- at upload -------------------------------------------------------------


def test_upload_writes_a_gzip_sibling_for_compressible_files_only(arcade):
    root = _deploy(arcade)
    names = set()
    for directory, _, files in os.walk(root):
        names.update(os.path.relpath(os.path.join(directory, name), root) for name in files)
    assert "index.html.gz" in names and os.path.join("pkg", "game.wasm.gz") in names
    # Too small to be worth it; and an .apk is not a compressible type.
    assert "tiny.js.gz" not in names and "rps.apk.gz" not in names and "version.txt.gz" not in names
    assert gzip.decompress(open(os.path.join(root, "pkg", "game.wasm.gz"), "rb").read()) == WASM
    assert not [name for name in names if name.startswith(".gz-")]


def test_a_tak_bundle_gets_a_gzip_index(tmp_path):
    store = Store(str(tmp_path))
    files = bundleFiles()
    files["index.html"] = b"<html>" + b"tak " * 1000 + b"</html>"
    store.add("tidewater", "1.0.0", files)
    root = store.versionDirectory("tidewater", "1.0.0")
    assert sorted(os.listdir(root)) == [".uploaded", "game.zip", "index.html", "index.html.gz", "version.txt"]


def test_a_bundles_own_variants_are_kept_not_regenerated(arcade):
    ownGzip = gzip.compress(WASM, compresslevel=1)
    root = _deploy(arcade, {"pkg/game.wasm.gz": ownGzip, "pkg/game.wasm.br": b"pretend brotli"})
    assert open(os.path.join(root, "pkg", "game.wasm.gz"), "rb").read() == ownGzip
    assert not os.path.exists(os.path.join(root, "pkg", "game.wasm.gz.gz"))
    assert not os.path.exists(os.path.join(root, "pkg", "game.wasm.br.gz"))


# --- negotiation -----------------------------------------------------------


def test_gzip_is_served_to_a_client_that_accepts_it(arcade):
    _deploy(arcade)
    response, data = _get(arcade, "/pkg/game.wasm", "gzip, deflate")
    assert response.status == 200
    assert response.getheader("Content-Encoding") == "gzip"
    # Still application/wasm, so the browser compiles while it streams.
    assert response.getheader("Content-Type") == "application/wasm"
    assert response.getheader("Vary") == "Accept-Encoding"
    assert int(response.getheader("Content-Length")) == len(data) < len(WASM)
    assert gzip.decompress(data) == WASM


def test_identity_without_accept_encoding_or_when_gzip_is_refused(arcade):
    _deploy(arcade)
    for header in (None, "identity", "gzip;q=0", "br", "*;q=0"):
        response, data = _get(arcade, "/pkg/game.wasm", header)
        assert response.getheader("Content-Encoding") is None, header
        assert response.getheader("Vary") == "Accept-Encoding", header
        assert data == WASM, header
        assert int(response.getheader("Content-Length")) == len(WASM)


def test_a_bundles_br_is_served_when_accepted(arcade):
    _deploy(arcade, {"pkg/game.wasm.br": b"pretend brotli"})
    response, data = _get(arcade, "/pkg/game.wasm", "gzip, deflate, br, zstd")
    assert (response.getheader("Content-Encoding"), data) == ("br", b"pretend brotli")
    assert response.getheader("Content-Type") == "application/wasm"
    response, data = _get(arcade, "/pkg/game.wasm", "gzip, br;q=0")
    assert response.getheader("Content-Encoding") == "gzip"
    assert gzip.decompress(data) == WASM


def test_a_bundles_gzip_is_used_for_any_type(arcade):
    # beyond-nations ships its own .gz siblings; an .apk is not a type arcade
    # compresses, but a sibling the bundle brings is still served.
    ownGzip = gzip.compress(b"apk" * 1000)
    _deploy(arcade, {"rps.apk.gz": ownGzip})
    response, data = _get(arcade, "/rps.apk", "gzip")
    assert (response.getheader("Content-Encoding"), data) == ("gzip", ownGzip)
    assert response.getheader("Content-Type") == "application/octet-stream"
    response, data = _get(arcade, "/rps.apk")
    assert response.getheader("Content-Encoding") is None and response.getheader("Vary") == "Accept-Encoding"


def test_uncompressible_files_carry_no_vary(arcade):
    _deploy(arcade)
    response, data = _get(arcade, "/rps.apk", "gzip")
    assert response.getheader("Content-Encoding") is None and response.getheader("Vary") is None
    assert data == b"apk" * 1000


def test_html_index_is_negotiated_and_still_counts_a_play(arcade):
    _deploy(arcade)
    response, data = _get(arcade, "/", "gzip")
    assert response.getheader("Content-Encoding") == "gzip"
    assert response.getheader("Content-Type") == "text/html; charset=utf-8"
    assert response.getheader("Link") == '<https://example.com/play/rps>; rel="canonical"'
    assert gzip.decompress(data).startswith(b"<html>site 0.1</html>")
    # Counted after the response is sent; another request lets it land.
    _, described = request(arcade, "GET", DOMAIN, "/api/games/rps")
    assert json.loads(described)["plays"] == 1


def test_a_tak_games_index_is_negotiated(arcade):
    files = bundleFiles(index=b"<html>" + b"tak " * 1000 + b"</html>")
    response, data = upload(arcade, body=tarBundle(files))
    assert response.status == 201, data
    response, data = request(arcade, "GET", TIDEWATER, "/", headers={"Accept-Encoding": "gzip"})
    assert response.getheader("Content-Encoding") == "gzip"
    assert gzip.decompress(data) == files["index.html"]
    response, data = request(arcade, "GET", TIDEWATER, "/web/game.zip", headers={"Accept-Encoding": "gzip"})
    assert response.getheader("Content-Encoding") is None and data == files["game.zip"]


# --- ETag / 304 / HEAD -------------------------------------------------------


def test_each_variant_has_its_own_etag_and_304(arcade):
    _deploy(arcade, {"pkg/game.wasm.br": b"pretend brotli"})
    tags = {}
    for header, coding in ((None, None), ("gzip", "gzip"), ("br", "br")):
        response, _ = _get(arcade, "/pkg/game.wasm", header)
        assert response.getheader("Content-Encoding") == coding
        tags[coding] = response.getheader("ETag")
    tag = hashlib.sha256(b"pkg/game.wasm").hexdigest()[:16]
    # Identity keeps the tag arcade has always sent.
    assert tags == {None: '"0.1-%s"' % tag, "gzip": '"0.1-%s-gz"' % tag, "br": '"0.1-%s-br"' % tag}
    for header, coding in ((None, None), ("gzip", "gzip"), ("br", "br")):
        response, data = _get(arcade, "/pkg/game.wasm", header, headers={"If-None-Match": tags[coding]})
        assert (response.status, data) == (304, b""), header
        assert response.getheader("ETag") == tags[coding]
        assert response.getheader("Vary") == "Accept-Encoding"
    # A tag for one variant does not validate another.
    response, data = _get(arcade, "/pkg/game.wasm", "gzip", headers={"If-None-Match": tags[None]})
    assert response.status == 200 and gzip.decompress(data) == WASM


def test_head_sends_the_variants_headers_and_no_body(arcade):
    root = _deploy(arcade)
    response, data = _get(arcade, "/pkg/game.wasm", "gzip", method="HEAD")
    assert (response.status, data) == (200, b"")
    assert response.getheader("Content-Encoding") == "gzip"
    assert int(response.getheader("Content-Length")) == os.path.getsize(
        os.path.join(root, "pkg", "game.wasm.gz")
    )
    response, data = _get(arcade, "/pkg/game.wasm", method="HEAD")
    assert int(response.getheader("Content-Length")) == len(WASM) and data == b""


def test_range_is_not_supported_and_the_whole_file_is_sent(arcade):
    # arcade has never answered Range; this change keeps it that way.
    _deploy(arcade)
    response, data = _get(arcade, "/pkg/game.wasm", headers={"Range": "bytes=0-9"})
    assert response.status == 200 and data == WASM and response.getheader("Accept-Ranges") is None


# --- streaming -------------------------------------------------------------


def _readInChunks(arcade, host, path, headers=None):
    import http.client

    connection = http.client.HTTPConnection("127.0.0.1", arcade.port, timeout=30)
    allHeaders = {"Host": host, "User-Agent": "Mozilla/5.0 (test browser)"}
    allHeaders.update(headers or {})
    connection.request("GET", path, headers=allHeaders)
    response = connection.getresponse()
    total = 0
    digest = hashlib.sha256()
    while True:
        chunk = response.read(64 * 1024)
        if not chunk:
            break
        total += len(chunk)
        digest.update(chunk)
    connection.close()
    return response, total, digest.hexdigest()


def test_a_large_file_is_streamed_without_being_read_whole(arcade):
    size = 20 * 1024 * 1024
    big = os.urandom(1024) * (size // 1024)
    arcade.store.add(
        "rps",
        "big",
        {"index.html": b"<html></html>", "version.txt": b"big\n", "index.data": big},
        static=True,
    )
    expected = hashlib.sha256(big).hexdigest()
    del big
    tracemalloc.start()
    try:
        response, total, digest = _readInChunks(arcade, RPS, "/index.data")
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert response.status == 200
    assert int(response.getheader("Content-Length")) == total == size
    assert digest == expected
    # The server used to hold the whole 20 MiB file for the response.
    assert peak < 2 * 1024 * 1024, peak


def test_reads_are_capped_at_the_chunk_size(arcade, monkeypatch):
    import builtins

    _deploy(arcade)
    sizes = []
    realOpen = builtins.open

    class Spy(object):
        def __init__(self, handle):
            self._handle = handle

        def read(self, size=-1):
            sizes.append(size)
            return self._handle.read(size)

        def __getattr__(self, name):
            return getattr(self._handle, name)

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            self._handle.close()

    def spyOpen(path, mode="r", *args, **kwargs):
        handle = realOpen(path, mode, *args, **kwargs)
        return Spy(handle) if str(path).endswith("game.wasm") and "b" in mode else handle

    monkeypatch.setattr("arcade.server.open", spyOpen, raising=False)
    response, data = _get(arcade, "/pkg/game.wasm")
    assert data == WASM
    assert sizes and all(0 < size <= precompress.CHUNK_BYTES for size in sizes), sizes


# --- backfill --------------------------------------------------------------


def _strip(root, suffix=".gz"):
    for directory, _, names in os.walk(root):
        for name in names:
            if name.endswith(suffix):
                os.unlink(os.path.join(directory, name))


def test_versions_stored_before_this_are_backfilled_on_first_request(arcade):
    root = _deploy(arcade)
    _strip(root)  # as a version uploaded by an older arcade
    wasmGz = os.path.join(root, "pkg", "game.wasm.gz")
    response, data = _get(arcade, "/pkg/game.wasm", "gzip")
    # Answered at once, uncompressed; the .gz is written in the background.
    assert response.getheader("Content-Encoding") is None and data == WASM
    assert response.getheader("Vary") == "Accept-Encoding"
    arcade.backfill.wait()
    assert gzip.decompress(open(wasmGz, "rb").read()) == WASM
    response, data = _get(arcade, "/pkg/game.wasm", "gzip")
    assert response.getheader("Content-Encoding") == "gzip" and gzip.decompress(data) == WASM
    # Only what was asked for: the page itself has not been touched yet.
    assert not os.path.exists(os.path.join(root, "index.html.gz"))
    assert not [name for name in os.listdir(os.path.join(root, "pkg")) if name.startswith(".gz-")]


def test_backfill_is_triggered_even_by_a_client_that_wants_identity(arcade):
    root = _deploy(arcade)
    _strip(root)
    _get(arcade, "/pkg/game.wasm")
    arcade.backfill.wait()
    assert os.path.exists(os.path.join(root, "pkg", "game.wasm.gz"))


def test_backfill_never_compresses_a_variant_asked_for_by_name(arcade):
    root = _deploy(arcade)
    response, _ = _get(arcade, "/pkg/game.wasm.gz")
    assert response.status == 200
    arcade.backfill.wait()
    assert not os.path.exists(os.path.join(root, "pkg", "game.wasm.gz.gz"))


def test_a_variant_asked_for_by_name_is_sent_as_stored_bytes_under_its_originals_type(arcade):
    # Characterization of current behaviour (#85): the gzip bytes are sent as
    # is, labelled with the original's type and with no Content-Encoding.
    root = _deploy(arcade)
    response, data = _get(arcade, "/pkg/game.wasm.gz", acceptEncoding="gzip, br")
    assert response.status == 200
    assert data == open(os.path.join(root, "pkg", "game.wasm.gz"), "rb").read()
    assert gzip.decompress(data) == WASM
    assert response.getheader("Content-Type") == "application/wasm"
    assert response.getheader("Content-Encoding") is None


def test_a_failed_backfill_is_not_retried(tmp_path):
    backfill = precompress.Backfill()
    missing = str(tmp_path / "gone.wasm")
    backfill.request(missing)
    backfill.wait()
    backfill.request(missing)
    assert backfill._queue.unfinished_tasks == 0
    assert os.listdir(str(tmp_path)) == []
