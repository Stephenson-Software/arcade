"""Background lookups kept on disk (arcade.remote): trailer stills and release notes."""

import json
import os

import pytest

from arcade import remote

JPEG = b"\xff\xd8\xff\xe0" + b"\0" * 64


class FakeWeb(object):
    """Answers like the network would, and records every request."""

    def __init__(self, pages=None):
        self.pages = pages if pages is not None else {}
        self.asked = []

    def __call__(self, url, maxBytes, accept):
        self.asked.append(url)
        answer = self.pages.get(url)
        if answer is None:
            raise remote.Failed("HTTP 404", 404)
        if isinstance(answer, remote.Failed):
            raise answer
        return answer


class Clock(object):
    def __init__(self, now=1_000_000.0):
        self.now = now

    def __call__(self):
        return self.now


def make(tmp_path, pages=None, clock=None):
    web = FakeWeb(pages)
    r = remote.Remote(str(tmp_path / ".remote"), get=web, clock=clock or Clock(), start=False)
    return r, web


def test_a_poster_is_fetched_in_the_background_and_then_served_from_disk(tmp_path):
    urls = ("https://example.com/trailers/a.jpg", "https://example.com/trailers/b.jpg")
    r, web = make(tmp_path, {urls[1]: ("image/jpeg", JPEG)})
    # Asking never waits: nothing yet, a fetch queued.
    assert r.poster("cave", urls) is None and web.asked == []
    r.runPending()
    assert web.asked == list(urls)  # the first 404s, the second is used
    path = r.poster("cave", urls)
    assert path and open(path, "rb").read() == JPEG
    r.runPending()
    assert web.asked == list(urls)  # fresh: not fetched again


def test_a_failed_poster_is_retried_only_after_a_while(tmp_path):
    clock = Clock()
    r, web = make(tmp_path, {}, clock)
    urls = ("https://example.com/x.jpg",)
    r.poster("cave", urls)
    r.runPending()
    r.poster("cave", urls)
    r.runPending()
    assert web.asked == ["https://example.com/x.jpg"]
    clock.now += remote.RETRY_SECONDS + 1
    r.poster("cave", urls)
    r.runPending()
    assert len(web.asked) == 2


@pytest.mark.parametrize("answer", [("text/html", b"<html>404 page</html>"), ("image/jpeg", b"GIF89a")])
def test_only_a_real_jpeg_is_kept(tmp_path, answer):
    r, _ = make(tmp_path, {"https://example.com/x.jpg": answer})
    r.poster("cave", ("https://example.com/x.jpg",))
    r.runPending()
    assert r.poster("cave", ("https://example.com/x.jpg",)) is None


def test_nothing_is_fetched_when_off(tmp_path):
    web = FakeWeb({})
    r = remote.Remote(str(tmp_path), enabled=False, get=web, start=False)
    assert r.poster("cave", ("https://example.com/x.jpg",)) is None
    assert r.notes("cave", "o/cave", "1.0.0") is None
    r.runPending()
    assert web.asked == []


def test_released_versions_only():
    assert remote.releasedVersion("0.14.0+gc1dc3db") == "0.14.0"
    assert remote.releasedVersion("1.2.3") == "1.2.3"
    assert remote.releasedVersion("1.2.3-rc.1+g1") == "1.2.3-rc.1"
    for dev in ("0.3.2-SNAPSHOT+g63c48b7", "a419eed+20261107", "", None, "latest"):
        assert remote.releasedVersion(dev) is None, dev


RELEASES = "https://api.github.com/repos/Preponderous-Software/second-helping/releases?per_page=30"
BODY = (
    "First release: a walkable 3D harvest fair that teaches ranked choice voting. Play it at "
    "https://second-helping.play.danielstephenson.dev\n\n"
    "- Five days: **The Count** and [The Spoiler](https://github.com/x/y/pull/3).\n"
    "- Desktop and touch controls.\n\n"
    "### Version\n\n`0.0.0` -> `0.1.0`\n\n### Verification\n\nCI passed.\n\n"
    "_drafted by Claude on behalf of Daniel Stephenson_"
)


def releases(*entries):
    return ("application/json", json.dumps(list(entries)).encode("utf-8"))


def test_release_notes_for_the_current_version_once_per_version(tmp_path):
    page = releases(
        {"tag_name": "0.2.0", "body": "later", "html_url": "https://github.com/o/r/releases/tag/0.2.0"},
        {"tag_name": "v0.1.0", "body": BODY, "html_url": "https://github.com/o/r/releases/tag/v0.1.0"},
    )
    r, web = make(tmp_path, {RELEASES: page})
    args = ("second-helping", "Preponderous-Software/second-helping", "0.1.0+g3cb2571")
    assert r.notes(*args) is None
    r.runPending()
    notes = r.notes(*args)
    assert notes["version"] == "0.1.0" and notes["url"] == "https://github.com/o/r/releases/tag/v0.1.0"
    assert notes["text"].startswith("First release: a walkable 3D harvest fair")
    assert "• Five days: The Count and The Spoiler." in notes["text"]
    assert "Version" not in notes["text"] and "drafted" not in notes["text"] and "**" not in notes["text"]
    # Once per version: asking again, or after a restart, does not go back to GitHub.
    r.notes(*args)
    r.runPending()
    again, web2 = make(tmp_path, {RELEASES: page})
    assert again.notes(*args)["version"] == "0.1.0"
    again.runPending()
    assert web.asked == [RELEASES] and web2.asked == []
    # A new version is looked up once more.
    r.notes("second-helping", "Preponderous-Software/second-helping", "0.2.0+gabc")
    r.runPending()
    assert len(web.asked) == 2


def test_a_version_with_no_release_is_looked_up_once_and_shows_nothing(tmp_path):
    r, web = make(tmp_path, {RELEASES: releases({"tag_name": "0.0.9", "body": "old"})})
    args = ("second-helping", "Preponderous-Software/second-helping", "0.1.0+g1")
    r.notes(*args)
    r.runPending()
    assert r.notes(*args) is None
    r.runPending()
    assert web.asked == [RELEASES]


def test_development_builds_never_ask_github(tmp_path):
    r, web = make(tmp_path, {})
    assert r.notes("roam", "Preponderous-Software/roam", "0.13.1-SNAPSHOT+gabc") is None
    r.runPending()
    assert web.asked == []


def test_github_is_rate_limited_and_backs_off(tmp_path):
    clock = Clock()
    pages = {}
    r, web = make(tmp_path, pages, clock)
    for i in range(remote.GITHUB_PER_HOUR + 5):
        r.notes("g%d" % i, "o/g%d" % i, "1.0.0")
    r.runPending()
    assert len(web.asked) == remote.GITHUB_PER_HOUR
    # A 403 (the unauthenticated limit) pauses every GitHub request.
    clock.now += 3601
    pages["https://api.github.com/repos/o/z0/releases?per_page=30"] = remote.Failed("HTTP 403", 403)
    r.notes("z0", "o/z0", "1.0.0")
    r.runPending()
    before = len(web.asked)
    r.notes("z1", "o/z1", "1.0.0")
    r.runPending()
    assert len(web.asked) == before


def test_bad_answers_are_silent(tmp_path):
    r, _ = make(tmp_path, {RELEASES: ("application/json", b"{not json")})
    args = ("second-helping", "Preponderous-Software/second-helping", "0.1.0")
    r.notes(*args)
    r.runPending()
    assert r.notes(*args) is None
    # A corrupt cache file reads as nothing.
    os.makedirs(str(tmp_path / ".remote" / "notes"), exist_ok=True)
    (tmp_path / ".remote" / "notes" / "second-helping.json").write_text("[")
    assert r.notes(*args) is None


def test_unsafe_names_are_refused(tmp_path):
    r, web = make(tmp_path, {})
    assert r.poster("../x", ("https://example.com/x.jpg",)) is None
    assert r.notes("cave", "not a repo", "1.0.0") is None
    r.runPending()
    assert web.asked == []


def test_release_text_is_trimmed_to_a_few_plain_lines():
    long = "word " * 400
    text = remote.release_text(long)
    assert len(text) <= remote.NOTES_MAX and text.endswith("…")
    generated = (
        "## What's Changed\n* feat: chests by @dmccoystephenson in https://github.com/o/r/pull/431\n\n"
        "**Full Changelog**: https://github.com/o/r/compare/a...b"
    )
    assert remote.release_text(generated) == "What's Changed\n• feat: chests"
    assert remote.first_sentence(remote.release_text(BODY)) == (
        "A walkable 3D harvest fair that teaches ranked choice voting."
    )


def test_a_heading_that_only_repeats_the_version_is_dropped():
    assert (
        remote.release_text("## 0.3.0\n\nThis update makes the day easier.")
        == "This update makes the day easier."
    )
    assert remote.release_text("## v1.2.0-rc.1\nFixes.") == "Fixes."
    assert remote.release_text("## New\n- A map.") == "New\n• A map."
