#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 || ! -f "$1" ]]; then
  echo "Usage: $0 /path/to/image.jpg" >&2
  exit 1
fi

IMAGE_PATH="$(cd "$(dirname "$1")" && pwd)/$(basename "$1")"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$SCRIPT_DIR/.venv-nudenet"

if ! command -v /opt/homebrew/bin/python3.12 >/dev/null 2>&1; then
  echo "Python 3.12 is required. On macOS: brew install python@3.12" >&2
  exit 1
fi

# Recreate an existing environment if it uses a different Python version.
if [[ -x "$VENV_DIR/bin/python" ]]; then
  VERSION="$($VENV_DIR/bin/python -c 'import sys; print(".".join(map(str, sys.version_info[:2])))' 2>/dev/null || true)"
  if [[ "$VERSION" != "3.12" ]]; then
    echo "Replacing incompatible Python $VERSION virtual environment..."
    rm -rf "$VENV_DIR"
  fi
fi

if [[ ! -x "$VENV_DIR/bin/python" ]]; then
  echo "Creating Python 3.12 virtual environment: $VENV_DIR"
  /opt/homebrew/bin/python3.12 -m venv "$VENV_DIR"
fi

PYTHON="$VENV_DIR/bin/python"
if ! "$PYTHON" -c 'import nudenet, onnxruntime' >/dev/null 2>&1; then
  echo "Installing NudeNet dependencies (first run only)..."
  "$PYTHON" -m pip install --upgrade pip
  "$PYTHON" -m pip install 'nudenet>=3.4.2'
fi

export IMAGE_PATH
echo "Scanning locally: $IMAGE_PATH"
"$PYTHON" - <<'PY'
import json
import os
from nudenet import NudeDetector

detector = NudeDetector()
results = detector.detect(os.environ['IMAGE_PATH'])
print(json.dumps(results, indent=2))
if not results:
    print('No detections returned (not proof of image safety).')
PY

"$VENV_DIR/bin/deactivate" 2>/dev/null || true
