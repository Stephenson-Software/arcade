"""Contract tests: each port's fake and its production adapter pass the same
tests, so a fake cannot drift from the real thing."""

import os

import pytest

from arcade.hosting import ports
from arcade.hosting.adapters import NullReporter, ReloadingYamlCatalog
from arcade.remote import Remote
from arcade.store import Store
from helpers import bundleFiles, game, registryText
from hosting_fakes import FakeCatalog, FakeNotes, FakeStore, Recorder

DOMAIN = "play.example.com"
TEXT = registryText([game("tidewater", aliases=["tidewater.example.org"]), game("rps", kind="static")])


# --- GameCatalog ------------------------------------------------------------


@pytest.fixture(params=["fake", "yaml"])
def catalog(request, tmp_path):
    if request.param == "fake":
        return FakeCatalog(TEXT, domain=DOMAIN)
    path = tmp_path / "games.yaml"
    path.write_text(TEXT)
    return ReloadingYamlCatalog(str(path), DOMAIN, log=lambda line: None)


def test_a_catalog_is_a_game_catalog(catalog):
    assert isinstance(catalog, ports.GameCatalog)


def test_a_catalog_answers_slugs_and_aliases(catalog):
    games = catalog.games()
    assert [g.slug for g in games] == ["rps", "tidewater"]
    assert len(games) == 2
    assert games.get("tidewater").slug == "tidewater"
    assert games.get("nosuch") is None
    assert games.forAlias("tidewater.example.org").slug == "tidewater"
    assert games.forAlias("elsewhere.example.org") is None


def test_the_yaml_catalog_keeps_the_last_good_registry(tmp_path):
    path = tmp_path / "games.yaml"
    path.write_text(TEXT)
    lines = []
    catalog = ReloadingYamlCatalog(str(path), DOMAIN, log=lines.append)
    path.write_text("games:\n  - slug: x\n")
    os.utime(str(path), ns=(10**18, 10**18))
    assert [g.slug for g in catalog.games()] == ["rps", "tidewater"]
    assert lines[-1].startswith("registry invalid, keeping the last good one: ")
    path.unlink()
    assert len(catalog.games()) == 2
    assert lines[-1].startswith("registry unreadable, keeping the last good one: ")


def test_the_yaml_catalog_refuses_a_missing_file_at_start(tmp_path):
    with pytest.raises(OSError):
        ReloadingYamlCatalog(str(tmp_path / "missing.yaml"), DOMAIN, log=lambda line: None)


# --- VersionStore and PlayCounter -------------------------------------------


@pytest.fixture(params=["fake", "filesystem"])
def store(request, tmp_path):
    if request.param == "fake":
        return FakeStore()
    return Store(str(tmp_path / "data"), keep=3)


def test_a_store_is_a_version_store_and_a_play_counter(store):
    assert isinstance(store, ports.VersionStore)
    assert isinstance(store, ports.PlayCounter)


def test_an_empty_store(store):
    assert store.current("tidewater") is None
    assert store.versions("tidewater") == []
    assert store.added("tidewater") is None
    assert store.plays("tidewater") == 0


def test_add_makes_a_version_current_unless_told_not_to(store):
    store.add("tidewater", "1.0.0", bundleFiles("1.0.0"))
    assert store.current("tidewater") == "1.0.0"
    store.add("tidewater", "1.1.0", bundleFiles("1.1.0"), activate=False)
    assert store.current("tidewater") == "1.0.0"
    assert store.versions("tidewater") == ["1.0.0", "1.1.0"]
    assert isinstance(store.added("tidewater"), int)


def test_versions_are_immutable(store):
    store.add("tidewater", "1.0.0", bundleFiles("1.0.0"))
    with pytest.raises(ports.VersionExists):
        store.add("tidewater", "1.0.0", bundleFiles("1.0.0"))


def test_set_current_needs_a_stored_version(store):
    store.add("tidewater", "1.0.0", bundleFiles("1.0.0"))
    store.add("tidewater", "1.1.0", bundleFiles("1.1.0"))
    store.setCurrent("tidewater", "1.0.0")
    assert store.current("tidewater") == "1.0.0"
    with pytest.raises(ports.NoSuchVersion):
        store.setCurrent("tidewater", "9.9.9")


def test_plays_count_up(store):
    store.addPlay("tidewater")
    store.addPlay("tidewater")
    assert store.plays("tidewater") == 2
    assert store.plays("rps") == 0


# --- EventReporter ----------------------------------------------------------


@pytest.mark.parametrize("reporter", [NullReporter(), Recorder()], ids=["null", "recorder"])
def test_a_reporter_takes_events_without_raising(reporter):
    assert isinstance(reporter, ports.EventReporter)
    reporter.report("page-served", tags={"slug": "tidewater"})
    reporter.report("startup")


# --- ReleaseNotes -----------------------------------------------------------


@pytest.fixture(params=["fake", "remote"])
def notes(request, tmp_path):
    if request.param == "fake":
        return FakeNotes()
    return Remote(str(tmp_path / ".remote"), enabled=False, start=False)


def test_notes_are_release_notes(notes):
    assert isinstance(notes, ports.ReleaseNotes)


@pytest.mark.parametrize("current", [None, "1.0.0", "1.0.0-dev.3"])
def test_nothing_looked_up_yet_is_none(notes, current):
    assert notes.notes("tidewater", "Stephenson-Software/Tidewater", current) is None
