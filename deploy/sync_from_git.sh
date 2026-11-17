#!/usr/bin/env bash
# Cloud deployment: main is authoritative; runtime files live outside releases.
set -Eeuo pipefail
umask 022
export PATH=/usr/local/bin:/usr/bin:/bin
BASE=/srv/jh-workbench
REPO="$BASE/source.git"
APP="$BASE/app"
PYTHON="$BASE/venv/bin/python"
export GIT_SSH_COMMAND='ssh -i /home/ubuntu/.ssh/jh_workbench_deploy -o IdentitiesOnly=yes -o BatchMode=yes -o StrictHostKeyChecking=yes -o ConnectTimeout=10'
export GIT_TERMINAL_PROMPT=0
mkdir -p "$BASE/releases" "$BASE/backups" "$BASE/frontend-deps"
exec 9>"$BASE/deploy.lock"
flock -n 9 || exit 0

if [[ ! -d "$REPO" ]]; then
    git init --bare "$REPO"
    git --git-dir="$REPO" remote add origin git@github.com:jiali9974-ai/juhang-workbench.git
fi
timeout 60 git --git-dir="$REPO" fetch --no-tags origin +refs/heads/main:refs/remotes/origin/main
target=$(git --git-dir="$REPO" rev-parse refs/remotes/origin/main)
current=$(git -C "$APP" rev-parse HEAD 2>/dev/null || true)
dirty=$(git -C "$APP" status --porcelain 2>/dev/null || true)
deployed=$(cat "$BASE/deployed-revision" 2>/dev/null || true)
if [[ "$current" == "$target" && "$deployed" == "$target" && -z "$dirty" ]]; then
    exit 0
fi

idle() {
    # Fail closed when a running service cannot report its queue.
    if ! systemctl is-active --quiet jh-workbench; then return 0; fi
    "$PYTHON" -c 'import json,sys,urllib.request
with urllib.request.urlopen("http://127.0.0.1:18765/api/jobs", timeout=10) as r:
    jobs=json.load(r)
sys.exit(1 if any(j["status"] in ("queued", "running") for j in jobs) else 0)'
}
if ! idle; then
    echo "Deployment deferred: editing jobs are active or queue is unavailable."
    exit 0
fi

stamp=$(date -u +%Y%m%dT%H%M%S)-$$
release="$BASE/releases/$target-$stamp"
git --git-dir="$REPO" worktree add --detach "$release" "$target"
if [[ ! -f "$BASE/secrets.yaml" && -f "$APP/secrets.yaml" ]]; then
    install -m 600 "$APP/secrets.yaml" "$BASE/secrets.yaml"
fi
[[ ! -f "$BASE/secrets.yaml" ]] || ln -s "$BASE/secrets.yaml" "$release/secrets.yaml"
ln -s "$BASE/models" "$release/models"
ln -s "$BASE/data" "$release/data"

lock_hash=$(sha256sum "$release/frontend/package-lock.json" | cut -d' ' -f1)
deps="$BASE/frontend-deps/$lock_hash"
if [[ ! -f "$deps/.complete" ]]; then
    mkdir -p "$deps"
    cp "$release/frontend/package.json" "$release/frontend/package-lock.json" "$deps/"
    (cd "$deps" && npm ci --no-audit --no-fund --fetch-retries=1 --fetch-timeout=45000)
    touch "$deps/.complete"
fi
ln -s "$deps/node_modules" "$release/frontend/node_modules"
(cd "$release/frontend" && npm run build)
"$PYTHON" -m compileall -q "$release/app.py" "$release/jh" "$release/deploy"
staged_config="$BASE/config.staged.$stamp.yaml"
JH_APP="$release" JH_SERVER_CONFIG="$staged_config" "$PYTHON" "$release/deploy/make_server_config.py"
(cd "$release" && JH_CONFIG="$staged_config" "$PYTHON" -c 'import app; assert app.app.title; print("Backend import OK")')

# Building can take time. Check the queue again immediately before switching.
if ! idle; then
    rm -f "$staged_config"
    echo "Deployment deferred after build: editing jobs are active."
    exit 0
fi
if [[ -L "$APP" ]]; then
    previous=$(readlink -f "$APP")
else
    previous="$BASE/backups/app-before-git-$stamp"
fi
config_backup="$BASE/backups/config-$stamp.yaml"
cp -p "$BASE/config.server.yaml" "$config_backup"
switched=0
rollback() {
    result=$?
    trap - ERR INT TERM
    if [[ "$switched" == 1 ]]; then
        ln -s "$previous" "$BASE/app.rollback.$$"
        mv -Tf "$BASE/app.rollback.$$" "$APP"
        cp -p "$config_backup" "$BASE/config.server.yaml"
        sudo -n systemctl restart jh-workbench || true
        echo "Deployment failed; restored $previous" >&2
    fi
    rm -f "$staged_config"
    exit "$result"
}
trap rollback ERR INT TERM
if [[ ! -L "$APP" ]]; then
    # Keep the original upload intact as the first rollback target.
    mv "$APP" "$previous"
    ln -s "$previous" "$APP"
fi
switched=1
ln -s "$release" "$BASE/app.next.$$"
mv -Tf "$BASE/app.next.$$" "$APP"
mv "$staged_config" "$BASE/config.server.yaml"
sudo -n systemctl restart jh-workbench
healthy=0
for attempt in $(seq 1 30); do
    if "$PYTHON" -c 'import json,urllib.request
with urllib.request.urlopen("http://127.0.0.1:18765/api/info", timeout=2) as r:
    assert "llm_ready" in json.load(r)
with urllib.request.urlopen("http://127.0.0.1:18765/", timeout=2) as r:
    assert b"/assets/" in r.read()' 2>/dev/null; then
        healthy=1
        break
    fi
    sleep 1
done
[[ "$healthy" == 1 ]]
[[ -z $(git -C "$APP" status --porcelain) ]]
printf '%s\n' "$target" >"$BASE/deployed-revision.next"
mv "$BASE/deployed-revision.next" "$BASE/deployed-revision"
trap - ERR INT TERM
echo "Deployed $target; frontend and backend health checks passed."
