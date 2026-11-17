"""虚拟主播：口播带货视频里出镜的人。

全工作台共用一个主播形象（data/tvc/_presenter/），所有项目出镜的都是同一个人，像一个固定的店铺主播。
可以按描述用 Qwen-Image 2.1 生成，也可以上传一张照片。新项目出方案时会把当时的主播照片复制进项目，
之后换主播不影响已有项目。
"""
from __future__ import annotations

import base64
import json
import random
import time
from pathlib import Path

from . import cloud, config, tvc_flows


def pdir() -> Path:
    d = config.data_root() / "tvc" / "_presenter"
    d.mkdir(parents=True, exist_ok=True)
    return d


def get() -> dict | None:
    f = pdir() / "presenter.json"
    if not f.exists():
        return None
    p = json.loads(f.read_text(encoding="utf-8"))
    return p if p.get("file") and (pdir() / p["file"]).exists() else None


def _save(p: dict) -> dict:
    p["updated"] = time.time()
    (pdir() / "presenter.json").write_text(json.dumps(p, ensure_ascii=False, indent=1), encoding="utf-8")
    return p


def default_prompt() -> str:
    return config.load()["tvc"]["presenter"]["portrait_prompt"]


def generate(prompt: str | None = None, seed: int | None = None) -> dict:
    """按描述生成主播照片（不带参考图的文生图）。"""
    prompt = (prompt or "").strip() or default_prompt()
    seed = seed if seed is not None else random.randrange(1 << 40)
    cloud.ensure_tunnel()
    out = cloud.run(tvc_flows.keyframe_graph(prompt, [], "jh/tvc_presenter", seed=seed))
    img = cloud.outputs_of(out, "images")[0]
    fn = f"presenter_{int(time.time())}.png"
    cloud.download(img, pdir() / fn)
    return _save({"file": fn, "prompt": prompt, "seed": seed, "source": "generated"})


def upload(image_b64: str, filename: str = "presenter.png") -> dict:
    ext = Path(filename).suffix.lower()
    if ext not in (".png", ".jpg", ".jpeg", ".webp"):
        ext = ".png"
    fn = f"presenter_{int(time.time())}{ext}"
    (pdir() / fn).write_bytes(base64.b64decode(image_b64.split(",", 1)[-1]))
    old = get() or {}
    return _save({"file": fn, "prompt": old.get("prompt") or "", "seed": None, "source": "uploaded"})


def file() -> Path:
    p = get()
    if not p:
        raise RuntimeError("还没有虚拟主播：先在「产品图生视频」首页生成或上传一张主播照片")
    return pdir() / p["file"]
