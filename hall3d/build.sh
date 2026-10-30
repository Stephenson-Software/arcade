#!/usr/bin/env bash
# Builds the walkable hall's engine (hall3d/main.cpp) into
# src/arcade/hall_assets/hall-engine.{js,wasm}, and copies the Strata web
# kit's page scripts (strata-kit.js, strata-loader.js) beside them. All four
# are committed, so arcade stays standard-library Python with no build step at
# deploy time.
#
# The kit and the engine both come from Strata's v0.7.0 wasm release tarball
# (kit 1.1, in its kit/ directory), checked against its pinned SHA-256: no
# vendored copy. Needs emsdk 6.0.11 activated (the version Strata's release
# is built with; everything linked into one .wasm must agree on it and on
# -fwasm-exceptions).
set -euo pipefail

here="$(cd "$(dirname "$0")" && pwd)"
repo="$(dirname "$here")"
work="${HALL3D_WORK:-$here/.build}"
mkdir -p "$work"

export STRATA_VERSION=0.7.0
export STRATA_SHA256=1aab559eb2477f42bfbeae1cd2e3cf70fcb8aa8b28fc8dce16ba1e0ba855049f
tarball="$work/strata-$STRATA_VERSION-wasm32-emscripten.tar.gz"
if [ ! -f "$tarball" ]; then
  curl -fsSL -o "$tarball.part" \
    "https://github.com/Preponderous-Software/strata/releases/download/v$STRATA_VERSION/strata-$STRATA_VERSION-wasm32-emscripten.tar.gz"
  mv "$tarball.part" "$tarball"
fi
echo "$STRATA_SHA256  $tarball" | sha256sum -c --quiet -
rm -rf "$work/kit-src" && mkdir -p "$work/kit-src"
tar xzf "$tarball" -C "$work/kit-src"

export STRATA_TARBALL="$tarball"
export KIT_DIR="$work/kit-src/kit"
export KIT_SOURCE="$here/main.cpp"
export KIT_OUT="$repo/src/arcade/hall_assets"
export KIT_NAME=hall-engine
export KIT_EXPORT_NAME=createHallEngine
export KIT_EXPORTS=_hall_texture,_hall_mesh,_hall_set_items,_hall_set_points,_hall_set_lights,_hall_set_view
export KIT_WORK="$work"
export EMSDK_VERSION=6.0.11

bash "$KIT_DIR/build-kit.sh"
# arcade serves a file's .gz sibling to a browser that accepts gzip; the
# image is read-only, so the copies are made here (-n: no name or time, so
# the same build gives the same bytes).
for f in hall-engine.wasm hall-engine.js; do gzip -9 -n -k -f "$KIT_OUT/$f"; done
