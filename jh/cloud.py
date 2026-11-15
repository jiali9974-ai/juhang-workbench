"""AutoDL 云端 ComfyUI：SSH 隧道 + 接口调用。

连接方式：本机用专用密钥（~/.ssh/jh_autodl，ssh 配置里的 Host jh-autodl）建一条隧道，
把云端 127.0.0.1:8188 映射到本机 127.0.0.1:<local_port>。隧道断了会自动重连。
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import threading
import time
import uuid
from pathlib import Path

import requests

from . import config

_lock = threading.Lock()
_tunnel: subprocess.Popen | None = None


def _cfg() -> dict:
    return config.load()["cloud"]


def base_url() -> str:
    return f"http://127.0.0.1:{_cfg()['local_port']}"


def _session() -> requests.Session:
    s = requests.Session()
    s.trust_env = False     # 本机隧道地址不走系统代理
    return s


def _port_open(port: int) -> bool:
    with socket.socket() as s:
        s.settimeout(1)
        return s.connect_ex(("127.0.0.1", port)) == 0


def alive() -> bool:
    try:
        return _session().get(base_url() + "/system_stats", timeout=5).ok
    except requests.RequestException:
        return False


def ensure_tunnel() -> None:
    """隧道没通就（重新）建立，最多重试几次（代理偶尔会断开 SSH 握手）。"""
    global _tunnel
    with _lock:
        if alive():
            return
        if _tunnel and _tunnel.poll() is None:
            _tunnel.terminate()
        c = _cfg()
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        for attempt in range(5):
            _tunnel = subprocess.Popen(
                ["ssh", "-N", "-o", "BatchMode=yes", "-o", "ExitOnForwardFailure=yes", "-o", "ServerAliveInterval=20",
                 "-o", "ServerAliveCountMax=3", "-L", f"{c['local_port']}:127.0.0.1:{c['remote_port']}", c["ssh_host"]],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=flags)
            for _ in range(30):
                time.sleep(0.5)
                if _tunnel.poll() is not None:
                    break
                if _port_open(c["local_port"]) and alive():
                    return
            if _tunnel.poll() is None:
                _tunnel.terminate()
            time.sleep(3 + attempt * 2)
        raise RuntimeError("连不上 AutoDL：请确认实例已开机，SSH 密钥已添加")


def ssh(cmd: str, timeout: int = 120) -> str:
    r = subprocess.run(["ssh", "-o", "BatchMode=yes", _cfg()["ssh_host"], cmd], capture_output=True, text=True,
                       encoding="utf-8", errors="ignore", timeout=timeout)
    return r.stdout


def status() -> dict:
    ok = alive()
    info = {"connected": ok}
    if ok:
        try:
            st = _session().get(base_url() + "/system_stats", timeout=5).json()
            dev = (st.get("devices") or [{}])[0]
            info.update(gpu=dev.get("name", ""), vram_total=dev.get("vram_total"), vram_free=dev.get("vram_free"))
            q = _session().get(base_url() + "/queue", timeout=5).json()
            info.update(running=len(q.get("queue_running", [])), pending=len(q.get("queue_pending", [])))
        except requests.RequestException:
            pass
    return info


# ---------------- ComfyUI 接口 ----------------

def free_vram() -> None:
    """让云端 ComfyUI 卸载已加载的模型、释放显存（换大模型前用）。"""
    ensure_tunnel()
    _session().post(base_url() + "/free", json={"unload_models": True, "free_memory": True}, timeout=60)


def upload_image(path: Path, name: str | None = None) -> str:
    """上传图片到云端 ComfyUI 的 input 目录，返回在工作流里引用的文件名。"""
    ensure_tunnel()
    name = name or f"jh_{uuid.uuid4().hex[:10]}{path.suffix.lower()}"
    with open(path, "rb") as f:
        r = _session().post(base_url() + "/upload/image", files={"image": (name, f, "image/png")},
                            data={"overwrite": "true", "subfolder": "jh"}, timeout=120)
    r.raise_for_status()
    j = r.json()
    return f"{j['subfolder']}/{j['name']}" if j.get("subfolder") else j["name"]


def run(graph: dict, progress=None, timeout: int = 3600) -> dict:
    """提交一个 API 格式的工作流，等它跑完，返回 history 里的输出。"""
    ensure_tunnel()
    s = _session()
    r = s.post(base_url() + "/prompt", json={"prompt": graph, "client_id": "jh-workbench"}, timeout=60)
    if r.status_code != 200:
        raise RuntimeError(f"云端拒绝了工作流：{r.text[:600]}")
    pid = r.json()["prompt_id"]
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            h = s.get(f"{base_url()}/history/{pid}", timeout=30).json()
        except requests.RequestException:
            ensure_tunnel()
            continue
        if pid in h:
            item = h[pid]
            st = item.get("status", {})
            if st.get("status_str") == "error":
                msgs = [m for m in st.get("messages", []) if m[0] == "execution_error"]
                detail = msgs[0][1].get("exception_message", "") if msgs else ""
                raise RuntimeError(f"云端执行出错：{detail[:600]}")
            if st.get("completed") or item.get("outputs"):
                return item.get("outputs", {})
        if progress:
            progress(time.time() - t0)
        time.sleep(2)
    raise RuntimeError("云端任务超时")


def download(file_info: dict, dst: Path) -> Path:
    """下载 history 输出里的一个文件（图片/视频）。"""
    dst.parent.mkdir(parents=True, exist_ok=True)
    params = {"filename": file_info["filename"], "subfolder": file_info.get("subfolder", ""), "type": file_info.get("type", "output")}
    with _session().get(base_url() + "/view", params=params, stream=True, timeout=600) as r:
        r.raise_for_status()
        with open(dst, "wb") as f:
            for chunk in r.iter_content(1 << 20):
                f.write(chunk)
    return dst


def outputs_of(outputs: dict, key: str) -> list[dict]:
    """从 history 输出里取某一类文件：images / videos / gifs / text。"""
    res = []
    for node_out in outputs.values():
        res += node_out.get(key, []) or []
    return res
