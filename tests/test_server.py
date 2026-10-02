import http.client
import json
import os
import threading
import time

import pytest

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
    allHeaders = {"Host": host}
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


def test_unknown_hosts_are_404_and_still_isolated(arcade):
    for host in ("example.com", "nope." + DOMAIN, "a.b." + DOMAIN, ""):
        response, _ = request(arcade, "GET", host, "/")
        assert response.status == 404
        assertIsolated(response)


def test_the_api_host_redirects_to_the_portal(arcade):
    response, _ = request(arcade, "GET", API, "/")
    assert response.status == 302
    assert response.getheader("Location") == "https://example.com/play"


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


def test_upload_size_cap(arcade):
    response, _ = upload(arcade, body=b"x" * (1024 * 1024 + 1))
    assert response.status == 413


def test_upload_needs_a_content_length(arcade):
    import socket

    sock = socket.create_connection(("127.0.0.1", arcade.port), timeout=10)
    sock.sendall(
        b"PUT /api/games/tidewater/versions/1 HTTP/1.1\r\nHost: %s\r\n"
        b"Authorization: Bearer %s\r\nConnection: close\r\n\r\n" % (API.encode(), TOKEN.encode())
    )
    reply = sock.recv(4096)
    sock.close()
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
    assert [g["slug"] for g in json.loads(data)["games"]] == ["overwinter", "tidewater"]
    assert request(arcade, "GET", API, "/api/games/nope")[0].status == 404
    assert request(arcade, "GET", API, "/api/other")[0].status == 404


def test_registry_changes_are_picked_up_and_bad_ones_ignored(arcade):
    newGame = "newgame." + DOMAIN
    assert request(arcade, "GET", newGame, "/")[0].status == 404
    time.sleep(0.01)
    arcade.registryFile.write_text(registryText([game("tidewater"), game("newgame")]))
    os.utime(str(arcade.registryFile), None)
    response, data = request(arcade, "GET", newGame, "/")
    assert b"not been deployed" in data
    time.sleep(0.01)
    arcade.registryFile.write_text("games:\n  - slug: broken\n")
    os.utime(str(arcade.registryFile), None)
    response, data = request(arcade, "GET", newGame, "/")
    assert b"not been deployed" in data
