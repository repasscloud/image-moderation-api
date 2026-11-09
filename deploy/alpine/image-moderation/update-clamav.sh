#!/bin/sh
# Daily request to the running FreshClam daemon; never launches another freshclam.
set -eu
CONTAINER=swoovr-image-clamav-1
PROCESSOR=swoovr-image-processor-1
LOCK=/run/update-clamav.lock
mkdir "$LOCK" 2>/dev/null || exit 0
trap 'rmdir "$LOCK"' EXIT HUP INT TERM
log() { logger -t clamav-update "$1"; printf '%s\n' "$1"; }

[ "$(docker inspect -f '{{.State.Running}}' "$CONTAINER" 2>/dev/null)" = true ] || {
    log 'ERROR: ClamAV container not running'; exit 1;
}
log 'Requesting signature check from running FreshClam daemon.'
docker exec "$CONTAINER" sh -c '
  pid=$(pidof freshclam | awk "{print \$1}")
  [ -n "$pid" ] || exit 1
  kill -USR1 "$pid"
' || { log 'ERROR: Could not signal FreshClam'; exit 1; }
# Give the daemon time to fetch definitions; clamd may also auto-reload on update.
sleep 60
log 'Requesting ClamAV database reload.'
docker exec -i "$PROCESSOR" python - <<'PY'
import socket
with socket.create_connection(('clamav', 3310), timeout=15) as sock:
    sock.sendall(b'zRELOAD\0')
    response = sock.recv(1024).decode(errors='replace').strip('\x00\r\n ')
    if response != 'RELOADING':
        raise RuntimeError(f'Unexpected reload response: {response!r}')
    print('ClamAV reload accepted.')
PY
sleep 30
VERSION=$(docker exec "$CONTAINER" clamdscan --version)
log "Loaded ClamAV version: $VERSION"
docker exec "$PROCESSOR" python -c \
    'import urllib.request; urllib.request.urlopen("http://127.0.0.1:8080/ready",timeout=15)' || {
    log 'ERROR: Image processor not ready following daily refresh.'; exit 1;
}
log 'Daily ClamAV refresh completed; processor ready.'
