#!/bin/sh
# Swoovr image moderation — Alpine Linux installer.
# Copy this folder to a fresh Alpine VM and run as root:  ./install.sh [image-moderation|caddy]
set -eu
BASE=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)
. "$BASE/lib/common.sh"

require_root
require_alpine
require_tty

role=${1-}
[ "$#" -gt 0 ] && shift
if [ -z "$role" ]; then
    info '' 'Swoovr image moderation — Alpine installer' '' \
        'What is this machine?' \
        '  1) image-moderation   processor + ClamAV (Docker), bound to the VPC IP' \
        '  2) caddy              public HTTPS gateway, round-robin to the processors' ''
    ask role 'Select 1 or 2'
fi

case "$role" in
    1|image-moderation) exec sh "$BASE/image-moderation/install.sh" "$@";;
    2|caddy) exec sh "$BASE/caddy/install.sh" "$@";;
    *) die "Unknown selection: $role";;
esac
