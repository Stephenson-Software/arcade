import io
import tarfile
import zipfile

import pytest

from arcade import bundle
from arcade.store import BUNDLE_FILES
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


def _member(name, kind=tarfile.REGTYPE):
    info = tarfile.TarInfo(name)
    info.type = kind
    return info


def _zipWithEntries(entries):
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as archive:
        for name, data in entries:
            archive.writestr(name, data)
    return out.getvalue()


def test_refuses_a_file_that_appears_twice_in_tar_and_zip():
    with pytest.raises(bundle.BundleError, match="version.txt appears twice"):
        bundle.unpack(tarBundle(bundleFiles("1"), extra=[_member("./version.txt")]), "1", CAP)
    entries = list(bundleFiles("1").items()) + [("./index.html", b"again")]
    with pytest.raises(bundle.BundleError, match="index.html appears twice"):
        bundle.unpack(_zipWithEntries(entries), "1", CAP)


def test_skips_root_and_zip_directory_entries_but_refuses_other_tar_directories():
    for root in (".", "./"):
        data = tarBundle(bundleFiles("1"), extra=[_member(root, tarfile.DIRTYPE)])
        assert sorted(bundle.unpack(data, "1", CAP)) == sorted(BUNDLE_FILES)
    entries = [("web/", b"")] + list(bundleFiles("1").items())
    assert sorted(bundle.unpack(_zipWithEntries(entries), "1", CAP)) == sorted(BUNDLE_FILES)
    with pytest.raises(bundle.BundleError, match="'web' is not a regular file"):
        bundle.unpack(tarBundle(bundleFiles("1"), extra=[_member("web", tarfile.DIRTYPE)]), "1", CAP)


def test_backslashes_are_read_as_separators():
    files = bundleFiles("1")
    files[".\\index.html"] = files.pop("index.html")
    assert "index.html" in bundle.unpack(_zipWithEntries(files.items()), "1", CAP)
    site = bundle.unpackStatic(_zipWithEntries(_site(extra={"a\\b.js": b"y"}).items()), "1", CAP)
    assert site["a/b.js"] == b"y"


@pytest.mark.parametrize("compression", ["bz2", "xz"])
def test_accepts_the_other_tar_compressions(compression):
    assert bundle.unpack(tarBundle(bundleFiles("1"), compression=compression), "1", CAP)


def test_the_stated_version_is_stripped_and_must_be_utf8():
    files = bundleFiles("1")
    files["version.txt"] = b"  1 \r\n"
    assert bundle.unpack(tarBundle(files), "1", CAP)["version.txt"] == b"  1 \r\n"
    files["version.txt"] = b"\xff\xfe"
    with pytest.raises(bundle.BundleError, match="version.txt is not UTF-8 text"):
        bundle.unpack(tarBundle(files), "1", CAP)
    with pytest.raises(bundle.BundleError, match="version.txt is not UTF-8 text"):
        bundle.unpackStatic(tarBundle(_site(extra={"version.txt": b"\xff"})), "1", CAP)


def test_a_corrupt_zip_is_refused_rather_than_read_as_a_tar():
    for unpack in (bundle.unpack, bundle.unpackStatic):
        with pytest.raises(bundle.BundleError, match="not a readable zip"):
            unpack(b"PK\x03\x04garbage", "1", CAP)


@pytest.mark.parametrize("name", ["", "./", "a\x00b", "a/", "/"])
def test_check_site_path_refuses_empty_absolute_and_nul_paths(name):
    with pytest.raises(bundle.BundleError, match="unacceptable path"):
        bundle.checkSitePath(name)


def test_check_site_path_returns_the_normalised_path():
    assert bundle.checkSitePath("./a\\b/c.js") == "a/b/c.js"
    assert bundle.checkSitePath("..hidden/.well-known/x") == "..hidden/.well-known/x"


def test_static_refuses_duplicates_devices_and_garbage():
    with pytest.raises(bundle.BundleError, match="index.html appears twice"):
        bundle.unpackStatic(tarBundle(_site(), extra=[_member("./index.html")]), "1", CAP)
    entries = list(_site().items()) + [("./js/app.js", b"again")]
    with pytest.raises(bundle.BundleError, match="js/app.js appears twice"):
        bundle.unpackStatic(_zipWithEntries(entries), "1", CAP)
    with pytest.raises(bundle.BundleError, match="links and devices are refused"):
        bundle.unpackStatic(tarBundle(_site(), extra=[_member("dev", tarfile.CHRTYPE)]), "1", CAP)
    with pytest.raises(bundle.BundleError, match="neither a zip nor a readable tar"):
        bundle.unpackStatic(b"hello", "1", CAP)


def test_static_skips_directory_entries():
    extra = [_member("js", tarfile.DIRTYPE), _member("./", tarfile.DIRTYPE)]
    assert sorted(bundle.unpackStatic(tarBundle(_site(), extra=extra), "1", CAP)) == sorted(_site())
    entries = [("js/", b"")] + list(_site().items())
    assert sorted(bundle.unpackStatic(_zipWithEntries(entries), "1", CAP)) == sorted(_site())


def test_static_reserves_the_uploaded_marker_only_at_the_top_level():
    with pytest.raises(bundle.BundleError, match=r"\.uploaded is reserved"):
        bundle.unpackStatic(tarBundle(_site(extra={".uploaded": b""})), "1", CAP)
    assert "a/.uploaded" in bundle.unpackStatic(tarBundle(_site(extra={"a/.uploaded": b""})), "1", CAP)


def test_static_refuses_a_path_that_is_both_a_file_and_a_directory():
    with pytest.raises(bundle.BundleError, match="'js/app.js' is both a file and a directory"):
        bundle.unpackStatic(tarBundle(_site(extra={"js/app.js/x": b""})), "1", CAP)


def test_static_zip_caps_count_bytes_and_files():
    with pytest.raises(bundle.BundleTooLarge, match="more than 10 bytes"):
        bundle.unpackStatic(zipBundle(_site()), "1", 10)
    with pytest.raises(bundle.BundleTooLarge, match="more than 2 files"):
        bundle.unpackStatic(zipBundle(_site()), "1", CAP, maxFiles=2)
    assert len(bundle.unpackStatic(zipBundle(_site()), "1", CAP, maxFiles=3)) == 3
