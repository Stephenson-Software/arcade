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


def test_every_alias_gets_its_own_numbered_router_in_registry_order():
    loaded = registry.loads(
        registryText([game("tidewater", aliases=["b.example.org", "a.example.org", "c.example.net"])]),
        domain=DOMAIN,
    )
    assert routers.hosts(loaded, DOMAIN, includeApi=False) == [
        ("arcade-tidewater", "tidewater.play.example.com"),
        ("arcade-tidewater-alias-1", "b.example.org"),
        ("arcade-tidewater-alias-2", "a.example.org"),
        ("arcade-tidewater-alias-3", "c.example.net"),
    ]


def test_an_empty_registry_still_has_the_api_host():
    empty = registry.loads("games: []\n")
    assert routers.hosts(empty, DOMAIN) == [("arcade-api", "play.example.com")]
    assert routers.hosts(empty, DOMAIN, includeApi=False) == []
    assert routers.generate(empty, DOMAIN, includeApi=False) == {"http": {"routers": {}}}


def test_overrides_replace_each_router_setting():
    generated = routers.generate(
        _registry(),
        DOMAIN,
        service="arcade@file",
        entryPoint="https",
        certResolver="staging",
        middlewares=("game-headers@file", "rate-limit@file"),
    )
    assert generated["http"]["routers"]["arcade-api"] == {
        "rule": "Host(`play.example.com`)",
        "entryPoints": ["https"],
        "service": "arcade@file",
        "middlewares": ["game-headers@file", "rate-limit@file"],
        "tls": {"certResolver": "staging"},
    }


def test_overrides_leave_the_defaults_alone():
    routers.generate(_registry(), DOMAIN, service="arcade@file", middlewares=())
    assert routers.DEFAULTS == {
        "service": "arcade@docker",
        "entryPoint": "websecure",
        "certResolver": "letsencrypt",
        "middlewares": ("secure-headers@file",),
    }
    generated = routers.generate(_registry(), DOMAIN)
    assert generated["http"]["routers"]["arcade-overwinter"]["service"] == "arcade@docker"


def test_routers_do_not_share_their_lists():
    generated = routers.generate(_registry(), DOMAIN)
    generated["http"]["routers"]["arcade-api"]["middlewares"].append("extra@file")
    generated["http"]["routers"]["arcade-api"]["entryPoints"].append("web")
    tidewater = generated["http"]["routers"]["arcade-tidewater"]
    assert tidewater["middlewares"] == ["secure-headers@file"]
    assert tidewater["entryPoints"] == ["websecure"]


def test_render_includes_the_api_host_with_sorted_keys_and_a_trailing_newline():
    text = routers.render(_registry(), DOMAIN, certResolver="staging")
    assert text.startswith(routers.HEADER)
    assert text.endswith("}\n")
    document = json.loads(text[len(routers.HEADER) :])
    assert document == routers.generate(_registry(), DOMAIN, certResolver="staging")
    assert list(document["http"]["routers"]) == sorted(document["http"]["routers"])
    assert document["http"]["routers"]["arcade-api"]["tls"] == {"certResolver": "staging"}


def test_render_of_an_empty_registry_keeps_the_api_router():
    text = routers.render(registry.loads("games: []\n"), DOMAIN)
    assert list(json.loads(text[len(routers.HEADER) :])["http"]["routers"]) == ["arcade-api"]
