"""Walk replays (RFC 0030 §3): arcade.walks, POST /api/walks and GET /api/walks/today,
and hall-replays.js under node."""

import datetime
import http.client
import json
import math
import os
import random
import shutil
import subprocess
import threading

import pytest

from arcade import hall, walks
from arcade.server import Arcade, Config, makeServer
from helpers import game, registryText

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
DOMAIN = "play.example.com"


def entry(slug, plays=0):
    return {"slug": slug, "title": slug.title(), "repo": "Stephenson-Software/" + slug, "plays": plays,
            "current": "1.0.0", "isolation": False, "url": "https://%s.%s/" % (slug, DOMAIN)}


def hall_of(n=12, reverse=False):
    games = [entry("g%02d" % i, plays=(n - i if not reverse else i)) for i in range(n)]
    games.append(entry("roam", plays=0))
    return hall.layout(games)


class Known(object):
    def __init__(self, *layouts):
        self.layouts = walks.Layouts()
        for layout in layouts:
            self.layouts.remember(layout)

    def get(self, key):
        return self.layouts.get(key)


def centre_walk(layout, n=10):
    """Down the centre walkway from the door, a point every 0.5 s at walking pace."""
    spawn = layout["room"].get("spawn") or {"x": 0, "z": layout["room"]["near"] - 1.2}
    return [[0.0, round(spawn["z"] - 1.2 * i, 2)] for i in range(n)]


def payload(layout, points=None, visits=None, **extra):
    body = {"layout": layout["layoutKey"], "dt": 0.5, "points": points or centre_walk(layout), "visits": visits or []}
    body.update(extra)
    return body


# --- the layout key ---------------------------------------------------------


def test_the_layout_key_names_the_cabinet_order():
    a, b = hall_of(), hall_of(reverse=True)
    assert a["layoutKey"] == hall_of()["layoutKey"]
    assert len(a["layoutKey"]) == 16 and int(a["layoutKey"], 16) >= 0
    assert a["layoutKey"] != b["layoutKey"]
    assert a["layoutKey"] == hall.layout_key([c["slug"] for c in a["cabinets"]])


# --- the collision port -----------------------------------------------------


def _inside(x, z, w, r=walks.RADIUS - 1e-6):
    for o, ri, fo, x0, z0, x1, z1 in w["obstacles"]:
        dx, dz = x - o[0], z - o[1]
        lx, lz = dx * ri[0] + dz * ri[1], dx * fo[0] + dz * fo[1]
        if math.hypot(lx - min(max(lx, x0), x1), lz - min(max(lz, z0), z1)) < r:
            return True
    return False


def test_resolve_pushes_points_out_of_cabinets_and_into_the_room():
    layout = hall_of()
    w = walks.world(layout)
    c = layout["cabinets"][2]
    x, z = walks.resolve(c["x"], c["z"], w)
    assert (x, z) != (c["x"], c["z"])
    b = w["bounds"]
    x, z = walks.resolve(b[2] + 5, b[3] + 5, w)
    assert x <= b[2] - walks.RADIUS + 1e-9 and z <= b[3] - walks.RADIUS + 1e-9


@pytest.mark.parametrize("count", [5, 31])
def test_resolve_matches_hall_walk_js(tmp_path, count):
    """The Python port and hall-walk.js give the same point for the same input."""
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    games = [entry("g%02d" % i, plays=i) for i in range(count)] + [entry("roam")]
    layout = hall.layout(games)
    b = walks.world(layout)["bounds"]
    rng = random.Random(7)
    points = [[rng.uniform(b[0] - 1, b[2] + 1), rng.uniform(b[1] - 1, b[3] + 1)] for _ in range(3000)]
    # And points right on cabinets (centres, corners), where the "inside" branch runs.
    for c in layout["cabinets"]:
        points.append([c["x"], c["z"]])
        points.append([c["x"] + 0.5, c["z"] + 0.3])
    (tmp_path / "layout.json").write_text(json.dumps(layout))
    (tmp_path / "points.json").write_text(json.dumps(points))
    run = subprocess.run(
        [node, os.path.join(ROOT, "tests", "browser", "hall_walk_parity.cjs"), str(tmp_path / "layout.json"),
         str(tmp_path / "points.json")],
        capture_output=True, text=True, timeout=120,
    )
    assert run.returncode == 0, run.stderr
    expected = json.loads(run.stdout)
    w = walks.world(layout)
    worst = 0.0
    for (x, z), (ex, ez) in zip(points, expected):
        px, pz = walks.resolve(x, z, w)
        worst = max(worst, abs(px - ex), abs(pz - ez))
    assert worst < 1e-9, worst


# --- checking a walk --------------------------------------------------------


def test_a_walk_is_rounded_and_clamped_and_keeps_nothing_else():
    layout = hall_of()
    known = Known(layout)
    c = layout["cabinets"][0]
    points = centre_walk(layout, 6) + [[c["x"], c["z"]]]  # the last point is inside a cabinet
    # Close enough to the previous point to pass the step check.
    points[-1] = [round(points[-2][0] + 0.3, 3), round(points[-2][1] - 0.3, 3)]
    walk = walks.clean(payload(layout, points, [{"slug": c["slug"], "at": 3}]), known)
    assert set(walk) == {"layout", "points", "visits"}
    w = walks.world(layout)
    for x, z in walk["points"]:
        assert not _inside(x, z, w, walks.RADIUS - 0.01)
    assert walk["visits"] == [{"slug": c["slug"], "at": 3}]
    # Rounded to the grid before the push-out: 0.13 -> 0.25 or 0.
    nudged = walks.clean(payload(layout, [[0.13, p[1] + 0.07] for p in centre_walk(layout, 5)]), known)
    assert all(x in (0.0, 0.25) for x, _ in nudged["points"])


def test_a_long_walk_is_truncated_not_refused():
    layout = hall_of(31)
    known = Known(layout)
    back_and_forth = [[0.0, 3.0 - abs(i % 14 - 7) * 1.0] for i in range(200)]
    visits = [{"slug": layout["cabinets"][i % 5]["slug"], "at": i * 10} for i in range(15)]
    walk = walks.clean(payload(layout, back_and_forth, visits), known)
    assert len(walk["points"]) == walks.MAX_POINTS
    assert len(walk["visits"]) == walks.MAX_VISITS
    assert all(v["at"] < walks.MAX_POINTS for v in walk["visits"])


@pytest.mark.parametrize(
    "change,why",
    [
        (lambda b: "nope", "object"),
        (lambda b: dict(b, ip="1.2.3.4"), "unexpected"),
        (lambda b: dict(b, layout="zz"), "layout"),
        (lambda b: dict(b, layout="0123456789abcdef"), "not a layout"),
        (lambda b: dict(b, dt=0.1), "dt"),
        (lambda b: dict(b, points=b["points"][:2]), "points"),
        (lambda b: dict(b, points=b["points"] + [["1", 2]]), "point"),
        (lambda b: dict(b, points=b["points"] + [[float("nan"), 2]]), "point"),
        (lambda b: dict(b, points=b["points"] + [[True, 2]]), "point"),
        (lambda b: dict(b, points=b["points"] + [[0, 2, 3]]), "point"),
        (lambda b: dict(b, points=[[0, 500]] * 5), "outside"),
        (lambda b: dict(b, points=b["points"][:5] + [[8, b["points"][4][1]]]), "further apart"),
        (lambda b: dict(b, visits=[{"slug": "nope", "at": 1}]), "not in that layout"),
        (lambda b: dict(b, visits=[{"slug": "g01", "at": -1}]), "point index"),
        (lambda b: dict(b, visits=[{"slug": "g01", "at": 1.5}]), "point index"),
        (lambda b: dict(b, visits=[{"slug": "g01", "at": 3}, {"slug": "g02", "at": 2}]), "walking order"),
        (lambda b: dict(b, visits=[{"slug": "g01", "at": 1, "t": 9}]), "visit"),
        (lambda b: dict(b, visits=[{"slug": "g01", "at": 1}] * 41), "too many"),
    ],
)
def test_malformed_or_forged_walks_are_refused(change, why):
    layout = hall_of()
    with pytest.raises(walks.Refused) as e:
        walks.clean(change(payload(layout)), Known(layout))
    assert why in str(e.value)


def test_layouts_remembers_only_the_last_few():
    known = walks.Layouts(size=2)
    keys = [known.remember(hall_of(n)) for n in (3, 4, 5)]
    assert known.get(keys[0]) is None
    assert known.get(keys[1]) is not None and known.get(keys[2]) is not None


# --- keeping them -----------------------------------------------------------


def test_a_day_keeps_a_random_sample_shuffled_and_old_days_go(tmp_path):
    store = walks.Walks(str(tmp_path), per_day=5, keep_days=7, rng=random.Random(1))
    day = datetime.date(2026, 10, 30)
    for i in range(40):
        store.add({"layout": "k", "points": [[i, 0]], "visits": []}, day)
    doc = json.loads((tmp_path / "2026-10-30.json").read_text())
    assert doc["seen"] == 40 and len(doc["walks"]) == 5
    firsts = sorted(w["points"][0][0] for w in doc["walks"])
    assert firsts != [0, 1, 2, 3, 4]  # a sample of the day, not the first five
    assert set(doc) == {"seen", "walks"}
    # Eight days on, the 30th is gone.
    store.add({"layout": "k", "points": [[0, 0]], "visits": []}, day + datetime.timedelta(days=7))
    assert sorted(os.listdir(tmp_path)) == ["2026-11-06.json"]


def test_the_hall_today_needs_k_walks_and_pools_yesterday(tmp_path):
    store = walks.Walks(str(tmp_path), rng=random.Random(2))
    day = datetime.date(2026, 10, 30)
    w = {"layout": "k", "points": [[0, 0]], "visits": []}
    for _ in range(walks.K - 1):
        store.add(w, day)
    assert store.sample(day) == []  # nine visitors: none on show
    store.add(w, day - datetime.timedelta(days=1))
    assert len(store.sample(day)) == walks.K  # today and yesterday together
    for _ in range(30):
        store.add(w, day)
    assert len(store.sample(day)) == walks.SAMPLE
    assert store.clear(day) and store.sample(day) == []


def test_the_rate_limit_forgets_a_client_after_its_window():
    now = [0.0]
    limit = walks.RateLimit(window=600, cap=3, clock=lambda: now[0])
    assert limit.allow("1.2.3.4")
    assert not limit.allow("1.2.3.4")
    assert limit.allow("5.6.7.8")
    assert "1.2.3.4" not in repr(limit._until)  # held as a keyed hash
    now[0] = 601
    assert limit.allow("1.2.3.4") and len(limit) == 1
    assert limit.allow("a") and limit.allow("b") and not limit.allow("c")  # the cap


# --- the endpoints ----------------------------------------------------------


@pytest.fixture
def arcade(tmp_path):
    path = tmp_path / "games.yaml"
    path.write_text(registryText([game("g%02d" % i) for i in range(8)]))
    config = Config(domain=DOMAIN, dataDirectory=str(tmp_path / "data"), registryPath=str(path),
                    landingUrl="https://example.com/play")
    instance = Arcade(config)
    server = makeServer(instance, "127.0.0.1", 0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    instance.port = server.server_address[1]
    instance.data = tmp_path / "data"
    yield instance
    server.shutdown()
    server.server_close()


def request(arcade, method, path, body=None, headers=None):
    connection = http.client.HTTPConnection("127.0.0.1", arcade.port, timeout=10)
    all_headers = {"Host": DOMAIN, "User-Agent": "Mozilla/5.0 (test browser)"}
    all_headers.update(headers or {})
    connection.request(method, path, body=body, headers=all_headers)
    response = connection.getresponse()
    data = response.read()
    connection.close()
    return response, data


def post(arcade, body, client="203.0.113.7"):
    data = body if isinstance(body, bytes) else json.dumps(body).encode()
    return request(arcade, "POST", "/api/walks", data,
                   {"Content-Type": "application/json", "X-Forwarded-For": "10.0.0.1, " + client})


def served_layout(arcade):
    return json.loads(request(arcade, "GET", "/hall/layout.json")[1])


def test_a_walk_is_kept_with_the_day_only(arcade):
    layout = served_layout(arcade)
    slug = layout["cabinets"][1]["slug"]
    response, data = post(arcade, payload(layout, visits=[{"slug": slug, "at": 4}]))
    assert response.status == 202, data
    files = os.listdir(arcade.data / ".hall-walks")
    assert files == [walks.today().isoformat() + ".json"]
    raw = (arcade.data / ".hall-walks" / files[0]).read_text()
    for leak in ("203.0.113", "10.0.0.1", "Mozilla", "test browser"):
        assert leak not in raw
    doc = json.loads(raw)
    assert set(doc) == {"seen", "walks"} and set(doc["walks"][0]) == {"layout", "points", "visits"}


def test_a_walk_naming_the_current_hall_is_kept_without_a_layout_load_first(arcade):
    layout = hall.served_layout([], "off")  # only for the shape; the key comes from the live one
    live = served_layout(arcade)
    arcade.layouts = walks.Layouts()  # as after a restart
    assert post(arcade, payload(live))[0].status == 202
    assert layout["layoutKey"] != live["layoutKey"]


def test_one_walk_per_client_per_window(arcade):
    layout = served_layout(arcade)
    assert post(arcade, payload(layout), client="198.51.100.1")[0].status == 202
    response, data = post(arcade, payload(layout), client="198.51.100.1")
    assert response.status == 429
    assert post(arcade, payload(layout), client="198.51.100.2")[0].status == 202
    # A refused walk costs no turn.
    assert post(arcade, dict(payload(layout), dt=1), client="198.51.100.3")[0].status == 400
    assert post(arcade, payload(layout), client="198.51.100.3")[0].status == 202


def test_bad_walks_get_clear_errors(arcade):
    layout = served_layout(arcade)
    assert post(arcade, b"not json")[0].status == 400
    response, data = post(arcade, dict(payload(layout), layout="0123456789abcdef"))
    assert response.status == 400 and b"layout" in data
    response, _ = post(arcade, b"{" + b" " * walks.MAX_BODY + b"}")
    assert response.status == 413
    assert not (arcade.data / ".hall-walks").exists()


def test_the_hall_today_is_empty_until_k_then_a_capped_sample(arcade):
    layout = served_layout(arcade)
    response, data = request(arcade, "GET", "/api/walks/today")
    assert response.status == 200 and json.loads(data) == {"dt": 0.5, "walks": []}
    assert response.getheader("Cache-Control") == "public, max-age=60"
    for i in range(walks.SAMPLE + 3):
        assert post(arcade, payload(layout), client="192.0.2.%d" % i)[0].status == 202
    doc = json.loads(request(arcade, "GET", "/api/walks/today")[1])
    assert len(doc["walks"]) == walks.SAMPLE
    assert set(doc["walks"][0]) == {"layout", "points", "visits"}


def test_walks_are_only_on_the_api_host(arcade):
    response, _ = request(arcade, "GET", "/api/walks/today", headers={"Host": "g01." + DOMAIN})
    assert response.status == 404


# --- hall-replays.js --------------------------------------------------------


def test_hall_replays_js_under_node_and_its_walk_is_accepted(tmp_path, arcade):
    """tests/browser/hall_replays_test.cjs records a walk the way the page does;
    arcade accepts what it would upload."""
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    a, b = hall_of(31), hall_of(31, reverse=True)
    (tmp_path / "a.json").write_text(json.dumps(a))
    (tmp_path / "b.json").write_text(json.dumps(b))
    out = tmp_path / "walk.json"
    run = subprocess.run(
        [node, os.path.join(ROOT, "tests", "browser", "hall_replays_test.cjs"), str(tmp_path / "a.json"),
         str(tmp_path / "b.json")],
        capture_output=True, text=True, timeout=120, env=dict(os.environ, REPLAY_OUT=str(out)),
    )
    assert run.returncode == 0, run.stdout + run.stderr
    body = json.loads(out.read_text())
    walk = walks.clean(body, Known(a))
    assert len(walk["points"]) == len(body["points"])
