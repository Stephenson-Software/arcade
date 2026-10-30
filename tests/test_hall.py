import http.client
import json
import math
import os
import threading

import pytest

from arcade import hall, server

from helpers import TOKEN_SHA, game, registryText

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")


def entry(slug, repo, plays=0, current="1.0.0", isolation=False):
    return {
        "slug": slug,
        "title": slug.title(),
        "repo": repo,
        "plays": plays,
        "current": current,
        "isolation": isolation,
        "url": "https://%s.play.example.com/" % slug,
    }


GAMES = [
    entry("tidewater", "Stephenson-Software/Tidewater", 286, isolation=True),
    entry("roam", "Preponderous-Software/roam", 220, isolation=True),
    entry("env-lib-cpp", "Preponderous-Software/env-lib-cpp", 374),
    entry("sdl-sketches", "dmccoystephenson/sdl-sketches", 113),
    entry("familiar", "Preponderous-Software/familiar", 95, current=None),
]


# ------------------------------------------------------------- the layout


def test_roam_stands_at_the_end_and_the_rest_are_by_plays():
    doc = hall.layout(GAMES)
    slugs = [c["slug"] for c in doc["cabinets"]]
    assert slugs == ["roam", "env-lib-cpp", "tidewater", "sdl-sketches", "familiar"]
    roam = doc["cabinets"][0]
    assert roam["featured"] and roam["x"] == 0 and roam["angle"] == 0
    # The end of the aisle is further from the door than every other cabinet.
    assert all(c["z"] > roam["z"] for c in doc["cabinets"][1:])


def test_the_most_played_cabinets_are_nearest_the_door():
    doc = hall.layout(GAMES)
    rest = doc["cabinets"][1:]
    zs = [c["z"] for c in rest]
    assert zs == sorted(zs, reverse=True)


def big_hall():
    games = [entry("g%02d" % i, "Stephenson-Software/G%d" % i, plays=100 + i) for i in range(30)]
    return hall.layout(games + [entry("roam", "Preponderous-Software/roam", 1, isolation=True)])


def test_cabinets_stand_back_to_back_in_rows_facing_the_door_or_the_stage():
    doc = big_hall()
    rest = doc["cabinets"][1:]
    zs = sorted({c["z"] for c in rest}, reverse=True)
    assert 4 <= len(zs) <= 8  # two to four islands of two rows
    for c in rest:
        assert c["angle"] in (0.0, round(math.pi, 6))
        assert c["y"] == 0
    # Rows pair up back to back: a door-facing row, then a stage-facing one just behind it.
    for front, back in zip(zs[0::2], zs[1::2]):
        assert {c["angle"] for c in rest if c["z"] == front} == {0.0}
        assert {c["angle"] for c in rest if c["z"] == back} == {round(math.pi, 6)}
        assert front - back == pytest.approx(2 * -hall.FOOTPRINT[1] + hall.BACK_GAP)


def test_walkways_are_at_least_two_and_a_half_metres():
    doc = big_hall()
    fp, room = hall.FOOTPRINT, doc["room"]
    rest = doc["cabinets"][1:]
    # Down the middle, door to stage: no cabinet.
    assert min(abs(c["x"]) - fp[2] for c in rest) * 2 >= 2.5
    # Along the side walls.
    assert room["halfWidth"] - max(abs(c["x"]) + fp[2] for c in rest) >= 2.5
    # Across the room, between one island's back row and the next island's front row.
    zs = sorted({c["z"] for c in rest}, reverse=True)
    for back, front in zip(zs[1::2], zs[2::2]):
        assert (back - fp[3]) - (front + fp[3]) >= 2.5
    # From the door to the first row, and from the last row to the stage.
    assert room["near"] - (zs[0] + fp[3]) >= 2.5
    assert (zs[-1] - fp[3]) - room["stage"]["front"] >= 2.5


def test_the_room_is_roughly_square():
    room = big_hall()["room"]
    width, depth = 2 * room["halfWidth"], room["near"] - room["far"]
    assert 0.75 < width / depth < 1.33, (width, depth)


def test_roam_stands_alone_on_a_raised_stage_at_the_back_in_sight_of_the_door():
    doc = big_hall()
    roam, room = doc["cabinets"][0], doc["room"]
    assert roam["featured"] and roam["x"] == 0 and roam["y"] == hall.STAGE_HEIGHT > 0
    stage = room["stage"]
    assert stage["back"] < roam["z"] < stage["front"] and stage["back"] - room["far"] < 0.5
    # The centre walkway is clear from the door to the stage.
    assert all(abs(c["x"]) > hall.CENTRE_WALK / 2 for c in doc["cabinets"][1:])
    assert room["spawn"]["x"] == 0 and room["spawn"]["z"] > 0


def test_a_change_counter_stands_beside_the_door():
    room = big_hall()["room"]
    signs = {s["text"]: s for s in room["signs"]}
    counter = signs["CHANGE \u00b7 PRIZES"]
    assert counter["z"] > room["near"] - 1 and abs(counter["x"]) > room["door"][1]
    # It is an obstacle, beside (not in) the doorway, and the spawn point is clear of it.
    near_obstacles = [o for o in room["obstacles"] if o[3] >= room["near"] - 0.01]
    assert near_obstacles and all(o[2] < room["door"][0] or o[0] > room["door"][1] for o in near_obstacles)
    sp = room["spawn"]
    assert not any(o[0] < sp["x"] < o[2] and o[1] < sp["z"] < o[3] for o in room["obstacles"])


def test_the_hall_is_lit_warm_and_bright():
    room = big_hall()["room"]
    assert room["style"]["ambient"] >= 0.5
    assert len(room["lights"]) >= 8
    assert sum(1 for p in room["props"] if p["unlit"]) >= 8  # ceiling panels and the stage's edge
    # The two fills (kept whatever the light budget) reach across the room.
    assert all(l[3] >= 12 for l in room["lights"][:2])


def test_side_panels_are_coloured_by_organisation():
    doc = {c["slug"]: c for c in hall.layout(GAMES)["cabinets"]}
    assert tuple(doc["roam"]["colour"]) == hall.ORG_COLOURS["Preponderous-Software"]
    assert tuple(doc["tidewater"]["colour"]) == hall.ORG_COLOURS["Stephenson-Software"]
    assert tuple(doc["sdl-sketches"]["colour"]) == hall.ORG_COLOURS["dmccoystephenson"]
    assert tuple(hall.layout([entry("x", "someone/else")])["cabinets"][0]["colour"]) == hall.OTHER_COLOUR


def test_the_most_played_cabinets_are_in_the_rows_nearest_the_door():
    doc = big_hall()
    rest = doc["cabinets"][1:]
    zs = [c["z"] for c in rest]
    assert zs == sorted(zs, reverse=True)
    # And within a row, nearest the centre walkway first.
    first = [c for c in rest if c["z"] == zs[0]]
    assert [abs(c["x"]) for c in first] == sorted(abs(c["x"]) for c in first)


def test_an_empty_registry_is_an_empty_hall():
    doc = hall.layout([])
    assert doc["cabinets"] == []


def test_the_layout_matches_the_readme_picture():
    """docs/media/arcade-hall.sources.json records the order the README
    picture was drawn in; the shared order() must reproduce it from the same
    play counts."""
    with open(os.path.join(ROOT, "docs", "media", "arcade-hall.sources.json")) as f:
        sources = json.load(f)
    games = [
        {"slug": c["slug"], "title": c["title"], "repo": c["repo"], "plays": c["plays"]}
        for c in sources["cabinets"]
    ]
    games.reverse()  # any input order
    assert [g["slug"] for g in hall.order(games)] == [c["slug"] for c in sources["cabinets"]]


def test_poster_names_follow_the_trailer_files():
    assert hall.poster_name("Stephenson-Software/Frog-Hopper-2D") == "frog-hopper-2d"
    assert hall.poster_name("Stephenson-Software/simpleDiceThrow") == "simple-dice-throw"
    assert hall.poster_urls({"slug": "viron-strata", "repo": "Preponderous-Software/viron-strata"})[
        -1
    ].startswith("https://raw.githubusercontent.com/Preponderous-Software/viron-strata/")


def test_served_layout_names_only_posters_arcade_has():
    doc = hall.served_layout(GAMES, embed=False)
    by = {c["slug"]: c for c in doc["cabinets"]}
    for slug, c in by.items():
        has = os.path.isfile(os.path.join(hall.POSTERS, slug + ".jpg"))
        assert c["poster"] == ("posters/%s.jpg" % slug if has else None)
    assert by["familiar"]["deployed"] is False and by["roam"]["isolation"] is True
    assert doc["embed"] is False and doc["modes"] is True


def test_asset_names_cannot_leave_the_hall():
    assert hall.asset_path("hall.js")
    assert hall.asset_path("posters/roam.jpg")
    for bad in (
        "../server.py",
        "posters/../../server.py",
        "/etc/passwd",
        ".hidden",
        "a/b/c.js",
        "posters/",
        "",
    ):
        assert hall.asset_path(bad) is None, bad


# --------------------------------------------------------------- serving


@pytest.fixture
def running(tmp_path):
    def start(embed="off", entries=None):
        registry = tmp_path / "games.yaml"
        registry.write_text(
            registryText(
                entries
                if entries is not None
                else [
                    game("tidewater", isolation="on"),
                    game("rps", token_sha256=TOKEN_SHA, kind="static"),
                ]
            )
        )
        config = server.Config(
            "play.example.com",
            str(tmp_path / "data"),
            str(registry),
            "https://example.com/play",
            hallEmbed=embed,
        )
        httpd = server.makeServer(server.Arcade(config), host="127.0.0.1", port=0)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        started.append(httpd)
        return httpd.server_address[1]

    started = []
    yield start
    for httpd in started:
        httpd.shutdown()
        httpd.server_close()


def get(port, path, host="play.example.com", headers=None):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    conn.request("GET", path, headers=dict({"Host": host}, **(headers or {})))
    res = conn.getresponse()
    body = res.read()
    conn.close()
    return res, body


def test_hall_redirects_to_its_directory_keeping_the_query(running):
    port = running()
    res, _ = get(port, "/hall?at=roam")
    assert res.status == 301 and res.getheader("Location") == "/hall/?at=roam"


def test_the_hall_page_is_plain_unless_asked_to_be_isolated(running):
    port = running()
    res, body = get(port, "/hall/")
    assert res.status == 200 and res.getheader("Content-Type").startswith("text/html")
    assert b'<canvas id="hall"' in body and b"hall.js" in body
    assert res.getheader("Cross-Origin-Opener-Policy") is None
    assert res.getheader("Cross-Origin-Embedder-Policy") is None
    csp = res.getheader("Content-Security-Policy")
    assert "frame-src https://*.play.example.com" in csp and "'wasm-unsafe-eval'" in csp
    res, _ = get(port, "/hall/?isolated=1")
    assert res.getheader("Cross-Origin-Opener-Policy") == "same-origin"
    assert res.getheader("Cross-Origin-Embedder-Policy") == "require-corp"
    # The two modes are different responses to a cache.
    assert res.getheader("ETag") != get(port, "/hall/")[0].getheader("ETag")


def test_the_layout_follows_the_registry(running):
    port = running(embed="on")
    res, body = get(port, "/hall/layout.json")
    assert res.status == 200 and res.getheader("Content-Type") == "application/json"
    doc = json.loads(body)
    assert doc["embed"] is True
    assert {c["slug"] for c in doc["cabinets"]} == {"tidewater", "rps"}
    tide = next(c for c in doc["cabinets"] if c["slug"] == "tidewater")
    assert tide["url"] == "https://tidewater.play.example.com/"
    assert tide["isolation"] is True and tide["deployed"] is False
    for key in ("room", "cabinet"):
        assert key in doc
    assert json.loads(get(running(), "/hall/layout.json")[1])["embed"] is False


def test_hall_assets_are_served_with_types_and_revalidated(running):
    port = running()
    for name, kind in (
        ("hall.js", "text/javascript"),
        ("hall-engine.wasm", "application/wasm"),
        ("strata-kit.js", "text/javascript"),
        ("hall.css", "text/css"),
        ("posters/roam.jpg", "image/jpeg"),
    ):
        res, body = get(port, "/hall/" + name)
        assert res.status == 200, name
        assert res.getheader("Content-Type").startswith(kind), name
        tag = res.getheader("ETag")
        res, _ = get(port, "/hall/" + name, headers={"If-None-Match": tag})
        assert res.status == 304, name


def test_the_engine_is_sent_gzipped_to_a_browser_that_accepts_it(running):
    port = running()
    res, body = get(port, "/hall/hall-engine.wasm", headers={"Accept-Encoding": "gzip"})
    assert res.getheader("Content-Encoding") == "gzip"
    assert res.getheader("Content-Type") == "application/wasm"
    assert body[:2] == b"\x1f\x8b"


def test_unknown_or_escaping_hall_paths_are_404(running):
    port = running()
    for path in ("/hall/nope.js", "/hall/../og.png", "/hall/posters/nope.jpg", "/hall/%2e%2e/server.py"):
        assert get(port, path)[0].status == 404, path


def test_the_hall_is_not_answered_on_a_game_host(running):
    port = running()
    res, _ = get(port, "/hall/", host="rps.play.example.com")
    # A game's host is the game's: arcade answers there as the game (not deployed).
    assert res.status == 404
    res, _ = get(port, "/hall/layout.json", host="rps.play.example.com")
    assert res.status == 404


def test_hall_embed_must_be_on_or_off(tmp_path):
    with pytest.raises(ValueError):
        server.Config("play.example.com", str(tmp_path), "x", "https://e.com", hallEmbed="maybe")
    env = {"ARCADE_HALL_EMBED": "ON"}
    assert server.Config.fromEnvironment(env).hallEmbed is True
    assert server.Config.fromEnvironment({}).hallEmbed is False


def test_the_landing_page_links_to_the_hall(running):
    port = running()
    _, body = get(port, "/")
    assert b'href="/hall/"' in body and b"Walk the hall" in body


def test_the_committed_engine_is_what_build_sh_names():
    with open(os.path.join(ROOT, "hall3d", "build.sh")) as f:
        script = f.read()
    for name in (
        "hall-engine.js",
        "hall-engine.wasm",
        "hall-engine.js.gz",
        "hall-engine.wasm.gz",
        "strata-kit.js",
        "strata-loader.js",
    ):
        assert os.path.isfile(os.path.join(hall.ASSETS, name)), name
    for export in (
        "_hall_texture",
        "_hall_mesh",
        "_hall_set_items",
        "_hall_set_points",
        "_hall_set_lights",
        "_hall_set_view",
    ):
        assert export in script


def test_the_walking_maths_hold_for_the_live_sized_hall(tmp_path):
    """tests/browser/hall_walk_test.cjs (plain node) against a 31-cabinet hall."""
    import shutil
    import subprocess

    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    games = [entry("g%02d" % i, "Stephenson-Software/G%d" % i, plays=i) for i in range(30)]
    games.append(entry("roam", "Preponderous-Software/roam", 1, isolation=True))
    path = tmp_path / "layout.json"
    path.write_text(json.dumps(hall.layout(games)))
    run = subprocess.run(
        [node, os.path.join(ROOT, "tests", "browser", "hall_walk_test.cjs"), str(path)],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert run.returncode == 0, run.stdout + run.stderr


def test_the_move_into_a_game_and_back():
    """tests/browser/hall_play_test.cjs (plain node): the state machine that
    eases the camera to a cabinet's screen, crossfades the game in once it
    has painted, and reverses on Back."""
    import shutil
    import subprocess

    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    run = subprocess.run(
        [node, os.path.join(ROOT, "tests", "browser", "hall_play_test.cjs")],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert run.returncode == 0, run.stdout + run.stderr


def test_attract_mode_glow_and_sound():
    """tests/browser/hall_life_test.cjs (plain node): attract-mode timing,
    the shimmer and glow ranges, scanlines, and sound off by default."""
    import shutil
    import subprocess

    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    run = subprocess.run(
        [node, os.path.join(ROOT, "tests", "browser", "hall_life_test.cjs")],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert run.returncode == 0, run.stdout + run.stderr


def test_the_hall_page_loads_its_scripts_in_order():
    with open(os.path.join(hall.ASSETS, "index.html")) as f:
        page = f.read()
    order = ["strata-loader.js", "strata-kit.js", "hall-walk.js", "hall-play.js", "hall-life.js", "hall.js"]
    at = [page.index('src="%s"' % name) for name in order]
    assert at == sorted(at)
    assert 'id="sound"' in page and 'aria-pressed="false"' in page


def test_blurbs_are_trimmed_to_one_short_line():
    assert hall.trim_blurb("  a\n b  ") == "a b"
    long = "word " * 60
    out = hall.trim_blurb(long)
    assert len(out) <= hall.BLURB_MAX and out.endswith("\u2026") and "\n" not in out
    with open(hall.BLURBS, encoding="utf-8") as f:
        committed = json.load(f)
    assert committed and all(len(v) <= hall.BLURB_MAX and "\n" not in v for v in committed.values())


def test_served_layout_carries_each_cabinets_org_and_blurb(monkeypatch, tmp_path):
    path = tmp_path / "blurbs.json"
    path.write_text(json.dumps({"tidewater": "A time-loop text adventure.", "roam": 5}))
    monkeypatch.setattr(hall, "BLURBS", str(path))
    doc = {c["slug"]: c for c in hall.served_layout(GAMES, False)["cabinets"]}
    assert doc["tidewater"]["org"] == "Stephenson-Software"
    assert doc["tidewater"]["blurb"] == "A time-loop text adventure."
    assert doc["roam"]["blurb"] is None  # not a string: ignored
    assert doc["env-lib-cpp"]["blurb"] is None
    # A missing or broken file means no blurbs, never an error.
    path.write_text("{not json")
    path.touch()
    os.utime(str(path), ns=(1, 1))
    assert all(c["blurb"] is None for c in hall.served_layout(GAMES, False)["cabinets"])
    monkeypatch.setattr(hall, "BLURBS", str(tmp_path / "absent.json"))
    assert all(c["blurb"] is None for c in hall.served_layout(GAMES, False)["cabinets"])


def test_every_live_game_has_a_poster():
    with open(os.path.join(ROOT, "docs", "media", "arcade-hall.sources.json")) as f:
        slugs = [c["slug"] for c in json.load(f)["cabinets"]]
    missing = [s for s in slugs if not os.path.isfile(os.path.join(hall.POSTERS, s + ".jpg"))]
    assert missing == []


def test_every_engine_export_is_in_the_build_and_used_by_the_page():
    import re

    with open(os.path.join(ROOT, "hall3d", "main.cpp")) as f:
        exports = set(re.findall(r"STRATA_KIT_EXPORT\s+\w+\s+(hall_\w+)\(", f.read()))
    with open(os.path.join(ROOT, "hall3d", "build.sh")) as f:
        listed = set(re.search(r"KIT_EXPORTS=(\S+)", f.read()).group(1).split(","))
    with open(os.path.join(hall.ASSETS, "hall.js")) as f:
        page = f.read()
    assert exports and {"_" + e for e in exports} <= listed
    for name in exports:
        assert "mod._%s" % name in page, name


def test_the_engine_starts_lighter_on_a_software_renderer():
    with open(os.path.join(hall.ASSETS, "hall.js")) as f:
        page = f.read()
    # Multisampling off, economy (half density, no point lights) from the start.
    assert "llvmpipe" in page and "swiftshader" in page.lower()
    assert "mod._hall_configure(" in page and "setEconomy(true)" in page


def test_the_readme_gif_of_playing_from_the_hall_is_small():
    path = os.path.join(ROOT, "docs", "media", "hall-play.gif")
    assert os.path.getsize(path) < 1024 * 1024
    with open(os.path.join(ROOT, "README.md")) as f:
        assert "docs/media/hall-play.gif" in f.read()
