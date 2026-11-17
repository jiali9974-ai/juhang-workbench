#!/usr/bin/env bash
set -euo pipefail
BASE=/root/autodl-tmp/jh-workbench
CURRENT=$(readlink -f "$BASE/current")
export JH_CONFIG="$CURRENT/config.yaml"
export PYTHONUNBUFFERED=1
export HF_HOME="$BASE/cache/huggingface"
export MODELSCOPE_CACHE="$BASE/cache/modelscope"
export OMP_NUM_THREADS=8
export MKL_NUM_THREADS=8
export MPLCONFIGDIR="$BASE/cache/matplotlib"
cd "$CURRENT/source"
exec "$CURRENT/venv/bin/uvicorn" app:app --host 0.0.0.0 --port 6006
