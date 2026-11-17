#!/usr/bin/env bash
# 只部署已经推送到 GitHub main 的版本；云端也会自动跟随推送。
set -euo pipefail
HOST="${JH_HOST:-ubuntu@106.75.239.166}"
ssh "$HOST" 'set -e
sudo -n systemctl start jh-workbench-sync.service
systemctl is-active jh-workbench
printf "Deployed commit: "
cat /srv/jh-workbench/deployed-revision'
