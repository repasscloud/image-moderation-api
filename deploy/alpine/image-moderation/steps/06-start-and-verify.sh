#!/bin/sh
# Start the stack (image pulled, never built) and require /ready HTTP 200.
set -eu
. "$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)/../../lib/common.sh"
require_root

ROOT=/opt/swoovr-image
sh "$ROOT/stack/stack.sh" "$ROOT/private/compose.env" up || {
    warn 'Stack did not become healthy. Recent logs (no credentials are printed):'
    docker ps --filter name=swoovr-image
    docker logs --tail 40 swoovr-image-clamav-1 2>&1 || true
    docker logs --tail 40 swoovr-image-processor-1 2>&1 || true
    exit 1
}
docker exec swoovr-image-processor-1 python -c \
    'import urllib.request; r=urllib.request.urlopen("http://127.0.0.1:8080/ready",timeout=15); assert r.status==200; print(r.read().decode())'
docker exec swoovr-image-clamav-1 clamdscan --version
docker ps --filter name=swoovr-image
