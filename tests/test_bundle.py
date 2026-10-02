import io
import tarfile

import pytest

from arcade import bundle
from helpers import ASSETS, bundleFiles, gameZip, tarBundle, zipBundle

CAP = 10 * 1024 * 1024


@pytest.mark.parametrize("compression", ["", "gz"])
def test_accepts_a_tar(compression):
    files = bundle.unpack(tarBundle(bundleFiles("1.2.3"), compression=compression), "1.2.3", CAP)
    assert sorted(files) == ["game.zip", "index.html", "version.txt"]


def test_accepts_a_dot_slash_prefix_and_a_zip():
    assert bundle.unpack(tarBundle(bundleFiles("1"), prefix="./"), "1", CAP)
    assert bundle.unpack(zipBundle(bundleFiles("1")), "1", CAP)


def test_refuses_an_extra_file():
    files = bundleFiles("1")
    files["notes.txt"] = b"x"
    with pytest.raises(bundle.BundleError, match="unexpected file 'notes.txt'"):
        bundle.unpack(tarBundle(files), "1", CAP)


def test_refuses_a_nested_path():
    files = bundleFiles("1")
    files["web/index.html"] = files.pop("index.html")
    with pytest.raises(bundle.BundleError, match="unexpected file"):
        bundle.unpack(tarBundle(files), "1", CAP)


def test_refuses_a_missing_file():
    files = bundleFiles("1")
    del files["game.zip"]
    with pytest.raises(bundle.BundleError, match="missing game.zip"):
        bundle.unpack(tarBundle(files), "1", CAP)


def test_refuses_a_version_mismatch():
    with pytest.raises(bundle.BundleError, match="version.txt says '1'"):
        bundle.unpack(tarBundle(bundleFiles("1")), "2", CAP)


def test_refuses_links():
    link = tarfile.TarInfo("index.html")
    link.type = tarfile.SYMTYPE
    link.linkname = "/etc/passwd"
    files = bundleFiles("1")
    del files["index.html"]
    with pytest.raises(bundle.BundleError, match="not a regular file"):
        bundle.unpack(tarBundle(files, extra=[link]), "1", CAP)


def test_refuses_a_game_zip_without_the_kit_assets():
    files = bundleFiles("1")
    files["game.zip"] = gameZip(assets={"boot.js": b""})
    with pytest.raises(bundle.BundleError, match="client.css, client.js, game-worker.js"):
        bundle.unpack(tarBundle(files), "1", CAP)
    files["game.zip"] = b"not a zip"
    with pytest.raises(bundle.BundleError, match="game.zip is not a readable zip"):
        bundle.unpack(tarBundle(files), "1", CAP)


def test_refuses_garbage_and_oversize():
    with pytest.raises(bundle.BundleError, match="neither a zip nor a readable tar"):
        bundle.unpack(b"hello", "1", CAP)
    with pytest.raises(bundle.BundleTooLarge):
        bundle.unpack(tarBundle(bundleFiles("1")), "1", 100)
    with pytest.raises(bundle.BundleTooLarge):
        bundle.unpack(zipBundle(bundleFiles("1")), "1", 100)


def test_read_asset_serves_only_flat_names(tmp_path):
    path = tmp_path / "game.zip"
    path.write_bytes(gameZip())
    assert bundle.readAsset(str(path), "boot.js") == ASSETS["boot.js"]
    for name in ("", "../boot.js", "x/boot.js", ".hidden", "missing.js"):
        assert bundle.readAsset(str(path), name) is None
    assert bundle.readAsset(str(tmp_path / "absent.zip"), "boot.js") is None


def _site(version="1", extra=None):
    files = {"index.html": b"<html>site</html>", "version.txt": (version + "\n").encode(), "js/app.js": b"x"}
    files.update(extra or {})
    return files


def test_static_accepts_any_tree_with_index_and_version():
    files = bundle.unpackStatic(tarBundle(_site("2.0", {"a/b/c.wasm": b"\0asm"})), "2.0", CAP)
    assert sorted(files) == ["a/b/c.wasm", "index.html", "js/app.js", "version.txt"]
    assert bundle.unpackStatic(zipBundle(_site("1")), "1", CAP)["js/app.js"] == b"x"
    assert "index.html" in bundle.unpackStatic(tarBundle(_site("1"), prefix="./"), "1", CAP)


@pytest.mark.parametrize("name", ["../escape.txt", "a/../../escape", "/abs.txt", "a//b", "a/./b"])
def test_static_refuses_paths_that_could_escape(name):
    with pytest.raises(bundle.BundleError, match="unacceptable path"):
        bundle.unpackStatic(tarBundle(_site(extra={name: b"x"})), "1", CAP)


def test_static_refuses_links_in_tar_and_zip():
    link = tarfile.TarInfo("evil")
    link.type = tarfile.SYMTYPE
    link.linkname = "/etc/passwd"
    with pytest.raises(bundle.BundleError, match="not a regular file"):
        bundle.unpackStatic(tarBundle(_site(), extra=[link]), "1", CAP)
    import zipfile

    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as archive:
        for name, data in _site().items():
            archive.writestr(name, data)
        info = zipfile.ZipInfo("evil")
        info.external_attr = (0o120777 << 16)
        archive.writestr(info, "/etc/passwd")
    with pytest.raises(bundle.BundleError, match="is a link"):
        bundle.unpackStatic(out.getvalue(), "1", CAP)


def test_static_needs_index_version_and_respects_caps():
    files = _site()
    del files["index.html"]
    with pytest.raises(bundle.BundleError, match="needs index.html"):
        bundle.unpackStatic(tarBundle(files), "1", CAP)
    with pytest.raises(bundle.BundleError, match="version.txt says"):
        bundle.unpackStatic(tarBundle(_site("1")), "2", CAP)
    with pytest.raises(bundle.BundleTooLarge):
        bundle.unpackStatic(tarBundle(_site()), "1", 10)
    with pytest.raises(bundle.BundleTooLarge, match="more than 2 files"):
        bundle.unpackStatic(tarBundle(_site()), "1", CAP, maxFiles=2)
