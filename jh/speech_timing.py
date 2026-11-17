"""编码前的人声时间规则：保留自然短停顿，裁掉超过阈值的无人声间隔。"""
from __future__ import annotations

import hashlib
import json
import threading
from functools import lru_cache
from uuid import uuid4

import numpy as np

from . import config

_lock = threading.Lock()


@lru_cache(maxsize=1)
def _detector(model_path: str):
    from funasr import AutoModel

    # 单独使用已有的轻量 VAD，在 CPU 上判断人声，不加载识别模型或占用出片显存。
    detector = AutoModel(model=model_path, device="cpu", disable_update=True, disable_pbar=True)
    # 识别时默认前后扩展 200/100ms；剪辑切点不能把这部分误算成人声。
    detector.model.vad_opts.do_extend = True
    detector.model.vad_opts.lookback_time_start_point = 0
    detector.model.vad_opts.lookahead_time_end_point = 0
    detector.model.vad_opts.max_single_segment_time = 600000
    return detector


def detect(audio: np.ndarray, sr: int) -> list[tuple[float, float]]:
    """检测实际送去出片的音轨。背景音乐在之后混入，不参与人声停顿判断。"""
    from scipy.signal import resample_poly
    from math import gcd

    mono = audio.mean(axis=1) if audio.ndim == 2 else audio
    if len(mono) < sr * .1 or not np.any(np.abs(mono) > 1e-7):
        return []
    divisor = gcd(sr, 16000)
    signal = resample_poly(mono, 16000 // divisor, sr // divisor).astype(np.float32)
    model_path = str(config.load()["asr"]["vad_dir"])
    digest = hashlib.sha256(b"speech-timing-v2|" + model_path.encode() + signal.tobytes()).hexdigest()
    cache = config.data_root() / "clipinfo" / "speech_timing" / f"{digest}.json"
    if cache.is_file():
        return [tuple(span) for span in json.loads(cache.read_text(encoding="utf-8"))]
    # 补静音使最后一个字也能完成端点检测；返回值仍限制在原音轨时长内。
    with _lock:
        detector = _detector(model_path)
        result = detector.generate(input=np.pad(signal, (0, 8000)), fs=16000, cache={},
                                   max_end_silence_time=400, disable_pbar=True)
    duration = len(signal) / 16000
    spans = [(max(0.0, start / 1000), min(duration, end / 1000))
             for start, end in result[0].get("value", []) if end > start >= 0 and start / 1000 < duration]
    cache.parent.mkdir(parents=True, exist_ok=True)
    temporary = cache.with_name(f"{digest}.{uuid4().hex}.tmp")
    try:
        temporary.write_text(json.dumps(spans), encoding="utf-8")
        temporary.replace(cache)
    finally:
        temporary.unlink(missing_ok=True)
    return spans


def retained_ranges(spans: list[tuple[float, float]], duration: float, *, threshold: float = 1.0,
                    lead: float = .05, tail: float = .05, first_lead: float | None = None) -> list[tuple[float, float]]:
    """相对音轨的保留区间；阈值判断在加余量之前，恰好 1 秒的停顿不裁。"""
    voices: list[list[float]] = []
    for a, b in sorted(spans):
        a, b = max(0.0, a), min(duration, b)
        if b <= a:
            continue
        if voices and a <= voices[-1][1]:
            voices[-1][1] = max(voices[-1][1], b)
        else:
            voices.append([a, b])
    if not voices:
        return [(0.0, duration)]
    ranges = []
    start = max(0.0, voices[0][0] - (lead if first_lead is None else first_lead))
    for (_, end), (next_start, _) in zip(voices, voices[1:]):
        if next_start - end > threshold + 1e-9:
            ranges.append((start, min(duration, end + tail)))
            start = max(0.0, next_start - lead)
    ranges.append((start, voices[-1][1] + tail))
    return [(round(a, 3), round(b, 3)) for a, b in ranges if b > a]
