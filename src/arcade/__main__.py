# @author Daniel McCoy Stephenson
"""Command line: serve, generate routers, check a registry, hash a token.

    python -m arcade serve
    python -m arcade routers --registry games.yaml [--domain play.example.com] [--check FILE]
    python -m arcade hosts --registry games.yaml [--domain ...]
    python -m arcade check-registry games.yaml
    python -m arcade hash-token            (reads the token from stdin)
"""

import argparse
import os
import sys

from arcade import __version__, registry, routers
from arcade.server import Arcade, Config, hashToken, log, makeServer

DEFAULT_DOMAIN = "play.danielstephenson.dev"


def _reporter():
    """A trace client for `page-served` events, or None when no key is set."""
    key = os.environ.get("ARCADE_TRACE_KEY", "").strip()
    if not key:
        return None
    from arcade.trace_client import TraceClient

    return TraceClient(
        os.environ.get("ARCADE_TRACE_URL", "https://trace.danielstephenson.dev"),
        os.environ.get("ARCADE_TRACE_PROGRAM", "arcade"),
        __version__,
        key=key,
    )


def serve(arguments):
    config = Config.fromEnvironment()
    reporter = _reporter()
    arcade = Arcade(config, reporter=reporter)
    host = os.environ.get("ARCADE_HOST", "0.0.0.0")
    port = int(os.environ.get("ARCADE_PORT", "8080"))
    server = makeServer(arcade, host, port)
    log(
        "arcade %s serving *.%s on %s:%d (data %s, registry %s, trace %s)"
        % (
            __version__,
            config.domain,
            host,
            port,
            config.dataDirectory,
            config.registryPath,
            "on" if reporter is not None and reporter.enabled else "off",
        )
    )
    if reporter is not None:
        reporter.report("startup")
    try:
        server.serve_forever()
    finally:
        if reporter is not None:
            reporter.close()
    return 0


def routersCommand(arguments):
    loaded = registry.load(arguments.registry, domain=arguments.domain)
    text = routers.render(loaded, arguments.domain)
    if arguments.check:
        try:
            with open(arguments.check, "r", encoding="utf-8") as existing:
                current = existing.read()
        except FileNotFoundError:
            current = None
        if current != text:
            print(
                "%s is stale: regenerate it with\n  python -m arcade routers --registry %s "
                "--domain %s > %s" % (arguments.check, arguments.registry, arguments.domain, arguments.check),
                file=sys.stderr,
            )
            return 1
        print("%s matches %s" % (arguments.check, arguments.registry))
        return 0
    sys.stdout.write(text)
    return 0


def hostsCommand(arguments):
    loaded = registry.load(arguments.registry, domain=arguments.domain)
    for _, host in routers.hosts(loaded, arguments.domain, includeApi=not arguments.games_only):
        print(host)
    return 0


def checkRegistry(arguments):
    loaded = registry.load(arguments.registry, domain=arguments.domain)
    print("%s: %d game(s) OK" % (arguments.registry, len(loaded)))
    return 0


def hashTokenCommand(arguments):
    token = sys.stdin.readline().strip()
    if not token:
        print("hash-token: no token on stdin", file=sys.stderr)
        return 2
    print(hashToken(token))
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(prog="arcade", description=__doc__.splitlines()[0])
    parser.add_argument("--version", action="version", version="arcade " + __version__)
    commands = parser.add_subparsers(dest="command")
    commands.required = True

    commands.add_parser("serve", help="run the server (configured by ARCADE_* variables)")

    for name, helpText in (
        ("routers", "print the Traefik routers for games.yaml"),
        ("hosts", "print every host arcade answers, one per line"),
    ):
        command = commands.add_parser(name, help=helpText)
        command.add_argument("--registry", required=True)
        command.add_argument("--domain", default=DEFAULT_DOMAIN)
        if name == "routers":
            command.add_argument("--check", metavar="FILE", help="exit 1 if FILE differs from the output")
        else:
            command.add_argument("--games-only", action="store_true", help="leave out play.<base> itself")

    check = commands.add_parser("check-registry", help="validate games.yaml")
    check.add_argument("registry")
    check.add_argument("--domain", default=DEFAULT_DOMAIN)

    commands.add_parser("hash-token", help="print the sha256 of a token read from stdin")

    arguments = parser.parse_args(argv)
    handlers = {
        "serve": serve,
        "routers": routersCommand,
        "hosts": hostsCommand,
        "check-registry": checkRegistry,
        "hash-token": hashTokenCommand,
    }
    try:
        return handlers[arguments.command](arguments)
    except registry.RegistryError as e:
        print("arcade: %s" % e, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
