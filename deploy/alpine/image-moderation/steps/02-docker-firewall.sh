#!/bin/sh
# Docker on nftables, IPv4 forwarding, UFW default-deny (incoming + routed), SSH open.
set -eu
. "$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)/../../lib/common.sh"
require_root

# Never discard a pre-existing custom Docker daemon configuration.
if [ -f /etc/docker/daemon.json ]; then
    grep -q '"firewall-backend"[[:space:]]*:[[:space:]]*"nftables"' /etc/docker/daemon.json ||
        die '/etc/docker/daemon.json exists without "firewall-backend": "nftables"; merge it manually.'
else
    mkdir -p /etc/docker
    cat > /etc/docker/daemon.json <<'JSON'
{
  "log-driver": "json-file",
  "log-opts": {"max-size": "10m", "max-file": "3"},
  "firewall-backend": "nftables"
}
JSON
fi
dockerd --validate --config-file /etc/docker/daemon.json
mkdir -p /etc/sysctl.d
printf '%s\n' 'net.ipv4.ip_forward=1' > /etc/sysctl.d/99-docker-forwarding.conf
sysctl -w net.ipv4.ip_forward=1
rc-service docker restart

if grep -q '^DEFAULT_FORWARD_POLICY=' /etc/default/ufw; then
    sed -i 's/^DEFAULT_FORWARD_POLICY=.*/DEFAULT_FORWARD_POLICY="DROP"/' /etc/default/ufw
else
    printf '%s\n' 'DEFAULT_FORWARD_POLICY="DROP"' >> /etc/default/ufw
fi
ufw default deny incoming
ufw default allow outgoing
ufw default deny routed
# SSH stays reachable from anywhere for administration/troubleshooting.
ufw allow 22/tcp
ufw --force enable
ufw reload
ufw status verbose
