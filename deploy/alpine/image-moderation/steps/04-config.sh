#!/bin/sh
# Write compose.env (non-secret settings) and validate it with the stack's own validator.
set -eu
. "$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)/../../lib/common.sh"
require_root

ROOT=/opt/swoovr-image
CONF=$ROOT/private/install.conf
BIND_IP=$(conf_get "$CONF" BIND_IP)
# The reviewed, digest-pinned image comes from the stack's compose.env.example.
IMAGE=$(conf_get "$ROOT/stack/compose.env.example" PROCESSOR_IMAGE)
case "$IMAGE" in *@sha256:*) ;; *) die 'compose.env.example has no digest-pinned PROCESSOR_IMAGE.';; esac

cat > "$ROOT/private/compose.env" <<EOF
PROCESSOR_IMAGE=$IMAGE
PROCESSOR_BIND_IP=$BIND_IP
PROCESSOR_ENV_FILE=$ROOT/private/processor.env
PROCESSOR_CONTROL_DIR=$ROOT/control
PROCESSOR_MEMORY=4g
PROCESSOR_CPUS=2
CLAMAV_MEMORY=4g
CLAMAV_CPUS=2
EOF
chmod 600 "$ROOT/private/compose.env"
info "Image: $IMAGE"
sh "$ROOT/stack/stack.sh" "$ROOT/private/compose.env" validate
info 'compose.env validated.'
