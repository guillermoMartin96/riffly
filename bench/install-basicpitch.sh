#!/bin/sh
# Creates bench/.venv-bp with Basic Pitch (ONNX backend). Usage: sh bench/install-basicpitch.sh
set -eu
cd "$(dirname "$0")"
PY=${PYTHON:-python3.12}
$PY -m venv .venv-bp
.venv-bp/bin/pip install -q --upgrade pip
.venv-bp/bin/pip install -q --only-binary=:all: -r requirements-basicpitch.txt
.venv-bp/bin/pip install -q --only-binary=:all: --no-deps basic-pitch==0.4.0
