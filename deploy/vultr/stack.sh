#!/bin/sh
set -eu
# Operator invokes this on ONE host at a time. Does not modify LB configuration.
if [ "$#" -ne 2 ]; then echo 'Usage: stack.sh /absolute/path/compose.env validate|up|status|drain|resume|stop' >&2; exit 2; fi
settings=$1
case "$settings" in /*) ;; *) echo 'compose.env path must be absolute' >&2; exit 2;; esac
root=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)
# Python parses deployment data; private processor.env is never printed or shell-evaluated.
python3 "$root/validate.py" "$settings"
compose() { docker compose --env-file "$settings" --file "$root/compose.yaml" --project-name swoovr-image "$@"; }
case "$2" in
  validate) compose config --quiet;;
  up) compose up -d --wait --wait-timeout 600;;
  status) compose ps;;
  drain|resume)
    control=$(python3 "$root/validate.py" "$settings" --control)
    if [ "$2" = drain ]; then touch "$control/drain"; chmod 644 "$control/drain"; else rm -f "$control/drain"; fi
    echo 'Readiness changed. Drain: wait for LB removal AND in-flight requests before stopping. Resume: verify LB readiness before next host.';;
  stop) compose stop --timeout 600;;
  *) echo 'Unknown action' >&2; exit 2;;
esac
