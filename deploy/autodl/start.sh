#!/usr/bin/env bash
set -euo pipefail
BASE=/root/autodl-tmp/jh-workbench
PYTHON=/root/miniconda3/bin/python
CONF="$BASE/automation/supervisord.conf"
if "$PYTHON" -m supervisor.supervisorctl -c "$CONF" pid >/dev/null 2>&1; then
    exit 0
fi
exec "$PYTHON" -m supervisor.supervisord -c "$CONF"
