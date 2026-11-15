"""从原素材里自动截一段老板原声，当配音的参考音色（声音克隆）。

挑选规则：在这条视频用到的素材里，找一段 6–12 秒、句子之间停顿很短、几乎都是人声的连续讲话，
优先粤语（粤语口音更稳），没有粤语就用普通话（Ming 用普通话录音也能保留音色）。
截出来的音频做了去低频噪声和响度统一，存在 data/voice_refs/<批次>/。
"""
from __future__ import annotations

import json
from pathlib import Path

from . import config, media

MIN_SEC, MAX_SEC, GOOD_LO, GOOD_HI = 5.0, 12.0, 7.0, 11.0
MAX_GAP = 0.6


def _transcript(batch: str, clip: str) -> dict | None:
    f = config.data_root() / "transcripts" / batch / f"{Path(clip).stem}.json"
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else None


def _candidates(t: dict):
    s = t["sentences"]
    for i in range(len(s)):
        start = s[i]["start"]
        j = i + 1
        while j < len(s) and s[j]["start"] - s[j - 1]["end"] <= MAX_GAP and s[j]["end"] - start <= MAX_SEC:
            j += 1
        win = s[i:j]
        dur = win[-1]["end"] - start
        if dur < MIN_SEC:
            continue
        speech = sum(x["end"] - x["start"] for x in win)
        yue = sum(x["end"] - x["start"] for x in win if x["lang"] == "yue")
        zh = sum(x["end"] - x["start"] for x in win if x["lang"] == "zh")
        lang = "yue" if yue >= speech * 0.8 else "zh" if zh >= speech * 0.8 else "mixed"
        # 人声占比高、语种单一、时长在 7–11 秒最好；太靠片头片尾的容易有杂音
        score = (speech / dur) * 2 + (1.0 if lang == "yue" else 0.6 if lang == "zh" else 0)
        score += 0.5 if GOOD_LO <= dur <= GOOD_HI else 0
        score -= 0.3 if start < 1.0 or win[-1]["end"] > t["duration"] - 1.0 else 0
        yield score, {"clip": t["clip"], "start": round(max(0, start - 0.1), 2), "end": round(win[-1]["end"] + 0.15, 2),
                      "lang": lang, "text": "".join(x["text"] for x in win)}


def ranked(script: dict, limit: int = 6) -> list[dict]:
    """按好坏排好的候选片段（互不重叠）。先在这条视频用到的素材里找，找不到再在整批素材里找。"""
    batch = script["batch"]
    used = list(dict.fromkeys(l["clip"] for l in script["lines"]))
    for pool in (used, None):
        clips = pool if pool is not None else [p.name for p in media.list_clips(config.material_root() / batch)]
        cands = []
        for c in clips:
            t = _transcript(batch, c)
            if t:
                cands += list(_candidates(t))
        cands.sort(key=lambda x: -x[0])
        picked: list[dict] = []
        for _, c in cands:
            if any(p["clip"] == c["clip"] and not (c["end"] <= p["start"] or c["start"] >= p["end"]) for p in picked):
                continue
            picked.append(c)
            if len(picked) >= limit:
                break
        if picked:
            return picked
    return []


def pick(script: dict) -> dict | None:
    r = ranked(script, 1)
    return r[0] if r else None


def extract(batch: str, ref: dict) -> Path:
    """把选中的那段原声截成参考音频（单声道 24kHz，去低频噪声、统一响度）。"""
    out = config.data_root() / "voice_refs" / batch / f"{Path(ref['clip']).stem}_{ref['start']:.2f}_{ref['end']:.2f}.wav"
    if not out.exists():
        out.parent.mkdir(parents=True, exist_ok=True)
        media.run_ffmpeg(["-ss", f"{ref['start']:.3f}", "-t", f"{ref['end'] - ref['start']:.3f}",
                          "-i", str(config.material_root() / batch / ref["clip"]), "-vn", "-ac", "1", "-ar", "24000",
                          "-af", "highpass=f=70,lowpass=f=11000,loudnorm=I=-18:TP=-2:LRA=7", "-c:a", "pcm_s16le", str(out)])
    return out


def reference_for(script: dict) -> Path | None:
    """这条视频用来克隆的参考音频。脚本里记下选中的片段，之后每次出片都用同一段，声音不会变。"""
    if script.get("voice_source", "original") != "original":
        return None
    ref = script.get("voice_ref") or pick(script)
    if not ref:
        return None
    script["voice_ref"] = ref
    return extract(script["batch"], ref)
