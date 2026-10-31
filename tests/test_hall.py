import html
import http.client
import json
import math
import os
import re
import threading

import pytest

from arcade import hall, hall_model, server

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


# ----------------------------------------------------- the cabinet model


def parts():
    return hall.layout(GAMES)["cabinet"]["model"]


def triangles(part):
    p, n, idx = part["p"], part["n"], part["i"]
    for k in range(0, len(idx), 3):
        tri = idx[k: k + 3]
        yield [p[3 * v: 3 * v + 3] for v in tri], [n[3 * v: 3 * v + 3] for v in tri]


def test_the_cabinet_model_is_well_formed_and_faces_out():
    model = parts()
    for name in ("detail", "accent", "lod", "art"):
        part = model[name]
        count = len(part["r"])
        assert len(part["p"]) == len(part["n"]) == 3 * count and count
        assert all(0 <= i < count for i in part["i"]) and len(part["i"]) % 3 == 0
        assert all(r in hall_model.ROLES or r == "art" for r in part["r"]), name
        # Every triangle is wound counter-clockwise seen from the side its normal points to.
        for (a, b, c), (na, _, _) in triangles(part):
            e1 = [b[i] - a[i] for i in range(3)]
            e2 = [c[i] - a[i] for i in range(3)]
            g = [e1[1] * e2[2] - e1[2] * e2[1], e1[2] * e2[0] - e1[0] * e2[2], e1[0] * e2[1] - e1[1] * e2[0]]
            if sum(v * v for v in g) > 1e-12:
                assert sum(g[i] * na[i] for i in range(3)) > 0, (name, a, b, c, na)
    assert len(model["art"]["t"]) == 2 * len(model["art"]["r"])
    assert all(0 <= v <= 1 for v in model["art"]["t"])


def test_the_cabinet_model_stands_inside_its_footprint():
    """Walking and collisions are unchanged: nothing reaches past the footprint."""
    x0, z0, x1, z1 = hall.FOOTPRINT
    for name, part in parts().items():
        if not isinstance(part, dict) or "p" not in part:
            continue
        p = part["p"]
        for k in range(0, len(p), 3):
            x, y, z = p[k: k + 3]
            assert x0 - 0.005 <= x <= x1 + 0.005 and z0 - 0.009 <= z <= z1 + 0.009, (name, x, y, z)
            assert -0.001 <= y <= 2.31


def inside(profile, z, y):
    hit = False
    for k in range(len(profile)):
        (za, ya), (zb, yb) = profile[k], profile[(k + 1) % len(profile)]
        if (ya > y) != (yb > y) and z < za + (y - ya) * (zb - za) / (yb - ya):
            hit = not hit
    return hit


def test_the_side_panels_are_fans_from_a_point_that_sees_every_edge():
    """The side art is a fan of triangles from SIDE_CENTRE: that is only the
    panel's outline if every edge turns the same way round the centre."""
    cz, cy = hall_model.SIDE_CENTRE
    prof = hall_model.SIDE_PROFILE
    turns = [(za - cz) * (yb - cy) - (ya - cy) * (zb - cz) for (za, ya), (zb, yb) in zip(prof, prof[1:] + prof[:1])]
    assert all(t > 0 for t in turns) or all(t < 0 for t in turns)


def test_the_stand_in_is_inside_the_detailed_cabinet():
    """So the far model never pokes out of the near one's outline, and the
    screen and marquee (in front of the body) are never behind it."""
    p = parts()["lod"]["p"]
    for k in range(0, len(p), 3):
        x, y, z = p[k: k + 3]
        assert abs(x) < hall_model.SIDE_X[1]
        assert inside(hall_model.SIDE_PROFILE, z, y)
        if abs(x) < hall_model.SIDE_X[0]:
            assert inside(hall_model.BODY_PROFILE, z - 0.005, y) or inside(hall_model.DECK_PROFILE, z - 0.005, y)
    prof = hall_model.LOD_PROFILE
    for rect in (hall.SCREEN, hall.MARQ):
        for step in range(11):
            y = rect[1] + (rect[3] - rect[1]) * step / 10
            front = max(za + (y - ya) * (zb - za) / (yb - ya)
                        for (za, ya), (zb, yb) in zip(prof, prof[1:] + prof[:1]) if (ya - y) * (yb - y) <= 0 and ya != yb)
            assert front < rect[4], (rect, y, front)
    assert parts()["lodDistance"] == pytest.approx(8.0, abs=1.0)


def test_cabinets_have_a_coin_door_with_glowing_slots_a_grille_and_a_t_molding():
    model = parts()
    detail = set(model["detail"]["r"])
    assert {"door", "grille", "molding", "deck", "ball", "button2"} <= detail
    assert set(model["accent"]["r"]) == {"slot", "slotdark"}  # drawn unlit
    # The control deck slopes down towards the player.
    assert hall_model.deck_y(0.68) < hall_model.deck_y(0.36)
    # The T-molding and the deck take the cabinet's organisation colour.
    org = hall.ORG_COLOURS["Stephenson-Software"]
    assert hall_model.role_colour("molding", org) != hall_model.role_colour("molding", hall.ORG_COLOURS["dmccoystephenson"])
    assert max(hall_model.role_colour("molding", org)) > 0.6


def test_every_live_game_has_side_art_the_panels_size():
    with open(os.path.join(ROOT, "docs", "media", "arcade-hall.sources.json")) as f:
        slugs = [c["slug"] for c in json.load(f)["cabinets"]]
    for slug in slugs:
        path = os.path.join(hall.POSTERS, slug + ".side.jpg")
        assert os.path.isfile(path), slug
        with open(path, "rb") as f:
            assert list(jpeg_size(f.read())) == hall_model.art_size(), slug


def test_served_layout_names_only_side_art_arcade_has(tmp_path, monkeypatch):
    (tmp_path / "tidewater.side.jpg").write_bytes(b"x")
    monkeypatch.setattr(hall, "POSTERS", str(tmp_path))
    doc = {c["slug"]: c for c in hall.served_layout(GAMES, True)["cabinets"]}
    assert doc["tidewater"]["side"] == "posters/tidewater.side.jpg"
    assert doc["roam"]["side"] is None
    assert hall.asset_path("posters/roam.side.jpg")


# ------------------------------------------------------- the room's details


def test_stools_are_tucked_under_some_decks_with_their_own_colliders():
    doc = big_hall()
    room, cabs = doc["room"], doc["cabinets"]
    stools = [t for t in room["things"] if t["part"] == "stool"]
    assert 3 <= len(stools) < len(cabs) / 2
    r = hall_model.STOOL_RADIUS
    for st in stools:
        # Its own collider...
        assert [round(v, 4) for v in (st["x"] - r, st["z"] - r, st["x"] + r, st["z"] + r)] in room["obstacles"]
        # ...in front of a cabinet, under its deck, and clear of where a visitor stands to play it.
        cab = min(cabs, key=lambda c: math.hypot(c["x"] - st["x"], c["z"] - st["z"]))
        f = (math.sin(cab["angle"]), math.cos(cab["angle"]))
        ahead = (st["x"] - cab["x"]) * f[0] + (st["z"] - cab["z"]) * f[1]
        assert ahead == pytest.approx(hall_model.STOOL_Z, abs=1e-3)
        assert ahead - r < hall.FOOTPRINT[3] < ahead + r < 1.15 - 0.28
    # The walkways between facing rows are still at least 2.5 m with a stool on either side.
    fp = hall.FOOTPRINT
    zs = sorted({c["z"] for c in cabs[1:]}, reverse=True)
    reach = hall_model.STOOL_Z + r - fp[3]
    for back, front in zip(zs[1::2], zs[2::2]):
        assert (back - fp[3]) - (front + fp[3]) - 2 * reach >= 2.5
    assert (zs[-1] - fp[3] - reach) - room["stage"]["front"] >= 2.5


def test_the_carpet_is_a_patterned_tile():
    pattern = hall.carpet_pattern()
    assert pattern == hall.carpet_pattern()  # the same every time (the page and the picture agree)
    kinds = {p[0] for p in pattern}
    assert kinds == set(hall.CARPET_KINDS.values())
    colours = len(hall.STYLE["carpetDots"])
    for kind, x, y, size, turn, k in pattern:
        assert 0 <= x <= 256 and 0 <= y <= 256 and 0 < size < 40 and 0 <= k < colours
    assert hall.room_for(10)["style"]["pattern"] == pattern


def test_a_neon_arcade_sign_hangs_over_the_door():
    room = big_hall()["room"]
    sign = next(s for s in room["signs"] if s["text"] == "ARCADE")
    assert sign["neon"] and abs(sign["x"]) < room["door"][1]
    assert room["door"][2] < sign["y"] - sign["h"] / 2 and sign["y"] + sign["h"] / 2 < room["height"]
    assert sign["facing"] == -1 and sign["z"] > room["near"] - 0.2


def test_ceiling_panels_have_frames_and_the_prize_shelf_has_plush():
    room = big_hall()["room"]
    h = room["height"]
    panels = [p for p in room["props"] if p["unlit"] and p["lo"][1] == round(h - 0.04, 4)]
    frames = [p for p in room["props"] if not p["unlit"] and p["lo"][1] == round(h - 0.032, 4)]
    assert panels and len(frames) == len(panels)
    plush = [t for t in room["things"] if t["part"] == "plush"]
    assert len(plush) >= 5 and all(t["z"] > room["near"] - 0.5 for t in plush)
    assert room["ceilingTile"] > 0


def test_the_rooms_things_are_well_formed():
    for name, part in big_hall()["room"]["thingParts"].items():
        count = len(part["r"])
        assert len(part["p"]) == 3 * count and all(0 <= i < count for i in part["i"]), name
        assert all(r in hall_model.ROLES for r in part["r"]), name
        for (a, b, c), (na, _, _) in triangles(part):
            e1 = [b[i] - a[i] for i in range(3)]
            e2 = [c[i] - a[i] for i in range(3)]
            g = [e1[1] * e2[2] - e1[2] * e2[1], e1[2] * e2[0] - e1[0] * e2[2], e1[0] * e2[1] - e1[1] * e2[0]]
            if sum(v * v for v in g) > 1e-12:
                assert sum(g[i] * na[i] for i in range(3)) > 0, name


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
    # The card's likes and boards come from arcade-social, and from nowhere else.
    assert "connect-src 'self' https://api.play.example.com;" in csp
    res, _ = get(port, "/hall/?isolated=1")
    assert res.getheader("Cross-Origin-Opener-Policy") == "same-origin"
    assert res.getheader("Cross-Origin-Embedder-Policy") == "require-corp"
    # The two modes are different responses to a cache.
    assert res.getheader("ETag") != get(port, "/hall/")[0].getheader("ETag")


def meta(body, prop):
    """The content of the one <meta> whose property or name is `prop`."""
    text = body.decode("utf-8")
    found = [line for line in text.splitlines() if '"%s"' % prop in line and line.startswith("<meta")]
    assert len(found) == 1, (prop, found)
    return found[0].split('content="', 1)[1].rsplit('"', 1)[0]


def test_the_hall_unfurls_with_its_own_card(running):
    port = running()
    res, body = get(port, "/hall/")
    assert b"<!--share-meta-->" not in body
    assert meta(body, "og:title") == "Arcade Hall"
    assert meta(body, "og:url") == "https://play.example.com/hall/"
    image = meta(body, "og:image")
    assert image.startswith("https://play.example.com/hall/cards/hall.jpg?v=")
    assert meta(body, "twitter:image") == image and meta(body, "twitter:card") == "summary_large_image"
    assert (meta(body, "og:image:width"), meta(body, "og:image:height")) == ("1200", "630")
    assert meta(body, "og:image:alt") == html.escape(hall.HALL_CARD_ALT)
    # The card itself is served, as a JPEG of the size the tags say.
    res, card = get(port, image.split("play.example.com", 1)[1])
    assert res.status == 200 and res.getheader("Content-Type") == "image/jpeg"
    assert card[:3] == b"\xff\xd8\xff"


def test_a_link_to_a_cabinet_unfurls_with_that_game(running):
    port = running()
    res, body = get(port, "/hall/?at=tidewater")
    assert res.status == 200
    assert meta(body, "og:title") == "Tidewater, in the Arcade Hall"
    assert meta(body, "og:url") == "https://play.example.com/hall/?at=tidewater"
    assert "/hall/cards/tidewater.jpg?v=" in meta(body, "og:image")
    assert "Tidewater arcade cabinet" in meta(body, "og:image:alt")
    assert meta(body, "og:description").endswith("Walk up to its cabinet in the arcade hall and play it.")
    assert "\u2026." not in meta(body, "og:description") and ".." not in meta(body, "og:description")
    # Each cabinet's page is its own response to a cache.
    assert res.getheader("ETag") != get(port, "/hall/")[0].getheader("ETag")
    tag = res.getheader("ETag")
    assert get(port, "/hall/?at=tidewater", headers={"If-None-Match": tag})[0].status == 304
    # A game with no card of its own yet gets the hall's, under its own title.
    _, body = get(port, "/hall/?at=rps")
    assert meta(body, "og:title") == "Rps, in the Arcade Hall"
    assert "/hall/cards/hall.jpg?v=" in meta(body, "og:image")
    # Anything not in the registry is the plain hall; nothing from the query is echoed.
    _, body = get(port, '/hall/?at=%22%3E%3Cscript%3E')
    assert meta(body, "og:title") == "Arcade Hall" and b"<script>" not in body


def test_every_card_is_a_1200_by_630_jpeg_and_small():
    names = sorted(os.listdir(hall.CARDS))
    assert "hall.jpg" in names
    for name in names:
        with open(os.path.join(hall.CARDS, name), "rb") as f:
            data = f.read()
        assert data[:3] == b"\xff\xd8\xff", name
        assert len(data) < 200 * 1024, name  # link scrapers give up on big images
        assert jpeg_size(data) == (hall.CARD_WIDTH, hall.CARD_HEIGHT), name


def jpeg_size(data):
    """(width, height) from a JPEG's start-of-frame marker."""
    i = 2
    while i < len(data):
        marker, length = data[i + 1], int.from_bytes(data[i + 2 : i + 4], "big")
        if marker in (0xC0, 0xC1, 0xC2):
            return int.from_bytes(data[i + 7 : i + 9], "big"), int.from_bytes(data[i + 5 : i + 7], "big")
        i += 2 + length
    raise AssertionError("no start-of-frame marker")


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
        "_hall_set_lods",
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


def test_the_gamepad_walks_looks_plays_and_goes_back():
    """tests/browser/hall_controls_test.cjs (plain node): the gamepad's
    dead zones, sticks, d-pad and buttons."""
    import shutil
    import subprocess

    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    run = subprocess.run(
        [node, os.path.join(ROOT, "tests", "browser", "hall_controls_test.cjs")],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert run.returncode == 0, run.stdout + run.stderr


def test_the_settings_panel_has_every_setting_and_keeps_them():
    with open(os.path.join(hall.ASSETS, "index.html")) as f:
        page = f.read()
    with open(os.path.join(hall.ASSETS, "hall.js")) as f:
        js = f.read()
    for el in ("set-sens", "set-invert", "set-fov", "bob", "set-reduce", "set-hum", "settings-btn"):
        assert 'id="%s"' % el in page, el
    # Head bob is off unless asked for: its box is never checked in the page.
    assert re.search(r'<input id="bob"[^>]*checked', page) is None
    # One JSON object in localStorage, read and written only through
    # HallControls.settings (which wraps every access in try/catch).
    assert "SET.load(localStore" in js and "SET.save(localStore" in js
    assert "localStorage.setItem" not in js and "localStorage.getItem" not in js
    # The field of view is the setting's, everywhere the hall uses one.
    assert "W.FOV" not in js


def test_the_hall_can_be_walked_by_keyboard_and_screen_reader():
    with open(os.path.join(hall.ASSETS, "index.html")) as f:
        page = f.read()
    with open(os.path.join(hall.ASSETS, "hall.js")) as f:
        js = f.read()
    body = page[page.index("<body>"):]
    # The skip link is the first thing in the page, and goes to the list of games.
    assert re.match(r'<body>\s*<a id="skip" class="skip" href="\.\./">Skip to game list</a>', body)
    assert re.search(r'<div id="announce"[^>]*aria-live="polite"', page)
    assert 'id="pointer"' in page and "Tab" in re.search(r'<canvas id="hall"[^>]*>', page).group(0)
    # Tab steps through the cabinets nearest first, and lets focus go past the
    # last one (no trap). Walking to one never sets the camera's yaw.
    fn = js[js.index("function tabCabinet"):js.index("function showPointer")]
    assert "C.order(" in fn and "clearFocus(); return false;" in fn
    start = js.index("function showPointer")
    pointer = js[start:js.index("\n  }\n", start)]
    assert "C.project(" in pointer
    assert "cam.yaw" not in fn and "cam.yaw" not in pointer


def test_the_hall_page_loads_its_scripts_in_order():
    with open(os.path.join(hall.ASSETS, "index.html")) as f:
        page = f.read()
    order = ["strata-loader.js", "strata-kit.js", "hall-walk.js", "hall-play.js", "hall-life.js", "hall-controls.js", "hall.js"]
    order += ["hall-share.js", "hall-social.js"]
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


def test_the_hall_has_a_map_that_can_be_toggled():
    with open(os.path.join(hall.ASSETS, "index.html")) as f:
        page = f.read()
    assert 'id="map"' in page and 'id="map-btn"' in page and 'aria-controls="map"' in page
    with open(os.path.join(hall.ASSETS, "hall.js")) as f:
        script = f.read()
    # Remembered, opened by M, and a tap on it walks without turning (target only).
    assert "arcade-hall.map" in script and 'e.key.toLowerCase() === "m"' in script
    assert "kit.cam.yaw =" not in script.split("function drawMap")[1].split("function after")[0]


def test_the_hall_has_a_share_button_that_links_to_the_spot(running):
    with open(os.path.join(hall.ASSETS, "index.html")) as f:
        page = f.read()
    assert 'id="share"' in page and 'aria-label="Share this spot"' in page
    assert 'id="toast"' in page and 'role="status"' in page
    with open(os.path.join(hall.ASSETS, "hall-share.js")) as f:
        script = f.read()
    # A cabinet's link is ?at=<slug> (it unfurls with that cabinet); elsewhere the #p= place.
    assert 'searchParams.set("at"' in script and "url.hash = `p=" in script
    # The share sheet on a phone, else the clipboard (and by hand without a secure context).
    assert "navigator.share" in script and "navigator.clipboard.writeText" in script
    assert 'execCommand("copy")' in script and '"AbortError"' in script
    # It only reads the hall's state; it never moves or turns the view.
    assert "__hall.place" not in script and "cam.yaw" not in script
    res, _ = get(running(), "/hall/hall-share.js")
    assert res.status == 200 and res.getheader("Content-Type").startswith("text/javascript")


def test_a_game_added_in_the_last_two_weeks_is_new():
    import datetime

    now = datetime.datetime(2026, 10, 29, 20, 0, tzinfo=datetime.timezone.utc)
    assert hall.is_new("2026-10-24T00:00:00Z", now)
    assert hall.is_new("2026-10-15T20:00:01Z", now)
    assert not hall.is_new("2026-10-15T20:00:00Z", now)  # exactly 14 days
    assert not hall.is_new("2026-10-01T00:00:00Z", now)
    assert not hall.is_new("2026-11-02T00:00:00Z", now)  # not yet
    for unknown in (None, "", "soon", 5):
        assert not hall.is_new(unknown, now)


def test_served_layout_marks_new_cabinets_from_api_added(monkeypatch):
    import datetime

    now = datetime.datetime(2026, 10, 29, 20, 0, tzinfo=datetime.timezone.utc)
    games = [dict(g) for g in GAMES]
    added = {"familiar": "2026-10-24T00:00:00Z", "tidewater": "2026-10-01T00:00:00Z", "roam": None}
    for g in games:
        if g["slug"] in added:
            g["added"] = added[g["slug"]]
    by = {c["slug"]: c for c in hall.served_layout(games, "off", now=now)["cabinets"]}
    assert by["familiar"]["new"] is True and by["familiar"]["added"] == "2026-10-24T00:00:00Z"
    assert by["tidewater"]["new"] is False and by["roam"]["new"] is False
    assert by["env-lib-cpp"]["new"] is False and by["env-lib-cpp"]["added"] is None


def test_the_marquee_carries_a_new_ribbon():
    with open(os.path.join(hall.ASSETS, "hall.js")) as f:
        page = f.read()
    assert "if (c.new) newRibbon(ctx, w, h);" in page and '"NEW"' in page


# ------------------------------------------------- live screens (trailers)


def mp4_size(data):
    """The (width, height) of an mp4's first track (its tkhd box)."""
    at = data.index(b"tkhd")
    return tuple(int.from_bytes(data[at + k : at + k + 2], "big") for k in ((80, 84) if data[at + 4] == 0 else (92, 96)))


def test_clip_names_follow_the_trailer_files():
    assert hall.clip_urls({"slug": "frog-hopper", "repo": "Stephenson-Software/Frog-Hopper-2D"}) == [
        "https://danielstephenson.dev/trailers/frog-hopper-2d.mp4",
        "https://danielstephenson.dev/trailers/frog-hopper.mp4",
    ]


def test_every_clip_is_a_small_16_by_9_mp4_for_a_live_game():
    with open(os.path.join(ROOT, "docs", "media", "arcade-hall.sources.json")) as f:
        slugs = {c["slug"] for c in json.load(f)["cabinets"]}
    names = sorted(os.listdir(hall.CLIPS))
    assert len(names) >= 20
    total = 0
    for name in names:
        assert name.endswith(".mp4"), name
        with open(os.path.join(hall.CLIPS, name), "rb") as f:
            data = f.read()
        total += len(data)
        assert data[4:8] == b"ftyp", name
        # The index first (faststart), so a clip starts before it has all arrived.
        assert data.index(b"moov") < data.index(b"mdat"), name
        assert mp4_size(data) == (384, 216), name
        assert len(data) < 256 * 1024, name
        assert hall.asset_path("clips/" + name)
    assert total < 3 * 1024 * 1024
    assert {n[:-4] for n in names} <= slugs | {"museum"}


def test_served_layout_names_only_clips_arcade_has(tmp_path, monkeypatch):
    (tmp_path / "tidewater.mp4").write_bytes(b"x")
    monkeypatch.setattr(hall, "CLIPS", str(tmp_path))
    doc = {c["slug"]: c for c in hall.served_layout(GAMES, True)["cabinets"]}
    assert doc["tidewater"]["clip"] == "clips/tidewater.mp4"
    assert doc["roam"]["clip"] is None


def test_byte_ranges():
    r = server.byteRange
    assert r(None, 100) is None and r("", 100) is None
    assert r("bytes=0-1", 100) == (0, 1)
    assert r("bytes=10-", 100) == (10, 99)
    assert r("bytes=90-500", 100) == (90, 99)
    assert r("bytes=-10", 100) == (90, 99)
    assert r("bytes=-500", 100) == (0, 99)
    assert r("bytes=100-", 100) == "unsatisfiable"
    assert r("bytes=-0", 100) == "unsatisfiable"
    # Not handled: the whole file instead.
    assert r("bytes=0-1,5-6", 100) is None
    assert r("items=0-1", 100) is None
    assert r("bytes=5-1", 100) is None


def test_clips_are_served_in_byte_ranges_for_safari(running):
    port = running()
    name = sorted(os.listdir(hall.CLIPS))[0]
    with open(os.path.join(hall.CLIPS, name), "rb") as f:
        data = f.read()
    res, body = get(port, "/hall/clips/" + name)
    assert res.status == 200 and body == data
    assert res.getheader("Content-Type") == "video/mp4" and res.getheader("Accept-Ranges") == "bytes"
    res, body = get(port, "/hall/clips/" + name, headers={"Range": "bytes=0-1"})
    assert res.status == 206 and body == data[:2]
    assert res.getheader("Content-Range") == "bytes 0-1/%d" % len(data)
    res, body = get(port, "/hall/clips/" + name, headers={"Range": "bytes=100-"})
    assert res.status == 206 and body == data[100:] and res.getheader("Content-Length") == str(len(data) - 100)
    res, body = get(port, "/hall/clips/" + name, headers={"Range": "bytes=%d-" % len(data)})
    assert res.status == 416 and res.getheader("Content-Range") == "bytes */%d" % len(data)
    # A compressed variant is never cut into ranges: the whole of it, as before.
    res, body = get(port, "/hall/hall-engine.wasm", headers={"Accept-Encoding": "gzip", "Range": "bytes=0-1"})
    assert res.status == 200 and res.getheader("Content-Encoding") == "gzip"


def test_which_screens_play_their_trailer():
    """tests/browser/hall_trailers_test.cjs (plain node): the nearest screens
    in sight play, at most a few, kept a little past the edge of range."""
    import shutil
    import subprocess

    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    run = subprocess.run(
        [node, os.path.join(ROOT, "tests", "browser", "hall_trailers_test.cjs")],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert run.returncode == 0, run.stdout + run.stderr


# ----------------------------------------------- popularity and the Hall of Fame


def test_the_hall_of_fame_hangs_by_the_door_across_from_the_counter():
    room = big_hall()["room"]
    fame, counter = room["fame"], {s["text"]: s for s in room["signs"]}["CHANGE · PRIZES"]
    # On the near wall, facing in, right of the door (the counter is left of it).
    assert fame["facing"] == -1 and room["near"] - 0.1 < fame["z"] < room["near"]
    assert fame["x"] - fame["w"] / 2 > room["door"][1] + 0.3 and counter["x"] < 0
    assert fame["x"] + fame["w"] / 2 < room["halfWidth"]
    # Up off the floor (over a lantern or a stool), under the ceiling, readable from the walkway.
    assert 0.9 < fame["y"] - fame["h"] / 2 and fame["y"] + fame["h"] / 2 < room["height"] - 0.5
    # Clear of every other sign on that wall.
    for s in room["signs"]:
        if abs(s["z"] - fame["z"]) < 0.6:
            assert abs(s["x"] - fame["x"]) >= (s["w"] + fame["w"]) / 2, s["text"]


def test_popularity_warmth_board_rows_and_values():
    """tests/browser/hall_fame_test.cjs (plain node): which marquees glow
    warmer, and what the Hall of Fame board lists."""
    import shutil
    import subprocess

    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    run = subprocess.run(
        [node, os.path.join(ROOT, "tests", "browser", "hall_fame_test.cjs")],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert run.returncode == 0, run.stdout + run.stderr


def test_the_card_shows_likes_and_boards_from_arcade_social(running):
    """tests/browser/hall_social_test.cjs (plain node) for the text; the page
    names arcade-social's URL and the card has a place for its line."""
    import shutil
    import subprocess

    res, body = get(running(), "/hall/")
    page = body.decode("utf-8")
    assert '<meta name="arcade-social" content="https://api.play.example.com">' in page
    assert "<!--social-meta-->" not in page
    assert 'id="card-social" hidden' in page
    with open(os.path.join(hall.ASSETS, "hall.js")) as f:
        script = f.read()
    assert 'new CustomEvent("hall:card"' in script
    with open(os.path.join(hall.ASSETS, "hall-social.js")) as f:
        social = f.read()
    # Public reads go without credentials; only the session, "my likes" and the heart carry them.
    assert social.count('credentials: "include"') == 2 and 'getJson("/v1/session", true)' in social
    assert '"X-Play-Client": "1"' in social
    # It reads the hall's state only through the event; it never moves or turns the view.
    assert "__hall" not in social.replace("__hallSocial", "") and "cam.yaw" not in social
    res, _ = get(running(), "/hall/hall-social.js")
    assert res.status == 200 and res.getheader("Content-Type").startswith("text/javascript")
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    run = subprocess.run(
        [node, os.path.join(ROOT, "tests", "browser", "hall_social_test.cjs")],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert run.returncode == 0, run.stdout + run.stderr
