#!/bin/sh
set -eu
# Refresh from the immutable build snapshot on a new revision or corrupt/incomplete cache.
# No runtime model download and no stale cached model after a rolling image upgrade.
if [ ! -f "$MODEL_CACHE/freepik/REVISION" ] \
    || ! cmp -s /opt/models/freepik/REVISION "$MODEL_CACHE/freepik/REVISION" \
    || ! (cd "$MODEL_CACHE/freepik" && sha256sum -c /opt/models/freepik/SHA256SUMS >/dev/null 2>&1); then
    mkdir -p "$MODEL_CACHE/freepik"
    cp -a /opt/models/freepik/. "$MODEL_CACHE/freepik/"
fi
(cd "$MODEL_CACHE/freepik" && sha256sum -c /opt/models/freepik/SHA256SUMS >/dev/null)
exec python -m app
