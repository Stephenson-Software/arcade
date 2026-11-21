"""The hosting core on fakes alone: no HTTP server, no disk, no network."""

import datetime

import pytest

from arcade.hosting import Denied, Deployed, Hosting, Rejected, addedOf, hashToken
from helpers import OTHER_TOKEN, TOKEN, bundleFiles, game, registryText, tarBundle
from hosting_fakes import FakeCatalog, FakeNotes, FakeStore, FakeVisits, Recorder

DOMAIN = "play.example.com"
NOTES = {"version": "1.0.0", "text": "New boats.", "url": "https://example.com/r"}


@pytest.fixture
def parts():
    text = registryText(
        [
            game("tidewater", aliases=["tidewater.example.org"]),
            game("overwinter", added="2026-10-01"),
            game("rps", kind="static"),
        ]
    )
    store = FakeStore()
    lines = []
    core = Hosting(
        domain=DOMAIN,
        catalog=FakeCatalog(text, domain=DOMAIN),
        versions=store,
        counter=store,
        reporter=Recorder(),
        notes=FakeNotes({("tidewater", "1.0.0"): NOTES}),
        visits=FakeVisits(),
        maxUploadBytes=1024 * 1024,
        log=lines.append,
    )
    return core, store, lines


def tidewater(core):
    return core.games().get("tidewater")


# --- hosts ------------------------------------------------------------------


@pytest.mark.parametrize(
    "host, slug",
    [
        ("tidewater." + DOMAIN, "tidewater"),
        ("tidewater.example.org", "tidewater"),
        ("nosuch." + DOMAIN, None),
        ("a.tidewater." + DOMAIN, None),
        (DOMAIN, None),
        ("elsewhere.example.org", None),
    ],
)
def test_game_for_host(parts, host, slug):
    core = parts[0]
    found = core.gameForHost(host)
    assert (found.slug if found else None) == slug


# --- authorise --------------------------------------------------------------


@pytest.mark.parametrize("header", [None, "", "Bearer ", "Bearer    ", "Basic abc", "bearer " + TOKEN])
def test_no_bearer_token_is_401(parts, header):
    assert parts[0].authorise("tidewater", header) == Denied(
        401, "an Authorization: Bearer <token> header is required"
    )


@pytest.mark.parametrize("slug, token", [("tidewater", OTHER_TOKEN), ("nosuch", TOKEN)])
def test_wrong_token_and_unknown_slug_look_the_same(parts, slug, token):
    assert parts[0].authorise(slug, "Bearer " + token) == Denied(403, "this token cannot deploy that game")


def test_the_right_token_returns_the_game(parts):
    core = parts[0]
    assert core.authorise("tidewater", "Bearer  %s " % TOKEN) is tidewater(core)


# --- deploy and rollback ----------------------------------------------------


@pytest.mark.parametrize("version, ok", [("1.0.0", True), ("v2-rc.1+b", True), ("current", False), ("plays", False), ("-1", False), ("a/b", False), ("x" * 65, False)])
def test_check_version(version, ok):
    rejected = Hosting.checkVersion(version)
    assert rejected is None if ok else rejected == Rejected(400, "bad version %r" % version)


def test_deploy_stores_and_logs(parts):
    core, store, lines = parts
    data = tarBundle(bundleFiles("1.0.0"))
    assert core.deploy(tidewater(core), "1.0.0", data, True, len(data)) == Deployed(201, game=tidewater(core))
    assert store.current("tidewater") == "1.0.0"
    assert lines == ["tidewater 1.0.0 uploaded (%d bytes) and made current" % len(data)]


def test_deploy_without_activating(parts):
    core, store, lines = parts
    data = tarBundle(bundleFiles("1.0.0"))
    core.deploy(tidewater(core), "1.0.0", data, False, 7)
    assert store.current("tidewater") is None
    assert lines == ["tidewater 1.0.0 uploaded (7 bytes)"]


def test_deploy_twice_is_409(parts):
    core = parts[0]
    data = tarBundle(bundleFiles("1.0.0"))
    core.deploy(tidewater(core), "1.0.0", data, True, len(data))
    assert core.deploy(tidewater(core), "1.0.0", data, True, len(data)) == Rejected(
        409, "version 1.0.0 already exists; versions are immutable"
    )


def test_a_bad_bundle_is_400_and_stores_nothing(parts):
    core, store, lines = parts
    outcome = core.deploy(tidewater(core), "1.0.0", b"not an archive", True, 14)
    assert isinstance(outcome, Rejected) and outcome.status == 400 and outcome.error
    assert store.versions("tidewater") == [] and lines == []


def test_a_store_failure_is_400_and_logged(parts):
    core, store, lines = parts

    def broken(*args, **kwargs):
        raise OSError("disk full")

    store.add = broken
    data = tarBundle(bundleFiles("1.0.0"))
    assert core.deploy(tidewater(core), "1.0.0", data, True, len(data)) == Rejected(
        400, "the bundle could not be stored: disk full"
    )
    assert lines == ["tidewater 1.0.0 upload could not be stored: disk full"]


def test_rollback(parts):
    core, store, lines = parts
    store.add("tidewater", "1.0.0", {})
    store.add("tidewater", "1.1.0", {})
    assert core.rollback(tidewater(core), "1.0.0") == Deployed(200, game=tidewater(core))
    assert store.current("tidewater") == "1.0.0"
    assert lines == ["tidewater current set to 1.0.0"]
    assert core.rollback(tidewater(core), "9.9.9") == Rejected(404, "version '9.9.9' is not on disk")


# --- describe ---------------------------------------------------------------


def test_describe(parts):
    core, store = parts[:2]
    store.add("tidewater", "1.0.0", {})
    store.addPlay("tidewater")
    described = core.describe(tidewater(core))
    assert described["url"] == "https://tidewater.%s/" % DOMAIN
    assert (described["current"], described["versions"], described["plays"]) == ("1.0.0", ["1.0.0"], 1)
    assert described["added"] == "2023-11-14T22:13:20Z"
    assert described["notes"] == NOTES
    assert described["aliases"] == ["tidewater.example.org"]


def test_added_prefers_the_registry(parts):
    core, store = parts[:2]
    store.add("overwinter", "1.0.0", {})
    assert addedOf(core.games().get("overwinter"), store) == "2026-10-01T00:00:00Z"
    assert addedOf(core.games().get("rps"), store) is None


def test_added_with_a_time():
    class Timed(object):
        slug = "x"
        added = datetime.datetime(2026, 10, 1, 12, 0, tzinfo=datetime.timezone(datetime.timedelta(hours=-6)))

    assert addedOf(Timed(), FakeStore()) == "2026-10-01T18:00:00Z"


# --- plays ------------------------------------------------------------------


@pytest.mark.parametrize("agent", [None, "", "Googlebot", "curl/8", "python-requests", "HeadlessChrome", "x arcade-watch"])
def test_scripts_are_not_plays(parts, agent):
    core, store = parts[:2]
    core.played("tidewater", agent, "1.2.3.4")
    assert store.plays("tidewater") == 0 and core.reporter.events == []


def test_a_person_plays_once_a_day(parts):
    core, store = parts[:2]
    for _ in range(2):
        core.played("tidewater", "Mozilla/5.0", "1.2.3.4")
    assert store.plays("tidewater") == 1
    assert core.reporter.events == [("page-served", {"slug": "tidewater"})]


def test_a_play_that_cannot_be_counted_is_logged_and_still_reported(parts):
    core, store, lines = parts
    store.failPlays = True
    core.played("tidewater", "Mozilla/5.0", None)
    assert lines == ["could not count a play of tidewater: disk full"]
    assert core.reporter.events == [("page-served", {"slug": "tidewater"})]


def test_hash_token():
    assert hashToken("abc") == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"


def test_a_bundle_too_large_unpacked_is_413(parts):
    core, store, lines = parts
    core.maxUploadBytes = 64 * 1024
    files = bundleFiles("1.0.0")
    files["index.html"] = b"0" * (core.maxUploadBytes + 1)  # compresses far below the cap
    data = tarBundle(files, compression="gz")
    assert len(data) < core.maxUploadBytes
    outcome = core.deploy(tidewater(core), "1.0.0", data, True, len(data))
    assert isinstance(outcome, Rejected) and outcome.status == 413 and outcome.error
    assert store.versions("tidewater") == [] and lines == []


def test_a_static_game_takes_a_static_bundle(parts):
    core, store = parts[:2]
    added = []
    real = store.add
    store.add = lambda *args, **kwargs: (added.append(kwargs["static"]), real(*args, **kwargs))
    rps = core.games().get("rps")
    data = tarBundle({"index.html": b"<html></html>", "version.txt": b"1.0.0\n"})
    assert core.deploy(rps, "1.0.0", data, True, len(data)) == Deployed(201, game=rps)
    assert added == [True]
    assert core.deploy(tidewater(core), "1.0.0", data, True, len(data)).status == 400
