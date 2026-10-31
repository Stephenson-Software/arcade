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


@pytest.mark.parametrize(
    "text, line",
    [
        ("# comment\n\ngames:\n  - slug: tidewater\n    colour: blue\n", 5),
        ("games:\n  - slug: tidewater\n\n\n      title: x\n", 5),
        ('games:\n  - slug: "a\\"b"\n', 2),
        ("game:\n", 1),
    ],
)
def test_parse_errors_name_the_offending_line(text, line):
    with pytest.raises(registry.RegistryError) as error:
        registry.loads(text)
    assert str(error.value).startswith("line %d: " % line)


def test_validation_errors_name_the_entry_line():
    text = registryText([game(), game("other", repo="not-a-repo")])
    with pytest.raises(registry.RegistryError) as error:
        registry.loads(text)
    assert str(error.value).startswith("line 6: ")


@pytest.mark.parametrize("slug", sorted(registry.RESERVED_SLUGS))
def test_every_reserved_slug_is_refused(slug):
    with pytest.raises(registry.RegistryError) as error:
        registry.loads(registryText([game(slug=slug)]))
    assert "slug %r is reserved" % slug in str(error.value)


def test_slug_length_limits():
    assert registry.loads(registryText([game(slug="ab")])).get("ab") is not None
    longest = "a" * 31
    assert registry.loads(registryText([game(slug=longest)])).get(longest) is not None
    for slug in ("a" * 32, "1abc", "ab_c"):
        with pytest.raises(registry.RegistryError) as error:
            registry.loads(registryText([game(slug=slug)]))
        assert "must match" in str(error.value)


def test_escaped_quotes_are_refused():
    with pytest.raises(registry.RegistryError) as error:
        registry.loads('games:\n  - slug: tidewater\n    title: "say \\"hi\\""\n')
    assert "escaped quotes are not supported" in str(error.value)


def test_quoted_values_and_hash_without_a_space_are_kept():
    text = (
        "games:\n"
        "  - slug: 'tidewater'\n"
        "    title: C#-ish # trailing comment\n"
        "    repo: Stephenson-Software/Tidewater\n"
        "    token_sha256: '%s'\n"
        "    aliases: []\n" % TOKEN_SHA
    )
    tidewater = registry.loads(text).get("tidewater")
    assert tidewater.title == "C#-ish"
    assert tidewater.tokenSha256 == TOKEN_SHA
    assert tidewater.aliases == ()


@pytest.mark.parametrize("value, expected", [("ON", True), ("True", True), ("Yes", True), ("OFF", False)])
def test_isolation_switch_is_case_insensitive(value, expected):
    loaded = registry.loads(registryText([game(kind="static", isolation=value)]))
    assert loaded.get("tidewater").isolation is expected


def test_an_alias_repeated_within_one_entry_is_refused():
    with pytest.raises(registry.RegistryError) as error:
        registry.loads(registryText([game(aliases=["a.example.org", "A.example.org"])]))
    assert "alias 'a.example.org' is already claimed by 'tidewater'" in str(error.value)


def test_aliases_under_the_domain_are_only_refused_when_a_domain_is_given():
    text = registryText([game(aliases=["x.play.example.com"])])
    assert registry.loads(text).forAlias("x.play.example.com").slug == "tidewater"
    with pytest.raises(registry.RegistryError):
        registry.loads(text, domain=DOMAIN)


def test_lookups_of_unknown_slugs_and_hosts_return_none():
    loaded = registry.loads(registryText([game(aliases=["a.example.org"])]))
    assert loaded.get("missing") is None
    assert loaded.forAlias("b.example.org") is None
    assert len(loaded) == 1


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


def test_canonical_is_optional_and_kept():
    loaded = registry.loads(
        registryText([game(), game("ferry", canonical="https://example.com/play/night-ferry")]), domain=DOMAIN
    )
    assert loaded.get("tidewater").canonical is None
    assert loaded.get("ferry").canonical == "https://example.com/play/night-ferry"


@pytest.mark.parametrize(
    "value",
    ["http://example.com/play/x", "example.com/play/x", "https://example.com/a b", 'https://example.com/"x', "https://"],
)
def test_a_canonical_that_is_not_a_plain_https_url_is_refused(value):
    with pytest.raises(registry.RegistryError) as error:
        registry.loads(registryText([game(canonical=value)]), domain=DOMAIN)
    assert "must be an https URL" in str(error.value)


def test_added_is_an_optional_day():
    loaded = registry.loads(registryText([game("tidewater", added="2026-10-24"), game("cave")]))
    assert loaded.get("tidewater").added.isoformat() == "2026-10-24"
    assert loaded.get("cave").added is None


@pytest.mark.parametrize("bad", ["2026-13-01", "2026-02-30", "26-10-24", "2026-10-24T00:00:00Z", "yesterday"])
def test_added_must_be_a_real_day(bad):
    with pytest.raises(registry.RegistryError, match="line 2: added for 'tidewater' must be a date"):
        registry.loads(registryText([game("tidewater", added=bad)]))


def test_the_registry_module_is_self_contained():
    # arcade-social vendors registry.py byte for byte, where there is no arcade
    # package: it may import only the standard library.
    import ast
    import os

    with open(os.path.join(os.path.dirname(registry.__file__), "registry.py"), encoding="utf-8") as f:
        tree = ast.parse(f.read())
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            assert node.module and not node.module.startswith("arcade"), node.module
        if isinstance(node, ast.Import):
            assert all(not alias.name.startswith("arcade") for alias in node.names)
