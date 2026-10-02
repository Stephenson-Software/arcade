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
