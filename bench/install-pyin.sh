#!/bin/sh
# Creates bench/.venv-pyin. Usage: sh bench/install-pyin.sh
set -eu
cd "$(dirname "$0")"
PY=${PYTHON:-python3.12}
$PY -m venv .venv-pyin
.venv-pyin/bin/pip install -q --upgrade pip
.venv-pyin/bin/pip install -q --only-binary=:all: -r requirements-pyin.txt
