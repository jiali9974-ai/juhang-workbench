"""Ming-3.0 TTS 引擎（audio.cpp 官方编译版 + 官方 GGUF 模型）。

工作台需要配音时自动在后台启动 audiocpp_server，工作台退出时引擎一起结束（Windows Job 对象），
闲置一段时间自动释放显存。不依赖“回归 Ming-3.0-Pro”整合包的网页服务。
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import threading
import time
from pathlib import Path

import requests

from . import config

_lock = threading.Lock()          # 一块显卡，同一时间只生成一句
_proc: subprocess.Popen | None = None
_port = 0
_job = None


def _cfg() -> dict:
    return config.load()["tts"]["ming"]


def engine_exe() -> Path:
    return Path(_cfg()["engine_dir"]) / "audiocpp_server.exe"


def model_path() -> Path:
    return Path(_cfg()["model"])


def available() -> tuple[bool, str]:
    if not engine_exe().is_file():
        return False, f"缺少引擎：{engine_exe()}"
    if not model_path().is_file():
        return False, f"缺少模型：{model_path()}"
    return True, "就绪"


def running() -> bool:
    return _proc is not None and _proc.poll() is None


def _free_port(preferred: int) -> int:
    for port in range(preferred, preferred + 50):
        with socket.socket() as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise RuntimeError("找不到可用端口")


def _kill_with_parent(proc: subprocess.Popen) -> None:
    """把引擎挂到 Job 对象上：工作台退出或被强杀时引擎一起结束，不留显存占用。"""
    global _job
    if os.name != "nt":
        return
    import ctypes

    k = ctypes.windll.kernel32
    if _job is None:
        k.CreateJobObjectW.restype = ctypes.c_void_p
        k.SetInformationJobObject.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_ulong]
        _job = k.CreateJobObjectW(None, None)
        info = (ctypes.c_byte * 144)()  # JOBOBJECT_EXTENDED_LIMIT_INFORMATION
        ctypes.cast(ctypes.addressof(info) + 16, ctypes.POINTER(ctypes.c_ulong))[0] = 0x2000  # KILL_ON_JOB_CLOSE
        k.SetInformationJobObject(_job, 9, info, 144)
    k.AssignProcessToJobObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    k.AssignProcessToJobObject(_job, int(proc._handle))


def _session() -> requests.Session:
    s = requests.Session()
    s.trust_env = False   # 本机地址不走系统代理
    return s


def start() -> None:
    global _proc, _port
    ok, msg = available()
    if not ok:
        raise RuntimeError(msg)
    cfg = _cfg()
    _port = _free_port(17871)
    conf = {
        "host": "127.0.0.1", "port": _port, "backend": cfg.get("backend", "cuda"), "device": 0,
        "lazy_load": False, "ui": False, "model_spec_override": "embedded", "log_request_body": False,
        # 关掉参考缓存，同一个种子才能读出同样的结果
        "models": [{"id": "ming", "family": "ming3_tts", "path": str(model_path()), "task": "tts", "mode": "offline",
                    "session_options": {"ming3_tts.reference_cache": False}}],
    }
    work = config.data_root() / "engine"
    work.mkdir(parents=True, exist_ok=True)
    conf_path = work / "ming.json"
    conf_path.write_text(json.dumps(conf, ensure_ascii=False, indent=1), encoding="utf-8")
    log = open(work / "ming.log", "a", encoding="utf-8")
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    _proc = subprocess.Popen(
        [str(engine_exe()), "--config", str(conf_path), "--no-ui",
         "--idle-unload-ms", str(int(cfg.get("idle_unload_minutes", 10) * 60_000))],
        cwd=str(engine_exe().parent), stdout=log, stderr=subprocess.STDOUT, creationflags=flags)
    _kill_with_parent(_proc)
    deadline = time.time() + 180
    s = _session()
    while time.time() < deadline:
        if _proc.poll() is not None:
            raise RuntimeError(f"Ming 引擎启动失败，详情见 {work / 'ming.log'}")
        try:
            s.get(f"http://127.0.0.1:{_port}/health", timeout=2)
            return
        except requests.RequestException:
            time.sleep(0.3)
    stop()
    raise RuntimeError("Ming 引擎启动超时")


def stop() -> None:
    global _proc
    if _proc and _proc.poll() is None:
        _proc.terminate()
        try:
            _proc.wait(10)
        except subprocess.TimeoutExpired:
            _proc.kill()
    _proc = None


def speech(payload: dict, timeout: int = 900) -> bytes:
    """调用引擎生成一段 WAV。引擎没起来会自动启动。"""
    with _lock:
        if not running():
            start()
        r = _session().post(f"http://127.0.0.1:{_port}/v1/audio/speech",
                            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                            headers={"Content-Type": "application/json"}, timeout=timeout)
        if r.status_code != 200:
            raise RuntimeError(f"Ming 生成失败：{r.text[:300]}")
        return r.content


def status() -> dict:
    ok, msg = available()
    return {"available": ok, "message": msg, "running": running()}
