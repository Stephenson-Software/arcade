import os
import time

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
    assert sorted(os.listdir(str(tmp_path / "tidewater"))) == [".added", "1.0.0", "current"]


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


def test_plays_are_counted_per_game_and_survive_a_new_store(tmp_path):
    store = Store(str(tmp_path))
    assert store.plays("tidewater") == 0
    store.addPlay("tidewater")
    store.addPlay("tidewater")
    store.addPlay("cave")
    assert (store.plays("tidewater"), store.plays("cave")) == (2, 1)
    assert Store(str(tmp_path)).plays("tidewater") == 2
    # The counter never becomes a version, and "plays" cannot be one.
    store.add("tidewater", "1", bundleFiles("1"))
    assert store.versions("tidewater") == ["1"]
    with pytest.raises(ValueError):
        store.add("tidewater", "plays", bundleFiles("plays"))


def test_an_unreadable_counter_reads_as_zero_and_recovers(tmp_path):
    store = Store(str(tmp_path))
    os.makedirs(str(tmp_path / "cave"))
    (tmp_path / "cave" / "plays").write_text("not a number")
    assert store.plays("cave") == 0
    store.addPlay("cave")
    assert store.plays("cave") == 1


def _stamp(tmp_path, slug, version, value):
    (tmp_path / slug / version / ".uploaded").write_text(str(value))


def _explode(*args):
    raise OSError("disk full")


def test_versions_are_ordered_by_upload_time_not_by_name(tmp_path):
    store = Store(str(tmp_path))
    for version in ("a", "b", "c"):
        store.add("tidewater", version, bundleFiles(version))
    _stamp(tmp_path, "tidewater", "a", 300)
    _stamp(tmp_path, "tidewater", "b", 100)
    _stamp(tmp_path, "tidewater", "c", 200)
    assert store.versions("tidewater") == ["b", "c", "a"]


def test_versions_skip_staging_leftovers_and_unreadable_stamps(tmp_path):
    store = Store(str(tmp_path))
    store.add("tidewater", "1", bundleFiles("1"))
    store.add("tidewater", "2", bundleFiles("2"))
    # A staging directory left by a crash is never a version, even with a stamp.
    os.makedirs(str(tmp_path / "tidewater" / ".upload-abc"))
    (tmp_path / "tidewater" / ".upload-abc" / ".uploaded").write_text("1")
    _stamp(tmp_path, "tidewater", "2", "not a number")
    store.addPlay("tidewater")
    assert store.versions("tidewater") == ["1"]
    assert store.versions("nothing-here") == []


def test_a_pointer_to_a_missing_or_malformed_version_reads_as_nothing_live(tmp_path):
    store = Store(str(tmp_path))
    store.add("tidewater", "1", bundleFiles("1"))
    pointer = tmp_path / "tidewater" / "current"
    for content in ("2\n", "../1\n", "\n", "plays\n"):
        pointer.write_text(content)
        assert store.current("tidewater") is None
    pointer.write_text("  1  \n")
    assert store.current("tidewater") == "1"


def test_file_path_only_names_bundle_files_and_checks_the_version(tmp_path):
    store = Store(str(tmp_path))
    expected = os.path.join(str(tmp_path), "tidewater", "1", "game.zip")
    assert store.filePath("tidewater", "1", "game.zip") == expected
    with pytest.raises(KeyError):
        store.filePath("tidewater", "1", ".uploaded")
    with pytest.raises(NoSuchVersion):
        store.filePath("tidewater", "../1", "index.html")
    with pytest.raises(NoSuchVersion):
        store.versionDirectory("tidewater", "current")


def test_set_current_refuses_an_incomplete_version_directory(tmp_path):
    store = Store(str(tmp_path))
    store.add("tidewater", "1", bundleFiles("1"))
    os.makedirs(str(tmp_path / "tidewater" / "2"))
    with pytest.raises(NoSuchVersion):
        store.setCurrent("tidewater", "2")
    assert store.current("tidewater") == "1"


def test_a_failed_pointer_write_keeps_the_previous_version_live(tmp_path, monkeypatch):
    store = Store(str(tmp_path))
    store.add("tidewater", "1", bundleFiles("1"))
    store.add("tidewater", "2", bundleFiles("2"), activate=False)
    monkeypatch.setattr(os, "replace", _explode)
    with pytest.raises(OSError):
        store.setCurrent("tidewater", "2")
    monkeypatch.undo()
    assert store.current("tidewater") == "1"
    assert sorted(os.listdir(str(tmp_path / "tidewater"))) == [".added", "1", "2", "current"]


def test_a_failed_counter_write_keeps_the_count_and_leaves_no_temporary(tmp_path, monkeypatch):
    store = Store(str(tmp_path))
    store.addPlay("cave")
    monkeypatch.setattr(os, "replace", _explode)
    with pytest.raises(OSError):
        store.addPlay("cave")
    monkeypatch.undo()
    assert store.plays("cave") == 1
    assert os.listdir(str(tmp_path / "cave")) == ["plays"]


def test_a_failed_static_write_leaves_nothing_behind(tmp_path, monkeypatch):
    store = Store(str(tmp_path))
    store.add("rps", "1", {"index.html": b"i", "version.txt": b"1\n"}, static=True)
    monkeypatch.setattr(os, "rename", _explode)
    with pytest.raises(OSError):
        store.add("rps", "2", {"index.html": b"i", "version.txt": b"2\n", "a/b.js": b"b"}, static=True)
    monkeypatch.undo()
    assert store.current("rps") == "1"
    assert sorted(os.listdir(str(tmp_path / "rps"))) == [".added", "1", "current"]


def test_prune_counts_per_game_and_keep_one_holds_only_the_live_version(tmp_path):
    store = Store(str(tmp_path), keep=1)
    store.add("tidewater", "1", bundleFiles("1"))
    store.add("cave", "1", bundleFiles("1"))
    store.add("tidewater", "2", bundleFiles("2"))
    assert store.versions("tidewater") == ["2"]
    assert store.versions("cave") == ["1"]
    # An inactive upload beyond the limit is pruned at once; the live one stays.
    store.add("tidewater", "3", bundleFiles("3"), activate=False)
    assert store.versions("tidewater") == ["2"]
    assert store.current("tidewater") == "2"


def test_site_path_refuses_a_link_out_of_the_version(tmp_path):
    store = Store(str(tmp_path / "data"))
    store.add("rps", "1", {"index.html": b"i", "version.txt": b"1\n"}, static=True)
    outside = tmp_path / "secret.txt"
    outside.write_text("secret")
    os.symlink(str(outside), str(tmp_path / "data" / "rps" / "1" / "leak.txt"))
    assert store.sitePath("rps", "1", "leak.txt") is None
    assert store.sitePath("rps", "1", "index.html") is not None


def test_the_first_upload_is_recorded_and_kept(tmp_path):
    store = Store(str(tmp_path), keep=2)
    assert store.added("tidewater") is None
    store.add("tidewater", "1", bundleFiles("1"))
    first = store.added("tidewater")
    assert first is not None and abs(first / 1e9 - time.time()) < 60
    # Later uploads, and pruning the first version away, leave it alone.
    for version in ("2", "3", "4"):
        store.add("tidewater", version, bundleFiles(version))
    assert "1" not in store.versions("tidewater")
    assert store.added("tidewater") == first


def _setUploaded(store, slug, version, ns):
    with open(os.path.join(store.versionDirectory(slug, version), ".uploaded"), "w") as f:
        f.write(str(ns))


def _forgetAdded(store, slug):
    os.unlink(os.path.join(str(store.root), slug, ".added"))


def test_a_slug_from_before_the_record_uses_its_oldest_version_while_none_was_pruned(tmp_path):
    store = Store(str(tmp_path), keep=3)
    store.add("tidewater", "1", bundleFiles("1"))
    store.add("tidewater", "2", bundleFiles("2"))
    _forgetAdded(store, "tidewater")
    _setUploaded(store, "tidewater", "1", 1000 * 10 ** 9)
    _setUploaded(store, "tidewater", "2", 2000 * 10 ** 9)
    assert store.added("tidewater") == 1000 * 10 ** 9
    # The next upload writes it down, so pruning cannot lose it.
    store.add("tidewater", "3", bundleFiles("3"))
    store.add("tidewater", "4", bundleFiles("4"))
    assert "1" not in store.versions("tidewater")
    assert store.added("tidewater") == 1000 * 10 ** 9


def test_a_slug_pruned_before_the_record_is_unknown_and_not_made_new(tmp_path):
    store = Store(str(tmp_path), keep=2)
    store.add("tidewater", "1", bundleFiles("1"))
    store.add("tidewater", "2", bundleFiles("2"))
    _forgetAdded(store, "tidewater")
    # As many versions as are kept: the first may be long gone.
    assert store.added("tidewater") is None
    store.add("tidewater", "3", bundleFiles("3"))
    assert store.added("tidewater") is None
    assert ".added" not in os.listdir(os.path.join(str(tmp_path), "tidewater"))


def test_added_is_never_a_version(tmp_path):
    store = Store(str(tmp_path))
    store.add("tidewater", "1", bundleFiles("1"))
    assert store.versions("tidewater") == ["1"]
    with pytest.raises(NoSuchVersion):
        store.versionDirectory("tidewater", ".added")
