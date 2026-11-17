"""整条视频转粤语（不剪辑）。

适合已经剪好的普通话成片：画面原样保留，只把声音和字幕换成粤语。
流程：语音识别（逐句时间） → 大模型逐句翻成粤语口语（按原句时长控制字数） → Demucs 把原声里的人声和背景音乐分开
→ 从分离出的人声里截一段做参考，克隆原主播的声音配粤语 → 每句对齐到原来的时间点（太长就稍微加快）
→ 背景音乐 + 粤语配音混音 → 模糊掉原来烧在画面里的普通话字幕，压上粤语字幕、左上角黄字、底部声明 → 导出。

中间结果都在 data/dub/<批次>/<素材名>/，翻译、分离、配音都有缓存，改了翻译重跑很快。
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import numpy as np
import soundfile as sf

from . import asr, config, llm, media, render, script as scriptmod, tts, voice

SR = 48000
ENGINE_NAMES = {"ming": "Ming", "cosyvoice3": "CosyVoice3", "azure": "Azure"}

SYSTEM = """你是一名香港短视频配音翻译。你会收到一条普通话短视频的逐句语音识别结果（带每句的时长和字数），
要把每一句翻成地道的粤语口语，用来配音和做字幕。画面里主播的嘴是按普通话原句在动，配音要尽量跟上他的嘴型。

规则：
- 写成粤语口语书面字，用简体字：呢、嘅、系、唔、畀、啲、咗、嚟、佢、哋、冇、睇、嘢、咁、噉、喺、嗰、乜、点解。
- 意思不变，语气保留（主播带货的口吻，亲切、节奏快）；普通话俗语换成粤语习惯说法（例如“踩缝纫机”→“踩衣车”，“挣”→“赚”，“看一看”→“睇下”）。
- 字数要贴近原句：每句粤语的字数落在方括号里给的范围内（和普通话原句的字数基本一样，一个字就是嘴巴动一下）。
  不要精简、不要删内容；原句里的“呢”“啊”“那么”这类口头语也照样翻出来（换成粤语的“咧”“啊”“噉”），主播说这些字的时候嘴也在动。
  粤语通常比普通话短，字数不够时用自然的粤语口语补足（例如“系咪”“嘅话”“啦”），但不要加原句没有的意思。
- 一个编号翻成一句，不要合并、不要拆分、不要漏；句末不加句号，可以保留逗号。
- 语音识别有错字，结合上下文和下面的常见错字表改正；品牌、表款写正确的中文名（例如 百达翡丽、江诗丹顿、劳力士）。
- 数字照原意写阿拉伯数字或中文都可以；价格里的“万”照写。
{glossary}
只输出 JSON：{{"lines": [{{"i": 0, "yue": "粤语"}}, ...]}}"""


def work_dir(batch: str, clip: str) -> Path:
    d = config.data_root() / "dub" / batch / Path(clip).stem
    d.mkdir(parents=True, exist_ok=True)
    return d


def _cfg() -> dict:
    return config.load()["dub"]


# ---------------- 1. 翻译 ----------------

TRANSLATE_VERSION = "v2-syllables"       # 翻译规则改了就换这个，旧的翻译缓存自动作废


def _syllables(text: str) -> int:
    """普通话/粤语的音节数：一个汉字一个音节，数字和字母按个数粗算。"""
    return sum(1 for ch in text if ch.isalnum())


def _budgets(t: dict) -> list[tuple[float, int, int, int]]:
    """每句：（时长, 原句字数, 粤语最少字数, 粤语最多字数）。"""
    cps_max = float(_cfg().get("max_chars_per_second", 6.5))
    s, out = t["sentences"], []
    for i, x in enumerate(s):
        nxt = s[i + 1]["start"] if i + 1 < len(s) else t["duration"]
        win = max(0.6, nxt - x["start"])
        n0 = max(1, _syllables(x["text"]))
        hi = max(2, min(n0 + 2, int(win * cps_max)))
        lo = max(1, min(hi, round(n0 * 0.85)))
        out.append((win, n0, lo, hi))
    return out


def translate(t: dict, wd: Path) -> list[str]:
    f = wd / "translation.json"
    sig = TRANSLATE_VERSION + "|" + "|".join(x["text"] for x in t["sentences"])
    if f.exists():
        d = json.loads(f.read_text(encoding="utf-8"))
        if d.get("sig") == sig:
            return d["lines"]
    cfg = config.load()["script"]
    gl = "\n".join(f"  - {g}" for g in cfg.get("glossary", []))
    system = SYSTEM.format(glossary=("常见错字表：\n" + gl) if gl else "")
    b = _budgets(t)
    rows = "\n".join(f"{i}. [{w:.1f} 秒，原句 {n0} 字，粤语写 {lo}–{hi} 字] {x['text']}"
                     for i, ((w, n0, lo, hi), x) in enumerate(zip(b, t["sentences"])))
    msgs = [{"role": "system", "content": system}, {"role": "user", "content": rows}]
    last = ""
    for _ in range(3):
        if last:
            msgs = msgs[:2] + [{"role": "user", "content": f"上一次的输出有问题：{last}。请修正后重新输出完整 JSON。"}]
        text = llm.chat(msgs, json_mode=True, temperature=0.4, max_tokens=6000)
        try:
            got = {int(x["i"]): str(x["yue"]).strip() for x in scriptmod._extract_json(text)["lines"]}
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as e:
            last = f"JSON 格式错误：{e}"
            continue
        lines = [got.get(i, "") for i in range(len(t["sentences"]))]
        miss = [i for i, x in enumerate(lines) if not x]
        short = [i for i, (x, (_, n0, lo, hi)) in enumerate(zip(lines, b)) if _syllables(x) < lo - 1]
        long = [i for i, (x, (_, n0, lo, hi)) in enumerate(zip(lines, b)) if _syllables(x) > hi + 2]
        if miss:
            last = f"第 {miss} 句没有翻译"
            continue
        if short or long:
            last = "；".join(([f"第 {short} 句字数太少，要接近原句字数，不要精简"] if short else []) +
                            ([f"第 {long} 句字数太多"] if long else []))
            continue
        f.write_text(json.dumps({"sig": sig, "lines": lines}, ensure_ascii=False, indent=1), encoding="utf-8")
        return lines
    raise RuntimeError(f"翻译不合格：{last}")


# ---------------- 2. 人声 / 背景分离 ----------------

def separate(clip_path: Path, wd: Path, progress=None) -> tuple[Path, Path]:
    """Demucs 分离：返回（人声, 背景音乐和环境声），都是 44.1kHz 立体声。"""
    voc, bg = wd / "vocals.wav", wd / "background.wav"
    if voc.exists() and bg.exists():
        return voc, bg
    src = wd / "original.wav"
    media.run_ffmpeg(["-i", str(clip_path), "-vn", "-ac", "2", "-ar", "44100", "-c:a", "pcm_s16le", str(src)])
    if progress:
        progress(0, 1, "分离人声和背景音乐（Demucs）")
    import torch
    from demucs.apply import apply_model
    from demucs.pretrained import get_model

    model = get_model(_cfg().get("demucs_model", "htdemucs"))
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    model.to(dev).eval()
    y, sr = sf.read(str(src), dtype="float32", always_2d=True)
    wav = torch.from_numpy(y.T.copy())
    ref = wav.mean(0)
    mean, std = ref.mean(), ref.std() + 1e-8
    with torch.no_grad():
        out = apply_model(model, ((wav - mean) / std)[None].to(dev), device=dev, shifts=1, split=True, overlap=0.25, progress=False)[0]
    out = (out * std + mean).cpu().numpy()
    names = list(model.sources)
    vocals = out[names.index("vocals")]
    rest = sum(out[i] for i, n in enumerate(names) if n != "vocals")
    sf.write(str(voc), vocals.T, sr)
    sf.write(str(bg), rest.T, sr)
    del model, out
    if dev == "cuda":
        torch.cuda.empty_cache()
    return voc, bg


# ---------------- 3. 配音 ----------------

def _voice_ref(t: dict, vocals: Path, wd: Path) -> tuple[Path, str]:
    """从分离出的干净人声里截一段 6–12 秒连续讲话，当克隆原主播声音的参考。"""
    cands = sorted(voice._candidates(t), key=lambda x: -x[0])
    if not cands:
        raise RuntimeError("找不到足够长的连续讲话来克隆声音")
    c = cands[0][1]
    out = wd / f"voice_ref_{c['start']:.2f}_{c['end']:.2f}.wav"
    if not out.exists():
        media.run_ffmpeg(["-ss", f"{c['start']:.3f}", "-t", f"{c['end'] - c['start']:.3f}", "-i", str(vocals), "-ac", "1", "-ar", "24000",
                          "-af", "highpass=f=70,lowpass=f=11000,loudnorm=I=-18:TP=-2:LRA=7", "-c:a", "pcm_s16le", str(out)])
    return out, ("yue" if c["lang"] == "yue" else "zh")


def _load48(path: Path, speed: float = 1.0, channels: int = 1) -> np.ndarray:
    """读成 48kHz（默认单声道，channels=2 返回 [n, 2]）；speed≠1 时用 atempo 变速（不变调）。"""
    af = f"atempo={speed:.4f}," if abs(speed - 1.0) > 0.01 else ""
    r = subprocess.run([config.ffmpeg(), "-hide_banner", "-loglevel", "error", "-i", str(path), "-af", f"{af}aresample={SR}",
                        "-ac", str(channels), "-f", "f32le", "-"], capture_output=True)
    if r.returncode:
        raise RuntimeError(r.stderr.decode("utf-8", "ignore")[-500:])
    y = np.frombuffer(r.stdout, dtype=np.float32).copy()
    return y.reshape(-1, channels) if channels > 1 else y


def _trim(y: np.ndarray, thr_db: float = -40.0) -> np.ndarray:
    """去掉配音前后的静音，对齐时按真正开口和闭口的时间算。"""
    frame = int(0.01 * SR)
    n = len(y) // frame
    if n == 0:
        return y
    e = np.sqrt((y[: n * frame].reshape(n, frame) ** 2).mean(1))
    idx = np.where(e > e.max() * 10 ** (thr_db / 20))[0]
    if not len(idx):
        return y
    return y[max(0, idx[0] - 2) * frame: min(len(y), (idx[-1] + 3) * frame)]


def build_voice(t: dict, lines: list[str], engine: str, ref: Path | None, ref_lang: str | None, wd: Path,
                progress=None) -> tuple[np.ndarray, list[dict]]:
    """逐句配音并对齐原句：每句粤语都变速（min_speed–max_speedup 倍）到正好占满原来那句普通话说话的时长，
    主播嘴在动的时候有声音、停下来的时候没声音；实在放不下才压到下一句前面一点，再不行顺延。"""
    s = t["sentences"]
    c = _cfg()
    max_speed = float((c.get("max_speedup_by_engine") or {}).get(engine, c["max_speedup"]))   # 有的引擎天生说得慢
    min_speed = float(c.get("min_speed", 0.85))
    tmp = wd / f"lines_{engine}"
    tmp.mkdir(exist_ok=True)
    use_ref = ref if engine in ("ming", "cosyvoice3") else None       # Azure 不能克隆声音
    placed, parts, prev_end = [], [], 0.0
    for i, (x, text) in enumerate(zip(s, lines)):
        if progress:
            progress(i, len(s), f"{ENGINE_NAMES.get(engine, engine)} 粤语配音 {i + 1}/{len(s)}")
        wav = tts.synthesize(text, engine, use_ref, ref_lang if use_ref else None)
        y = _trim(_load48(wav))
        d = len(y) / SR
        nxt = s[i + 1]["start"] if i + 1 < len(s) else t["duration"]
        start = max(x["start"], prev_end + 0.04)
        target = max(0.3, x["end"] - start)                           # 原句说话的时长
        speed = min(max_speed, max(min_speed, d / target))
        if start + d / speed > nxt + 0.15:                             # 还会压到下一句：再快一点
            speed = min(max_speed, max(speed, d / max(0.3, nxt + 0.15 - start)))
        if abs(speed - 1.0) > 0.01:
            f = tmp / f"{i:03d}.wav"
            sf.write(str(f), y, SR)
            y = _load48(f, speed)
        dur = len(y) / SR
        placed.append({"i": i, "text": text, "start": round(start, 3), "end": round(start + dur, 3), "speed": round(speed, 3),
                       "orig": [round(x["start"], 3), round(x["end"], 3)]})
        parts.append((start, y))
        prev_end = start + dur
    total = max(t["duration"], prev_end + 0.3)
    track = np.zeros(int(total * SR) + SR, dtype=np.float32)
    for st, y in parts:
        a = int(st * SR)
        track[a:a + len(y)] += y
    (wd / f"timing_{engine}.json").write_text(json.dumps(placed, ensure_ascii=False, indent=1), encoding="utf-8")
    return track[: int(total * SR)], placed


def _rms(y: np.ndarray) -> float:
    y = y[np.abs(y) > 1e-4]
    return float(np.sqrt(np.mean(y ** 2))) if len(y) else 0.0


def mix(voice_track: np.ndarray, vocals: Path | None, background: Path | None, wd: Path, name: str = "mix.wav") -> Path:
    """粤语配音音量对齐原来的人声，再和背景音乐相加（保持原片的人声/音乐比例）。"""
    out = wd / name
    v = voice_track
    if vocals is not None:
        target = _rms(_load48(vocals))
        cur = _rms(v)
        if target > 0 and cur > 0:
            v = v * (target / cur)
    st = np.stack([v, v], axis=1)
    if background is not None:
        bg = _load48(background, channels=2)
        n = min(len(bg), len(st))
        st[:n] += bg[:n]
    peak = np.abs(st).max()
    if peak > 0.98:
        st *= 0.98 / peak
    sf.write(str(out), st, SR)
    return out


# ---------------- 4. 出片 ----------------

def render_video(clip_path: Path, mix_wav: Path, placed: list[dict], total: float, wd: Path, out: Path, progress=None,
                 tag: str = "") -> Path:
    cfg = config.load()
    r = cfg["render"]
    W, H, fps = r["width"], r["height"], r["fps"]
    max_chars = cfg["style"]["subtitle"]["max_chars_per_line"]
    cover = _cfg().get("cover_old_subtitles") or []

    seg = render.Segment(clip=clip_path, v_start=0.0, v_dur=total)
    subs = []
    for p in placed:
        subs += render.timed_chunks(p["text"], p["start"], p["end"], max_chars)
    if len(cover) == 4:
        # 有旧字幕要盖：两句之间停顿不长（≤2.5 秒）时，上一句字幕留到下一句出来，旧字幕一直被压住
        for k in range(len(subs)):
            a0, b0, text = subs[k]
            nxt = subs[k + 1][0] if k + 1 < len(subs) else total
            if nxt - b0 <= 2.5:
                subs[k] = (a0, nxt, text)
    seg.subs = subs
    work = wd / (f"render_{tag}" if tag else "render")
    if work.exists():
        shutil.rmtree(work)
    work.mkdir()
    y_ratio = (cover[1] + cover[3] / 2) if len(cover) == 4 else None    # 粤语字幕最后一行压在原字幕的位置上
    render.build_ass([seg], total, work / "video.ass", y_ratio=y_ratio, bottom_line=y_ratio is not None)
    shutil.copytree(cfg["style"]["font_dir"], work / "fonts")

    # 先裁成 9:16 → 模糊原来的字幕条（边缘羽化，不是硬框） → 放大到输出尺寸 → 烧粤语字幕和角标；配音比原片长时最后一帧定格
    inputs = ["-i", str(clip_path.resolve()), "-i", str(mix_wav.resolve())]
    chain = f"[0:v]crop='min(iw,ih*{W}/{H})':'min(ih,iw*{H}/{W})',scale={W}:{H}:flags=lanczos,setsar=1"
    if len(cover) == 4:
        import cv2

        x, y, w, h = cover
        F = 28                                                   # 羽化宽度（像素）
        bx, by, bw, bh = int(W * x) - F, int(H * y) - F, int(W * w) + 2 * F, int(H * h) + 2 * F
        bw, bh = bw - bw % 2, bh - bh % 2
        mask = np.zeros((bh, bw), np.float32)
        mask[F:bh - F, F:bw - F] = 1.0
        mask = cv2.GaussianBlur(mask, (0, 0), F / 2.5)
        mask = np.clip(mask / mask.max(), 0, 1)
        (work / "mask.png").write_bytes(cv2.imencode(".png", (mask * 255).astype(np.uint8))[1].tobytes())   # cv2.imwrite 不认中文路径
        inputs += ["-loop", "1", "-i", str((work / "mask.png").resolve())]
        chain += (f"[base];[base]split[a][b];[b]crop={bw}:{bh}:{bx}:{by},boxblur=luma_radius=24:luma_power=3,format=yuva420p[bl];"
                  f"[2:v]format=gray[m];[bl][m]alphamerge[blm];[a][blm]overlay={bx}:{by}:shortest=1")
    chain += f",fps={fps},tpad=stop_mode=clone:stop_duration=10,subtitles=video.ass:fontsdir=fonts,format=yuv420p[vout]"
    afx = "[1:a]loudnorm=I=-15:TP=-1.5:LRA=9,aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo[aout]"
    if progress:
        progress(0, 1, "合成画面、字幕和声音")
    cmd = [cfg["paths"]["ffmpeg"], "-hide_banner", "-loglevel", "error", "-y", *inputs,
           "-filter_complex", f"{chain};{afx}", "-map", "[vout]", "-map", "[aout]", "-t", f"{total:.3f}",
           *render._venc(), "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(out.resolve())]
    res = subprocess.run(cmd, cwd=work, capture_output=True, text=True, encoding="utf-8", errors="ignore")
    if res.returncode != 0:
        raise RuntimeError(f"合成失败：{res.stderr[-2000:]}")
    return out


def dub_clip(batch: str, clip: str, progress=None, engine: str | None = None) -> Path:
    engine = engine or config.load()["tts"]["engine"]
    if engine not in ENGINE_NAMES:
        raise ValueError(f"未知的配音引擎：{engine}")
    clip_path = config.material_root() / batch / clip
    wd = work_dir(batch, clip)
    tdir = config.data_root() / "transcripts" / batch
    tdir.mkdir(parents=True, exist_ok=True)
    if progress:
        progress(0, 1, "语音识别")
    t = asr.transcribe_clip(clip_path, tdir)
    t.setdefault("clip", clip)
    if not t["sentences"]:
        raise RuntimeError(f"{clip} 里没识别到讲话")
    if progress:
        progress(0, 1, "大模型逐句翻成粤语")
    lines = translate(t, wd)
    vocals = background = None
    if _cfg().get("keep_bgm", True):
        vocals, background = separate(clip_path, wd, progress)
    ref, ref_lang = _voice_ref(t, vocals or clip_path, wd)
    track, placed = build_voice(t, lines, engine, ref, ref_lang, wd, progress)
    total = len(track) / SR
    mix_wav = mix(track, vocals, background, wd, f"mix_{engine}.wav")
    out_dir = config.output_root() / batch
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{Path(clip).stem}_粤语_{ENGINE_NAMES[engine]}.mp4"
    render_video(clip_path, mix_wav, placed, total, wd, out, progress, tag=engine)
    meta = {"clip": clip, "engine": engine, "output": str(out), "duration": round(total, 2), "sentences": len(placed),
            "voice_ref": ref.name if engine != "azure" else None, "ref_lang": ref_lang,
            "max_speed": max(p["speed"] for p in placed), "min_speed": min(p["speed"] for p in placed)}
    (wd / f"dub_{engine}.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    return out


def dub_batch(batch: str, clips: list[str] | None = None, progress=None, engine: str | None = None) -> list[str]:
    names = clips or [p.name for p in media.list_clips(config.material_root() / batch)]
    outs = []
    for i, c in enumerate(names):
        def pr(a, b, m, i=i):
            if progress:
                progress(i, len(names), f"{c}：{m}" if len(names) > 1 else m)
        outs.append(str(dub_clip(batch, c, pr, engine)))
    return outs
