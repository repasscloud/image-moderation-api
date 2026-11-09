#!/bin/sh
# Create the Docker networks, then open exactly the forwarding paths the stack needs:
#   - outbound internet from the processor/ClamAV egress networks
#   - inbound TCP 8080 from the allowed VPC source (Caddy gateway IP, or the VPC subnet)
# UFW "deny routed" applies because Docker DNATs published ports onto its bridges.
set -eu
. "$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)/../../lib/common.sh"
require_root

ROOT=/opt/swoovr-image
CONF=$ROOT/private/install.conf
VPC_IF=$(conf_get "$CONF" VPC_IF)
ALLOW_FROM=$(conf_get "$CONF" ALLOW_FROM)
EGRESS_IF=$(default_route_iface)
[ -n "$EGRESS_IF" ] || die 'No default IPv4 route; cannot determine the internet-facing interface.'
info "VPC interface: $VPC_IF   egress interface: $EGRESS_IF   8080 allowed from: $ALLOW_FROM"
wait_for_docker

# Creates containers and networks without starting anything.
docker compose --env-file "$ROOT/private/compose.env" -f "$ROOT/stack/compose.yaml" \
    -p swoovr-image create

for network in swoovr-image_outbound swoovr-image_signatures; do
    subnet=$(docker network inspect "$network" --format '{{range .IPAM.Config}}{{.Subnet}}{{end}}')
    bridge=$(docker network inspect "$network" --format '{{index .Options "com.docker.network.bridge.name"}}')
    if [ -z "$bridge" ] || [ "$bridge" = '<no value>' ]; then
        bridge="br-$(docker network inspect "$network" --format '{{.Id}}' | cut -c1-12)"
    fi
    case "$subnet" in *.*/*) ;; *) die "Missing IPv4 subnet for $network";; esac
    info "Outbound: $network ($bridge, $subnet) -> $EGRESS_IF"
    ufw route allow in on "$bridge" out on "$EGRESS_IF" from "$subnet" to any
done

info "Inbound: $ALLOW_FROM -> TCP 8080 via $VPC_IF"
ufw route allow in on "$VPC_IF" out on 'br+' from "$ALLOW_FROM" to any port 8080 proto tcp

ufw reload
ufw status verbose
nft -a list chain ip filter FORWARD || true

heading 'Docker outbound HTTPS check'
docker run --rm --network swoovr-image_signatures python:3.12-alpine python -c '
import socket
socket.create_connection(("database.clamav.net", 443), timeout=15).close()
print("ClamAV outbound HTTPS: OK")'
