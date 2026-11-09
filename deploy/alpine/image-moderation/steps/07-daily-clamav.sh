#!/bin/sh
# Install the 03:00 daily ClamAV refresh (signals the existing FreshClam; never starts another).
set -eu
HERE=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)
. "$HERE/../../lib/common.sh"
require_root

install -m 755 "$HERE/../update-clamav.sh" /usr/local/bin/update-clamav.sh
rc-update add crond default 2>/dev/null || true
rc-service crond start || true
(crontab -l 2>/dev/null | grep -v '/usr/local/bin/update-clamav.sh' || true
 echo '0 3 * * * /usr/local/bin/update-clamav.sh') | crontab -
crontab -l | grep '/usr/local/bin/update-clamav.sh'
