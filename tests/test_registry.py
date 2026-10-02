import pytest

from arcade import registry
from helpers import TOKEN_SHA, game, registryText

DOMAIN = "play.example.com"


def test_parses_a_full_entry_with_comments_and_aliases():
    text = (
        "# hosted games\n"
        "games:\n"
        "  - slug: tidewater   # the first\n"
        '    title: "Tidewater # not a comment"\n'
        "    repo: Stephenson-Software/Tidewater\n"
        "    owner: dmccoystephenson\n"
        '    token_sha256: "%s"\n'
        "    aliases: [Tidewater.Example.org, old.example.net]\n"
        "\n"
        "  - slug: overwinter\n"
        "    title: Overwinter\n"
        "    repo: Stephenson-Software/Overwinter\n"
        "    token_sha256: %s\n" % (TOKEN_SHA, TOKEN_SHA)
    )
    loaded = registry.loads(text, domain=DOMAIN)
    assert [g.slug for g in loaded] == ["overwinter", "tidewater"]
    tidewater = loaded.get("tidewater")
    assert tidewater.title == "Tidewater # not a comment"
    assert tidewater.owner == "dmccoystephenson"
    assert tidewater.aliases == ("tidewater.example.org", "old.example.net")
    assert loaded.forAlias("old.example.net") is tidewater
    assert loaded.get("overwinter").aliases == ()


def test_an_empty_registry():
    assert len(registry.loads("games: []\n")) == 0
    assert len(registry.loads("games:\n")) == 0


@pytest.mark.parametrize(
    "text, message",
    [
        ("", "empty"),
        ("game:\n", "must start with 'games:'"),
        ("games: []\n  - slug: x\n", "content after"),
        ("games:\n    slug: x\n", "outside any"),
        ("games:\n  - slug: tidewater\n      title: x\n", "unexpected indentation"),
        ("games:\n\t- slug: x\n", "tabs"),
        ("games:\n  - slug tidewater\n", "expected 'key: value'"),
        ("games:\n  - slug: tidewater\n    colour: blue\n", "unknown key 'colour'"),
        ("games:\n  - slug: a\n    slug: b\n", "given twice"),
        ('games:\n  - slug: "tidewater\n', "unterminated"),
        ("games:\n  - slug: tidewater\n    aliases: a.example.org\n", "flow, list"),
        ("games:\n  - slug: {x: 1}\n", "unsupported value"),
        ("games:\n  - slug:\n", "a value is required"),
    ],
)
def test_malformed_text_is_refused_with_its_line(text, message):
    with pytest.raises(registry.RegistryError) as error:
        registry.loads(text)
    assert message in str(error.value)


@pytest.mark.parametrize(
    "entries, message",
    [
        ([{"slug": "tidewater", "title": "T", "repo": "a/b"}], "missing token_sha256"),
        ([game(slug="Tidewater")], "must match"),
        ([game(slug="a")], "must match"),
        ([game(slug="play")], "reserved"),
        ([game(), game()], "already registered on line 2"),
        ([game(token_sha256="abc")], "64 lowercase hex"),
        ([game(token_sha256=TOKEN_SHA.upper())], "64 lowercase hex"),
        ([game(repo="not-a-repo")], "owner/name"),
        ([game(aliases=["not a host"])], "not a hostname"),
        ([game(aliases=["x.play.example.com"])], "where slugs live"),
        ([game(aliases=["play.example.com"])], "where slugs live"),
        ([game(aliases=["a.example.org"]), game(slug="other", aliases=["a.example.org"])], "already claimed"),
    ],
)
def test_invalid_entries_are_refused(entries, message):
    with pytest.raises(registry.RegistryError) as error:
        registry.loads(registryText(entries), domain=DOMAIN)
    assert message in str(error.value)


def test_load_reads_a_file(tmp_path):
    path = tmp_path / "games.yaml"
    path.write_text(registryText([game()]))
    assert registry.load(str(path)).get("tidewater").repo == "Stephenson-Software/Tidewater"


def test_kind_and_isolation_defaults_and_overrides():
    text = registryText(
        [
            game("tidewater"),
            game("rps", kind="static"),
            game("emscripten", kind="static", isolation="on"),
            game("explicit", kind="tak", isolation="yes"),
        ]
    )
    loaded = registry.loads(text)
    assert (loaded.get("tidewater").kind, loaded.get("tidewater").isolation) == ("tak", True)
    assert (loaded.get("rps").kind, loaded.get("rps").isolation) == ("static", False)
    assert loaded.get("emscripten").isolation is True
    assert loaded.get("explicit").isolation is True


@pytest.mark.parametrize(
    "extra, message",
    [
        ({"kind": "flash"}, "must be one of tak, static"),
        ({"isolation": "maybe"}, "must be on or off"),
        ({"isolation": "off"}, "needs isolation"),
        ({"kind": "tak", "isolation": "no"}, "needs isolation"),
    ],
)
def test_bad_kind_or_isolation_is_refused(extra, message):
    with pytest.raises(registry.RegistryError) as error:
        registry.loads(registryText([game(**extra)]))
    assert message in str(error.value)
