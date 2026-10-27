#!/bin/sh
set -eu
# A fresh named volume may hide the build-time model snapshot. Seed it offline.
if [ ! -f "$MODEL_CACHE/freepik/model.safetensors" ]; then
    mkdir -p "$MODEL_CACHE/freepik"
    cp -a /opt/models/freepik/. "$MODEL_CACHE/freepik/"
fi
exec python -m app
