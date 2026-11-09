#!/bin/sh
# Image-moderation node: processor + ClamAV Docker Compose stack bound to this VM's VPC IP.
# Collects every answer before changing anything, then runs steps/01..07 and reboots.
set -eu
umask 077
HERE=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)
. "$HERE/../lib/common.sh"
require_root
require_alpine
require_tty

ROOT=/opt/swoovr-image
PRIVATE=$ROOT/private

heading 'Image-moderation node'
info 'All answers are collected before anything on this VM is changed.' ''

# 1. VPC bind address -----------------------------------------------------------
ask BIND_IP 'VPC IPv4 to bind the processor (port 8080) to' "$(first_private_ipv4)"
valid_ipv4 "$BIND_IP" || die "Not a valid IPv4 address: $BIND_IP"
is_private_ipv4 "$BIND_IP" || die 'Use the private VPC address (10/8, 172.16/12, 192.168/16), never the public IP.'
IFACE_INFO=$(iface_for_ipv4 "$BIND_IP") ||
    die "$BIND_IP is not assigned to this VM. Attach the VPC and check 'ip -4 addr' first."
VPC_IF=${IFACE_INFO% *}
VPC_SUBNET=$(cidr_network "${IFACE_INFO#* }")
info "  -> interface $VPC_IF, subnet $VPC_SUBNET"

# 2. Who may reach port 8080 ------------------------------------------------------
ask GATEWAY_IP "Caddy gateway VPC IPv4 allowed to reach :8080 (blank = whole subnet $VPC_SUBNET)"
if [ -n "$GATEWAY_IP" ]; then
    valid_ipv4 "$GATEWAY_IP" || die "Not a valid IPv4 address: $GATEWAY_IP"
    ipv4_in_cidr "$GATEWAY_IP" "$VPC_SUBNET" || die "$GATEWAY_IP is not inside $VPC_SUBNET."
    [ "$GATEWAY_IP" != "$BIND_IP" ] || die 'The gateway IP cannot be this VM.'
    ALLOW_FROM=$GATEWAY_IP
else
    ALLOW_FROM=$VPC_SUBNET
fi

# 3. Credentials (not echoed) ------------------------------------------------------
ask_secret API_KEY 'API_KEY (identical on every node, min 32 chars)'
[ "${#API_KEY}" -ge 32 ] || die 'API_KEY must be at least 32 characters.'
ask ARACHNID_API_USERNAME 'ARACHNID_API_USERNAME'
[ -n "$ARACHNID_API_USERNAME" ] || die 'ARACHNID_API_USERNAME is required.'
ask_secret ARACHNID_API_PASSWORD 'ARACHNID_API_PASSWORD'
[ -n "$ARACHNID_API_PASSWORD" ] || die 'ARACHNID_API_PASSWORD is required.'
for v in "$API_KEY" "$ARACHNID_API_USERNAME" "$ARACHNID_API_PASSWORD"; do
    single_line "$v" || die 'Carriage-return characters are not supported in credentials.'
done

if [ -e "$PRIVATE/processor.env" ]; then
    confirm 'Existing credentials found in processor.env. Replace them?' || die 'Cancelled.'
fi

info '' 'Summary' \
    "  Bind:         $BIND_IP:8080 on $VPC_IF" \
    "  Allow 8080:   from $ALLOW_FROM only" \
    '  SSH:          TCP 22 open to any source' \
    '  Credentials:  API_KEY, Arachnid username/password (hidden)' ''
confirm 'Install now? The VM reboots automatically once every step succeeds.' || die 'Cancelled.'

# Persist answers -----------------------------------------------------------------
mkdir -p "$PRIVATE" "$ROOT/control"
chmod 700 "$PRIVATE"
chmod 755 "$ROOT" "$ROOT/control"
printf 'API_KEY=%s\nARACHNID_API_USERNAME=%s\nARACHNID_API_PASSWORD=%s\nCLAMAV_MAX_SIGNATURE_AGE_HOURS=72\nCLAMAV_TIMEOUT_SECONDS=30\nSCAN_TIMEOUT_SECONDS=120\nARACHNID_TIMEOUT_SECONDS=15\nNSFW_DTYPE=float32\n' \
    "$API_KEY" "$ARACHNID_API_USERNAME" "$ARACHNID_API_PASSWORD" > "$PRIVATE/processor.env"
chmod 600 "$PRIVATE/processor.env"
unset API_KEY ARACHNID_API_USERNAME ARACHNID_API_PASSWORD
printf 'BIND_IP=%s\nVPC_IF=%s\nVPC_SUBNET=%s\nALLOW_FROM=%s\n' \
    "$BIND_IP" "$VPC_IF" "$VPC_SUBNET" "$ALLOW_FROM" > "$PRIVATE/install.conf"
chmod 600 "$PRIVATE/install.conf"

# Run steps -------------------------------------------------------------------------
for step in 01-packages 02-docker-firewall 03-stack-files 04-config 05-networks-and-ufw 06-start-and-verify 07-daily-clamav; do
    heading "$step"
    sh "$HERE/steps/$step.sh" ||
        die "$step failed. Nothing was rebooted. Fix the issue, then rerun ./install.sh or: sh $HERE/steps/$step.sh"
done

info '' 'All steps succeeded. Rebooting in 10 seconds (Ctrl+C to cancel).'
sleep 10
reboot
