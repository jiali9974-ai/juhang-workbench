"""Pull main, stage a complete release, switch when idle, roll back on failure."""
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import traceback
import urllib.request

BASE = Path("/root/autodl-tmp/jh-workbench")
REPO = BASE / "source.git"
PYTHON = "/root/miniconda3/bin/python"
CONF = BASE / "automation/supervisord.conf"
os.environ["PATH"] = "/usr/local/bin:/usr/bin:/bin:/root/miniconda3/bin"
os.environ["GIT_SSH_COMMAND"] = f"ssh -F {BASE}/auth/ssh_config"
os.environ["GIT_TERMINAL_PROMPT"] = "0"
os.environ["PIP_CACHE_DIR"] = str(BASE / "cache/pip")
os.environ["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
os.environ["HF_HOME"] = str(BASE / "cache/huggingface")
os.environ["MODELSCOPE_CACHE"] = str(BASE / "cache/modelscope")


def run(*args, cwd=None, capture=False, timeout=1800):
    result = subprocess.run([str(a) for a in args], cwd=cwd, check=True, timeout=timeout,
                            stdout=subprocess.PIPE if capture else None,
                            text=True)
    return result.stdout.strip() if capture else None


def api(path):
    with urllib.request.urlopen("http://127.0.0.1:6006" + path, timeout=5) as response:
        return json.load(response)


def idle():
    try:
        return not any(j["status"] in ("queued", "running") for j in api("/api/jobs"))
    except Exception:
        return not (BASE / "current").exists()


def atomic_link(target, destination):
    staging = destination.with_name(destination.name + f".next.{os.getpid()}")
    staging.unlink(missing_ok=True)
    staging.symlink_to(target, target_is_directory=True)
    staging.replace(destination)


def control(action):
    run(PYTHON, "-m", "supervisor.supervisorctl", "-c", CONF, action, "jh-workbench", timeout=90)


def healthy():
    try:
        assert "llm_ready" in api("/api/info")
        with urllib.request.urlopen("http://127.0.0.1:6006/", timeout=3) as response:
            assert b"/assets/" in response.read()
        return True
    except Exception:
        return False


def sync():
    BASE.mkdir(parents=True, exist_ok=True)
    with (BASE / "deploy.lock").open("w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        if not REPO.exists():
            run("git", "init", "--bare", REPO)
            run("git", f"--git-dir={REPO}", "remote", "add", "origin",
                "git@github.com:jiali9974-ai/juhang-workbench.git")
        run("git", f"--git-dir={REPO}", "fetch", "--quiet", "--no-tags", "origin",
            "+refs/heads/main:refs/remotes/origin/main", timeout=90)
        target = run("git", f"--git-dir={REPO}", "rev-parse", "refs/remotes/origin/main", capture=True)
        marker = BASE / "deployed-revision"
        current = BASE / "current"
        source = BASE / "releases" / target
        if marker.exists() and marker.read_text().strip() == target and current.exists():
            dirty = run("git", "-C", current.resolve() / "source", "status", "--porcelain", capture=True)
            if not dirty:
                return
            # Preserve unexpected server edits; do not overwrite or destroy them.
            raise RuntimeError("Cloud source has local changes; inspect before deployment: " + dirty)
        if not idle():
            print("Update deferred: editing jobs are active or application is unavailable.", flush=True)
            return
        for name in ("releases", "runtime", "envs", "materials", "outputs", "models", "data", "cache"):
            (BASE / name).mkdir(parents=True, exist_ok=True)
        if not source.exists():
            run("git", f"--git-dir={REPO}", "worktree", "add", "--detach", source, target)
        for name in ("models", "data", "secrets.yaml"):
            path = source / name
            if not path.exists() and not path.is_symlink():
                path.symlink_to(BASE / name, target_is_directory=name != "secrets.yaml")
        requirements = source / "deploy/autodl/requirements.txt"
        digest = hashlib.sha256(requirements.read_bytes()).hexdigest()[:20]
        venv = BASE / "envs" / digest
        if not (venv / ".complete").exists():
            run(PYTHON, "-m", "venv", venv)
            run(venv / "bin/python", "-m", "pip", "install", "--quiet", "-r", requirements)
            run(venv / "bin/python", "-m", "pip", "check")
            (venv / ".complete").touch()
        lock_hash = hashlib.sha256((source / "frontend/package-lock.json").read_bytes()).hexdigest()[:20]
        deps = BASE / "frontend-deps" / lock_hash
        if not (deps / ".complete").exists():
            deps.mkdir(parents=True, exist_ok=True)
            for name in ("package.json", "package-lock.json"):
                shutil.copy2(source / "frontend" / name, deps / name)
            run("npm", "ci", "--no-audit", "--no-fund", cwd=deps)
            (deps / ".complete").touch()
        modules = source / "frontend/node_modules"
        if not modules.exists():
            modules.symlink_to(deps / "node_modules", target_is_directory=True)
        run("npm", "run", "build", cwd=source / "frontend")
        runtime = BASE / "runtime" / f"{target}-{int(time.time())}"
        runtime.mkdir()
        (runtime / "source").symlink_to(source, target_is_directory=True)
        (runtime / "venv").symlink_to(venv, target_is_directory=True)
        cfg = runtime / "config.yaml"
        run(venv / "bin/python", source / "deploy/autodl/make_config.py", source, BASE, cfg)
        env = os.environ.copy()
        env["JH_CONFIG"] = str(cfg)
        subprocess.run([str(venv / "bin/python"), "-c", "import app; assert app.app.title"],
                       cwd=source, env=env, check=True, timeout=90)
        if not idle():
            print("Update deferred after staging: editing jobs are active.", flush=True)
            return
        previous = current.resolve() if current.exists() else None
        atomic_link(runtime, current)
        try:
            if previous is not None:
                control("restart")
            else:
                run("bash", BASE / "automation/start.sh")
            for _ in range(45):
                if healthy():
                    break
                time.sleep(1)
            else:
                raise RuntimeError("Frontend/backend health checks failed")
        except BaseException:
            if previous is not None:
                atomic_link(previous, current)
                control("restart")
                print("Rolled back to " + str(previous), flush=True)
            raise
        staging = marker.with_suffix(".next")
        staging.write_text(target + "\n")
        staging.replace(marker)
        print("Deployed " + target + "; frontend/backend health checks passed.", flush=True)


if __name__ == "__main__":
    while True:
        try:
            sync()
        except Exception:
            traceback.print_exc()
            if "--loop" not in sys.argv:
                sys.exit(1)
        if "--loop" not in sys.argv:
            break
        time.sleep(30)
