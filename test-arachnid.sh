
#!/usr/bin/env bash
set -euo pipefail

python3 -m venv .venv
source .venv/bin/activate

python3 -m pip install --upgrade pip
python3 -m pip install pdqhash numpy opencv-python-headless

API_URL="https://shield.projectarachnid.com/v1/pdq"

if [[ $# -ne 1 || ! -f "$1" ]]; then
    echo "Usage: $0 /path/to/image.jpg"
    exit 1
fi

IMAGE_PATH="$1"

# Prompt for credentials if not already provided.
if [[ -z "${API_USERNAME:-}" ]]; then
    read -r -p "API Username: " API_USERNAME
fi

if [[ -z "${API_PASSWORD:-}" ]]; then
    read -r -s -p "API Password: " API_PASSWORD
    echo
fi

export IMAGE_PATH

echo "Calculating PDQ hash locally..."

# Compute 256-bit PDQ hash and encode its 32 bytes as Base64.
PDQ_HASH=$(python3 - <<'PY'
import os
import sys
import base64
import cv2
import numpy as np
import pdqhash

image = cv2.imread(os.environ["IMAGE_PATH"])
if image is None:
    sys.exit("ERROR: Unable to read image.")

image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
hash_vector, quality = pdqhash.compute(image)

if len(hash_vector) != 256:
    sys.exit("ERROR: Invalid PDQ hash length.")

hash_bytes = np.packbits(
    np.asarray(hash_vector, dtype=np.uint8)
).tobytes()

print(f"PDQ quality: {quality}", file=sys.stderr)
print(base64.b64encode(hash_bytes).decode("ascii"))
PY
)

echo "PDQ hash (Base64): $PDQ_HASH"

# Generate the exact JSON payload expected by Shield.
PAYLOAD=$(printf '{"hashes":["%s"]}' "$PDQ_HASH")

echo
echo "Submitting PDQ hash to Project Arachnid Shield..."

# Use a temporary curl config to avoid putting the password
# directly in curl's command-line arguments.
CURL_CONFIG=$(mktemp)
RESPONSE_FILE=$(mktemp)

cleanup() {
    rm -f "$CURL_CONFIG" "$RESPONSE_FILE"
}
trap cleanup EXIT

chmod 600 "$CURL_CONFIG"

export API_USERNAME API_PASSWORD CURL_CONFIG
python3 - <<'PY'
import json
import os

def quote(value):
    return json.dumps(value, ensure_ascii=True)

with open(os.environ["CURL_CONFIG"], "w") as config:
    credentials = (
        os.environ["API_USERNAME"] + ":" +
        os.environ["API_PASSWORD"]
    )
    config.write("user = " + quote(credentials) + "\n")
PY

HTTP_CODE=$(curl \
    --silent \
    --show-error \
    --basic \
    --config "$CURL_CONFIG" \
    --request POST \
    --header "Content-Type: application/json" \
    --data "$PAYLOAD" \
    --output "$RESPONSE_FILE" \
    --write-out "%{http_code}" \
    "$API_URL")

echo "HTTP Status: $HTTP_CODE"
echo
echo "API Response:"

python3 -m json.tool < "$RESPONSE_FILE" || cat "$RESPONSE_FILE"

if [[ "$HTTP_CODE" != "200" ]]; then
    echo "ERROR: API request failed."
    exit 1
fi

echo
echo "Classification:"
python3 - "$PDQ_HASH" "$RESPONSE_FILE" <<'PY'
import json
import sys

expected_hash = sys.argv[1]
with open(sys.argv[2]) as f:
    response = json.load(f)

scanned = response.get("scanned_hashes", {})
result = scanned.get(expected_hash)

if result is None:
    print("No result for the submitted hash.")
    sys.exit(1)

classification = result.get("classification", "unknown")
match_type = result.get("match_type")

print("  Classification:", classification)
print("  Match type:", match_type or "none")

if classification == "no-known-match":
    print("  Result: No match in the known-content database.")
elif classification == "test":
    print("  Result: Test classification.")
elif classification in ("csam", "harmful-abusive-material"):
    print("  Result: FLAGGED - do not publish this media.")
else:
    print("  Result: Unexpected classification.")
    sys.exit(1)
PY

deactivate
