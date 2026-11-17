"""产品图生视频流程，两种风格：

- presenter（口播带货，照参考作品，默认）：产品图 → Qwen3-VL 识别 → 大模型按 skills/product_presenter.md 写镜头和粤语口播
  → 每个镜头配音（Ming 粤语）→ Qwen-Image 2.1 出关键帧（产品图 + 虚拟主播照片做参考）
  → MiniMax H3 从关键帧往后生成视频（镜头时长 = 配音时长）→ 按素材剪辑同一套样式合成（字幕、左上角黄字、底部声明）。
- typography（产品贴字 TVC）：产品图 → 识别 → 大模型按 skills/product_tvc.md 出方案 → Qwen-Image 2.1 出关键帧
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

import numpy as np
import soundfile as sf

from . import cloud, config, media, tvc_flows, tvc_plan

CAPTION_PROMPT = ("请仔细看这张产品图，用中文客观描述：1.产品品类和品牌（看得清才写）2.外形结构 3.材质和颜色 "
                  "4.产品上能看清的文字 5.最突出的2-3个设计特点。只描述产品本身，不描述手、桌面和背景。分条输出，200字以内。")
STEPS = ["analyze", "plan", "keyframes", "segments", "final"]
STYLES = ("presenter", "typography")


def style_of(p: dict) -> str:
    return p.get("style") or "typography"          # 老项目没有这个字段，都是贴字 TVC


def _pc() -> dict:
    return config.load()["tvc"]["presenter"]


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
        out.append({k: p.get(k) for k in ("id", "created", "updated", "brief", "stage", "final")} | {"style": style_of(p)} |
                   {"title": (p.get("plan") or {}).get("title") or p["brief"].get("product"),
                    "cover": next((k["file"] for k in reversed(p.get("keyframes", [])) if k.get("file")), None)})
    return out


def create(image_b64: str, filename: str, brief: dict, style: str | None = None) -> dict:
    pid = time.strftime("%m%d_%H%M%S_") + uuid.uuid4().hex[:4]
    d = pdir(pid)
    d.mkdir(parents=True)
    ext = Path(filename or "product.png").suffix.lower() or ".png"
    if ext not in (".png", ".jpg", ".jpeg", ".webp"):
        ext = ".png"
    raw = base64.b64decode(image_b64.split(",", 1)[-1])
    (d / f"product{ext}").write_bytes(raw)
    style = style if style in STYLES else config.load()["tvc"].get("default_style", "presenter")
    p = {"id": pid, "created": time.time(), "brief": brief, "style": style, "product_file": f"product{ext}", "stage": "created",
         "caption": "", "plan": None, "keyframes": [], "segments": [], "voice": [], "final": None, "cloud": {}}
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
    if style_of(p) == "presenter":
        return _plan_presenter(p, progress)
    if progress:
        progress(0, 1, "大模型写分镜和视频提示词")
    pl = tvc_plan.generate(p["brief"], p.get("caption", ""))
    p["plan"] = pl
    p["keyframes"] = [{"id": k["id"], "file": None, "seed": None, "status": "pending"} for k in pl["keyframes"]]
    p["segments"] = [{"id": s["id"], "file": None, "seed": None, "status": "pending"} for s in pl["segments"]]
    p["final"] = None
    p["stage"] = "planned"
    return save(p)


def _plan_presenter(p: dict, progress=None) -> dict:
    from . import presenter

    if not presenter.get():                       # 还没有虚拟主播：按默认描述生成一个
        if progress:
            progress(0, 1, "生成虚拟主播形象")
        presenter.generate()
    src = presenter.file()
    dst = pdir(p["id"]) / f"presenter{src.suffix}"
    shutil.copy2(src, dst)                        # 复制进项目：之后换主播不影响这个项目
    p["presenter_file"] = dst.name
    if progress:
        progress(0, 1, "大模型写镜头和粤语口播")
    pl = tvc_plan.generate_presenter(p["brief"], p.get("caption", ""))
    n = len(pl["shots"])
    p["plan"] = pl
    p["keyframes"] = [{"id": i, "file": None, "seed": None, "status": "pending"} for i in range(1, n + 1)]
    p["segments"] = [{"id": i, "file": None, "seed": None, "status": "pending", "seconds": None} for i in range(1, n + 1)]
    p["voice"] = [None] * n
    p["final"] = None
    p["stage"] = "planned"
    return save(p)


# ---------------- 口播带货：配音 ----------------

def _lines_sig(lines: list[str]) -> str:
    import hashlib

    return hashlib.md5("|".join(lines).encode("utf-8")).hexdigest()[:10]


def shot_seconds(voice_dur: float) -> float:
    """镜头时长 = 配音时长 + 一点余量，限制在 [min, max] 秒。"""
    c = _pc()
    return round(min(float(c["max_seconds"]), max(float(c["min_seconds"]), voice_dur + 0.35)), 2)


def voiceover(p: dict, only: int | None = None, progress=None) -> dict:
    """给每个镜头配音（同一个镜头的几句连起来），记录每句在镜头里的起止时间，供字幕使用。
    文案没改过的镜头直接跳过。配音变长、视频不够长的镜头会标成需要重做。"""
    from . import tts

    shots = p["plan"]["shots"]
    p.setdefault("voice", [None] * len(shots))
    while len(p["voice"]) < len(shots):
        p["voice"].append(None)
    gap = float(_pc()["line_gap"])
    d = pdir(p["id"])
    for i, shot in enumerate(shots, 1):
        if only and i != only:
            continue
        lines = [str(x).strip() for x in shot.get("lines") or [] if str(x).strip()]
        sig = _lines_sig(lines)
        v = p["voice"][i - 1]
        if v and v.get("sig") == sig and (d / v["file"]).exists():
            continue
        if progress:
            progress(i - 1, len(shots), f"配音 {i}/{len(shots)}")
        chunks, timing, t, sr = [], [], 0.0, None
        for j, text in enumerate(lines):
            wav = tts.synthesize(text)
            y, r = sf.read(str(wav), dtype="float32", always_2d=False)
            if y.ndim > 1:
                y = y.mean(axis=1)
            if sr and r != sr:
                raise RuntimeError("配音采样率不一致")
            sr = r
            if j:
                chunks.append(np.zeros(int(gap * sr), dtype=np.float32))
                t += gap
            dur = len(y) / sr
            timing.append({"text": text, "start": round(t, 3), "end": round(t + dur, 3)})
            chunks.append(y)
            t += dur
        fn = f"voice_{i:02d}_{sig}.wav"
        sf.write(str(d / fn), np.concatenate(chunks) if chunks else np.zeros(1, np.float32), sr or 24000)
        p["voice"][i - 1] = {"file": fn, "dur": round(t, 3), "sig": sig, "lines": timing}
        seg = p["segments"][i - 1]
        if seg.get("file") and (seg.get("seconds") or 0) + 0.2 < shot_seconds(t):
            seg["status"] = "stale"                # 配音比视频长了，这个镜头的视频要重做
        p["final"] = None
    return save(p)


def keyframe(p: dict, idx: int, new_seed: bool = False) -> dict:
    """生成第 idx 张关键帧（从 1 开始）。重画会让用到它的视频段失效。"""
    kf = p["keyframes"][idx - 1]
    presenter_style = style_of(p) == "presenter"
    shot = p["plan"]["shots"][idx - 1] if presenter_style else None
    prompt = shot["image_prompt"] if shot else p["plan"]["keyframes"][idx - 1]["image_prompt"]
    seed = random.randrange(1 << 40) if (new_seed or kf.get("seed") is None) else kf["seed"]
    prod = _cloud_name(p, "product", pdir(p["id"]) / p["product_file"])
    refs = [prod]
    if shot and shot.get("type") == "presenter":   # 主播镜头：<image2> = 虚拟主播照片
        refs.append(_cloud_name(p, "presenter", pdir(p["id"]) / p["presenter_file"]))
    out = cloud.run(tvc_flows.keyframe_graph(prompt, refs, f"jh/tvc_{p['id']}_kf{idx}", seed=seed))
    img = cloud.outputs_of(out, "images")[0]
    fn = f"kf_{idx:02d}_{int(time.time())}.png"
    cloud.download(img, pdir(p["id"]) / fn)
    kf.update(file=fn, seed=seed, status="done")
    for s in p["segments"]:                       # 用到这张关键帧的视频段要重做
        used = (s["id"] == idx) if presenter_style else (idx in (s["id"], s["id"] + 1))
        if used and s.get("file"):
            s["status"] = "stale"
    p["final"] = None
    return save(p)


def with_dialogue(video_prompt: str, lines: list[str], seconds: float) -> str:
    """主播镜头：让 H3 里的人真的说这句粤语台词。成片会把 H3 的声音换成 Ming 配音，但嘴型是按同一句粤语、同样的时长动的，
    换上配音后口型对得上。台词用配音时的读法（型号逐位读、字母分开读），音节数和配音一致。"""
    import re

    from . import tts

    said = "，".join(tts.cantonese_tts_text(x) for x in lines if x.strip())
    if not said:
        return video_prompt
    dialogue = (f'Dialogue: from the very start of the shot the man speaks Cantonese (粤语) to the camera, saying exactly: "{said}". '
                f"He speaks at a natural pace, his lip movements clearly match each Cantonese syllable, and he finishes just before "
                f"the end of the {seconds:.1f}-second shot.")
    audio = "Audio: the man's voice clearly speaking these Cantonese words, light shop ambience. No background music."
    body = re.sub(r"(?im)^\s*Audio:.*$", audio, video_prompt)
    if body == video_prompt:                       # 原提示词没有 Audio 行：直接追加
        body = video_prompt.rstrip() + "\n\n" + audio
    return body.replace(audio, dialogue + "\n\n" + audio, 1)


def _segment_presenter(p: dict, idx: int, new_seed: bool = False, progress=None) -> dict:
    """口播带货：第 idx 个镜头 = 关键帧 idx 做首帧，H3 往后生成，时长跟这个镜头的配音一样长。"""
    shot = p["plan"]["shots"][idx - 1]
    kf = p["keyframes"][idx - 1]
    if not kf.get("file"):
        raise RuntimeError(f"镜头 {idx} 的关键帧还没生成")
    if not (p.get("voice") or [None] * idx)[idx - 1]:
        p = voiceover(p, only=idx)
    seg, v = p["segments"][idx - 1], p["voice"][idx - 1]
    seconds = shot_seconds(v["dur"])
    first = _cloud_name(p, f"kf{idx}", pdir(p["id"]) / kf["file"])
    last = first if _pc().get("same_last_frame", True) else None   # 首帧 = 尾帧：动作只能回到原位，手表不会越转越变形
    seed = random.randrange(1 << 40) if (new_seed or seg.get("seed") is None) else seg["seed"]
    prompt = shot["video_prompt"]
    if shot.get("type") == "presenter" and _pc().get("speak_lines", True):
        prompt = with_dialogue(prompt, [x["text"] for x in v["lines"]], seconds)
    seg["prompt_used"] = prompt
    graph = tvc_flows.h3_graph(prompt, first, last, seconds, f"jh/tvc_{p['id']}_seg{idx}", seed=seed)
    out = cloud.run(graph, progress=(lambda t: progress(0, 1, f"镜头 {idx} 生成中 {int(t)} 秒")) if progress else None)
    vids = [x for x in cloud.outputs_of(out, "images") + cloud.outputs_of(out, "videos")
            if str(x.get("filename", "")).endswith((".mp4", ".webm", ".mov"))]
    fn = f"seg_{idx:02d}_{int(time.time())}.mp4"
    cloud.download(vids[0], pdir(p["id"]) / fn)
    seg.update(file=fn, seed=seed, status="done", seconds=seconds)
    p["final"] = None
    return save(p)


def segment(p: dict, idx: int, new_seed: bool = False, progress=None) -> dict:
    """生成第 idx 段视频：关键帧 idx 为首帧，关键帧 idx+1 为尾帧。"""
    if style_of(p) == "presenter":
        return _segment_presenter(p, idx, new_seed, progress)
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


def _compose_presenter(p: dict, progress=None) -> dict:
    """按素材剪辑同一套样式合成：每个镜头配上自己的配音和字幕，加左上角黄字、底部声明，统一响度。"""
    from . import render

    d = pdir(p["id"])
    if not p["segments"] or any(s.get("status") != "done" for s in p["segments"]):
        raise RuntimeError("还有镜头的视频没生成或已失效，先把所有镜头生成好")
    p = voiceover(p)                              # 文案改过的镜头先重新配音
    if any(s.get("status") != "done" for s in p["segments"]):
        raise RuntimeError("有镜头的配音变长了，视频不够长，先重做标着「需重做」的镜头")
    max_chars = config.load()["style"]["subtitle"]["max_chars_per_line"]
    parts = []
    for s, v in zip(p["segments"], p["voice"]):
        seg = render.Segment(clip=d / s["file"], v_start=0.0, v_dur=round(v["dur"] + 0.25, 3), tts_wav=d / v["file"], zoom=1.0)
        for line in v["lines"]:
            seg.subs += render.timed_chunks(line["text"], line["start"], line["end"], max_chars)
        parts.append(seg)
    work = d / "_compose"
    if work.exists():
        shutil.rmtree(work)
    fn = f"final_{int(time.time())}.mp4"
    body = work / "picture.mp4"
    render.compose_segments(parts, work, body, progress)
    if progress:
        progress(0, 1, "成片声音处理")
    audio = _presenter_audio(p, parts, work / "audio")
    from . import audiofx

    audiofx.replace_audio(body, audio, d / fn)
    p["final"] = fn
    p["stage"] = "done"
    return save(p)


def _presenter_audio(p: dict, parts: list, work: Path) -> Path:
    """成片的声音：粤语配音（高通 + 两遍响度标准化，不会忽大忽小）+ H3 生成的店内环境声（用 Demucs 去掉里面的人声，
    低于配音约 22dB 垫在下面，听起来像在店里录的，不是干巴巴的配音）+ 限幅。"""
    from . import audiofx, dub

    d = pdir(p["id"])
    c = _pc()
    total = sum(x.v_dur for x in parts)
    n = int(total * audiofx.SR) + audiofx.SR
    voice = np.zeros(n, dtype=np.float32)
    bed = np.zeros((n, 2), dtype=np.float32)
    use_bed = c.get("ambience_db") is not None
    t = 0.0
    for i, x in enumerate(parts):
        a, length = int(t * audiofx.SR), int(x.v_dur * audiofx.SR)
        v = audiofx.load(x.tts_wav)[:length]
        voice[a:a + len(v)] += v
        if use_bed:
            sep = work / f"seg{i + 1:02d}"
            sep.mkdir(parents=True, exist_ok=True)
            try:
                _, background = dub.separate(x.clip, sep)
                b = audiofx.fade(audiofx.load(background, channels=2)[:length].copy())
                bed[a:a + len(b)] += b
            except Exception:  # noqa: BLE001  某个镜头没有声音或分离失败：这一段就不垫环境声
                pass
        t += x.v_dur
    voice, bed = voice[: int(total * audiofx.SR)], bed[: int(total * audiofx.SR)]
    return audiofx.master(voice, bed if use_bed else None, work, bed_db=float(c.get("ambience_db") or -22),
                          target_i=float(c.get("voice_lufs", -16)))


def compose(p: dict, progress=None) -> dict:
    """按顺序拼接视频段 → 统一 1080×1920 / 24fps → 有背景音乐就混进去（压低音效）。"""
    if style_of(p) == "presenter":
        return _compose_presenter(p, progress)
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
    presenter_style = style_of(p) == "presenter"
    if not p.get("plan"):
        step(i, "大模型写镜头和粤语口播" if presenter_style else "大模型写分镜和视频提示词")
        p = plan(p, progress=lambda a, b, m: step(i, m))
    i += 1
    n_total = 2 + len(p["keyframes"]) + len(p["segments"]) + 1
    if presenter_style:
        step(i, "粤语配音")
        p = voiceover(p, progress=lambda a, b, m: step(i, m))
    cloud.free_vram()
    for k in range(1, len(p["keyframes"]) + 1):
        if p["keyframes"][k - 1].get("status") != "done":
            step(i, f"生成{'镜头' if presenter_style else ''}关键帧 {k}/{len(p['keyframes'])}（Qwen-Image 2.1）")
            p = keyframe(p, k)
        i += 1
    if until == "keyframes":
        p["stage"] = "keyframes"
        return save(p)
    cloud.free_vram()
    for s in range(1, len(p["segments"]) + 1):
        if p["segments"][s - 1].get("status") != "done":
            step(i, f"生成{'镜头视频' if presenter_style else '视频段'} {s}/{len(p['segments'])}（MiniMax H3）")
            p = segment(p, s, progress=lambda a, b, m, i=i: step(i, m))
        i += 1
    step(i, "合成成片")
    return compose(p)
