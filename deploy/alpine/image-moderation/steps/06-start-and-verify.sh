#!/bin/sh
# Start the stack (image pulled, never built) and require /ready HTTP 200.
set -eu
. "$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)/../../lib/common.sh"
require_root

ROOT=/opt/swoovr-image
PROC=swoovr-image-processor-1
CLAM=swoovr-image-clamav-1

# Print "<status> <body>" for /ready from inside the processor (works for 200 and 503).
ready_report() {
    docker exec "$PROC" python -c '
import urllib.request, urllib.error
try:
    r = urllib.request.urlopen("http://127.0.0.1:8080/ready", timeout=15)
    print(r.status, r.read().decode())
except urllib.error.HTTPError as e:
    print(e.code, e.read().decode())
except Exception as e:
    print("unreachable", type(e).__name__, e)' 2>&1 || true
}

diagnose() {
    warn 'Stack did not become healthy. Diagnostics (no credentials are printed):'
    docker ps --filter name=swoovr-image
    printf '\n-- /ready (names the failing engine) --\n'
    ready_report
    printf '\n-- Docker health-check results --\n'
    docker inspect --format '{{range .State.Health.Log}}exit={{.ExitCode}} {{.Output}}{{"\n"}}{{end}}' "$PROC" 2>&1 | tail -n 4 || true
    printf '\n-- ClamAV signature version vs host clock (signatures must be <72h old) --\n'
    docker exec "$CLAM" clamdscan --version 2>&1 || true
    printf 'host UTC: %s\n' "$(date -u)"
    printf '\n-- recent logs --\n'
    docker logs --tail 40 "$CLAM" 2>&1 || true
    docker logs --tail 40 "$PROC" 2>&1 || true
}

# Ask clamd to reload its database (from the processor: 3310 is only on the internal network).
clamd_reload() {
    docker exec -i "$PROC" python - <<'PY' 2>&1 || true
import socket
with socket.create_connection(("clamav", 3310), timeout=15) as s:
    s.sendall(b"zRELOAD\0")
    print("clamd:", s.recv(1024).decode(errors="replace").strip("\0\r\n "))
PY
}

# Poll /ready for up to $1 seconds; succeed on HTTP 200.
wait_ready() {
    _end=$(( $(date +%s) + $1 ))
    while [ "$(date +%s)" -lt "$_end" ]; do
        case "$(ready_report)" in '200 '*) return 0;; esac
        sleep 10
    done
    return 1
}

if ! sh "$ROOT/stack/stack.sh" "$ROOT/private/compose.env" up; then
    # Known first-boot race on a fresh volume: clamd loads the signatures baked into the
    # ClamAV image (can be >72h old) while FreshClam downloads newer ones, and clamd isn't
    # listening yet when FreshClam tries to notify it. A reload picks up the new database.
    case "$(ready_report)" in
        *'"malware":"failed"'*)
            info 'ClamAV signatures not loaded yet (fresh-volume race). Asking clamd to reload...'
            clamd_reload
            wait_ready 180 || { diagnose; exit 1; }
            ;;
        *) diagnose; exit 1;;
    esac
fi

report=$(ready_report)
case "$report" in
    '200 '*) printf '%s\n' "$report";;
    *) diagnose; exit 1;;
esac
docker exec "$CLAM" clamdscan --version
docker ps --filter name=swoovr-image
