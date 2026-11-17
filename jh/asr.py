"""语音识别：VAD 切段 → SenseVoice 识别（带语种和逐字时间戳）→ 按标点切句。

输出 transcript.json，结构：
{
  "clip": "xxx.MOV", "duration": 117.2,
  "sentences": [
    {"start": 1.23, "end": 3.45, "lang": "yue", "text": "呢两只表呢，"}
  ]
}
时间单位都是秒，相对原素材开头。
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

import numpy as np
import soundfile as sf

from . import config, media

LANG_TAGS = {"yue", "zh", "en", "ja", "ko", "nospeech"}
PUNCT = "，。？！、,.?!；;：:"
SENT_END = "。？！.?!"


@lru_cache(maxsize=1)
def _models():
    from funasr import AutoModel

    cfg = config.load()["asr"]
    dev = cfg["device"]
    vad = AutoModel(model=cfg["vad_dir"], device=dev, disable_update=True,
                    max_single_segment_time=cfg["vad_max_segment_ms"])
    sv = AutoModel(model=cfg["sensevoice_dir"], device=dev, disable_update=True)
    return vad, sv


TRANSCRIPT_VERSION = 2       # 2：每句带逐字时间（words），用来在句子里面剪掉口误和停顿


def _parse_tags(text: str) -> tuple[str, str]:
    tags = re.findall(r"<\|([^|]+)\|>", text)
    lang = next((t for t in tags if t in LANG_TAGS), "unknown")
    clean = re.sub(r"<\|[^|]+\|>", "", text).strip()
    return lang, clean


def _split_sentences(words: list[str], ts: list[list[int]], offset: float, lang: str) -> list[dict]:
    """把逐字时间戳按标点切成句子。words/ts 来自 SenseVoice，ts 单位毫秒。"""
    out, cur, cur_s, cur_e, cur_w = [], "", None, None, []
    for w, (s, e) in zip(words, ts):
        if cur_s is None:
            cur_s = s
        cur += w
        cur_e = e
        cur_w.append([w, round(offset + s / 1000, 3), round(offset + e / 1000, 3)])   # 逐字时间：剪口误、剪停顿要用
        if w and w[-1] in PUNCT and len(cur.strip(PUNCT)) >= 4 or (w and w[-1] in SENT_END):
            out.append({"start": round(offset + cur_s / 1000, 3), "end": round(offset + cur_e / 1000, 3),
                        "lang": lang, "text": cur, "words": cur_w})
            cur, cur_s, cur_w = "", None, []
    if cur.strip(PUNCT):
        out.append({"start": round(offset + cur_s / 1000, 3), "end": round(offset + cur_e / 1000, 3),
                    "lang": lang, "text": cur, "words": cur_w})
    return out


def transcribe_clip(clip: Path, out_dir: Path) -> dict:
    out_json = out_dir / f"{clip.stem}.json"
    if out_json.exists():
        old = json.loads(out_json.read_text(encoding="utf-8"))
        if old.get("v", 1) >= TRANSCRIPT_VERSION:
            return old                              # 旧版识别结果没有逐字时间，重新识别一次（几秒钟一条）

    info = media.probe(clip)
    wav = media.extract_audio_16k(clip, out_dir / "audio16k" / f"{clip.stem}.wav")
    audio, sr = sf.read(str(wav), dtype="float32")
    vad, sv = _models()

    segs = vad.generate(input=audio, fs=sr)[0]["value"]  # [[start_ms, end_ms], ...]，直接传数组，不依赖系统 ffmpeg
    sentences = []
    for s_ms, e_ms in segs:
        chunk = audio[int(s_ms * sr / 1000): int(e_ms * sr / 1000)]
        if len(chunk) < sr * 0.3:
            continue
        r = sv.generate(input=chunk, cache={}, language="auto", use_itn=True,
                        output_timestamp=True, ban_emo_unk=True)[0]
        lang, text = _parse_tags(r["text"])
        if not text or lang == "nospeech":
            continue
        words, ts = r.get("words"), r.get("timestamp")
        if words and ts and len(words) == len(ts):
            sentences += _split_sentences(words, ts, s_ms / 1000, lang)
        else:
            sentences.append({"start": s_ms / 1000, "end": e_ms / 1000, "lang": lang, "text": text})

    result = {
        "v": TRANSCRIPT_VERSION,
        "clip": clip.name,
        "path": str(clip),
        "duration": round(info.duration, 3),
        "width": info.width,
        "height": info.height,
        "fps": info.fps,
        "sentences": sentences,
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    return result


def transcribe_folder(folder: Path, out_dir: Path, progress=None) -> list[dict]:
    clips = media.list_clips(folder)
    results = []
    for i, c in enumerate(clips):
        if progress:
            progress(i, len(clips), c.name)
        results.append(transcribe_clip(c, out_dir))
    if progress:
        progress(len(clips), len(clips), "完成")
    return results


def lang_stats(results: list[dict]) -> dict:
    tot: dict[str, float] = {}
    for r in results:
        for s in r["sentences"]:
            tot[s["lang"]] = tot.get(s["lang"], 0) + (s["end"] - s["start"])
    return {k: round(v, 1) for k, v in sorted(tot.items(), key=lambda x: -x[1])}
