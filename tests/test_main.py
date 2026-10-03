import io
import json

import pytest

from arcade import __main__ as cli
from arcade import __version__
from helpers import game, registryText

DOMAIN = "play.example.com"


class FakeServer(object):
    def __init__(self, arcade, host, port):
        self.arcade = arcade
        self.host = host
        self.port = port
        self.served = False

    def serve_forever(self):
        self.served = True


class FakeReporter(object):
    enabled = True

    def __init__(self):
        self.events = []
        self.closed = False

    def report(self, name, tags=None):
        self.events.append((name, tags))

    def close(self):
        self.closed = True


@pytest.fixture
def servers(monkeypatch):
    made = []

    def makeServer(arcade, host, port):
        made.append(FakeServer(arcade, host, port))
        return made[-1]

    monkeypatch.setattr(cli, "makeServer", makeServer)
    return made


@pytest.fixture
def serveEnvironment(tmp_path, monkeypatch):
    registryPath = tmp_path / "games.yaml"
    registryPath.write_text(registryText([game("tidewater")]))
    monkeypatch.setenv("ARCADE_DOMAIN", DOMAIN)
    monkeypatch.setenv("ARCADE_DATA", str(tmp_path / "data"))
    monkeypatch.setenv("ARCADE_REGISTRY", str(registryPath))
    monkeypatch.setenv("ARCADE_HOST", "127.0.0.1")
    monkeypatch.setenv("ARCADE_PORT", "9123")
    return registryPath


def test_version_flag_prints_the_package_version(capsys):
    with pytest.raises(SystemExit) as exit:
        cli.main(["--version"])
    assert exit.value.code == 0
    assert capsys.readouterr().out.strip() == "arcade " + __version__


def test_a_subcommand_is_required(capsys):
    with pytest.raises(SystemExit) as exit:
        cli.main([])
    assert exit.value.code == 2
    assert "usage: arcade" in capsys.readouterr().err


def test_routers_prints_the_document_for_every_host(tmp_path, capsys):
    games = tmp_path / "games.yaml"
    games.write_text(registryText([game("tidewater")]))
    assert cli.main(["routers", "--registry", str(games), "--domain", DOMAIN]) == 0
    out = capsys.readouterr().out
    assert out.startswith("# GENERATED")
    body = "\n".join(line for line in out.splitlines() if not line.startswith("#"))
    assert sorted(json.loads(body)["http"]["routers"]) == ["arcade-api", "arcade-tidewater"]


def test_routers_check_reports_a_match_on_stdout(tmp_path, capsys):
    games = tmp_path / "games.yaml"
    games.write_text(registryText([game("tidewater")]))
    out = tmp_path / "arcade.yml"
    cli.main(["routers", "--registry", str(games), "--domain", DOMAIN])
    out.write_text(capsys.readouterr().out)
    assert cli.main(["routers", "--registry", str(games), "--domain", DOMAIN, "--check", str(out)]) == 0
    assert capsys.readouterr().out.strip() == "%s matches %s" % (out, games)


def test_check_registry_counts_the_games(tmp_path, capsys):
    games = tmp_path / "games.yaml"
    games.write_text(registryText([game("tidewater"), game("overwinter")]))
    assert cli.main(["check-registry", str(games)]) == 0
    assert capsys.readouterr().out.strip() == "%s: 2 game(s) OK" % games


@pytest.mark.parametrize("command", ["routers", "hosts"])
def test_an_invalid_registry_is_reported_without_a_traceback(tmp_path, capsys, command):
    games = tmp_path / "games.yaml"
    games.write_text(registryText([game("tidewater"), game("tidewater")]))
    assert cli.main([command, "--registry", str(games), "--domain", DOMAIN]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.startswith("arcade: ")
    assert "Traceback" not in captured.err


def test_check_registry_refuses_an_alias_under_the_given_domain(tmp_path, capsys):
    games = tmp_path / "games.yaml"
    games.write_text(registryText([game("tidewater", aliases=["old.play.example.com"])]))
    assert cli.main(["check-registry", str(games)]) == 0
    capsys.readouterr()
    assert cli.main(["check-registry", str(games), "--domain", DOMAIN]) == 1
    assert capsys.readouterr().err.startswith("arcade: ")


def test_hash_token_strips_surrounding_whitespace(monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin", io.StringIO("  abc  \n"))
    assert cli.main(["hash-token"]) == 0
    assert capsys.readouterr().out.strip() == cli.hashToken("abc")
    monkeypatch.setattr("sys.stdin", io.StringIO("   \n"))
    assert cli.main(["hash-token"]) == 2
    assert "no token on stdin" in capsys.readouterr().err


def test_no_trace_key_means_no_reporter(monkeypatch):
    monkeypatch.delenv("ARCADE_TRACE_KEY", raising=False)
    assert cli._reporter() is None
    monkeypatch.setenv("ARCADE_TRACE_KEY", "   ")
    assert cli._reporter() is None


def test_a_trace_key_builds_a_client_for_the_configured_program(monkeypatch):
    # DO_NOT_TRACK keeps the client from starting its sender thread, so nothing reaches the network.
    monkeypatch.setenv("DO_NOT_TRACK", "1")
    monkeypatch.setenv("ARCADE_TRACE_KEY", " a-key ")
    monkeypatch.setenv("ARCADE_TRACE_URL", "https://trace.example.org/")
    monkeypatch.setenv("ARCADE_TRACE_PROGRAM", "arcade-test")
    reporter = cli._reporter()
    assert reporter._endpoint == "https://trace.example.org/api/metrics"
    assert reporter._application == "arcade-test"
    assert reporter._version == __version__
    assert reporter._key == "a-key"
    assert not reporter.enabled
    assert reporter.disabled_reason == "environment"


def test_the_trace_endpoint_and_program_default_to_the_documented_ones(monkeypatch):
    monkeypatch.setenv("DO_NOT_TRACK", "1")
    monkeypatch.setenv("ARCADE_TRACE_KEY", "a-key")
    monkeypatch.delenv("ARCADE_TRACE_URL", raising=False)
    monkeypatch.delenv("ARCADE_TRACE_PROGRAM", raising=False)
    reporter = cli._reporter()
    assert reporter._endpoint == "https://trace.danielstephenson.dev/api/metrics"
    assert reporter._application == "arcade"


def test_serve_reads_its_address_from_the_environment(serveEnvironment, servers, monkeypatch, capsys):
    monkeypatch.setattr(cli, "_reporter", lambda: None)
    assert cli.main(["serve"]) == 0
    (server,) = servers
    assert (server.host, server.port, server.served) == ("127.0.0.1", 9123, True)
    assert server.arcade.config.domain == DOMAIN
    assert server.arcade.reporter is None
    err = capsys.readouterr().err
    assert "arcade %s serving *.%s on 127.0.0.1:9123" % (__version__, DOMAIN) in err
    assert "trace off" in err


def test_serve_reports_startup_and_closes_the_reporter(serveEnvironment, servers, monkeypatch, capsys):
    reporter = FakeReporter()
    monkeypatch.setattr(cli, "_reporter", lambda: reporter)
    assert cli.main(["serve"]) == 0
    assert servers[0].arcade.reporter is reporter
    assert reporter.events == [("startup", None)]
    assert reporter.closed
    assert "trace on" in capsys.readouterr().err


def test_serve_refuses_an_invalid_registry_before_binding(serveEnvironment, servers, monkeypatch, capsys):
    serveEnvironment.write_text("games:\n  - slug: x\n")
    monkeypatch.setattr(cli, "_reporter", lambda: None)
    assert cli.main(["serve"]) == 1
    assert servers == []
    assert capsys.readouterr().err.startswith("arcade: ")
