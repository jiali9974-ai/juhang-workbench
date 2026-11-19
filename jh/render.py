"""按已确认的剪辑脚本出片。

流程：逐段裁切（竖屏 1440×2560、特写放大）→ 拼接 → 烧字幕和角标、混背景音乐 → 导出 MP4。
"""
from __future__ import annotations

import json
import shutil
import tempfile
from dataclasses import dataclass, field, replace
from pathlib import Path

import cv2
import numpy as np

from . import cancellation, config, fonts, graphics, look, media, script as scriptmod

PUNCT_STRIP = "，。,.！!？?、；;：: "


@dataclass
class Segment:
    clip: Path
    v_start: float
    v_dur: float
    audio_wav: Path | None = None           # 清理口误后的原声音轨；None 表示直接使用素材音轨
    subs: list[tuple[float, float, str]] = field(default_factory=list)  # 相对本段开头的时间
    zoom: float | None = None
    punch: bool = False                   # 同一机位跳剪：这一段稍微放大一点，跳剪看起来是有意的
    face: bool | None = None              # 这段画面有没有人脸（决定要不要磨皮）；None = 出片时再判断
    a_start: float = 0.0                   # 独立音轨起点；裁掉停顿时声音与画面同步移动
    a_dur: float | None = None             # 片尾补留白时，音轨到原边界截止，再补静音，避免带入后一句


# ---------------- 原声剪辑：句子里面剪掉口误、犹豫声、长停顿 ----------------

HESITATION = set("嗯呃额哎诶唉")
MAX_PAUSE, KEEP_PAUSE = 0.35, 0.20        # 句子里超过 0.35 秒的停顿压到 0.2 秒（停顿里的换气、杂音一起去掉）
MAX_CHAR, KEEP_CHAR = 0.60, 0.40          # 拖得很长的字（“啊~~”或字后面带着杂音）只留 0.4 秒


def _is_punct(w: str) -> bool:
    return not scriptmod._bare(w)


_transcript_cache: dict[tuple[str, str], dict] = {}


def line_words(batch: str, l: dict) -> list | None:
    """这句的逐字时间。新脚本里自带；旧脚本去识别结果里找（识别结果是旧版就重新识别这一条素材）。"""
    if l.get("words"):
        return l["words"]
    from . import asr

    key = (batch, l["clip"])
    if key not in _transcript_cache:
        tdir = config.data_root() / "transcripts" / batch
        _transcript_cache[key] = asr.transcribe_clip(config.material_root() / batch / l["clip"], tdir)
    sents = _transcript_cache[key]["sentences"]
    for snt in sents:
        if abs(snt["start"] - l["start"]) < 0.05 and abs(snt["end"] - l["end"]) < 0.05:
            l["words"] = snt.get("words")
            return l["words"]
    # 重新识别后句子边界有一点点变化：把落在这句时间范围里的字拼起来
    ws = [w for snt in sents for w in (snt.get("words") or [])
          if w[1] >= l["start"] - 0.05 and w[2] <= l["end"] + 0.05]
    l["words"] = ws or None
    return l["words"]


def _kept_word_indices(l: dict, words: list) -> list[int]:
    """从后往前对齐保留原话，返回真正保留的非标点字。"""
    import difflib

    chars, owner = [], []                  # 每个（非标点）字属于哪个 word
    for wi, (w, _, _) in enumerate(words):
        for ch in scriptmod._bare(w):
            chars.append(ch)
            owner.append(wi)
    keep = scriptmod._bare(l.get("keep") or l.get("src_text") or "")
    kept = [False] * len(words)
    # 从后往前对齐：口误通常是“说一半 → 重来一遍”，要删的是前面那半截，保留后面完整的那遍
    pos, j = [], len(chars) - 1
    for ch in reversed(keep):
        while j >= 0 and chars[j] != ch:
            j -= 1
        if j < 0:
            pos = None
            break
        pos.append(j)
        j -= 1
    if pos is not None:
        for k in pos:
            kept[owner[k]] = True
    else:                                  # keep 不是原话删字得来的（旧数据）：退回模糊对齐
        sm = difflib.SequenceMatcher(None, "".join(chars), keep, autojunk=False)
        for a, _, n in sm.get_matching_blocks():
            for k in range(a, a + n):
                kept[owner[k]] = True
    real = [i for i, (w, _, _) in enumerate(words) if not _is_punct(w) and kept[i]]
    # 句首、句尾的犹豫声不要（嗯、呃……；句首的“啊”也不要）
    while real and (scriptmod._bare(words[real[0]][0]) in HESITATION or (scriptmod._bare(words[real[0]][0]) == "啊" and len(real) > 1)):
        kept[real.pop(0)] = False
    while real and scriptmod._bare(words[real[-1]][0]) in HESITATION:
        kept[real.pop()] = False
    return real


def keep_pieces(l: dict, words: list | None, *, final: bool = False,
                trim_lead: bool = False, trim_tail: bool = False) -> list[tuple[float, float]]:
    """这句原话真正要用的时间段；口误旁边的余量只能补底噪，不能取回已删除的原声。"""
    if not words:
        return [(max(0.0, l["start"] - (0 if trim_lead else 0.08)), l["end"] + (0 if trim_tail else 0.12))]
    real = _kept_word_indices(l, words)
    if not real:
        return []
    kept = set(real)
    first, last = real[0], real[-1]
    pieces: list[list[float]] = []
    for i in range(first, last + 1):
        w, a, b = words[i]
        if _is_punct(w):
            # 句子中间的停顿：前后的字都保留时才算停顿，超过 MAX_PAUSE 就压到 KEEP_PAUSE
            nxt_real = next((j for j in range(i + 1, last + 1) if not _is_punct(words[j][0])), None)
            if pieces and i - 1 in kept and nxt_real in kept:
                pieces.append([a, a + (KEEP_PAUSE if b - a > MAX_PAUSE else b - a)])
            continue
        if i not in kept:
            continue
        # 片尾最后一个字保留完整尾音，不能先按拖音规则截短，再补片尾留白。
        pieces.append([a, b if final and i == last else a + (KEEP_CHAR if b - a > MAX_CHAR else b - a)])
    # 不能越过已删字的边界（包括隔着标点的口误）。正常切点的留白由后续人声裁剪补足。
    lead = 0 if trim_lead or any(not _is_punct(w[0]) for w in words[:first]) else 0.08
    tail = 0 if trim_tail or any(not _is_punct(w[0]) for w in words[last + 1:]) else 0.12
    pieces[0][0] = max(0.0, pieces[0][0] - lead)
    pieces[-1][1] = pieces[-1][1] + tail
    merged: list[list[float]] = []
    for a, b in pieces:
        if merged and a - merged[-1][1] < 0.02:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    return [(round(a, 3), round(b, 3)) for a, b in merged if b - a >= 0.06]


def _script_keep_pieces(script: dict) -> list[tuple[dict, list[tuple[float, float]]]]:
    """相邻句子一起检查：下一句删掉重说的开头时，上一句尾部也不能带回那段口误。"""
    lines = script["lines"]
    words = [line_words(script["batch"], l) for l in lines]
    deleted_edges = []
    for l, ws in zip(lines, words):
        real = _kept_word_indices(l, ws) if ws else []
        first, last = (real[0], real[-1]) if real else (len(ws or []), -1)
        deleted_edges.append((any(not _is_punct(w[0]) for w in (ws or [])[:first]),
                              any(not _is_punct(w[0]) for w in (ws or [])[last + 1:])))

    def adjacent(left: dict, right: dict) -> bool:
        return left["clip"] == right["clip"] and -0.01 <= right["start"] - left["end"] <= 0.35

    return [(l, keep_pieces(l, ws, final=i == len(lines) - 1,
                           trim_lead=i > 0 and adjacent(lines[i - 1], l) and deleted_edges[i - 1][1],
                           trim_tail=i + 1 < len(lines) and adjacent(l, lines[i + 1]) and deleted_edges[i + 1][0]))
            for i, (l, ws) in enumerate(zip(lines, words))]


# ---------------- 字幕切分 ----------------

def sub_lines() -> int:
    """一屏字幕最多几行（style.subtitle.lines，默认 2）。"""
    return max(1, int(config.load()["style"]["subtitle"].get("lines", 2)))


def split_subtitle(text: str, max_chars: int) -> list[str]:
    """按逗号和长度把一句字幕切成屏幕上一次显示的小段（每段最多 sub_lines() 行）。"""
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
    limit = max_chars * sub_lines()
    for p in parts:
        p = p.strip(PUNCT_STRIP)
        if not p:
            continue
        if out and len(out[-1]) + len(p) <= max_chars:
            out[-1] = out[-1] + " " + p      # 很短的分句合并显示
            continue
        while len(p) > limit:                  # 一屏放不下：在合适的地方分屏
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
    r = cancellation.run_process([config.ffmpeg(), "-hide_banner", "-loglevel", "error", "-ss", f"{t:.3f}", "-i", str(clip),
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
    material = config.material_root() / script["batch"]
    segs: list[Segment] = []

    if cfg["render"].get("slip_trim", "audio") == "audio":
        # 口误处保留连续画面，删掉的声音换成素材自己的环境底噪；
        # 超过阈值的无人声停顿在分段规划完成后统一同步裁掉音画。
        if scriptmod.fill_keep(script) and script.get("id"):
            scriptmod.save(script)
        pieces_by_line = {id(l): pieces for l, pieces in _script_keep_pieces(script)}
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
        for gi, g in enumerate(groups):
            if progress:
                progress(gi, len(groups), f"清理口误声音 {gi + 1}/{len(groups)}")
            v0 = max(0.0, g[0]["start"] - 0.08)
            v1 = g[-1]["end"] + 0.12
            keep_iv: list[tuple[float, float]] = []
            for l in g:
                keep_iv += pieces_by_line[id(l)]
            if keep_iv:
                # 片段之间的间隔（config render.segment_gap）：上一段说完最后一个字留 0.05 秒、下一段开口前留 0.05 秒；
                # 成片第一段开口前也只留 0.02 秒，开头第一幕直接说话。开口、说完的位置按声音判断（识别给的时间常差 0.2–0.7 秒）
                gap = cfg["render"].get("segment_gap") or {}
                lead = float(gap.get("first_lead", 0.02)) if gi == 0 else float(gap.get("lead", 0.05))
                tail = float(gap.get("final_tail", 0.2) if gi == len(groups) - 1 else gap.get("tail", 0.05))
                v0, v1 = tighten(material / g[0]["clip"], keep_iv[0][0], keep_iv[-1][1], lead, tail)
            seg = Segment(clip=material / g[0]["clip"], v_start=v0, v_dur=v1 - v0, zoom=g[0].get("zoom"))
            seg.audio_wav = clean_audio(script["batch"], seg.clip, v0, v1 - v0, keep_iv)
            for l in g:
                a, b = max(0.0, l["start"] - v0), min(v1 - v0, l["end"] - v0)
                if b - a > 0.2:
                    seg.subs += timed_chunks(l["subtitle"], a, b, max_chars)
            segs.append(seg)
    else:
        # 画面也一起剪（跳剪）：每句只用真正要的时间段
        if scriptmod.fill_keep(script) and script.get("id"):
            scriptmod.save(script)
        flat: list[tuple[dict, float, float]] = []          # (句子, 素材起点, 素材终点)
        for l, pieces in _script_keep_pieces(script):
            for a, b in pieces:
                flat.append((l, a, b))
        if flat:                                            # 开头第一幕直接从第一个字开口的地方开始
            l, a, b = flat[0]
            flat[0] = (l, min(opening_start(material / l["clip"], a), b - 0.1), b)
        # 同一素材里首尾相接的片段合并成一段，减少切点
        runs: list[list] = []
        for l, a, b in flat:
            if runs and runs[-1][0]["clip"] == l["clip"] and runs[-1][0].get("zoom") == l.get("zoom") and abs(a - runs[-1][2]) < 0.03:
                runs[-1][2] = b
                runs[-1][3].append((l, a, b))
            else:
                runs.append([l, a, b, [(l, a, b)]])
        # 字幕：每句的字幕铺在这句所有片段的总时长上，再按片段切开
        out_t, line_span, seg_starts = 0.0, {}, []
        for l0, a, b, parts in runs:
            seg_starts.append(out_t)
            for l, pa, pb in parts:
                s0, s1 = line_span.get(id(l), (out_t, out_t))
                line_span[id(l)] = (s0 if id(l) in line_span else out_t, out_t + (pb - pa))
                out_t += pb - pa
        subs_global = []
        for l in script["lines"]:
            if id(l) in line_span:
                t0, t1 = line_span[id(l)]
                subs_global += timed_chunks(l["subtitle"], t0, t1, max_chars)
        prev = None
        for (l0, a, b, parts), st in zip(runs, seg_starts):
            seg = Segment(clip=material / l0["clip"], v_start=a, v_dur=b - a, zoom=l0.get("zoom"))
            for x0, x1, text in subs_global:
                c0, c1 = max(x0, st), min(x1, st + seg.v_dur)
                if c1 - c0 > 0.05:
                    seg.subs.append((c0 - st, c1 - st, text))
            # 同一机位中间剪掉了一截（跳剪）：下一段稍微放大，看起来是有意的切换
            if prev is not None and prev.clip == seg.clip and seg.v_start > prev.v_start + prev.v_dur + 0.02:
                seg.punch = not prev.punch
            segs.append(seg)
            prev = seg
    segs = apply_speech_timing(segs, progress)
    rcfg = cfg["render"]
    for s in segs:
        if s.zoom is None:
            s.face = has_face(s.clip, s.v_start + s.v_dur / 2)
            s.zoom = rcfg["talk_zoom"] if s.face else rcfg["product_zoom"]
        if s.punch:
            s.zoom = round(s.zoom * float(rcfg.get("jump_cut_punch", 1.08)), 3)
    return segs


def apply_speech_timing(segs: list[Segment], progress=None) -> list[Segment]:
    """处理最终人声音轨后，再同步裁画面、音轨和字幕；原声清理后经过这里。"""
    from . import speech_timing

    cfg = config.load()["render"]
    gap = cfg.get("segment_gap") or {}
    threshold = float((cfg.get("silence_cut") or {}).get("threshold", 1.0))
    lead, tail = float(gap.get("lead", .05)), float(gap.get("tail", .05))
    result = []
    for index, seg in enumerate(segs):
        if progress:
            progress(index, len(segs), f"裁剪无人声停顿 {index + 1}/{len(segs)}")
        source, start = (seg.audio_wav, seg.a_start) if seg.audio_wav else (seg.clip, seg.v_start)
        audio = _clip_audio(source, start, seg.v_dur)
        voices = speech_timing.detect(audio, AUDIO_SR)
        ranges = speech_timing.retained_ranges(voices, seg.v_dur, threshold=threshold, lead=lead, tail=tail,
                                               first_lead=float(gap.get("first_lead", .02)) if index == 0 else lead)
        if voices and index == len(segs) - 1:
            a, _ = ranges[-1]
            ranges[-1] = (a, round(max(b for _, b in voices) + float(gap.get("final_tail", .2)), 3))
        for a, b in ranges:
            subs = [(round(max(a, x) - a, 3), round(min(b, y) - a, 3), text)
                    for x, y, text in seg.subs if min(b, y) > max(a, x)]
            result.append(replace(seg, v_start=round(seg.v_start + a, 3), v_dur=round(b - a, 3),
                                  a_start=round(seg.a_start + a, 3),
                                  a_dur=round(max(0.0, min(b, seg.v_dur, seg.a_dur if seg.a_dur is not None else seg.v_dur) - a), 3),
                                  subs=subs))
    return result


# ---------------- 只删声音：口误处换成环境底噪 ----------------

AUDIO_SR = 48000


def _clip_audio(clip: Path, start: float | None = None, dur: float | None = None) -> np.ndarray:
    args = [config.ffmpeg(), "-hide_banner", "-loglevel", "error"]
    if start is not None:
        args += ["-ss", f"{start:.3f}", "-t", f"{dur:.3f}"]
    args += ["-i", str(clip), "-vn", "-ac", "2", "-ar", str(AUDIO_SR), "-f", "f32le", "-"]
    r = cancellation.run_process(args, capture_output=True)
    return np.frombuffer(r.stdout, dtype=np.float32).reshape(-1, 2).copy()


def speech_onset(clip: Path, p0: float, look: float = 1.2) -> float | None:
    """从 p0（识别给的第一个保留字的起点）往后找人声真正开口的时间（素材里的秒数）。
    识别给的起点常常比实际开口早 0.2–0.7 秒，所以按声音判断（10 毫秒一帧算响度）：
    - p0 处安静：往后找第一次连续 30 毫秒明显响起来的地方，再往回退到刚开始变响的那一帧；
    - p0 处已经有声音：如果 0.3 秒内接着有一段 ≥0.12 秒的安静，前面那点声音是被删掉的字（“来开始”）的尾巴，跳过它再找；
      没有安静（一直连着在说）就是从 p0 开口，不动。
    找不到明显的人声返回 None。"""
    t0 = max(0.0, p0 - 1.0)
    y = _clip_audio(clip, t0, (p0 - t0) + look + 1.0).mean(axis=1)
    hop = AUDIO_SR // 100
    n = len(y) // hop
    i0, iend = int(round((p0 - t0) * 100)), min(n - 3, int(round((p0 - t0 + look) * 100)))
    if iend - i0 < 5:
        return None
    db = 20 * np.log10(np.sqrt((y[:n * hop].reshape(n, hop) ** 2).mean(axis=1)) + 1e-9)
    floor, peak = float(np.percentile(db, 10)), float(db.max())
    if peak - floor < 15:                  # 这一段没有明显的人声
        return None
    loud, quiet = max(floor + 15, peak - 35), floor + 8
    i = i0
    if db[i0] >= loud:
        run, gap_end = 0, None
        for k in range(i0, min(iend, i0 + 30 + 12)):
            run = run + 1 if db[k] < loud else 0
            if run >= 12:
                gap_end = k
                break
        if gap_end is None:
            return p0                      # 一直连着在说：就从 p0 开口
        i = gap_end
    for k in range(i, iend):
        if db[k] >= loud and db[k + 1] >= loud - 6 and db[k + 2] >= loud - 6:
            j = k
            while j > i and db[j - 1] > quiet and k - j < 15:     # 往回退到刚开始变响（最多 0.15 秒）
                j -= 1
            return t0 + j / 100
    return None


def speech_offset(clip: Path, p1: float, look: float = 1.0) -> float | None:
    """往回找 p1（识别给的最后一个保留字的结尾，已带余量）之前人声真正说完的时间。
    p1 处还在响（后面紧接着被删掉的字）就返回 p1；找不到明显的人声返回 None。"""
    t0 = max(0.0, p1 - look - 0.5)
    y = _clip_audio(clip, t0, (p1 - t0) + 0.5).mean(axis=1)
    hop = AUDIO_SR // 100
    n = len(y) // hop
    i1 = min(n - 1, int(round((p1 - t0) * 100)))
    i_lo = max(2, int(round((p1 - look - t0) * 100)))
    if i1 - i_lo < 5:
        return None
    db = 20 * np.log10(np.sqrt((y[:n * hop].reshape(n, hop) ** 2).mean(axis=1)) + 1e-9)
    floor, peak = float(np.percentile(db, 10)), float(db.max())
    if peak - floor < 15:
        return None
    loud, quiet = max(floor + 15, peak - 35), floor + 8
    if db[i1] >= loud:
        return p1
    for k in range(i1, i_lo, -1):
        if db[k] >= loud and db[k - 1] >= loud - 6 and db[k - 2] >= loud - 6:
            return t0 + (k + 1) / 100          # 最后一帧还算人声的地方就是说完（很轻的尾音算在留的 tail 里）
    return None


def tighten(clip: Path, p0: float, p1: float, lead: float, tail: float) -> tuple[float, float]:
    """一段画面的起止：开口前只留 lead 秒、说完最后一个字只留 tail 秒（按声音判断开口和说完的位置）。
    只会往里收，不会超出 p0–p1（要用的声音范围），保证不切到字。"""
    a, b = p0, p1
    on = speech_onset(clip, p0)
    if on is not None:
        a = max(p0, on - lead)
    off = speech_offset(clip, p1)
    if off is not None:
        b = min(p1, off + tail)
    if b - a < 0.3:                        # 量出来不合理（太短）就不收
        return p0, p1
    return round(a, 3), round(b, 3)


def opening_start(clip: Path, first_piece: float) -> float:
    """成片第一段从哪里开始：直接从第一个字开口的地方开场（往前只留 0.02 秒，不切掉声母），
    跳过句首被删掉的“来开始”和开口前的空白。"""
    onset = speech_onset(clip, first_piece)
    return round(max(first_piece, onset - 0.02), 3) if onset is not None else first_piece


def room_tone(batch: str, clip: Path, seconds: float) -> np.ndarray:
    """这条素材的环境底噪：取最安静的那些片段的频谱，生成同样“听感”的平稳噪声（任意长度、不会有循环感）。"""
    import librosa

    cache = config.data_root() / "renders" / batch / "_audio" / f"roomtone_{clip.stem}.npy"
    if cache.exists():
        mag = np.load(cache)
    else:
        y = _clip_audio(clip).mean(axis=1)
        S = np.abs(librosa.stft(y, n_fft=2048, hop_length=512))
        e = S.mean(axis=0)
        quiet = e <= np.percentile(e, 8)                    # 最安静的 8% 帧（停顿里的店内环境声）
        mag = S[:, quiet].mean(axis=1) if quiet.any() else S.mean(axis=1) * 0.05
        cache.parent.mkdir(parents=True, exist_ok=True)
        np.save(cache, mag)
    n = int(seconds * AUDIO_SR) + 4096
    frames = n // 512 + 2
    rng = np.random.default_rng(int(abs(hash(clip.name))) % (2 ** 32))
    phase = np.exp(2j * np.pi * rng.random((len(mag), frames)))
    tone = librosa.istft(mag[:, None] * phase, hop_length=512, length=n)
    return np.stack([tone, tone], axis=1).astype(np.float32)


def clean_audio(batch: str, clip: Path, v0: float, dur: float, keep_iv: list[tuple[float, float]]) -> Path:
    """这一段画面的声音：keep_iv（素材里的秒数）里用主播原声，其余（口误、犹豫声、换气、拖音）换成环境底噪。"""
    import hashlib

    import soundfile as sf

    key = hashlib.md5(f"bounded-v3|{clip.name}|{v0:.3f}|{dur:.3f}|{keep_iv}".encode()).hexdigest()[:12]
    out = config.data_root() / "renders" / batch / "_audio" / f"{clip.stem}_{v0:.2f}_{key}.wav"
    if out.exists():
        return out
    y = _clip_audio(clip, v0, dur + 0.5)
    n = len(y)
    mask = np.zeros(n, dtype=np.float32)
    for a, b in keep_iv:
        i0, i1 = max(0, int((a - v0) * AUDIO_SR)), min(n, int((b - v0) * AUDIO_SR))
        if i1 > i0:
            mask[i0:i1] = 1.0
    ramp = int(0.015 * AUDIO_SR)                            # 15 毫秒交叉淡化，换底噪的地方听不出接缝
    if ramp > 1:
        k = np.hanning(2 * ramp + 1).astype(np.float32)
        # 淡化只发生在保留范围里面；向外卷积会把已删除的字头/尾重新混回来。
        mask *= np.clip(2 * np.convolve(mask, k / k.sum(), mode="same") - 1, 0.0, 1.0)
    tone = room_tone(batch, clip, n / AUDIO_SR)[:n]
    mixed = y * mask[:, None] + tone * (1.0 - mask[:, None])
    out.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(out), mixed, AUDIO_SR)
    return out


# ---------------- 编码 ----------------

def _venc(intermediate: bool = False) -> list[str]:
    """intermediate=True：逐段剪出来的中间文件（成片还要烧字幕再编码一次），用更高码率，两次压缩后细节损失小
    （实测 20M+20M 人脸细节少约 18%，60M+30M 少约 13%）。"""
    r = config.load()["render"]
    if r["encoder"] == "h264_nvenc":
        rate = r.get("segment_bitrate", "60M") if intermediate else r["bitrate"]
        peak = f"{int(str(rate).rstrip('Mm')) * 4 // 3}M"
        return ["-c:v", "h264_nvenc", "-preset", "p5", "-rc", "vbr", "-b:v", rate, "-maxrate", peak,
                "-bufsize", peak, "-profile:v", "high"]
    return ["-c:v", "libx264", "-preset", "medium", "-crf", "14" if intermediate else "17"]


def face_spans(clip: Path, start: float, dur: float, step: float = 0.5) -> list[tuple[float, float]]:
    """这段画面里哪些时间有人脸（相对这段开头的秒数）。一次解码低分辨率的抽帧（每 step 秒一帧）逐帧找脸，很快。"""
    global _face
    if _face is None:
        _face = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    w, h = 360, 640
    r = cancellation.run_process([config.ffmpeg(), "-hide_banner", "-loglevel", "error", "-ss", f"{start:.3f}", "-t", f"{dur:.3f}",
                        "-i", str(clip), "-vf", f"fps={1 / step:.4f},scale={w}:{h}", "-f", "rawvideo", "-pix_fmt", "gray", "-"],
                       capture_output=True)
    frames = np.frombuffer(r.stdout, np.uint8)
    n = len(frames) // (w * h)
    hits = []
    for i in range(n):
        g = frames[i * w * h:(i + 1) * w * h].reshape(h, w)
        if len(_face.detectMultiScale(g, scaleFactor=1.1, minNeighbors=6, minSize=(40, 40))):
            hits.append(i * step)
    spans: list[list[float]] = []
    for t in hits:
        a, b = max(0.0, t - step / 2), min(dur, t + step / 2)
        if spans and a <= spans[-1][1] + 1e-6:
            spans[-1][1] = b
        else:
            spans.append([a, b])
    return [(round(a, 2), round(b, 2)) for a, b in spans]


def encode_segment(seg: Segment, out: Path, settings: dict | None = None) -> None:
    r = config.load()["render"]
    W, H, fps = r["width"], r["height"], r["fps"]
    z = max(1.0, float(seg.zoom or 1.0))
    effects = look.filters(settings)
    filters = [f"crop='min(iw,ih*{W}/{H})/{z}':'min(ih,iw*{H}/{W})/{z}'", f"scale={W}:{H}:flags=lanczos"]
    if effects["normalize"]:
        from . import normalize

        nf = normalize.segment_filter(seg.clip, seg.v_start, seg.v_dur)   # 不同素材光线不同：按这段的肤色拉齐亮度和白平衡
        if nf:
            filters.append(nf)
    if effects["sharpen"]:
        face = face_spans(seg.clip, seg.v_start, seg.v_dur)
        whole = len(face) == 1 and face[0][0] <= 0.05 and face[0][1] >= seg.v_dur - 0.05
        if not whole:
            expr = "+".join(f"between(t,{a:.2f},{b:.2f})" for a, b in face)
            filters.append(effects["sharpen"] + (f":enable='not({expr})'" if expr else ""))
    if effects["tone"]:
        filters.append(effects["tone"])
    filters.extend([f"fps={fps}", "setsar=1", "format=yuv420p", "tpad=stop_mode=clone:stop_duration=3"])
    vf = ",".join(filters)
    source = ["-ss", f"{seg.v_start:.3f}", "-t", f"{seg.v_dur + 0.5:.3f}", "-i", str(seg.clip)]
    voice = ["-ss", f"{seg.a_start:.3f}", "-i", str(seg.audio_wav)] if seg.audio_wav else []
    f = 0.012                              # 切点两边各淡 12 毫秒，剪掉口误后接上不会“咔”一声
    fades = f"afade=t=in:d={f},afade=t=out:st={max(0.0, seg.v_dur - f):.3f}:d={f}"
    audio_trim = f"atrim=duration={seg.a_dur:.3f}," if seg.a_dur is not None else ""
    af = f"[{int(bool(voice))}:a]aresample=48000,aformat=channel_layouts=stereo,{audio_trim}apad,{fades}[a]"
    inputs = [*source, *voice, "-filter_complex", f"[0:v]{vf}[v];{af}",
              "-map", "[v]", "-map", "[a]", "-t", f"{seg.v_dur:.3f}", "-c:a", "aac", "-b:a", "256k"]
    encoder = _venc(intermediate=True)
    if effects["smooth"]:
        from . import skin

        skin.video(inputs, encoder, out, W, H, fps, effects["smooth"])
    else:
        media.run_ffmpeg([*inputs, *encoder, str(out)])


def _ass_time(t: float) -> str:
    t = max(0.0, t)
    h, rem = divmod(t, 3600)
    m, s = divmod(rem, 60)
    return f"{int(h)}:{int(m):02d}:{s:05.2f}"


def build_ass(segs: list[Segment], total: float, path: Path, y_ratio: float | None = None, bottom_line: bool = False,
              design: dict | None = None) -> None:
    """y_ratio：字幕中心高度（画面比例），不传就用配置里的。
    bottom_line=True：让字幕最后一行的中心落在 y_ratio（两行字幕往上长），整条转粤语时用来始终压住原视频烧进去的普通话字幕。"""
    cfg = config.load()
    st, r = cfg["style"], cfg["render"]
    W, H = r["width"], r["height"]
    design = graphics.current() if design is None else design
    font_catalog = {item["id"]: item for item in fonts.catalog()}
    caption = design["subtitle"]
    if any(layer["font_id"] not in font_catalog for layer in [caption, *design["elements"]]):
        raise RuntimeError("画面设置使用的字体不存在，请在画面编辑中重新选择字体")
    sub, slo, dis = st["subtitle"], st["slogan"], st["disclaimer"]
    font = st["font_name"]
    bold = -1 if st.get("font_bold") else 0
    y_sub = int(H * (y_ratio if y_ratio is not None else caption["y"] / 100))
    x_sub = int(W * caption["x"] / 100)
    caption_size = caption["size"] * W / 1440
    caption_style = graphics.style_tags(caption, W, font_catalog[caption["font_id"]]["family"], font_catalog[caption["font_id"]]["weight"])
    caption_style += f"\\shad{sub.get('shadow', 2)}"
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Sub,{font},{sub['size']},{sub['color']},&H000000FF,{sub['outline_color']},{sub.get('shadow_color', '&H64000000')},{bold},0,0,0,100,100,{sub.get('spacing', 2)},0,1,{sub['outline']},{sub.get('shadow', 2)},5,60,60,0,1
Style: Slogan,{font},{slo['size']},{slo['color']},&H000000FF,{slo['outline_color']},&H64000000,{bold},0,0,0,100,100,0,0,1,6,2,7,0,0,0,1
Style: Disc,{font},{dis['size']},{dis['color']},&H000000FF,{dis['outline_color']},&H64000000,{bold},0,0,0,100,100,2,0,1,6,0,5,0,0,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    ev = []
    ev.extend(graphics.events(design, total, W, H, font_catalog))
    t = 0.0
    for s in segs:
        for a, b, text in s.subs:
            a2, b2 = t + a, min(t + b, t + s.v_dur)
            if b2 - a2 < 0.05 or not caption["enabled"]:
                continue
            pos = f"\\an2\\pos({x_sub},{y_sub + int(caption_size) // 2})" if bottom_line else f"\\pos({x_sub},{y_sub})"
            text = graphics.escape(text)
            shown = wrap_line(text, sub["max_chars_per_line"]) if sub_lines() >= 2 else text.replace(" ", "")
            ev.append(f"Dialogue: 2,{_ass_time(a2)},{_ass_time(b2)},Sub,,0,0,0,,{{{pos}{caption_style}}}{shown}")
        t += s.v_dur
    path.write_text(header + "\n".join(ev) + "\n", encoding="utf-8")


def render(script: dict, progress=None, on_stage=None) -> Path:
    work = config.data_root() / "renders" / script["batch"] / script["id"]
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)

    if on_stage:
        on_stage("look")
    segs = plan(script, progress)
    out_dir = config.output_root() / script["batch"]
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{script['id']}.mp4"
    cover = None
    settings = look.current()
    design = graphics.current()
    ccfg = config.load()["render"].get("cover") or {}
    if ccfg.get("enabled") and script.get("cover"):
        if on_stage:
            on_stage("cover")
        from . import cover as covermod

        if progress:
            progress(0, 1, "做封面")
        try:
            # 边做边检查：脸不自然、抠图不对就换一帧重做（见 cover.make_best_cover，记录在 cover_check.json）
            cover = covermod.make_best_cover(segs, script["cover"], work / "cover.png", settings=settings,
                                             source_out=work / f"{script['id']}_封面原图.jpg")
            from PIL import Image as _Image                 # cv2.imread 不认中文路径，用 PIL 存 jpg

            _Image.open(cover).convert("RGB").save(work / f"{script['id']}_封面.jpg", quality=92)
        except Exception as e:  # noqa: BLE001
            (work / "cover_error.txt").write_text(repr(e), encoding="utf-8")
            raise RuntimeError(f"封面生成失败，已停止出片：{e}") from e
    # 输出目录仅发布完整成片；取消重新生成时保留原来的成片。
    with tempfile.TemporaryDirectory(prefix=".render-", dir=out_dir) as temporary:
        pending = Path(temporary) / out.name
        total = compose_segments(segs, work, pending, progress, cover=cover, settings=settings, on_stage=on_stage, design=design)
        cover_jpg = work / f"{script['id']}_封面.jpg"
        if cover and cover_jpg.exists():
            embed_cover(pending, cover_jpg)
        cancellation.check()
        pending.replace(out)
        # 只在成片成功发布后更新封面说明；取消重生成时保留旧成片的说明。
        selection_file = out_dir / f"{script['id']}_封面选择.json"
        check_file = work / "cover_check.json"
        if cover and check_file.is_file():
            chosen = json.loads(check_file.read_text(encoding="utf-8")).get("chosen", {})
            selection_file.write_text(json.dumps(chosen, ensure_ascii=False, indent=1), encoding="utf-8")
        else:
            selection_file.unlink(missing_ok=True)
        if cover:
            for suffix in ("_封面.jpg", "_封面原图.jpg", "_封面原图.json"):
                image = work / f"{script['id']}{suffix}"
                if image.exists():
                    image.replace(out_dir / image.name)

    meta = {"script": script["id"], "duration": round(total, 2), "segments": len(segs),
            "output": str(out)}
    (work / "render.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    return out


def embed_cover(video: Path, cover_jpg: Path) -> None:
    """把封面图写进 mp4（封面图片轨，attached_pic），不重新编码；已经有封面的先去掉旧的再写新的。"""
    tmp = video.with_name(video.stem + "_cover_tmp.mp4")
    media.run_ffmpeg(["-i", str(video), "-i", str(cover_jpg),
                      "-map", "0:V", "-map", "0:a?", "-map", "1:v",        # 0:V 只取真正的画面轨，不带旧封面
                      "-c", "copy", "-disposition:v:1", "attached_pic", "-movflags", "+faststart", str(tmp)])
    tmp.replace(video)


def compose_segments(segs: list[Segment], work: Path, out: Path, progress=None,
                     cover: Path | None = None, settings: dict | None = None, on_stage=None, design: dict | None = None) -> float:
    """逐段编码 → 拼接 → 烧字幕和角标（左上角竖排黄字、底部声明）、响度统一、混背景音乐 → 导出 out。返回总时长。
    素材剪辑统一使用这一套成片样式。"""
    cfg = config.load()
    settings = look.current() if settings is None else settings
    design = graphics.current() if design is None else design
    work.mkdir(parents=True, exist_ok=True)
    seg_files = []
    if on_stage:
        on_stage("look")
    for i, s in enumerate(segs):
        if progress:
            progress(i, len(segs), f"剪辑片段 {i + 1}/{len(segs)}")
        f = work / f"seg_{i:03d}.mp4"
        encode_segment(s, f, settings)
        seg_files.append(f)

    if on_stage:
        on_stage("render")
    (work / "concat.txt").write_text("".join(f"file '{f.name}'\n" for f in seg_files), encoding="utf-8")
    media.run_ffmpeg(["-f", "concat", "-safe", "0", "-i", str(work / "concat.txt"), "-c", "copy",
                      str(work / "body.mp4")])

    total = sum(s.v_dur for s in segs)
    build_ass(segs, total, work / "video.ass", design=design)
    fonts.snapshot(work / "fonts")

    if progress:
        progress(len(segs), len(segs), "合成字幕与音乐")

    r = cfg["render"]
    if r.get("audio_master") == "voice_bgm":
        # 照参考视频：人声两遍标准化（不抽动）、背景音乐循环铺满并固定比人声低一截，不压低；封面放在最开头一两帧
        from . import audiofx

        mix = audiofx.master_voice_bgm(work / "body.mp4", Path(r["bgm"]) if r.get("bgm") else None, total, work / "audio",
                                       voice_lufs=float(r.get("voice_lufs", -11)), bgm_below=float(r.get("bgm_below_lu", 12)))
        inputs = ["-i", "body.mp4", "-i", str(mix.resolve())]
        filt = "[0:v]subtitles=video.ass:fontsdir=fonts"
        if cover:
            W, H = r["width"], r["height"]
            secs = float((r.get("cover") or {}).get("seconds", 0.034))
            frames = max(1, round(secs * float(r["fps"])))       # 按帧数判断（按时间 t 判断时封面不出现，实测）
            inputs += ["-loop", "1", "-t", f"{secs + 0.2:.3f}", "-i", str(Path(cover).resolve())]
            filt += f"[sv];[2:v]scale={W}:{H},format=yuv420p[cv];[sv][cv]overlay=0:0:enable='lt(n,{frames})':eof_action=pass"
        filt += "[vout]"
        cmd = [cfg["paths"]["ffmpeg"], "-hide_banner", "-loglevel", "error", "-y", *inputs,
               "-filter_complex", filt, "-map", "[vout]", "-map", "1:a", "-t", f"{total:.3f}",
               *_venc(), "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(out.resolve())]
        res = cancellation.run_process(cmd, cwd=work, capture_output=True, text=True, encoding="utf-8", errors="ignore")
        if res.returncode != 0:
            raise RuntimeError(f"合成失败：{res.stderr[-2000:]}")
        return total
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
    res = cancellation.run_process(cmd, cwd=work, capture_output=True, text=True, encoding="utf-8", errors="ignore")
    if res.returncode != 0:
        raise RuntimeError(f"合成失败：{res.stderr[-2000:]}")
    return total
