#!/bin/sh
# Regenerate docs/img/ from the example configs with synthetic data (no hardware, no real
# host data). Run from the repository root with the package installed:
#   pip install -e . && sh scripts/make-screenshots.sh
set -eu
AT=2026-01-15T10:24
rm -rf docs/img
aoostar-lcd preview -c examples/gallery.yaml --out docs/img --at "$AT" --no-data-frame
aoostar-lcd preview -c examples/gallery-es-light.yaml --out docs/img/es-light --at "$AT"
