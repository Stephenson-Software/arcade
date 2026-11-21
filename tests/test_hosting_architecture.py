"""Architecture tests for arcade.hosting: dependencies point inward, and each
port or adapter file holds exactly one class."""

import ast
import pathlib

import pytest

HOSTING = pathlib.Path(__file__).resolve().parent.parent / "src" / "arcade" / "hosting"
INNER = [HOSTING / "model.py", HOSTING / "core.py"] + sorted((HOSTING / "ports").glob("*.py"))
# Inner layers may not reach the outer layers, nor the modules that do I/O
# for them (those are adapters, wired in by the service).
FORBIDDEN = (
    "arcade.hosting.adapters",
    "arcade.hosting.service",
    "arcade.server",
    "arcade.__main__",
    "arcade.remote",
    "arcade.trace_client",
)


def imports(source):
    found = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            found += [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.append(node.module)
            found += ["%s.%s" % (node.module, alias.name) for alias in node.names]
    return found


def violations(source):
    return sorted({name for name in imports(source) if name.startswith(FORBIDDEN)})


def classes(source):
    return [node.name for node in ast.parse(source).body if isinstance(node, ast.ClassDef)]


@pytest.mark.parametrize("path", INNER, ids=lambda p: p.relative_to(HOSTING).as_posix())
def test_inner_layers_never_import_outer_ones(path):
    assert violations(path.read_text()) == []


@pytest.mark.parametrize(
    "path",
    [p for p in sorted((HOSTING / "ports").glob("*.py")) + sorted((HOSTING / "adapters").glob("*.py"))
     if p.name != "__init__.py"],
    ids=lambda p: p.relative_to(HOSTING).as_posix(),
)
def test_one_class_per_port_or_adapter_file(path):
    assert len(classes(path.read_text())) == 1


def test_the_checks_can_fail():
    # A checker that cannot see a violation passes it.
    assert violations("from arcade.hosting.adapters import NullReporter\nimport arcade.server\n") == [
        "arcade.hosting.adapters",
        "arcade.hosting.adapters.NullReporter",
        "arcade.server",
    ]
    assert violations("from arcade.hosting import adapters\n") == ["arcade.hosting.adapters"]
    assert len(classes("class A(object):\n    pass\n\n\nclass B(object):\n    pass\n")) == 2
