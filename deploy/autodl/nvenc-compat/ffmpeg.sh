#!/usr/bin/env bash
set -euo pipefail
HERE=$(cd -- "$(dirname -- "$0")" && pwd)
# Restrict the driver response to the GPUs already assigned to this container.
# The compatibility library applies only to this FFmpeg process.
export LD_PRELOAD="$HERE/libnvenc_fix.so${LD_PRELOAD:+:$LD_PRELOAD}"
exec /usr/bin/ffmpeg -nostdin "$@"
