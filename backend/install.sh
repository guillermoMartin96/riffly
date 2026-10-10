#!/bin/sh
# Creates backend/.venv with the pinned runtime, including Basic Pitch 0.4.0 (ONNX), approved in DR-0001.
# basic-pitch's own metadata cannot be resolved on Python 3.12 (it requires tensorflow-macos on macOS
# and tensorflow<2.15.1 elsewhere, which have no 3.12 wheels), so it is installed with --no-deps on top of
# requirements.lock, which pins every dependency it actually uses with the ONNX backend.
# Usage: sh backend/install.sh   (env: PYTHON=python3.12, PIP_FLAGS for extra pip flags)
set -eu
cd "$(dirname "$0")"
PY=${PYTHON:-python3.12}
FLAGS=${PIP_FLAGS:-}
$PY -m venv .venv
.venv/bin/pip install -q $FLAGS --upgrade pip
.venv/bin/pip install -q $FLAGS --only-binary=:all: -r requirements.lock
.venv/bin/pip install -q $FLAGS --only-binary=:all: --no-deps basic-pitch==0.4.0
.venv/bin/pip install -q $FLAGS --no-deps -e .
# Verify the only unmet declarations are basic-pitch's unused TensorFlow/CoreML/TFLite backends.
UNEXPECTED=$(.venv/bin/pip check 2>&1 | grep -vE "^basic-pitch 0\.4\.0 requires (tensorflow|tensorflow-macos|coremltools|tflite-runtime|onnxruntime)," | grep -v "^No broken requirements" || true)
if [ -n "$UNEXPECTED" ]; then echo "Unexpected dependency problems:"; echo "$UNEXPECTED"; exit 1; fi
echo "backend venv ready ($(.venv/bin/python --version))"
