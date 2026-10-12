#!/bin/sh
# Clean-install test for the Basic Pitch ONNX workaround (DR-0001 condition 2).
# Builds a brand-new venv in a temp dir from the pinned lock with the pip cache disabled, then:
#  1. records any declared-dependency deviations reported by `pip check`,
#  2. runs a smoke transcription of a known synthetic clip,
#  3. checks the fresh install reproduces the benchmark venv's notes on 20 GuitarSet holdout clips.
# Usage: sh bench/clean_install_test.sh   (requires the corpus in bench/.cache/corpus)
set -eu
cd "$(dirname "$0")"
PY=${PYTHON:-python3.12}
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
echo "== python: $($PY --version) at $(command -v $PY); platform: $(uname -sm)"
$PY -m venv "$TMP/venv"
"$TMP/venv/bin/pip" install -q --no-cache-dir --upgrade pip
"$TMP/venv/bin/pip" install -q --no-cache-dir --only-binary=:all: -r requirements-basicpitch.lock
"$TMP/venv/bin/pip" install -q --no-cache-dir --only-binary=:all: --no-deps basic-pitch==0.4.0
echo "== pip check (expected: only basic-pitch's unmet tensorflow-macos/coremltools declarations)"
"$TMP/venv/bin/pip" check || true
echo "== installed size: $(du -sh "$TMP/venv" | cut -f1)"
echo "== smoke + reproducibility"
"$TMP/venv/bin/python" -W ignore -m jamrecall_bench.verify_install 2>&1 | grep -viE "warning|reinstall"
