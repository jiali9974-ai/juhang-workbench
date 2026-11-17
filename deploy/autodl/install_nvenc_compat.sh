#!/usr/bin/env bash
set -euo pipefail
BASE=${1:-/root/autodl-tmp/jh-workbench}
SOURCE=$(cd -- "$(dirname -- "$0")/nvenc-compat" && pwd)
digest=$(sha256sum "$SOURCE/nvenc_fix.c" | cut -c1-20)
DEST="$BASE/engines/nvenc-compat/$digest"
mkdir -p "$DEST"
if [[ ! -f "$DEST/.complete" ]]; then
    gcc -shared -fPIC -O2 -o "$DEST/libnvenc_fix.so.next" "$SOURCE/nvenc_fix.c" -ldl
    mv "$DEST/libnvenc_fix.so.next" "$DEST/libnvenc_fix.so"
    cp "$SOURCE/LICENSE" "$SOURCE/upstream.json" "$DEST/"
    touch "$DEST/.complete"
fi
cp "$SOURCE/ffmpeg.sh" "$DEST/ffmpeg"
chmod 755 "$DEST/ffmpeg"
