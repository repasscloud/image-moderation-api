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
rc-service docker start || rc-service docker restart
rc-service crond start || true
docker --version
docker compose version
