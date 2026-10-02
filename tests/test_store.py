import os

import pytest

from arcade.store import NoSuchVersion, Store, VersionExists
from helpers import bundleFiles


def test_add_makes_a_version_current(tmp_path):
    store = Store(str(tmp_path))
    assert store.current("tidewater") is None
    assert store.versions("tidewater") == []
    store.add("tidewater", "1.0.0", bundleFiles("1.0.0"))
    assert store.current("tidewater") == "1.0.0"
    assert store.versions("tidewater") == ["1.0.0"]
    with open(store.filePath("tidewater", "1.0.0", "version.txt"), "rb") as stored:
        assert stored.read() == b"1.0.0\n"


def test_versions_are_immutable(tmp_path):
    store = Store(str(tmp_path))
    store.add("tidewater", "1.0.0", bundleFiles("1.0.0"))
    with pytest.raises(VersionExists):
        store.add("tidewater", "1.0.0", bundleFiles("1.0.0"))


def test_activate_false_keeps_the_live_version(tmp_path):
    store = Store(str(tmp_path))
    store.add("tidewater", "1.0.0", bundleFiles("1.0.0"))
    store.add("tidewater", "1.1.0", bundleFiles("1.1.0"), activate=False)
    assert store.current("tidewater") == "1.0.0"
    assert store.versions("tidewater") == ["1.0.0", "1.1.0"]


def test_set_current_is_rollback(tmp_path):
    store = Store(str(tmp_path))
    store.add("tidewater", "1.0.0", bundleFiles("1.0.0"))
    store.add("tidewater", "1.1.0", bundleFiles("1.1.0"))
    store.setCurrent("tidewater", "1.0.0")
    assert store.current("tidewater") == "1.0.0"
    with pytest.raises(NoSuchVersion):
        store.setCurrent("tidewater", "9.9.9")
    with pytest.raises(NoSuchVersion):
        store.setCurrent("tidewater", "../escape")


def test_prune_keeps_the_newest_and_never_the_current(tmp_path):
    store = Store(str(tmp_path), keep=2)
    store.add("tidewater", "1", bundleFiles("1"))
    store.add("tidewater", "2", bundleFiles("2"), activate=False)
    store.add("tidewater", "3", bundleFiles("3"), activate=False)
    # 1 is current and oldest: 2 goes instead.
    assert store.versions("tidewater") == ["1", "3"]
    assert store.current("tidewater") == "1"
    store.add("tidewater", "4", bundleFiles("4"))
    assert store.versions("tidewater") == ["3", "4"]


def test_a_failed_write_leaves_nothing_behind(tmp_path, monkeypatch):
    store = Store(str(tmp_path))
    store.add("tidewater", "1.0.0", bundleFiles("1.0.0"))

    def explode(*args):
        raise OSError("disk full")

    monkeypatch.setattr(os, "rename", explode)
    with pytest.raises(OSError):
        store.add("tidewater", "1.1.0", bundleFiles("1.1.0"))
    monkeypatch.undo()
    assert store.current("tidewater") == "1.0.0"
    assert sorted(os.listdir(str(tmp_path / "tidewater"))) == ["1.0.0", "current"]


def test_rejects_bad_versions_and_partial_bundles(tmp_path):
    store = Store(str(tmp_path))
    with pytest.raises(ValueError):
        store.add("tidewater", "../x", bundleFiles("1"))
    with pytest.raises(ValueError):
        store.add("tidewater", "1", {"index.html": b""})
    with pytest.raises(ValueError):
        Store(str(tmp_path), keep=0)


def test_ignores_incomplete_version_directories(tmp_path):
    store = Store(str(tmp_path))
    store.add("tidewater", "1", bundleFiles("1"))
    os.makedirs(str(tmp_path / "tidewater" / "2"))
    assert store.versions("tidewater") == ["1"]


def test_static_bundles_keep_their_tree(tmp_path):
    store = Store(str(tmp_path))
    files = {"index.html": b"i", "version.txt": b"1\n", "a/b/c.wasm": b"w"}
    store.add("rps", "1", files, static=True)
    assert open(store.sitePath("rps", "1", "a/b/c.wasm"), "rb").read() == b"w"
    for bad in ("../x", "a/../../x", "missing.js", ".uploaded", "a/b"):
        assert store.sitePath("rps", "1", bad) is None
    with pytest.raises(ValueError):
        store.add("rps", "2", {"version.txt": b"2"}, static=True)
    with pytest.raises(ValueError):
        store.add("rps", "3", {"index.html": b"", "version.txt": b"3", ".uploaded": b"0"}, static=True)
    with pytest.raises(Exception):
        store.add("rps", "4", {"index.html": b"", "version.txt": b"4", "../x": b""}, static=True)


def test_current_is_not_a_version_name_and_a_broken_pointer_is_survivable(tmp_path):
    store = Store(str(tmp_path))
    with pytest.raises(ValueError):
        store.add("tidewater", "current", bundleFiles("current"))
    store.add("tidewater", "1", bundleFiles("1"))
    # A pointer that cannot be read (here: replaced by a directory) reads as
    # "nothing deployed", not an exception that takes the API down.
    os.remove(str(tmp_path / "tidewater" / "current"))
    os.makedirs(str(tmp_path / "tidewater" / "current"))
    assert store.current("tidewater") is None
