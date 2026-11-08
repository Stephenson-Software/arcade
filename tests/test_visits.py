"""Honest play counts: arcade.visits, and the server counting a game's page at
most once per visitor per game per UTC day."""

import datetime
import json
import time

from arcade import visits
from test_server import API, TIDEWATER, arcade, request, upload  # noqa: F401  (fixture)

DAY = datetime.date(2026, 11, 8)


def test_a_visitor_counts_once_per_game_per_day():
    v = visits.Visits()
    assert v.first("cave", "203.0.113.5", "Safari", DAY) is True
    assert v.first("cave", "203.0.113.5", "Safari", DAY) is False
    # Another game, another address or another browser is another play.
    assert v.first("dice", "203.0.113.5", "Safari", DAY) is True
    assert v.first("cave", "203.0.113.6", "Safari", DAY) is True
    assert v.first("cave", "203.0.113.5", "Firefox", DAY) is True
    # The next UTC day starts over.
    assert v.first("cave", "203.0.113.5", "Safari", DAY + datetime.timedelta(days=1)) is True


def test_nothing_identifying_is_kept_and_the_key_changes_each_day():
    v = visits.Visits()
    v.first("cave", "203.0.113.5", "Safari", DAY)
    salt = v._salt
    held = list(v._seen)
    assert len(held) == 1 and len(held[0]) == visits.DIGEST_BYTES
    assert b"203.0.113.5" not in held[0] and b"Safari" not in held[0]
    v.first("cave", "203.0.113.5", "Safari", DAY + datetime.timedelta(days=1))
    assert v._salt != salt and len(v) == 1 and held[0] not in v._seen
    # Two processes (or a restart) never share a key.
    assert visits.Visits()._salt == b""


def test_memory_is_bounded():
    v = visits.Visits(maxKeys=3)
    assert [v.first("cave", "10.0.0.%d" % i, "Safari", DAY) for i in range(5)] == [
        True,
        True,
        True,
        False,
        False,
    ]
    assert len(v) == 3
    # A visitor already seen is still a repeat, not a play.
    assert v.first("cave", "10.0.0.0", "Safari", DAY) is False


def plays(arcade, expect=None):  # noqa: F811
    """The play count, once the last page load's count has landed (it is
    counted after the response is sent)."""
    for _ in range(50):
        n = json.loads(request(arcade, "GET", API, "/api/games/tidewater")[1])["plays"]
        if expect is None or n == expect:
            return n
        time.sleep(0.02)
    return n


def test_reloads_do_not_count_again(arcade):  # noqa: F811
    upload(arcade)
    phone = {"User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) Safari/604.1"}
    for _ in range(4):
        request(arcade, "GET", TIDEWATER, "/", headers=phone)
    request(arcade, "GET", TIDEWATER, "/play", headers=phone)
    assert plays(arcade, 1) == 1
    # Behind the proxy, the client is the last X-Forwarded-For hop: two people, two plays.
    for client in ("198.51.100.1", "198.51.100.2", "198.51.100.2"):
        headers = dict(phone, **{"X-Forwarded-For": "10.9.9.9, " + client})
        request(arcade, "GET", TIDEWATER, "/", headers=headers)
    assert plays(arcade, 3) == 3
    # The day's per-day count moves with the all-time one.
    assert sum(arcade.store.daily("tidewater").values()) == 3


def test_the_monitor_marker_is_never_a_play(arcade):  # noqa: F811
    upload(arcade)
    watch = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 Safari/604.1 arcade-watch"
    request(arcade, "GET", TIDEWATER, "/", headers={"User-Agent": watch})
    request(
        arcade, "GET", TIDEWATER, "/", headers={"User-Agent": "Mozilla/5.0 (X11) Chrome/130 Arcade-Watch/1"}
    )
    request(arcade, "GET", TIDEWATER, "/", headers={"User-Agent": "Mozilla/5.0 (a person)"})
    assert plays(arcade, 1) == 1  # only the person's
    for _ in range(50):
        if arcade.reporter.events:
            break
        time.sleep(0.02)
    assert arcade.reporter.events == [("page-served", {"slug": "tidewater"})]


def test_counts_already_on_disk_are_kept(arcade):  # noqa: F811
    upload(arcade)
    for _ in range(7):
        arcade.store.addPlay("tidewater")
    request(arcade, "GET", TIDEWATER, "/")
    request(arcade, "GET", TIDEWATER, "/")
    assert plays(arcade, 8) == 8
