"""按已确认的剪辑脚本出片。

流程：逐段裁切（竖屏 1440×2560、特写放大、换配音）→ 拼接 → 烧字幕和角标、混背景音乐 → 导出 MP4。
"""
from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np

from . import config, media, script as scriptmod, tts

PUNCT_STRIP = "，。,.！!？?、；;：: "


@dataclass
class Segment:
    clip: Path
    v_start: float
    v_dur: float
    tts_wav: Path | None = None           # None 表示用原声
    subs: list[tuple[float, float, str]] = field(default_factory=list)  # 相对本段开头的时间
    zoom: float | None = None


# ---------------- 字幕切分 ----------------

def split_subtitle(text: str, max_chars: int) -> list[str]:
    """按逗号和长度把一句字幕切成屏幕上一次显示的小段（每段最多两行）。"""
    text = text.strip()
    parts, buf = [], ""
    for ch in text:
        buf += ch
        if ch in "，,、；;":
            parts.append(buf)
            buf = ""
    if buf:
        parts.append(buf)
    out: list[str] = []
    limit = max_chars * 2
    for p in parts:
        p = p.strip(PUNCT_STRIP)
        if not p:
            continue
        if out and len(out[-1]) + len(p) <= max_chars:
            out[-1] = out[-1] + " " + p      # 很短的分句合并显示
            continue
        while len(p) > limit:                  # 两行放不下：在合适的地方分屏
            i = _best_break(p, len(p) // 2 - 4, min(limit, len(p) // 2 + 4))
            out.append(p[:i])
            p = p[i:]
        out.append(p)
    return out or [text]


def timed_chunks(text: str, t0: float, t1: float, max_chars: int) -> list[tuple[float, float, str]]:
    chunks = split_subtitle(text, max_chars)
    total = sum(len(c) for c in chunks) or 1
    res, t = [], t0
    for c in chunks:
        d = (t1 - t0) * len(c) / total
        res.append((t, t + d, c))
        t += d
    return res


BREAK_AFTER = set("嘅咧啊啦呢嘞喎㗎噶话系的只同又而就都，、")


def _best_break(text: str, lo: int, hi: int) -> int:
    """在 [lo, hi] 里挑一个断点：优先在语气词、助词后面，靠近中间，不拆开数字和英文。"""
    n = len(text)
    mid = n / 2
    cands = [i for i in range(max(1, lo), min(n - 1, hi) + 1)
             if not (text[i - 1].isascii() and text[i - 1].isalnum() and text[i].isascii() and text[i].isalnum())]
    if not cands:
        return max(1, min(n - 1, round(mid)))
    preferred = [i for i in cands if text[i - 1] in BREAK_AFTER]
    return min(preferred or cands, key=lambda i: (abs(i - mid), -i))


def wrap_line(text: str, max_chars: int) -> str:
    """超过一行的字幕拆成两行（ASS 用 \\N），每行最多 max_chars+1 个字。"""
    text = text.replace(" ", "")
    if len(text) <= max_chars:
        return text
    hi = max_chars + 1
    i = _best_break(text, len(text) - hi, hi)
    return text[:i] + r"\N" + text[i:]


# ---------------- 镜头判断 ----------------

_face = None


def has_face(clip: Path, t: float) -> bool:
    global _face
    if _face is None:
        _face = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    r = subprocess.run([config.ffmpeg(), "-hide_banner", "-loglevel", "error", "-ss", f"{t:.3f}", "-i", str(clip),
                        "-frames:v", "1", "-vf", "scale=540:-2", "-f", "image2pipe", "-vcodec", "png", "-"],
                       capture_output=True)
    if not r.stdout:
        return False
    img = cv2.imdecode(np.frombuffer(r.stdout, np.uint8), cv2.IMREAD_GRAYSCALE)
    faces = _face.detectMultiScale(img, scaleFactor=1.1, minNeighbors=6, minSize=(60, 60))
    return len(faces) > 0


# ---------------- 规划分段 ----------------

def plan(script: dict, progress=None) -> list[Segment]:
    cfg = config.load()
    max_chars = cfg["style"]["subtitle"]["max_chars_per_line"]
    mode = scriptmod.resolved_voice_mode(script)
    material = config.material_root() / script["batch"]
    segs: list[Segment] = []

    if mode == "original":
        # 同一条素材里间隔很短的相邻句子合并成一段，避免碎切
        group: list[dict] = []
        groups: list[list[dict]] = []
        for l in script["lines"]:
            if group and (l["clip"] != group[-1]["clip"] or l["start"] - group[-1]["end"] > 0.35
                          or l["start"] < group[-1]["end"] - 0.01 or l.get("zoom") != group[-1].get("zoom")):
                groups.append(group)
                group = []
            group.append(l)
        if group:
            groups.append(group)
        for g in groups:
            v0 = max(0.0, g[0]["start"] - 0.08)
            v1 = g[-1]["end"] + 0.12
            seg = Segment(clip=material / g[0]["clip"], v_start=v0, v_dur=v1 - v0, zoom=g[0].get("zoom"))
            for l in g:
                seg.subs += timed_chunks(l["subtitle"], l["start"] - v0, l["end"] - v0, max_chars)
            segs.append(seg)
    else:
        from . import voice

        ref_wav = voice.reference_for(script)     # 老板原声参考（脚本里选了“固定音色”时为 None）
        if ref_wav and script.get("id"):
            scriptmod.save(script)                 # 记下选中的原声片段，下次出片同一个声音
        for i, l in enumerate(script["lines"]):
            if progress:
                progress(i, len(script["lines"]), f"配音 {i + 1}/{len(script['lines'])}")
            wav = tts.synthesize(l["subtitle"], script.get("tts_engine"), ref_wav, (script.get("voice_ref") or {}).get("lang"))
            d = tts.wav_duration(wav)
            seg = Segment(clip=material / l["clip"], v_start=max(0.0, l["start"] - 0.05), v_dur=d + 0.18,
                          tts_wav=wav, zoom=l.get("zoom"))
            seg.subs = timed_chunks(l["subtitle"], 0.02, d, max_chars)
            segs.append(seg)

    rcfg = cfg["render"]
    for s in segs:
        if s.zoom is None:
            s.zoom = rcfg["talk_zoom"] if has_face(s.clip, s.v_start + s.v_dur / 2) else rcfg["product_zoom"]
    return segs


# ---------------- 编码 ----------------

def _venc() -> list[str]:
    r = config.load()["render"]
    if r["encoder"] == "h264_nvenc":
        return ["-c:v", "h264_nvenc", "-preset", "p5", "-rc", "vbr", "-b:v", r["bitrate"], "-maxrate", "40M",
                "-bufsize", "40M", "-profile:v", "high"]
    return ["-c:v", "libx264", "-preset", "medium", "-crf", "17"]


def encode_segment(seg: Segment, out: Path) -> None:
    r = config.load()["render"]
    W, H, fps = r["width"], r["height"], r["fps"]
    z = max(1.0, float(seg.zoom or 1.0))
    # 先按输出比例裁成 9:16，再按放大倍数从中心裁小，最后缩放到输出尺寸
    vf = (f"crop='min(iw,ih*{W}/{H})/{z}':'min(ih,iw*{H}/{W})/{z}',"
          f"scale={W}:{H}:flags=lanczos,fps={fps},setsar=1,format=yuv420p,"
          f"tpad=stop_mode=clone:stop_duration=3")
    args = ["-ss", f"{seg.v_start:.3f}", "-t", f"{seg.v_dur + 0.5:.3f}", "-i", str(seg.clip)]
    if seg.tts_wav:
        args += ["-i", str(seg.tts_wav)]
        af = "[1:a]aresample=48000,aformat=channel_layouts=stereo,apad[a]"
    else:
        af = "[0:a]aresample=48000,aformat=channel_layouts=stereo,apad[a]"
    args += ["-filter_complex", f"[0:v]{vf}[v];{af}", "-map", "[v]", "-map", "[a]",
             "-t", f"{seg.v_dur:.3f}", *_venc(), "-c:a", "aac", "-b:a", "256k", str(out)]
    media.run_ffmpeg(args)


def _ass_time(t: float) -> str:
    t = max(0.0, t)
    h, rem = divmod(t, 3600)
    m, s = divmod(rem, 60)
    return f"{int(h)}:{int(m):02d}:{s:05.2f}"


def build_ass(segs: list[Segment], total: float, path: Path) -> None:
    cfg = config.load()
    st, r = cfg["style"], cfg["render"]
    W, H = r["width"], r["height"]
    sub, slo, dis = st["subtitle"], st["slogan"], st["disclaimer"]
    font = st["font_name"]
    bold = -1 if st.get("font_bold") else 0
    y_sub = int(H * sub["y_ratio"])
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Sub,{font},{sub['size']},{sub['color']},&H000000FF,{sub['outline_color']},&H64000000,{bold},0,0,0,100,100,2,0,1,{sub['outline']},2,5,60,60,0,1
Style: Slogan,{font},{slo['size']},{slo['color']},&H000000FF,{slo['outline_color']},&H64000000,{bold},0,0,0,100,100,0,0,1,6,2,7,0,0,0,1
Style: Disc,{font},{dis['size']},{dis['color']},&H000000FF,{dis['outline_color']},&H64000000,{bold},0,0,0,100,100,2,0,1,6,0,5,0,0,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    ev = []
    end = _ass_time(total)
    for ci, col in enumerate(slo["columns"]):
        x = slo["x"] + ci * int(slo["column_gap"])
        ev.append(f"Dialogue: 1,0:00:00.00,{end},Slogan,,0,0,0,,{{\\pos({x},{slo['y']})}}" + r"\N".join(col))
    ev.append(f"Dialogue: 1,0:00:00.00,{end},Disc,,0,0,0,,{{\\pos({W // 2},{int(H * dis['y_ratio'])})}}{dis['text']}")
    t = 0.0
    for s in segs:
        for a, b, text in s.subs:
            a2, b2 = t + a, min(t + b, t + s.v_dur)
            if b2 - a2 < 0.05:
                continue
            ev.append(f"Dialogue: 2,{_ass_time(a2)},{_ass_time(b2)},Sub,,0,0,0,,"
                      f"{{\\pos({W // 2},{y_sub})}}{wrap_line(text, sub['max_chars_per_line'])}")
        t += s.v_dur
    path.write_text(header + "\n".join(ev) + "\n", encoding="utf-8")


def render(script: dict, progress=None) -> Path:
    cfg = config.load()
    work = config.data_root() / "renders" / script["batch"] / script["id"]
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)

    segs = plan(script, progress)
    seg_files = []
    for i, s in enumerate(segs):
        if progress:
            progress(i, len(segs), f"剪辑片段 {i + 1}/{len(segs)}")
        f = work / f"seg_{i:03d}.mp4"
        encode_segment(s, f)
        seg_files.append(f)

    (work / "concat.txt").write_text("".join(f"file '{f.name}'\n" for f in seg_files), encoding="utf-8")
    media.run_ffmpeg(["-f", "concat", "-safe", "0", "-i", str(work / "concat.txt"), "-c", "copy",
                      str(work / "body.mp4")])

    total = sum(s.v_dur for s in segs)
    build_ass(segs, total, work / "video.ass")
    shutil.copytree(cfg["style"]["font_dir"], work / "fonts")

    if progress:
        progress(len(segs), len(segs), "合成字幕与音乐")
    out_dir = config.data_root() / "outputs" / script["batch"]
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{script['id']}.mp4"

    r = cfg["render"]
    inputs = ["-i", "body.mp4"]
    voice = "[0:a]loudnorm=I=-15:TP=-1.5:LRA=9,aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo[voice]"
    if r.get("bgm"):
        inputs += ["-stream_loop", "-1", "-i", str(Path(r["bgm"]).resolve())]
        afx = (f"{voice};[voice]asplit=2[v1][v2];"
               f"[1:a]aresample=48000,aformat=channel_layouts=stereo,volume={r['bgm_volume']}[bg];"
               f"[bg][v1]sidechaincompress=threshold=0.05:ratio=6:attack=20:release=400[duck];"
               f"[v2][duck]amix=inputs=2:duration=first:normalize=0[aout]")
    else:
        afx = voice.replace("[voice]", "[aout]")
    filt = f"[0:v]subtitles=video.ass:fontsdir=fonts[vout];{afx}"
    cmd = [cfg["paths"]["ffmpeg"], "-hide_banner", "-loglevel", "error", "-y", *inputs,
           "-filter_complex", filt, "-map", "[vout]", "-map", "[aout]", "-t", f"{total:.3f}",
           *_venc(), "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(out.resolve())]
    res = subprocess.run(cmd, cwd=work, capture_output=True, text=True, encoding="utf-8", errors="ignore")
    if res.returncode != 0:
        raise RuntimeError(f"合成失败：{res.stderr[-2000:]}")

    meta = {"script": script["id"], "duration": round(total, 2), "segments": len(segs),
            "voice_mode": scriptmod.resolved_voice_mode(script), "output": str(out)}
    (work / "render.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    return out
