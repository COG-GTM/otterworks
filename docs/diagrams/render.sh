#!/usr/bin/env bash
# Render docs/diagrams/*.dot to PNG and SVG (needs Graphviz: apt-get install graphviz).
set -euo pipefail
cd "$(dirname "$0")"
for src in *.dot; do
  dot -Tpng -Gdpi=110 "$src" -o "${src%.dot}.png"
  dot -Tsvg "$src" -o "${src%.dot}.svg"
done
