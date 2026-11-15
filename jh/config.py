"""读取 config.yaml，提供全局配置。"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent


@lru_cache(maxsize=1)
def load() -> dict:
    path = Path(os.environ.get("JH_CONFIG", ROOT / "config.yaml"))
    with open(path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    # 有些库（funasr、torchaudio）会直接调用 ffmpeg，把配置里的 ffmpeg 目录加进 PATH
    ff_dir = str(Path(cfg["paths"]["ffmpeg"]).parent)
    if Path(cfg["paths"]["ffmpeg"]).is_absolute() and ff_dir not in os.environ.get("PATH", ""):
        os.environ["PATH"] = ff_dir + os.pathsep + os.environ.get("PATH", "")
    return cfg


def data_root() -> Path:
    p = Path(load()["paths"]["data_root"])
    p.mkdir(parents=True, exist_ok=True)
    return p


def material_root() -> Path:
    return Path(load()["paths"]["material_root"])


def ffmpeg() -> str:
    return load()["paths"]["ffmpeg"]


def secret(name: str) -> str:
    """先读环境变量，没有再读项目根目录的 secrets.yaml（这个文件只放在本机，不要外传）。"""
    if os.environ.get(name):
        return os.environ[name]
    p = ROOT / "secrets.yaml"
    if p.exists():
        with open(p, "r", encoding="utf-8") as f:
            return str((yaml.safe_load(f) or {}).get(name, "") or "")
    return ""
