#!/bin/sh
# Alpine packages and services. Keeps the installed Alpine release branch.
set -eu
. "$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)/../../lib/common.sh"
require_root

ensure_community_repo
apk update
apk upgrade
apk add docker docker-cli-compose docker-openrc nftables iptables kmod \
    curl ca-certificates git python3 ufw
rc-update add docker default 2>/dev/null || true
rc-update add ufw default 2>/dev/null || true
rc-update add crond default 2>/dev/null || true
rc-service crond start || true

# apk upgrade may have replaced the kernel: Docker can't start until we reboot into it.
if running_kernel_modules_missing; then
    warn "Running kernel $(uname -r) has lost its modules (kernel upgraded by apk)."
    exit "$EXIT_REBOOT_REQUIRED"
fi

rc-service docker start || rc-service docker restart
wait_for_docker
docker --version
docker compose version
