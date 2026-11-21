"""片头开口定位：保留字词约束、原声端点检查及本地识别复核。"""
from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

import numpy as np

from . import asr, cancellation, config, script as scriptmod, speech_timing

if TYPE_CHECKING:
    from .render import Segment


def _levels(audio: np.ndarray, sr: int) -> np.ndarray:
    mono = audio.mean(axis=1) if audio.ndim == 2 else audio
    hop = max(1, round(sr * .01))
    count = len(mono) // hop
    if not count:
        return np.empty(0)
    return 20 * np.log10(np.sqrt(np.mean(mono[:count * hop].reshape(count, hop) ** 2, axis=1)) + 1e-9)


def _runs(mask: np.ndarray, length: int = 4) -> list[int]:
    starts, count = [], 0
    for index, active in enumerate(mask):
        count = count + 1 if active else 0
        if count == length:
            starts.append(index - length + 1)
    return starts


def _words(seg: Segment) -> list[tuple[str, float, float]]:
    end = seg.v_start + (seg.v_content_dur if seg.v_content_dur is not None else seg.v_dur)
    return sorted(((scriptmod._bare(text), a - seg.v_start, b - seg.v_start)
                   for line in seg.source_lines for text, a, b in line.get("words") or []
                   if scriptmod._bare(text) and min(end, b) > max(seg.v_start, a) + .001),
                  key=lambda word: (word[1], word[2]))


def _locate(db: np.ndarray, words: list, voices: list, max_lead: float, *, lead: float = .02) -> tuple[float, float, float]:
    # 超长首字不能作为开口起点；从后续可信字的声音估计讲话响度，避免用片头底噪定阈值。
    reference = [(text, a, b) for text, a, b in words[:6]
                 if (b - a) / len(text) <= .60 and b > 0 and a < len(db) / 100]
    values = [db[max(0, round(a * 100)):min(len(db), round(b * 100))] for _, a, b in reference]
    values = [value for value in values if len(value)]
    if not values:
        raise ValueError("片头缺少可信的逐字时间，请重新识别素材")
    core = np.concatenate(values)
    high = max(-65.0, float(np.percentile(core, 30)) - 6)
    low = max(-75.0, float(np.percentile(core, 10)) - 24)
    voiced = np.zeros(len(db), dtype=bool)
    for a, b in voices:
        voiced[max(0, round((a - .03) * 100)):min(len(db), round((b + .03) * 100))] = True
    active = _runs((db >= high) & voiced)
    first_text, first_a, first_b = words[0]
    if (first_b - first_a) / len(first_text) > .60:
        anchor = reference[0][1]
        lower = max(0.0, anchor - .60 * len(first_text))
        upper = max(anchor + .15, lower + .1)
    else:
        lower, upper = max(0.0, first_a - .35), first_b + .05
    candidates = [index for index in active if lower - .01 <= index / 100 <= upper
                  or (index / 100 < lower and np.all(
                      db[index:min(len(db), round(lower * 100) + 4)] >= low))]
    if not candidates:
        raise ValueError("无法可靠定位片头第一字的开口，请检查识别时间或原素材")
    core_start = candidates[0]
    # 追到低能量声母的起点；允许 20ms 的短低谷，不因爆破音或清辅音切掉字头。
    cursor, quiet, onset = core_start, 0, core_start
    while cursor > 0:
        cursor -= 1
        quiet = quiet + 1 if db[cursor] < low else 0
        if quiet >= 3:
            break
        if db[cursor] >= low:
            onset = cursor
    if core_start / 100 - max(0.0, onset / 100 - lead) > max_lead:
        raise ValueError("片头原声与底噪无法可靠分开，请检查素材后再出片")
    return onset / 100, core_start / 100, high


def trim(seg: Segment, read_audio, *, sr: int = 48000, report: dict | None = None) -> Segment:
    review = report if report is not None else {}
    cfg = config.load()["render"].get("opening_cut") or {}
    review.clear()  # 首段被短段规则删除后，不沿用被删镜头的阈值或编码检查结果。
    review.update(version=1, clip=str(seg.clip), original_start=seg.v_start, trimmed_seconds=0.0)
    if not cfg.get("enabled", True):
        review.update(status="disabled")
        return seg
    cancellation.check()
    words = _words(seg)
    if not words:
        review.update(status="rejected", reason="片头缺少逐字时间，无法保证第一字完整")
        raise ValueError(review["reason"] + "；请重新识别素材")
    lead = min(.05, max(0.0, float((config.load()["render"].get("segment_gap") or {}).get("first_lead", .02))))
    max_lead = min(.25, max(.05, float(cfg.get("max_lead", .1))))
    text, first_a, first_b = words[0]
    if first_a <= max_lead and (first_b - first_a) / len(text) <= .60:
        review.update(status="ready", method="trusted_word_time", speech_start=max(0.0, first_a),
                      expected_prefix="".join(word[0] for word in words)[:2])
        return seg
    review.update(status="checking", method="waveform_and_local_asr")
    try:
        content = min(seg.v_dur, seg.v_content_dur) if seg.v_content_dur is not None else seg.v_dur
        seconds = min(content, max(1.0, float(cfg.get("search_seconds", 5.0))))
        source, start = (seg.audio_wav, seg.a_start) if seg.audio_wav else (seg.clip, seg.v_start)
        audio = read_audio(source, start, seconds)
        db = _levels(audio, sr)
        voices = speech_timing.detect(audio, sr)
        onset, core_start, threshold = _locate(db, words, voices, max_lead, lead=lead)
        cut = round(max(0.0, onset - lead), 3)
        review.update(detected_onset=onset, speech_start=round(onset - cut, 3),
                      core_start=round(core_start - cut, 3), threshold_dbfs=threshold,
                      max_lead=max_lead, proposed_trim_seconds=cut)
        prefix = "".join(word[0] for word in words)
        second_end = next((b for _, _, b in words[1:]), first_b)
        expected = prefix[:2] if second_end - cut <= 1.0 else prefix[:1]
        excerpt = audio[round(cut * sr):round((cut + 1.0) * sr)]
        heard = scriptmod._bare(asr.recognize_audio(excerpt, sr))
        review.update(expected_prefix=expected, recognized_text=heard)
        if not heard.startswith(expected):
            raise ValueError("片头裁剪后首字复核未通过，请检查原素材或重新识别")
        cancellation.check()
        subs = [(round(max(cut, a) - cut, 3), round(b - cut, 3), text)
                for a, b, text in seg.subs if b > cut]
        review.update(status="ready", trimmed_seconds=cut, final_start=round(seg.v_start + cut, 3))
        return replace(seg, v_start=round(seg.v_start + cut, 3), v_dur=round(seg.v_dur - cut, 3),
                       a_start=round(seg.a_start + cut, 3),
                       a_dur=round(max(0.0, (seg.a_dur if seg.a_dur is not None else seg.v_dur) - cut), 3),
                       v_content_dur=round(max(0.0, content - cut), 3), subs=subs,
                       speech_spans=[(round(max(cut, a) - cut, 3), round(b - cut, 3))
                                     for a, b in seg.speech_spans if b > cut])
    except Exception as error:
        review.update(status="rejected", reason=str(error))
        raise


def check_encoded(audio: np.ndarray, sr: int, report: dict) -> None:
    """检查未混背景音乐的拼接人声，不能让音乐掩盖开口延迟。"""
    if "threshold_dbfs" not in report:
        return
    starts = _runs(_levels(audio, sr) >= report["threshold_dbfs"] - 3)
    onset = starts[0] / 100 if starts else None
    # AAC 与拼接时间戳允许 40ms 的编码误差，目标仍远早于第一秒。
    passed = onset is not None and onset <= report["max_lead"] + .04
    report.update(encoded_onset=onset, encoded_check="passed" if passed else "rejected")
    if not passed:
        raise ValueError("片头成片校验未通过：有效讲话未及时开始，已停止导出")
