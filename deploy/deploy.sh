#!/bin/bash
# 把本机工作台的代码同步到云服务器并重启（在 Git Bash 里运行：bash deploy/deploy.sh，按提示输入服务器密码）。
# 只同步代码、前端打包结果、字体、配置；服务器上的素材、识别结果、成片不受影响。
# 改了前端要先 cd frontend && npm run build 再部署。
set -euo pipefail
HOST="${JH_HOST:-ubuntu@106.75.239.166}"
cd "$(dirname "$0")/.."
PKG="$(mktemp -d)/jh-app.tgz"
tar czf "$PKG" --exclude=__pycache__ app.py jh web skills fonts frontend/dist config.yaml deploy
scp "$PKG" "$HOST:/tmp/jh-app.tgz"
ssh "$HOST" 'set -e
tar xzf /tmp/jh-app.tgz -C /srv/jh-workbench/app && rm /tmp/jh-app.tgz
/srv/jh-workbench/venv/bin/python /srv/jh-workbench/app/deploy/make_server_config.py
sudo systemctl restart jh-workbench && sleep 3 && systemctl is-active jh-workbench'
rm -f "$PKG"
echo "部署完成：http://106.75.239.166:8765"
