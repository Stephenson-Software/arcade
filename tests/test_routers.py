import json

from arcade import __main__ as cli
from arcade import registry, routers
from helpers import TOKEN, TOKEN_SHA, game, registryText

DOMAIN = "play.example.com"


def _registry():
    return registry.loads(
        registryText([game("tidewater", aliases=["tidewater.example.org"]), game("overwinter")]),
        domain=DOMAIN,
    )


def test_one_router_per_host_in_a_stable_order():
    assert routers.hosts(_registry(), DOMAIN) == [
        ("arcade-api", "play.example.com"),
        ("arcade-overwinter", "overwinter.play.example.com"),
        ("arcade-tidewater", "tidewater.play.example.com"),
        ("arcade-tidewater-alias-1", "tidewater.example.org"),
    ]


def test_each_router_gets_its_own_certificate_and_the_shared_service():
    generated = routers.generate(_registry(), DOMAIN)
    alias = generated["http"]["routers"]["arcade-tidewater-alias-1"]
    assert alias == {
        "rule": "Host(`tidewater.example.org`)",
        "entryPoints": ["websecure"],
        "service": "arcade@docker",
        "middlewares": ["secure-headers@file"],
        "tls": {"certResolver": "letsencrypt"},
    }


def test_render_is_a_commented_json_document():
    text = routers.render(_registry(), DOMAIN)
    assert text.startswith("# GENERATED")
    body = "\n".join(line for line in text.splitlines() if not line.startswith("#"))
    assert len(json.loads(body)["http"]["routers"]) == 4
    assert text == routers.render(_registry(), DOMAIN)


def test_cli_check_passes_when_fresh_and_fails_when_stale(tmp_path, capsys):
    games = tmp_path / "games.yaml"
    games.write_text(registryText([game("tidewater")]))
    out = tmp_path / "arcade.yml"
    assert cli.main(["routers", "--registry", str(games), "--domain", DOMAIN]) == 0
    out.write_text(capsys.readouterr().out)
    assert cli.main(["routers", "--registry", str(games), "--domain", DOMAIN, "--check", str(out)]) == 0
    games.write_text(registryText([game("tidewater"), game("overwinter")]))
    assert cli.main(["routers", "--registry", str(games), "--domain", DOMAIN, "--check", str(out)]) == 1
    assert "is stale" in capsys.readouterr().err
    assert cli.main(["routers", "--registry", str(games), "--check", str(tmp_path / "none.yml")]) == 1


def test_cli_hosts_check_registry_and_hash_token(tmp_path, capsys, monkeypatch):
    games = tmp_path / "games.yaml"
    games.write_text(registryText([game("tidewater")]))
    assert cli.main(["hosts", "--registry", str(games), "--domain", DOMAIN]) == 0
    assert capsys.readouterr().out.split() == ["play.example.com", "tidewater.play.example.com"]
    assert cli.main(["check-registry", str(games)]) == 0
    games.write_text("games:\n  - slug: x\n")
    assert cli.main(["check-registry", str(games)]) == 1
    monkeypatch.setattr("sys.stdin", __import__("io").StringIO(TOKEN + "\n"))
    capsys.readouterr()
    assert cli.main(["hash-token"]) == 0
    assert capsys.readouterr().out.strip() == TOKEN_SHA
    monkeypatch.setattr("sys.stdin", __import__("io").StringIO(""))
    assert cli.main(["hash-token"]) == 2


def test_the_provider_document_leaves_the_api_host_to_compose():
    document = routers.providerDocument(_registry(), DOMAIN, service="arcade@file")
    names = sorted(document["http"]["routers"])
    assert names == ["arcade-overwinter", "arcade-tidewater", "arcade-tidewater-alias-1"]
    assert {r["service"] for r in document["http"]["routers"].values()} == {"arcade@file"}
    assert routers.providerDocument(registry.loads("games: []\n"), DOMAIN) == {}


def test_cli_hosts_games_only(tmp_path, capsys):
    games = tmp_path / "games.yaml"
    games.write_text(registryText([game("tidewater", aliases=["t.example.org"])]))
    assert cli.main(["hosts", "--registry", str(games), "--domain", DOMAIN, "--games-only"]) == 0
    assert capsys.readouterr().out.split() == ["tidewater.play.example.com", "t.example.org"]
