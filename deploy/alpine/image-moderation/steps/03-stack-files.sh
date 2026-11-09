#!/bin/sh
# Install the Compose stack files (compose.yaml, stack.sh, validate.py) into /opt/swoovr-image/stack.
# Source order: bundled ./stack (from bundle.sh), sibling ../vultr (repo checkout), else git clone.
set -eu
HERE=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)
. "$HERE/../../lib/common.sh"
require_root

ROOT=/opt/swoovr-image
BUNDLE=$(CDPATH='' cd -- "$HERE/../.." && pwd)
FILES='compose.yaml stack.sh validate.py compose.env.example'

if [ -f "$BUNDLE/stack/compose.yaml" ]; then
    SRC=$BUNDLE/stack
elif [ -f "$BUNDLE/../vultr/compose.yaml" ]; then
    SRC=$(CDPATH='' cd -- "$BUNDLE/../vultr" && pwd)
else
    info 'Stack files not bundled; cloning the public repository.'
    rm -rf "$ROOT/src"
    git clone --depth 1 https://github.com/repasscloud/image-moderation-api.git "$ROOT/src"
    SRC=$ROOT/src/deploy/vultr
fi
info "Using stack files from $SRC"

mkdir -p "$ROOT/stack"
chmod 755 "$ROOT/stack"
for f in $FILES; do
    [ -f "$SRC/$f" ] || die "Missing $SRC/$f"
    install -m 644 "$SRC/$f" "$ROOT/stack/$f"
done
chmod 755 "$ROOT/stack/stack.sh"
