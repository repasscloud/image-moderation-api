#!/bin/sh
# Build one self-contained tarball to copy to a VM: this installer + the processor stack files.
#   sh deploy/alpine/bundle.sh [output.tar.gz]
#   scp swoovr-alpine.tar.gz root@VM:/root/ && ssh root@VM 'tar xzf swoovr-alpine.tar.gz && ./swoovr-alpine/install.sh'
set -eu
HERE=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)
STACK=$(CDPATH='' cd -- "$HERE/../vultr" && pwd)
OUT=${1:-$PWD/swoovr-alpine.tar.gz}
case "$OUT" in /*) ;; *) OUT=$PWD/$OUT;; esac

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
dest=$tmp/swoovr-alpine
mkdir -p "$dest/stack"
cp -R "$HERE/install.sh" "$HERE/README.md" "$HERE/lib" "$HERE/image-moderation" "$HERE/caddy" "$dest/"
for f in compose.yaml stack.sh validate.py compose.env.example; do
    cp "$STACK/$f" "$dest/stack/$f"
done
find "$dest" -name .DS_Store -delete
chmod 755 "$dest/install.sh" "$dest/caddy/swoovr-backend" "$dest/caddy/swoovr-gateway-test"
COPYFILE_DISABLE=1 tar -C "$tmp" -czf "$OUT" swoovr-alpine
echo "Wrote $OUT"
