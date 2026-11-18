#!/usr/bin/env bash
# Installed on the system disk: AutoDL may copy the data disk after first boot.
set -euo pipefail
BASE=/root/autodl-tmp/jh-workbench
exec 9>/run/jh-workbench-boot.lock
flock -n 9 || exit 0
echo "$(date -Is) Waiting for the cloned workbench data disk"
while true; do
    if [[ -f "$BASE/automation/start.sh" && -f "$BASE/current/source/app.py" &&
          -x "$BASE/current/venv/bin/python" ]]; then
        # Do not pass the boot guard lock to the daemon.
        if bash "$BASE/automation/start.sh" 9>&-; then
            for attempt in $(seq 1 12); do
                if /root/miniconda3/bin/python -c '
import json, urllib.request
with urllib.request.urlopen("http://127.0.0.1:6006/api/info", timeout=3) as r:
    assert "llm_ready" in json.load(r)
' 2>/dev/null; then
                    echo "$(date -Is) Workbench startup passed"
                    exit 0
                fi
                sleep 2
            done
        fi
    fi
    sleep 5
done
