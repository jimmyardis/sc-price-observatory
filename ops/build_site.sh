#!/usr/bin/env bash
# Assemble the static site: everything in site/, plus the published snapshots it reads.
# Used by the Pages workflow and for local preview:
#   ops/build_site.sh && python3 -m http.server -d .tmp/site 8765
set -euo pipefail
cd "$(dirname "$0")/.."
OUT=${1:-.tmp/site}
rm -rf "$OUT"
mkdir -p "$OUT"
cp -r site/. "$OUT/"
mkdir -p "$OUT/snapshots"
cp -r snapshots/. "$OUT/snapshots/"
rm -f "$OUT/README.md" "$OUT/snapshots/.gitkeep"
echo "built $OUT ($(du -sh "$OUT" | cut -f1))"
