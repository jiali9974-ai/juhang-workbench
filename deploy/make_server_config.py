"""在云服务器上运行：把同步上来的 config.yaml 改成服务器版 config.server.yaml。

服务器没有显卡（2 核 / 8G），只做「原素材出片」：识别走 CPU、出片用 libx264，路径换成 /srv/jh-workbench 下的。
字幕样式、调色、脚本规则等其余配置保持和本机一致，所以每次部署都从最新的 config.yaml 重新生成。
"""
from __future__ import annotations

import os
from pathlib import Path

import yaml

BASE = Path("/srv/jh-workbench")
APP = Path(os.environ.get("JH_APP", BASE / "app"))

# 本机路径前缀 → 服务器路径（长的放前面先匹配）
PREFIXES = [
    ("D:/巨航/workbench/data", str(BASE / "data")),
    ("D:/巨航/workbench/models", str(BASE / "models")),
    ("D:/jhwb/models", str(BASE / "models")),
    ("D:/巨航/workbench/", str(APP) + "/"),
    ("D:/jhwb/", str(APP) + "/"),
]


def _fix(v):
    if isinstance(v, dict):
        return {k: _fix(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_fix(x) for x in v]
    if isinstance(v, str):
        s = v.replace("\\", "/") if v[:2].upper() in ("C:", "D:", "E:") else v
        for a, b in PREFIXES:
            if s.startswith(a):
                return b + s[len(a):]
    return v


def main() -> None:
    cfg = yaml.safe_load((APP / "config.yaml").read_text(encoding="utf-8"))
    cfg = _fix(cfg)
    cfg["paths"].update(material_root=str(BASE / "materials"), data_root=str(BASE / "data"),
                        ffmpeg="/usr/bin/ffmpeg", cosyvoice_repo="")
    cfg["asr"]["device"] = "cpu"
    cfg["render"]["encoder"] = "libx264"
    cfg.setdefault("gpu", {})["mode"] = "cpu"
    out = Path(os.environ.get("JH_SERVER_CONFIG", BASE / "config.server.yaml"))
    out.write_text("# 自动生成（deploy/make_server_config.py），不要手改；改本机 config.yaml 后重新部署\n"
                   + yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False), encoding="utf-8")
    print("wrote", out)


if __name__ == "__main__":
    main()
