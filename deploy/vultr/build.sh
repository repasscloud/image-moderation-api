#!/bin/sh
set -eu
# Build only; no push/deploy. Build includes offline model snapshot, never runtime secrets.
if [ "$#" -ne 1 ]; then echo 'Usage: build.sh registry/name:review-tag' >&2; exit 2; fi
case "$1" in *' '*|*'@'*|'') echo 'Provide a plain image tag' >&2; exit 2;; esac
root=$(CDPATH='' cd -- "$(dirname -- "$0")/../.." && pwd)
exec docker build --pull --tag "$1" "$root"
