"""产品图生视频（产品贴字 TVC）流程。

产品图 → Qwen3-VL 识别 → 大模型按 skills/product_tvc.md 出方案 → Qwen-Image 2.1 出关键帧
→ MiniMax H3 首尾帧逐段出视频（第 k 段 = 关键帧 k → k+1）→ 拼接成片。

每个项目一个文件夹 data/tvc/<项目号>/，project.json 记录全部状态，任何一步都能单独重做。
"""
from __future__ import annotations

import base64
import json
import random
import shutil
import time
import uuid
from pathlib import Path

from . import cloud, config, media, tvc_flows, tvc_plan

CAPTION_PROMPT = ("请仔细看这张产品图，用中文客观描述：1.产品品类和品牌（看得清才写）2.外形结构 3.材质和颜色 "
                  "4.产品上能看清的文字 5.最突出的2-3个设计特点。只描述产品本身，不描述手、桌面和背景。分条输出，200字以内。")
STEPS = ["analyze", "plan", "keyframes", "segments", "final"]


def root() -> Path:
    p = config.data_root() / "tvc"
    p.mkdir(parents=True, exist_ok=True)
    return p


def pdir(pid: str) -> Path:
    if not pid or "/" in pid or "\\" in pid or ".." in pid:
        raise ValueError("项目号不对")
    return root() / pid


def load(pid: str) -> dict:
    return json.loads((pdir(pid) / "project.json").read_text(encoding="utf-8"))


def save(p: dict) -> dict:
    p["updated"] = time.time()
    (pdir(p["id"]) / "project.json").write_text(json.dumps(p, ensure_ascii=False, indent=1), encoding="utf-8")
    return p


def list_projects() -> list[dict]:
    out = []
    for f in sorted(root().glob("*/project.json"), key=lambda x: -x.stat().st_mtime):
        try:
            p = json.loads(f.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        out.append({k: p.get(k) for k in ("id", "created", "updated", "brief", "stage", "final")} |
                   {"title": (p.get("plan") or {}).get("title") or p["brief"].get("product"),
                    "cover": next((k["file"] for k in reversed(p.get("keyframes", [])) if k.get("file")), None)})
    return out


def create(image_b64: str, filename: str, brief: dict) -> dict:
    pid = time.strftime("%m%d_%H%M%S_") + uuid.uuid4().hex[:4]
    d = pdir(pid)
    d.mkdir(parents=True)
    ext = Path(filename or "product.png").suffix.lower() or ".png"
    if ext not in (".png", ".jpg", ".jpeg", ".webp"):
        ext = ".png"
    raw = base64.b64decode(image_b64.split(",", 1)[-1])
    (d / f"product{ext}").write_bytes(raw)
    p = {"id": pid, "created": time.time(), "brief": brief, "product_file": f"product{ext}", "stage": "created",
         "caption": "", "plan": None, "keyframes": [], "segments": [], "final": None, "cloud": {}}
    return save(p)


# ---------------- 各步骤 ----------------

def _cloud_name(p: dict, key: str, local: Path) -> str:
    """把本地文件传到云端（同一文件只传一次），返回云端引用名。"""
    sig = f"{local.name}:{local.stat().st_mtime_ns}"
    c = p.setdefault("cloud", {})
    if c.get(key, {}).get("sig") != sig:
        c[key] = {"sig": sig, "name": cloud.upload_image(local, f"tvc_{p['id']}_{key}{local.suffix}")}
    return c[key]["name"]


def analyze(p: dict, progress=None) -> dict:
    if progress:
        progress(0, 1, "识别产品图（Qwen3-VL）")
    name = _cloud_name(p, "product", pdir(p["id"]) / p["product_file"])
    out = cloud.run(tvc_flows.caption_graph(name, CAPTION_PROMPT))
    texts = cloud.outputs_of(out, "text")
    p["caption"] = (texts[0] if texts else "").strip()
    p["stage"] = "analyzed"
    return save(p)


def plan(p: dict, progress=None) -> dict:
    if progress:
        progress(0, 1, "大模型写分镜和视频提示词")
    pl = tvc_plan.generate(p["brief"], p.get("caption", ""))
    p["plan"] = pl
    p["keyframes"] = [{"id": k["id"], "file": None, "seed": None, "status": "pending"} for k in pl["keyframes"]]
    p["segments"] = [{"id": s["id"], "file": None, "seed": None, "status": "pending"} for s in pl["segments"]]
    p["final"] = None
    p["stage"] = "planned"
    return save(p)


def keyframe(p: dict, idx: int, new_seed: bool = False) -> dict:
    """生成第 idx 张关键帧（从 1 开始）。重画会让用到它的视频段失效。"""
    kf = p["keyframes"][idx - 1]
    prompt = p["plan"]["keyframes"][idx - 1]["image_prompt"]
    seed = random.randrange(1 << 40) if (new_seed or kf.get("seed") is None) else kf["seed"]
    prod = _cloud_name(p, "product", pdir(p["id"]) / p["product_file"])
    out = cloud.run(tvc_flows.keyframe_graph(prompt, [prod], f"jh/tvc_{p['id']}_kf{idx}", seed=seed))
    img = cloud.outputs_of(out, "images")[0]
    fn = f"kf_{idx:02d}_{int(time.time())}.png"
    cloud.download(img, pdir(p["id"]) / fn)
    kf.update(file=fn, seed=seed, status="done")
    for s in p["segments"]:                       # 用到这张关键帧的视频段要重做
        if idx in (s["id"], s["id"] + 1) and s.get("file"):
            s["status"] = "stale"
    p["final"] = None
    return save(p)


def segment(p: dict, idx: int, new_seed: bool = False, progress=None) -> dict:
    """生成第 idx 段视频：关键帧 idx 为首帧，关键帧 idx+1 为尾帧。"""
    seg = p["segments"][idx - 1]
    sp = p["plan"]["segments"][idx - 1]
    a, b = p["keyframes"][sp["from"] - 1], p["keyframes"][sp["to"] - 1]
    if not a.get("file") or not b.get("file"):
        raise RuntimeError(f"第 {idx} 段需要的关键帧还没生成")
    first = _cloud_name(p, f"kf{sp['from']}", pdir(p["id"]) / a["file"])
    last = _cloud_name(p, f"kf{sp['to']}", pdir(p["id"]) / b["file"])
    seed = random.randrange(1 << 40) if (new_seed or seg.get("seed") is None) else seg["seed"]
    graph = tvc_flows.h3_graph(sp["video_prompt"], first, last, float(sp.get("seconds") or config.load()["tvc"]["seconds_per_segment"]),
                               f"jh/tvc_{p['id']}_seg{idx}", seed=seed)
    out = cloud.run(graph, progress=(lambda t: progress(0, 1, f"第 {idx} 段生成中 {int(t)} 秒")) if progress else None)
    vids = [v for v in cloud.outputs_of(out, "images") + cloud.outputs_of(out, "videos")
            if str(v.get("filename", "")).endswith((".mp4", ".webm", ".mov"))]
    fn = f"seg_{idx:02d}_{int(time.time())}.mp4"
    cloud.download(vids[0], pdir(p["id"]) / fn)
    seg.update(file=fn, seed=seed, status="done")
    p["final"] = None
    return save(p)


def compose(p: dict, progress=None) -> dict:
    """按顺序拼接视频段 → 统一 1080×1920 / 24fps → 有背景音乐就混进去（压低音效）。"""
    if progress:
        progress(0, 1, "合成成片")
    d = pdir(p["id"])
    segs = p["segments"]
    if not segs or any(s.get("status") != "done" for s in segs):
        raise RuntimeError("还有视频段没生成或已失效，先把所有段生成好")
    work = d / "_compose"
    if work.exists():
        shutil.rmtree(work)
    work.mkdir()
    parts = []
    for i, s in enumerate(segs):
        # 相邻两段共用同一张关键帧：除最后一段外，去掉每段最后一帧，避免拼接处停顿一帧
        info = media.probe(d / s["file"])
        keep = info.duration - (1 / 24 if i < len(segs) - 1 else 0)
        out = work / f"p{i:02d}.mp4"
        media.run_ffmpeg(["-i", str(d / s["file"]), "-t", f"{keep:.4f}",
                          "-vf", "scale=1080:1920:flags=lanczos,fps=24,setsar=1,format=yuv420p",
                          "-af", "aresample=48000,aformat=channel_layouts=stereo",
                          "-c:v", "libx264", "-preset", "medium", "-crf", "16", "-c:a", "aac", "-b:a", "192k", str(out)])
        parts.append(out)
    (work / "list.txt").write_text("".join(f"file '{x.name}'\n" for x in parts), encoding="utf-8")
    body = work / "body.mp4"
    media.run_ffmpeg(["-f", "concat", "-safe", "0", "-i", str(work / "list.txt"), "-c", "copy", str(body)])
    fn = f"final_{int(time.time())}.mp4"
    bgm = config.load()["tvc"].get("bgm_file") or ""
    if bgm and Path(bgm).exists():
        media.run_ffmpeg(["-i", str(body), "-stream_loop", "-1", "-i", bgm, "-filter_complex",
                          "[0:a]volume=0.6[fx];[1:a]volume=0.5,afade=t=out:st=13.5:d=1.5[m];[fx][m]amix=inputs=2:duration=first:normalize=0[a]",
                          "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
                          "-movflags", "+faststart", str(d / fn)])
    else:
        media.run_ffmpeg(["-i", str(body), "-c", "copy", "-movflags", "+faststart", str(d / fn)])
    p["final"] = fn
    p["stage"] = "done"
    return save(p)


def run(pid: str, until: str = "final", progress=None) -> dict:
    """从当前进度一路跑到 until（keyframes = 出完关键帧停下来审核；final = 直接出成片）。"""
    p = load(pid)
    n_total = 2 + len(p.get("keyframes") or [None] * 4) + len(p.get("segments") or [None] * 3) + 1

    def step(i, msg):
        if progress:
            progress(i, n_total, msg)

    i = 0
    if not p.get("caption"):
        step(i, "识别产品图（Qwen3-VL）")
        p = analyze(p)
    i += 1
    if not p.get("plan"):
        step(i, "大模型写分镜和视频提示词")
        p = plan(p)
    i += 1
    n_total = 2 + len(p["keyframes"]) + len(p["segments"]) + 1
    cloud.free_vram()
    for k in range(1, len(p["keyframes"]) + 1):
        if p["keyframes"][k - 1].get("status") != "done":
            step(i, f"生成关键帧 {k}/{len(p['keyframes'])}（Qwen-Image 2.1）")
            p = keyframe(p, k)
        i += 1
    if until == "keyframes":
        p["stage"] = "keyframes"
        return save(p)
    cloud.free_vram()
    for s in range(1, len(p["segments"]) + 1):
        if p["segments"][s - 1].get("status") != "done":
            step(i, f"生成视频段 {s}/{len(p['segments'])}（MiniMax H3）")
            p = segment(p, s, progress=lambda a, b, m, i=i: step(i, m))
        i += 1
    step(i, "合成成片")
    return compose(p)
