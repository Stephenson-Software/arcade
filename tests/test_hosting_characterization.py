"""Characterization tests for the hosting core (written against the code
before the ports-and-adapters refactor, and kept green through it).

They pin the API's exact status codes and error texts, the fields `describe`
returns, which page loads count as plays, and which hosts name which game.
"""

import json
import socket

import pytest

from helpers import OTHER_TOKEN, TOKEN, bundleFiles, tarBundle
from test_server import API, DOMAIN, arcade, plays, request, upload, waitFor  # noqa: F401 (fixture)


def body(data):
    return json.loads(data)


def rollback(arcade, slug, payload, token=TOKEN):
    headers = {"Content-Type": "application/json"}
    if token is not None:
        headers["Authorization"] = "Bearer " + token
    data = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
    return request(arcade, "POST", API, "/api/games/%s/current" % slug, data, headers)


# --- authorise ------------------------------------------------------------


@pytest.mark.parametrize("token", [None, "", "   "])
def test_upload_without_a_bearer_token_is_401(arcade, token):
    headers = {} if token is None else {"Authorization": "Bearer " + token}
    response, data = request(arcade, "PUT", API, "/api/games/tidewater/versions/1.0.0", b"x", headers)
    assert response.status == 401
    assert body(data) == {"error": "an Authorization: Bearer <token> header is required"}


def test_upload_with_another_games_token_is_403(arcade):
    response, data = upload(arcade, slug="tidewater", token=OTHER_TOKEN)
    assert response.status == 403
    assert body(data) == {"error": "this token cannot deploy that game"}


def test_upload_to_an_unknown_slug_is_403(arcade):
    response, data = upload(arcade, slug="nosuch")
    assert response.status == 403
    assert body(data) == {"error": "this token cannot deploy that game"}


# --- upload ---------------------------------------------------------------


def test_upload_with_a_bad_version_is_400(arcade):
    response, data = upload(arcade, version="current")
    assert response.status == 400
    assert body(data) == {"error": "bad version 'current'"}


def test_upload_of_a_broken_bundle_is_400_with_the_bundle_error(arcade):
    response, data = upload(arcade, body=b"this is not an archive")
    assert response.status == 400
    assert set(body(data)) == {"error"}
    assert body(data)["error"]


def test_upload_twice_is_409(arcade):
    assert upload(arcade)[0].status == 201
    response, data = upload(arcade)
    assert response.status == 409
    assert body(data) == {"error": "version 1.0.0 already exists; versions are immutable"}


def test_upload_over_the_cap_is_413_with_its_message(arcade):
    # Only the headers are sent; the server refuses from the declared length
    # and closes the connection, so read until it does.
    sock = socket.create_connection(("127.0.0.1", arcade.port), timeout=10)
    sock.sendall(
        b"PUT /api/games/tidewater/versions/1 HTTP/1.1\r\nHost: %s\r\n"
        b"Authorization: Bearer %s\r\nContent-Length: %d\r\n\r\n"
        % (API.encode(), TOKEN.encode(), arcade.config.maxUploadBytes + 1)
    )
    reply = b""
    while True:
        chunk = sock.recv(4096)
        if not chunk:
            break
        reply += chunk
    sock.close()
    assert reply.startswith(b"HTTP/1.1 413")
    assert body(reply.split(b"\r\n\r\n", 1)[1]) == {
        "error": "uploads are capped at %d bytes" % arcade.config.maxUploadBytes
    }


def test_upload_answers_201_with_the_full_description(arcade):
    response, data = upload(arcade)
    assert response.status == 201
    assert body(data) == {
        "slug": "tidewater",
        "title": "Tidewater",
        "repo": "Stephenson-Software/Tidewater",
        "url": "https://tidewater.%s/" % DOMAIN,
        "aliases": ["tidewater.example.org"],
        "kind": "tak",
        "isolation": True,
        "current": "1.0.0",
        "versions": ["1.0.0"],
        "plays": 0,
        "added": body(data)["added"],
        "tags": [],
        "org": body(data)["org"],
        "engine": body(data)["engine"],
        "featured": None,
        "notes": None,
    }
    assert body(data)["added"].endswith("Z")


def test_upload_with_activate_false_keeps_nothing_current(arcade):
    response, data = upload(arcade, query="?activate=false")
    assert response.status == 201
    assert body(data)["current"] is None
    assert body(data)["versions"] == ["1.0.0"]


def test_the_registry_added_day_wins_over_the_first_upload(arcade):
    upload(arcade, slug="overwinter", token=OTHER_TOKEN)
    data = request(arcade, "GET", API, "/api/games/overwinter")[1]
    assert body(data)["added"] == "2026-10-01T00:00:00Z"


# --- rollback -------------------------------------------------------------


def test_rollback_to_a_missing_version_is_404(arcade):
    upload(arcade)
    response, data = rollback(arcade, "tidewater", {"version": "9.9.9"})
    assert response.status == 404
    assert body(data) == {"error": "version '9.9.9' is not on disk"}


def test_rollback_with_a_large_body_is_413(arcade):
    response, data = rollback(arcade, "tidewater", b" " * 4097)
    assert response.status == 413
    assert body(data) == {"error": "body too large"}


@pytest.mark.parametrize("payload", [b"[]", b"{}", b'{"version": 3}', b"not json"])
def test_rollback_with_a_bad_body_is_400(arcade, payload):
    response, data = rollback(arcade, "tidewater", payload)
    assert response.status == 400
    assert body(data) == {"error": 'expected a JSON body {"version": "<version>"}'}


def test_rollback_moves_current_and_answers_the_description(arcade):
    upload(arcade, version="1.0.0")
    upload(arcade, version="1.1.0")
    response, data = rollback(arcade, "tidewater", {"version": "1.0.0"})
    assert response.status == 200
    assert body(data)["current"] == "1.0.0"
    assert body(data)["versions"] == ["1.0.0", "1.1.0"]


# --- hosts ----------------------------------------------------------------


@pytest.mark.parametrize(
    "host",
    ["nosuch." + DOMAIN, "a.tidewater." + DOMAIN, "elsewhere.example.org", "tidewater.example.org.evil"],
)
def test_hosts_that_name_no_game_are_404(arcade, host):
    response, data = request(arcade, "GET", host, "/")
    assert (response.status, data) == (404, b"No game is served at this address.\n")


def test_an_alias_serves_its_game(arcade):
    upload(arcade)
    response, data = request(arcade, "GET", "tidewater.example.org", "/")
    assert response.status == 200
    assert b"v1.0.0" in data


def test_an_undeployed_game_says_so(arcade):
    response, data = request(arcade, "GET", "tidewater." + DOMAIN, "/")
    assert (response.status, data) == (404, b"Tidewater has not been deployed yet.\n")


def test_writes_to_a_game_host_are_405(arcade):
    response, data = request(arcade, "PUT", "tidewater." + DOMAIN, "/", b"")
    assert response.status == 405
    assert data == ("Games are read-only; uploads go to https://%s/api/\n" % DOMAIN).encode()


# --- plays ----------------------------------------------------------------


@pytest.mark.parametrize("agent", ["", "Googlebot/2.1", "curl/8.0", "Mozilla/5.0 arcade-watch"])
def test_scripts_and_crawlers_are_not_plays(arcade, agent):
    upload(arcade)
    request(arcade, "GET", "tidewater." + DOMAIN, "/", headers={"User-Agent": agent})
    assert plays(arcade, 0) == 0
    assert arcade.reporter.events == []


def test_one_visitor_counts_once_a_day(arcade):
    upload(arcade)
    for _ in range(3):
        request(arcade, "GET", "tidewater." + DOMAIN, "/")
    assert plays(arcade, 1) == 1
    assert waitFor(lambda: arcade.reporter.events) == [("page-served", {"slug": "tidewater"})]


def test_a_head_request_is_not_a_play(arcade):
    upload(arcade)
    request(arcade, "HEAD", "tidewater." + DOMAIN, "/")
    assert plays(arcade, 0) == 0
