"""美颜和调色的强度设置、FFmpeg 调色与锐化滤镜，以及对比预览图。

设置存在 data/settings/look.json，出片时读取：
  smooth  局部磨皮强度 0–1（0 = 不磨）。0.5 对应 1234_01 磨皮试片的力度。
  tone    提亮调色强度 0–1（0 = 不额外调色）。温和提亮中间调，保留人物、服饰和产品色相
  sharpen 手表特写锐化强度 0–1（0 = 不锐化）。只用在没有人脸的画面
  normalize 按片段校正曝光与白平衡，保留不同人物肤色（见 normalize.py）
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path

from . import cancellation, config

DEFAULTS = {"enabled": True, "normalize": True, "smooth": 0.5, "tone": 0.35, "sharpen": 0.5}


def _path() -> Path:
    p = config.data_root() / "settings" / "look.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _clamp(v, lo=0.0, hi=1.0) -> float:
    try:
        return max(lo, min(hi, float(v)))
    except (TypeError, ValueError):
        return lo


def current() -> dict:
    s = dict(DEFAULTS)
    p = _path()
    if p.exists():
        try:
            s.update(json.loads(p.read_text(encoding="utf-8")))
        except json.JSONDecodeError:
            pass
    return normalize(s)


def normalize(s: dict) -> dict:
    return {"enabled": bool(s.get("enabled", True)), "normalize": bool(s.get("normalize", True)),
            "smooth": round(_clamp(s.get("smooth", DEFAULTS["smooth"])), 3),
            "tone": round(_clamp(s.get("tone", DEFAULTS["tone"])), 3),
            "sharpen": round(_clamp(s.get("sharpen", DEFAULTS["sharpen"])), 3)}


def save(s: dict) -> dict:
    s = normalize(s)
    _path().write_text(json.dumps(s, ensure_ascii=False, indent=1), encoding="utf-8")
    return s


def _tone_filter(strength: float) -> str:
    from . import grading

    return grading.tone_filter(strength)


def filters(s: dict | None = None) -> dict:
    """返回局部磨皮强度和 FFmpeg 的锐化、调色滤镜。"""
    s = normalize(current() if s is None else s)
    out = {"normalize": False, "smooth": 0.0, "sharpen": "", "tone": ""}
    if not s["enabled"]:
        return out
    out["normalize"] = s["normalize"]
    out["smooth"] = s["smooth"]
    if s["sharpen"] > 0.01:
        out["sharpen"] = f"unsharp=lx=5:ly=5:la={0.45 * s['sharpen']:.2f}:cx=5:cy=5:ca=0"
    if s["tone"] > 0.01:
        out["tone"] = _tone_filter(s["tone"])
    return out


# ---------------- 对比预览 ----------------

def _preview_dir() -> Path:
    d = config.data_root() / "preview" / "look"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _framing(width: int, height: int, zoom: float) -> str:
    return (f"crop='min(iw,ih*{width}/{height})/{zoom}':'min(ih,iw*{height}/{width})/{zoom}',"
            f"scale={width}:{height}:flags=lanczos")


def _grab_gray(clip: Path, t: float, framing: str, w: int, h: int):
    import numpy as np

    r = cancellation.run_process([config.ffmpeg(), "-hide_banner", "-loglevel", "error", "-ss", f"{t:.2f}", "-i", str(clip),
                        "-frames:v", "1", "-vf", framing, "-f", "rawvideo", "-pix_fmt", "gray", "-"], capture_output=True)
    return np.frombuffer(r.stdout, np.uint8).reshape(h, w) if len(r.stdout) == w * h else None


def _candidate_times(batch: str) -> list[tuple[str, float]]:
    """预览候选时间点：优先取这一批剪辑脚本里真正用到的句子（每句取 3 个点）；还没出脚本就均匀扫前 12 条素材。"""
    from . import media, script as scriptmod

    pts: list[tuple[str, float]] = []
    for sc in scriptmod.list_scripts(batch):
        for line in sc.get("lines", []):
            a, b = float(line["start"]), float(line["end"])
            for frac in (0.25, 0.5, 0.75):
                pts.append((line["clip"], round(a + (b - a) * frac, 2)))
    if not pts:
        for clip in media.list_clips(config.material_root() / batch)[:12]:
            dur = media.probe(clip).duration
            pts += [(clip.name, round(dur * f, 2)) for f in (0.1, 0.3, 0.5, 0.7, 0.9)]
    seen, out = set(), []
    for c, t in pts:                                   # 同一条素材 2 秒内的点只留一个
        key = (c, round(t / 2))
        if key not in seen:
            seen.add(key)
            out.append((c, t))
    return out[:120]


def sample_frames(batch: str) -> dict:
    """这一批素材里挑预览用的帧，每种最多 5 帧，按清晰度排好（第一帧最好）。结果有缓存。
    face：有正脸、脸够大、脸部最清楚；watch：没有人脸、画面中间细节最多（手表特写对上焦、手没在晃）。"""
    import cv2

    cache = _preview_dir() / f"frames_{batch}_v3.json"
    if cache.exists():
        return json.loads(cache.read_text(encoding="utf-8"))
    r = config.load()["render"]
    w, h = 270, 480
    framing = {"face": _framing(w, h, float(r["talk_zoom"])), "watch": _framing(w, h, float(r["product_zoom"]))}
    det = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    lap = lambda g: float(cv2.Laplacian(g, cv2.CV_64F).var())
    scored: dict[str, list] = {"face": [], "watch": []}
    folder = config.material_root() / batch
    for clip, t in _candidate_times(batch):
        g = _grab_gray(folder / clip, t, framing["watch"], w, h)
        if g is None:
            continue
        faces = det.detectMultiScale(g, scaleFactor=1.1, minNeighbors=6, minSize=(36, 36))
        if len(faces):
            g2 = _grab_gray(folder / clip, t, framing["face"], w, h)
            f2 = det.detectMultiScale(g2, scaleFactor=1.1, minNeighbors=6, minSize=(36, 36)) if g2 is not None else []
            if len(f2):
                x, y, fw, fh = max(f2, key=lambda q: q[2] * q[3])
                if fw >= w * 0.22 and y > 4:               # 脸够大、没被画面顶部切掉
                    scored["face"].append((lap(g2[y:y + fh, x:x + fw]) * (fw / w), clip, t))
        else:
            c = g[h // 5:h * 4 // 5, w // 6:w * 5 // 6]   # 手表通常在画面中间
            if c.mean() > 40:
                scored["watch"].append((lap(c), clip, t))
    found = {}
    for k, lst in scored.items():
        lst.sort(reverse=True)
        picked, used = [], set()
        for _, c, t in lst:                       # 每条素材最多一帧，「换一帧」能换到不同的表、不同的镜头
            if c in used:
                continue
            used.add(c)
            picked.append({"clip": c, "t": t})
            if len(picked) == 5:
                break
        found[k] = picked
    found = {k: v for k, v in found.items() if v}
    cache.write_text(json.dumps(found, ensure_ascii=False), encoding="utf-8")
    return found


def preview(batch: str, kind: str, s: dict | None = None, index: int = 0) -> dict:
    """出一组对比图：原片（只裁切缩放）和按设置美颜调色后的，返回文件名。kind = face / watch；index = 第几帧（换一帧）。"""
    r = config.load()["render"]
    W, H = r["width"], r["height"]
    frames = sample_frames(batch)
    if kind not in frames:
        kind = next(iter(frames), None)
        if kind is None:
            raise RuntimeError("这一批素材里找不到能预览的画面")
    cands = frames[kind]
    idx = int(index or 0) % len(cands)
    f = cands[idx]
    clip = config.material_root() / batch / f["clip"]
    z = float(r["talk_zoom"] if kind == "face" else r["product_zoom"])
    base = _framing(W, H, z)
    fl = filters(s)
    chain = base
    if fl["normalize"]:
        from . import normalize

        nf = normalize.segment_filter(clip, f["t"] - 1, 2)
        if nf:
            chain += "," + nf
    if kind != "face" and fl["sharpen"]:
        chain += "," + fl["sharpen"]
    if fl["tone"]:
        chain += "," + fl["tone"]
    d = _preview_dir()
    stamp = time.time_ns()
    orig = d / f"{batch}_{kind}_{idx}_v3_orig.jpg"
    out = d / f"{batch}_{kind}_look_{stamp}.jpg"
    for old in d.glob(f"{batch}_{kind}_look_*.jpg"):     # 只留最新一张
        old.unlink(missing_ok=True)
    show = "scale=720:1280:flags=lanczos"                  # 按出片分辨率处理（磨皮半径和成片一致），再缩小给页面看
    source = ["-ss", f"{f['t']:.2f}", "-i", str(clip)]
    if kind == "face":
        from . import skin

        if not orig.exists():
            skin.still([*source, "-vf", base], ["-vf", show, "-q:v", "2", str(orig)], W, H, 0)
        skin.still([*source, "-vf", chain], ["-vf", show, "-q:v", "2", str(out)], W, H, fl["smooth"])
    else:
        if not orig.exists():
            _ff([*source, "-frames:v", "1", "-vf", f"{base},{show}", "-q:v", "2", str(orig)])
        _ff([*source, "-frames:v", "1", "-vf", f"{chain},{show}", "-q:v", "2", str(out)])
    return {"kind": kind, "original": orig.name, "beauty": out.name, "frames": list(frames.keys()),
            "index": idx, "count": len(cands)}


def _ff(args: list[str]) -> None:
    r = cancellation.run_process([config.ffmpeg(), "-hide_banner", "-loglevel", "error", "-y", *args], capture_output=True, text=True,
                       encoding="utf-8", errors="ignore")
    if r.returncode:
        raise RuntimeError(f"预览图生成失败：{r.stderr[-600:]}")


_source_preview_lock = threading.Lock()


def preview_source(source: dict | None, kind: str, s: dict | None = None,
                   active_jobs: list[dict] | None = None) -> dict:
    # 相同缓存文件生成完成后才交给下一个请求，避免返回仍在写入的 JPEG。
    with _source_preview_lock:
        return _preview_source(source, kind, s, active_jobs)


def _preview_source(source: dict | None, kind: str, s: dict | None,
                    active_jobs: list[dict] | None) -> dict:
    """用未美颜的封面原图 / 内置默认图测试，素材删除后也能继续对比。"""
    import hashlib
    import shutil
    from . import look_sources

    selected = look_sources.resolve(source, active_jobs)
    kind = "watch" if kind == "watch" else "face"
    settings = normalize(current() if s is None else s)
    fl = filters(settings)
    r = config.load()["render"]
    W, H = r["width"], r["height"]
    stat = selected.image.stat()
    identity = [str(selected.image), stat.st_mtime_ns, stat.st_size, W, H]
    digest = lambda value: hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()[:24]
    d = _preview_dir()
    original = d / f"source_{digest(identity)}_original.jpg"
    # 滤镜算法变化时，同一组滑块也要重新计算，不能继续显示旧的偏色预览。
    beauty = d / f"source_{digest([identity, selected.normalization, settings, kind, fl])}_beauty.jpg"
    base = f"scale={W}:{H}:flags=lanczos"
    show = "scale=720:1280:flags=lanczos"
    if not original.is_file():
        _ff(["-i", str(selected.image), "-frames:v", "1", "-vf", f"{base},{show}", "-q:v", "2", str(original)])
    if not beauty.is_file():
        chain = base
        if fl["normalize"] and selected.normalization:
            # 保存的旧校正使用 16–235 的视频亮度；JPEG 必须先转成相同范围。
            chain += ",scale=in_range=auto:out_range=tv,format=yuv444p," + selected.normalization
        if kind == "watch" and fl["sharpen"]:
            chain += "," + fl["sharpen"]
        if fl["tone"]:
            chain += "," + fl["tone"]
        if chain == base and (kind != "face" or not fl["smooth"]):
            shutil.copyfile(original, beauty)
        elif kind == "face" and fl["smooth"]:
            from . import skin

            skin.still(["-i", str(selected.image), "-vf", chain],
                       ["-vf", show, "-q:v", "2", str(beauty)], W, H, fl["smooth"])
        else:
            _ff(["-i", str(selected.image), "-frames:v", "1", "-vf", f"{chain},{show}", "-q:v", "2", str(beauty)])
    return {"kind": kind, "original": original.name, "beauty": beauty.name,
            "frames": ["face", "watch"], "index": 0, "count": 1,
            "source": selected.origin, "fallback": selected.fallback}
