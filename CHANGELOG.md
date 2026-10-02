# Changelog

All notable changes to this project are documented in this file. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.0.0/), and the project uses semantic versioning.

## [0.1.0] - 2026-10-01

### Added

- The arcade server (RFC 0006 v1.1). It serves `<slug>.play.<base>` and registry aliases with tak's
  exact routes and the three cross-origin isolation headers on every response, and serves `/tak/`
  from each game's own `game.zip`.
- An upload API with a bearer token per game (only its SHA-256 is stored), validation before any
  write, immutable versions, `?activate=false`, rollback via `POST …/current`, pruning to the last 5
  versions (never the current one), and atomic writes.
- A strict, stdlib-only parser for `games.yaml` that reports errors by line and hot-reloads, keeping
  the last good registry on error.
- `python -m arcade routers|hosts|check-registry|hash-token`: generated Traefik routers, one per
  host (TLS option B), with `--check` for CI.
- Optional trace reporting (`page-served` per slug) through the vendored trace-client-python 0.3.0.
- A Dockerfile with a `/healthz` health check, and CI on Python 3.8 and 3.12 plus an image smoke test.
