import datetime
import json

import pytest

from arcade import hall, seasons

from test_hall import GAMES, entry, get, running  # noqa: F401 (running is a fixture)

UTC = datetime.timezone.utc


def at(y, m, d, hh=12, mm=0):
    return datetime.datetime(y, m, d, hh, mm, tzinfo=UTC)


def big_games():
    games = [entry("g%02d" % i, "Stephenson-Software/G%d" % i, plays=100 + i) for i in range(30)]
    return games + [entry("roam", "Preponderous-Software/roam", 1), entry("familiar", "Preponderous-Software/familiar")]


# ------------------------------------------------------------- the clock


def test_denver_is_seven_hours_behind_in_winter_and_six_in_summer():
    assert seasons.denver(at(2026, 1, 15, 12)) == datetime.datetime(2026, 1, 15, 5)
    assert seasons.denver(at(2026, 7, 4, 12)) == datetime.datetime(2026, 7, 4, 6)
    # 2026: daylight time from 2026-03-08 09:00 UTC to 2026-11-01 08:00 UTC.
    assert seasons.denver(at(2026, 3, 8, 8, 59)).hour == 1
    assert seasons.denver(at(2026, 3, 8, 9, 0)).hour == 3
    assert seasons.denver(at(2026, 11, 1, 7, 59)).hour == 1
    assert seasons.denver(at(2026, 11, 1, 8, 0)).hour == 1  # 01:00 again, in standard time
    # A naive time is taken as UTC.
    assert seasons.denver(datetime.datetime(2026, 1, 15, 12)) == datetime.datetime(2026, 1, 15, 5)


def test_denver_matches_the_tz_database_where_python_has_it():
    try:
        from zoneinfo import ZoneInfo

        zone = ZoneInfo(seasons.TIME_ZONE)
    except Exception:  # Python 3.8, or no tz data in the image
        pytest.skip("no zoneinfo")
    t = at(2025, 1, 1, 0, 30)
    while t < at(2028, 1, 1):
        assert seasons.denver(t) == t.astimezone(zone).replace(tzinfo=None), t
        t += datetime.timedelta(hours=7, minutes=13)


# ----------------------------------------------------------- the seasons


def test_halloween_runs_from_october_20_to_november_1_in_denver():
    def name(t):
        s = seasons.pick(t)
        return s.name if s else None

    assert name(at(2026, 10, 19, 12)) is None
    # Midnight on the 20th in Denver is 06:00 UTC (daylight time).
    assert name(at(2026, 10, 20, 5, 59)) is None
    assert name(at(2026, 10, 20, 6, 0)) == "halloween"
    assert name(at(2026, 10, 29, 23)) == "halloween"
    assert name(at(2026, 10, 31, 23)) == "halloween"
    # All of November 1 in Denver (standard time from 08:00 UTC): until 07:00 UTC on the 2nd.
    assert name(at(2026, 11, 2, 6, 59)) == "halloween"
    assert name(at(2026, 11, 2, 7, 0)) is None


def test_winter_is_a_stub_shown_only_when_asked_for():
    assert seasons.pick(at(2026, 12, 24)) is None
    assert seasons.pick(at(2027, 1, 3)) is None
    winter = seasons.BY_NAME["winter"]
    assert not winter.ready
    assert winter.covers(datetime.date(2026, 12, 24)) and winter.covers(datetime.date(2027, 1, 6))
    assert not winter.covers(datetime.date(2027, 1, 7)) and not winter.covers(datetime.date(2026, 11, 30))
    assert seasons.pick(at(2026, 6, 1), "winter") is winter


def test_the_override_names_a_season_or_turns_decor_off():
    summer, october = at(2026, 6, 1), at(2026, 10, 29)
    assert seasons.pick(summer, "halloween").name == "halloween"
    assert seasons.pick(summer, " Halloween ").name == "halloween"
    assert seasons.pick(october, "none") is None
    assert seasons.pick(october, "off") is None
    # Unknown: the date decides.
    assert seasons.pick(october, "easter").name == "halloween"
    assert seasons.pick(summer, "easter") is None


# --------------------------------------------------------------- the decor


def dressed(name="halloween", games=None):
    return hall.served_layout(games or big_games(), "off", season=name)


def test_out_of_season_the_hall_is_as_it_was():
    plain = hall.served_layout(big_games(), "off", season="none")
    assert plain["season"] is None
    assert plain["room"] == hall.layout(big_games())["room"]


def test_halloween_tints_the_lights_more_orange():
    plain, spooky = dressed("none")["room"], dressed()["room"]
    light, base = spooky["lights"][0][4:7], plain["lights"][0][4:7]
    assert light[0] == base[0] and light[1] < base[1] and light[2] < base[2]
    assert spooky["style"]["light"] == seasons.BY_NAME["halloween"].light
    # Slightly: the same lights, in the same places.
    assert [l[:4] for l in spooky["lights"]] == [l[:4] for l in plain["lights"]]
    assert spooky["style"]["ambient"] == plain["style"]["ambient"]


def test_lanterns_stand_by_the_door_and_on_the_counter():
    doc = dressed()
    ss, room = doc["season"], doc["room"]
    assert ss["name"] == "halloween"
    by_door = [L for L in ss["lanterns"] if L["y"] == 0]
    on_counter = [L for L in ss["lanterns"] if L["y"] > 1]
    assert len(by_door) >= 2 and len(on_counter) >= 2
    d0, d1 = room["door"][0], room["door"][1]
    # Either side of the doorway, against the wall, not in it.
    assert any(L["x"] < d0 for L in by_door) and any(L["x"] > d1 for L in by_door)
    for L in by_door:
        assert L["x"] + L["size"] / 2 < d0 or L["x"] - L["size"] / 2 > d1
        assert room["near"] - L["z"] < 0.6
    counter = seasons._counter(room)
    for L in on_counter:
        assert counter[0] < L["x"] < counter[2] and counter[1] < L["z"] < counter[3] and L["y"] == counter[4]
    # Lit by flickering lights at the door and the counter.
    assert len(ss["lights"]) >= 2 and all(len(l) == 8 for l in ss["lights"])


def test_decor_never_narrows_a_walkway_or_moves_a_cabinet():
    plain, doc = dressed("none"), dressed()
    assert doc["cabinets"] == plain["cabinets"] and doc["room"]["spawn"] == plain["room"]["spawn"]
    room = doc["room"]
    added = room["obstacles"][len(plain["room"]["obstacles"]) :]
    assert len(added) == 3  # the lanterns by the door, and nothing else
    for x0, z0, x1, z1 in added:
        # Against the near wall, clear of the doorway, the centre walkway and the spawn point.
        assert z1 == room["near"] and room["near"] - z0 < 0.6
        assert x1 < room["door"][0] or x0 > room["door"][1]
        sp = room["spawn"]
        assert not (x0 - 0.3 < sp["x"] < x1 + 0.3 and z0 - 0.3 < sp["z"] < z1 + 0.3)
    # The cobwebs are up in the corners, the banner above head height.
    for web in doc["season"]["cobwebs"]:
        assert abs(web["x"]) == room["halfWidth"] and web["z"] in (room["near"], room["far"])
    banner = doc["season"]["banner"]
    assert banner["y"] - banner["h"] / 2 > 2.4
    assert abs(banner["x"]) + banner["w"] / 2 < hall.CENTRE_WALK / 2 + 0.05


def test_familiar_is_on_a_banner_in_sight_of_the_door():
    doc = dressed()
    banner, room = doc["season"]["banner"], doc["room"]
    assert banner["slug"] == "familiar" and banner["facing"] == 1
    assert banner["z"] < room["spawn"]["z"]
    # Far enough in that all of it is in view from where a visitor starts
    # (62 degree vertical field of view, looking level).
    import math

    top = banner["y"] + banner["h"] / 2 - 1.62
    assert math.degrees(math.atan2(top, room["spawn"]["z"] - banner["z"])) < 31 - 5
    # No Familiar in the registry: no banner, the rest of the decor stays.
    without = dressed(games=[g for g in big_games() if g["slug"] != "familiar"])
    assert "banner" not in without["season"] and without["season"]["lanterns"]


def test_the_winter_stub_brings_no_decor_yet():
    doc = dressed("winter")
    assert doc["season"]["name"] == "winter"
    assert doc["season"]["lanterns"] == [] and doc["season"]["cobwebs"] == []
    assert doc["room"]["obstacles"] == dressed("none")["room"]["obstacles"]


def test_layout_json_takes_a_season_override(running):  # noqa: F811
    port = running()
    doc = json.loads(get(port, "/hall/layout.json?season=halloween")[1])
    assert doc["season"]["name"] == "halloween" and doc["season"]["lanterns"]
    assert json.loads(get(port, "/hall/layout.json?season=none")[1])["season"] is None
    # Without one, the date decides: some season or none, never an error.
    res, body = get(port, "/hall/layout.json")
    assert res.status == 200 and "season" in json.loads(body)


def test_the_page_asks_for_the_season_it_was_given_and_draws_it():
    import os

    with open(os.path.join(hall.ASSETS, "hall.js")) as f:
        page = f.read()
    assert '"layout.json" + (season ? "?season="' in page
    assert "buildSeason(points)" in page and "HallLife.candle" in page
