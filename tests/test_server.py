import http.client
import json
import os
import threading

import pytest

from arcade import __version__ as arcade_version
from arcade.server import ISOLATION_HEADERS, Arcade, Config, makeServer
from helpers import ASSETS, OTHER_SHA, OTHER_TOKEN, TOKEN, bundleFiles, game, registryText, tarBundle

DOMAIN = "play.example.com"
API = DOMAIN
TIDEWATER = "tidewater." + DOMAIN


class Recorder(object):
    def __init__(self):
        self.events = []

    def report(self, name, tags=None):
        self.events.append((name, tags))


@pytest.fixture
def arcade(tmp_path):
    registryPath = tmp_path / "games.yaml"
    registryPath.write_text(
        registryText(
            [
                game("tidewater", aliases=["tidewater.example.org"]),
                game("overwinter", token_sha256=OTHER_SHA),
                game("rps", kind="static"),
                game("pthreads", kind="static", isolation="on"),
            ]
        )
    )
    config = Config(
        domain=DOMAIN,
        dataDirectory=str(tmp_path / "data"),
        registryPath=str(registryPath),
        landingUrl="https://example.com/play",
        maxUploadBytes=1024 * 1024,
        keep=3,
    )
    instance = Arcade(config, reporter=Recorder())
    server = makeServer(instance, "127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    instance.port = server.server_address[1]
    instance.registryFile = registryPath
    yield instance
    server.shutdown()
    server.server_close()


def request(arcade, method, host, path, body=None, headers=None):
    connection = http.client.HTTPConnection("127.0.0.1", arcade.port, timeout=10)
    # A browser's User-Agent unless a test says otherwise: arcade counts a
    # page load as a play only when a person (not a script) made it.
    allHeaders = {"Host": host, "User-Agent": "Mozilla/5.0 (test browser)"}
    allHeaders.update(headers or {})
    connection.request(method, path, body=body, headers=allHeaders)
    response = connection.getresponse()
    data = response.read()
    connection.close()
    return response, data


def upload(arcade, slug="tidewater", version="1.0.0", token=TOKEN, body=None, query=""):
    body = tarBundle(bundleFiles(version)) if body is None else body
    headers = {"Content-Type": "application/x-tar"}
    if token is not None:
        headers["Authorization"] = "Bearer " + token
    return request(arcade, "PUT", API, "/api/games/%s/versions/%s%s" % (slug, version, query), body, headers)


def assertIsolated(response):
    for name, value in ISOLATION_HEADERS:
        assert response.getheader(name) == value, name


def test_health_on_any_host(arcade):
    response, data = request(arcade, "GET", "localhost:8080", "/healthz")
    assert (response.status, data) == (200, b"ok\n")


def test_the_api_host_reports_the_running_version(arcade):
    for method in ("GET", "HEAD"):
        response, data = request(arcade, method, API, "/version.json")
        assert response.status == 200
        assert response.getheader("Content-Type") == "application/json"
        assert response.getheader("Cache-Control") == "no-store"
        if method == "GET":
            assert json.loads(data) == {"version": arcade_version}
        else:
            assert data == b""


def test_version_json_on_a_game_host_belongs_to_the_game(arcade):
    site = dict(_site("0.1"), **{"version.json": b'{"game": "rps"}'})
    assert upload(arcade, slug="rps", version="0.1", body=tarBundle(site))[0].status == 201
    response, data = request(arcade, "GET", "rps." + DOMAIN, "/version.json")
    assert (response.status, data) == (200, b'{"game": "rps"}')
    upload(arcade)
    for host in (TIDEWATER, "tidewater.example.org", "nope." + DOMAIN, "localhost"):
        assert request(arcade, "GET", host, "/version.json")[0].status == 404, host


def test_unknown_hosts_are_404_and_still_isolated(arcade):
    for host in ("example.com", "nope." + DOMAIN, "a.b." + DOMAIN, ""):
        response, _ = request(arcade, "GET", host, "/")
        assert response.status == 404
        assertIsolated(response)


def test_the_api_host_serves_a_landing_page_listing_every_game(arcade):
    upload(arcade, "tidewater", "1.0.0")
    response, data = request(arcade, "GET", API, "/")
    assert response.status == 200
    assert response.getheader("Content-Type") == "text/html; charset=utf-8"
    page = data.decode("utf-8")
    # A deployed game is linked at its own host; one with nothing deployed is listed, unlinked.
    assert '<a href="https://tidewater.%s/">' % DOMAIN in page
    for slug in ("overwinter", "rps", "pthreads"):
        assert "https://%s.%s/" % (slug, DOMAIN) not in page
    assert page.count("<li>") == 4
    assert "Coming soon" in page
    assert '<a class="browse" href="https://example.com/play">Browse all games' in page
    assert response.getheader("Cache-Control") == "public, max-age=60"
    assert "default-src 'none'" in response.getheader("Content-Security-Policy")


def test_the_landing_page_makes_no_external_requests(arcade):
    _, data = request(arcade, "GET", API, "/index.html")
    page = data.decode("utf-8")
    assert "<script" not in page
    assert "<img" not in page
    assert 'rel="stylesheet"' not in page
    assert "@import" not in page and "url(" not in page
    # Phone-friendly, and both colour schemes.
    assert 'name="viewport"' in page
    assert "prefers-color-scheme: dark" in page


def test_the_landing_page_follows_the_registry(arcade):
    arcade.registryFile.write_text(registryText([game("tidewater"), game("newgame")]))
    os.utime(str(arcade.registryFile), ns=(10**18, 10**18))
    arcade.registry.refresh()
    _, data = request(arcade, "GET", API, "/")
    assert data.decode("utf-8").count("<li>") == 2


def test_head_on_the_landing_page_has_no_body(arcade):
    response, data = request(arcade, "HEAD", API, "/")
    assert response.status == 200
    assert data == b""


def test_redirect_mode_keeps_the_old_302(arcade):
    arcade.config.landingMode = "redirect"
    response, _ = request(arcade, "GET", API, "/")
    assert response.status == 302
    assert response.getheader("Location") == "https://example.com/play"


def test_landing_mode_is_validated():
    with pytest.raises(ValueError):
        Config("d", "/tmp", "/tmp/r", "https://x", landingMode="iframe")
    assert Config.fromEnvironment({}).landingMode == "page"
    assert Config.fromEnvironment({"ARCADE_LANDING_MODE": "Redirect"}).landingMode == "redirect"


def test_a_registered_game_before_any_deploy(arcade):
    response, data = request(arcade, "GET", TIDEWATER, "/")
    assert response.status == 404
    assert b"not been deployed" in data


def test_upload_then_play(arcade):
    response, data = upload(arcade)
    assert response.status == 201, data
    described = json.loads(data)
    assert described["current"] == "1.0.0"
    assert described["url"] == "https://tidewater.play.example.com/"

    for path in ("/", "/play", "/play/", "/index.html"):
        response, data = request(arcade, "GET", TIDEWATER, path)
        assert response.status == 200
        assert response.getheader("Content-Type") == "text/html; charset=utf-8"
        assert b"v1.0.0" in data
        assertIsolated(response)

    response, data = request(arcade, "GET", TIDEWATER, "/web/game.zip")
    assert (response.status, response.getheader("Content-Type")) == (200, "application/zip")
    assert data == bundleFiles("1.0.0")["game.zip"]
    response, data = request(arcade, "GET", TIDEWATER, "/web/version.txt")
    assert data == b"1.0.0\n"

    response, data = request(arcade, "GET", TIDEWATER, "/tak/boot.js")
    assert response.status == 200
    assert response.getheader("Content-Type") == "text/javascript"
    assert data == ASSETS["boot.js"]
    response, _ = request(arcade, "GET", TIDEWATER, "/tak/client.css")
    assert response.getheader("Content-Type") == "text/css"

    for path in ("/tak/", "/tak/../web/game.zip", "/tak/x/boot.js", "/tak/missing.js", "/web/", "/web/index.html", "/secret", "/healthz/x"):
        response, _ = request(arcade, "GET", TIDEWATER, path)
        assert response.status == 404, path
        assertIsolated(response)


def test_an_alias_serves_the_same_game(arcade):
    upload(arcade)
    response, data = request(arcade, "GET", "Tidewater.Example.org:443", "/")
    assert response.status == 200
    assert b"v1.0.0" in data


def test_index_loads_are_reported_per_slug(arcade):
    upload(arcade)
    request(arcade, "GET", TIDEWATER, "/")
    request(arcade, "HEAD", TIDEWATER, "/")
    request(arcade, "GET", TIDEWATER, "/web/game.zip")
    assert arcade.reporter.events == [("page-served", {"slug": "tidewater"})]


def test_etag_revalidation_and_head(arcade):
    upload(arcade)
    response, data = request(arcade, "GET", TIDEWATER, "/web/game.zip")
    etag = response.getheader("ETag")
    assert response.getheader("Cache-Control") == "no-cache"
    response, data = request(arcade, "GET", TIDEWATER, "/web/game.zip", headers={"If-None-Match": etag})
    assert (response.status, data) == (304, b"")
    response, data = request(arcade, "HEAD", TIDEWATER, "/")
    assert response.status == 200 and data == b""
    assert int(response.getheader("Content-Length")) > 0
    upload(arcade, version="1.1.0")
    response, _ = request(arcade, "GET", TIDEWATER, "/web/game.zip", headers={"If-None-Match": etag})
    assert response.status == 200


def test_games_are_read_only(arcade):
    response, _ = request(arcade, "PUT", TIDEWATER, "/", b"x")
    assert response.status == 405


@pytest.mark.parametrize(
    "token, status",
    [(None, 401), ("", 401), ("wrong", 403), (OTHER_TOKEN, 403)],
)
def test_upload_needs_that_games_token(arcade, token, status):
    response, _ = upload(arcade, token=token)
    assert response.status == status
    assert arcade.store.current("tidewater") is None


def test_unknown_slug_looks_like_a_wrong_token(arcade):
    response, _ = upload(arcade, slug="nonexistent")
    assert response.status == 403


def test_each_token_deploys_only_its_own_game(arcade):
    response, _ = upload(arcade, slug="overwinter", token=OTHER_TOKEN)
    assert response.status == 201


def test_upload_validation_errors(arcade):
    response, data = upload(arcade, version="2.0.0", body=tarBundle(bundleFiles("1.0.0")))
    assert response.status == 400 and b"version.txt says" in data
    response, data = upload(arcade, version="..", body=b"x")
    assert response.status in (400, 404)
    response, data = upload(arcade, version="bad%20version", body=b"x")
    assert response.status == 400
    response, data = upload(arcade, body=b"not an archive")
    assert response.status == 400
    assert arcade.store.current("tidewater") is None


def _raw(arcade, head):
    import socket

    sock = socket.create_connection(("127.0.0.1", arcade.port), timeout=10)
    sock.sendall(head)
    reply = sock.recv(4096)
    sock.close()
    return reply


def test_upload_size_cap(arcade):
    # Refused from the declared length alone, before the body is read: only
    # the headers are sent, as a client streaming a huge upload would have.
    reply = _raw(
        arcade,
        b"PUT /api/games/tidewater/versions/1 HTTP/1.1\r\nHost: %s\r\n"
        b"Authorization: Bearer %s\r\nContent-Length: %d\r\n\r\n"
        % (API.encode(), TOKEN.encode(), 1024 * 1024 + 1),
    )
    assert reply.startswith(b"HTTP/1.1 413")


def test_upload_needs_a_content_length(arcade):
    reply = _raw(
        arcade,
        b"PUT /api/games/tidewater/versions/1 HTTP/1.1\r\nHost: %s\r\n"
        b"Authorization: Bearer %s\r\nConnection: close\r\n\r\n" % (API.encode(), TOKEN.encode()),
    )
    assert reply.startswith(b"HTTP/1.1 411")


def test_versions_are_immutable_over_http(arcade):
    assert upload(arcade)[0].status == 201
    response, _ = upload(arcade)
    assert response.status == 409


def test_activate_false_and_rollback(arcade):
    upload(arcade, version="1.0.0")
    upload(arcade, version="2.0.0", query="?activate=false")
    assert request(arcade, "GET", TIDEWATER, "/web/version.txt")[1] == b"1.0.0\n"

    def rollback(body, token=TOKEN):
        return request(
            arcade, "POST", API, "/api/games/tidewater/current", body,
            {"Authorization": "Bearer " + token, "Content-Type": "application/json"},
        )

    response, data = rollback(json.dumps({"version": "2.0.0"}))
    assert response.status == 200 and json.loads(data)["current"] == "2.0.0"
    assert request(arcade, "GET", TIDEWATER, "/web/version.txt")[1] == b"2.0.0\n"
    assert rollback(json.dumps({"version": "9"}))[0].status == 404
    assert rollback("not json")[0].status == 400
    assert rollback(json.dumps({"version": 3}))[0].status == 400
    assert rollback(json.dumps({"version": "1.0.0"}), token="wrong")[0].status == 403


def test_describe_endpoints(arcade):
    upload(arcade)
    response, data = request(arcade, "GET", API, "/api/games/tidewater")
    described = json.loads(data)
    assert described["versions"] == ["1.0.0"]
    assert described["aliases"] == ["tidewater.example.org"]
    assert "token_sha256" not in data.decode() and "tokenSha256" not in data.decode()
    response, data = request(arcade, "GET", API, "/api/games")
    assert [g["slug"] for g in json.loads(data)["games"]] == ["overwinter", "pthreads", "rps", "tidewater"]
    assert request(arcade, "GET", API, "/api/games/nope")[0].status == 404
    assert request(arcade, "GET", API, "/api/other")[0].status == 404


def test_registry_changes_are_picked_up_and_bad_ones_ignored(arcade):
    newGame = "newgame." + DOMAIN
    assert request(arcade, "GET", newGame, "/")[0].status == 404
    # Explicit, distinct mtimes: a coarse filesystem clock must not hide a change.
    stamp = os.stat(str(arcade.registryFile)).st_mtime_ns
    arcade.registryFile.write_text(registryText([game("tidewater"), game("newgame")]))
    os.utime(str(arcade.registryFile), ns=(stamp + 10 ** 9, stamp + 10 ** 9))
    response, data = request(arcade, "GET", newGame, "/")
    assert b"not been deployed" in data
    arcade.registryFile.write_text("games:\n  - slug: broken\n")
    os.utime(str(arcade.registryFile), ns=(stamp + 2 * 10 ** 9, stamp + 2 * 10 ** 9))
    response, data = request(arcade, "GET", newGame, "/")
    assert b"not been deployed" in data


def test_traefik_reads_its_routers_on_the_internal_host_only(arcade):
    response, data = request(arcade, "GET", "arcade:8080", "/traefik/dynamic.json")
    assert response.status == 200
    routersByName = json.loads(data)["http"]["routers"]
    assert routersByName["arcade-tidewater"]["rule"] == "Host(`tidewater.play.example.com`)"
    assert routersByName["arcade-tidewater"]["service"] == "arcade@docker"
    assert "arcade-api" not in routersByName
    assert request(arcade, "GET", "arcade", "/")[0].status == 404
    for host in (API, TIDEWATER, "tidewater.example.org"):
        assert request(arcade, "GET", host, "/traefik/dynamic.json")[0].status == 404


def _site(version):
    return {
        "index.html": ("<html>site %s</html>" % version).encode(),
        "version.txt": (version + "\n").encode(),
        "pkg/game.wasm": b"\0asm",
        "pkg/index.html": b"nested index",
        "rps.apk": b"apk",
        "style.css": b"body{}",
    }


def test_static_game_is_served_as_files_without_isolation(arcade):
    response, data = upload(arcade, slug="rps", version="0.1", body=tarBundle(_site("0.1")))
    assert response.status == 201, data
    assert json.loads(data)["kind"] == "static" and json.loads(data)["isolation"] is False
    host = "rps." + DOMAIN
    response, data = request(arcade, "GET", host, "/")
    assert (response.status, data) == (200, b"<html>site 0.1</html>")
    assert response.getheader("Content-Type") == "text/html; charset=utf-8"
    for name, _ in ISOLATION_HEADERS:
        assert response.getheader(name) is None, name
    response, data = request(arcade, "GET", host, "/pkg/game.wasm")
    assert (response.status, response.getheader("Content-Type"), data) == (200, "application/wasm", b"\0asm")
    assert request(arcade, "GET", host, "/pkg/")[1] == b"nested index"
    assert request(arcade, "GET", host, "/rps.apk")[0].getheader("Content-Type") == "application/octet-stream"
    assert request(arcade, "GET", host, "/style.css")[0].getheader("Content-Type") == "text/css; charset=utf-8"
    for path in ("/missing", "/pkg", "/../version.txt", "/.uploaded", "/pkg/../../x"):
        assert request(arcade, "GET", host, path)[0].status == 404, path
    assert arcade.reporter.events == [("page-served", {"slug": "rps"})]


def test_static_game_with_isolation_on_sends_the_headers(arcade):
    upload(arcade, slug="pthreads", version="1", body=tarBundle(_site("1")))
    assertIsolated(request(arcade, "GET", "pthreads." + DOMAIN, "/")[0])


def test_a_tak_bundle_is_refused_for_a_static_game_and_vice_versa(arcade):
    response, data = upload(arcade, slug="rps", version="1.0.0")  # a tak bundle: no index at top? it has one
    assert response.status == 201  # index.html + version.txt + game.zip is also a valid site
    response, data = upload(arcade, slug="tidewater", version="2", body=tarBundle(_site("2")))
    assert response.status == 400 and b"unexpected file" in data


def test_isolation_is_decided_per_request_on_a_kept_alive_connection(arcade):
    upload(arcade, slug="rps", version="1", body=tarBundle(_site("1")))
    upload(arcade)
    connection = http.client.HTTPConnection("127.0.0.1", arcade.port, timeout=10)
    connection.request("GET", "/", headers={"Host": "rps." + DOMAIN})
    first = connection.getresponse()
    first.read()
    assert first.getheader("Cross-Origin-Embedder-Policy") is None
    connection.request("GET", "/", headers={"Host": TIDEWATER})
    second = connection.getresponse()
    second.read()
    assertIsolated(second)
    # Requests that never reach a game must not inherit the static game's
    # choice either: the API host and an unknown host, each straight after it.
    for host, path in ((API, "/api/games"), ("nope." + DOMAIN, "/")):
        connection.request("GET", "/", headers={"Host": "rps." + DOMAIN})
        connection.getresponse().read()
        connection.request("GET", path, headers={"Host": host})
        response = connection.getresponse()
        response.read()
        assertIsolated(response)
    connection.close()


def test_a_version_named_current_is_refused_and_cannot_break_the_api(arcade):
    response, data = upload(arcade, version="current", body=tarBundle(bundleFiles("current")))
    assert response.status == 400, data
    assert upload(arcade)[0].status == 201
    response, data = request(arcade, "GET", API, "/api/games")
    assert response.status == 200
    assert request(arcade, "GET", TIDEWATER, "/")[0].status == 200


def test_bad_static_trees_get_a_400_not_a_dropped_connection(arcade):
    for extra in ({".uploaded": b"0"}, {"a": b"file", "a/b": b"nested under a file"}):
        files = _site("9")
        files.update(extra)
        response, data = upload(arcade, slug="rps", version="9", body=tarBundle(files))
        assert response.status == 400, (extra, data)
    assert arcade.store.versions("rps") == []


def test_odd_file_names_are_served_with_a_safe_etag(arcade):
    files = _site("1")
    files['we"ird name.txt'] = b"q"
    files["café-☃.txt"] = b"u"
    assert upload(arcade, slug="rps", version="1", body=tarBundle(files))[0].status == 201
    for path in ('/we%22ird%20name.txt', "/caf%C3%A9-%E2%98%83.txt"):
        response, data = request(arcade, "GET", "rps." + DOMAIN, path)
        assert response.status == 200, path
        etag = response.getheader("ETag")
        assert etag.startswith('"') and etag.endswith('"') and '"' not in etag[1:-1]


def test_page_loads_are_counted_bots_are_not_and_the_api_shares_counts(arcade):
    upload(arcade)
    request(arcade, "GET", TIDEWATER, "/", headers={"User-Agent": "Mozilla/5.0 (iPhone) Safari"})
    request(arcade, "GET", TIDEWATER, "/play", headers={"User-Agent": "Mozilla/5.0"})
    request(arcade, "HEAD", TIDEWATER, "/")
    request(arcade, "GET", TIDEWATER, "/web/game.zip")
    for bot in ("Googlebot/2.1", "facebookexternalhit/1.1", "curl/8.5", "Discordbot/2.0", ""):
        request(arcade, "GET", TIDEWATER, "/", headers={"User-Agent": bot})
    response, data = request(arcade, "GET", API, "/api/games/tidewater")
    assert json.loads(data)["plays"] == 2
    assert response.getheader("Access-Control-Allow-Origin") == "*"
    response, data = request(arcade, "GET", API, "/api/games")
    assert {g["slug"]: g["plays"] for g in json.loads(data)["games"]}["tidewater"] == 2
    assert response.getheader("Access-Control-Allow-Origin") == "*"
    # Writes are not opened to other origins.
    response, _ = upload(arcade, version="9.9.9")
    assert response.getheader("Access-Control-Allow-Origin") is None


def test_game_documents_may_be_embedded_by_other_origins():
    # The portal frames games; a cross-origin-isolated parent needs the child's
    # CORP to allow it. Isolation itself (COOP/COEP) is unchanged.
    assert ("Cross-Origin-Resource-Policy", "cross-origin") in ISOLATION_HEADERS
    assert ("Cross-Origin-Embedder-Policy", "require-corp") in ISOLATION_HEADERS


def test_the_traefik_middlewares_are_configurable(tmp_path):
    registryPath = tmp_path / "games.yaml"
    registryPath.write_text(registryText([game("tidewater")]))
    config = Config.fromEnvironment({
        "ARCADE_DOMAIN": DOMAIN, "ARCADE_DATA": str(tmp_path / "d"), "ARCADE_REGISTRY": str(registryPath),
        "ARCADE_TRAEFIK_MIDDLEWARES": "game-headers@file, rate-limit@file",
    })
    instance = Arcade(config)
    server = makeServer(instance, "127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    instance.port = server.server_address[1]
    try:
        _, data = request(instance, "GET", "arcade", "/traefik/dynamic.json")
        assert json.loads(data)["http"]["routers"]["arcade-tidewater"]["middlewares"] == ["game-headers@file", "rate-limit@file"]
    finally:
        server.shutdown()
        server.server_close()
    assert Config.fromEnvironment({}).traefikMiddlewares == ("secure-headers@file",)
