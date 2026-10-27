#!/usr/bin/env bash
set -euo pipefail

# Usage: ./test-nsfw-image-detector.sh "/absolute/path/to/image.jpg"
# Creates/reuses a dedicated Python 3.12 virtual environment beside this script.

if [[ $# -ne 1 || ! -f "$1" ]]; then
    echo "Usage: $0 /path/to/image.jpg" >&2
    exit 1
fi

IMAGE_PATH="$(cd "$(dirname "$1")" && pwd)/$(basename "$1")"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="${NSFW_VENV_DIR:-$SCRIPT_DIR/.venv-nsfw}"

if ! command -v /opt/homebrew/bin/python3.12 >/dev/null 2>&1; then
    echo "Python 3.12 is required. Install with: brew install python@3.12" >&2
    exit 1
fi

# Recreate a venv created with a different Python version.
if [[ -f "$VENV_DIR/pyvenv.cfg" ]] && ! grep -Eq '^version = 3\.12\.' "$VENV_DIR/pyvenv.cfg"; then
    echo "Recreating virtual environment with Python 3.12..."
    rm -rf "$VENV_DIR"
fi

if [[ ! -f "$VENV_DIR/bin/activate" ]]; then
    echo "Creating Python virtual environment: $VENV_DIR"
    /opt/homebrew/bin/python3.12 -m venv "$VENV_DIR"
fi

# Ensure that the environment is deactivated even on errors.
cleanup() {
    if declare -f deactivate >/dev/null 2>&1; then
        deactivate
    fi
}
trap cleanup EXIT
# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"

if ! python -c 'import nsfw_image_detector; from PIL import Image' >/dev/null 2>&1; then
    echo "Installing nsfw-image-detector (first run only)..."
    python -m pip install --upgrade pip
    python -m pip install 'nsfw-image-detector==0.1.2'
fi

echo "Scanning locally: $IMAGE_PATH"
# The model may download its weights during the first execution.
python - "$IMAGE_PATH" <<'PY'
import json
import sys
from pathlib import Path
from PIL import Image, ImageOps
from nsfw_image_detector import NSFWDetector

path = Path(sys.argv[1])
detector = NSFWDetector()
with Image.open(path) as source:
    image = ImageOps.exif_transpose(source).convert("RGB")
    result = {
        "image": str(path),
        "is_nsfw": bool(detector.is_nsfw(image)),
        "probabilities": detector.predict_proba(image),
    }

# Handle Python, NumPy and PyTorch numeric output values.
def serializable(value):
    if isinstance(value, dict):
        return {str(k): serializable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [serializable(v) for v in value]
    if hasattr(value, "tolist"):
        return serializable(value.tolist())
    if hasattr(value, "item"):
        return value.item()
    return value

print(json.dumps(serializable(result), indent=2))
PY

"$VENV_DIR/bin/deactivate" 2>/dev/null || true
