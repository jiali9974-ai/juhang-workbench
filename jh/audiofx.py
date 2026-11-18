"""成片声音处理：原声两遍响度标准化、背景音乐循环混音和限幅。"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import numpy as np
import soundfile as sf

from . import config

SR = 48000


def _ff(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run([config.ffmpeg(), "-hide_banner", "-y", *args], capture_output=True, text=True,
                          encoding="utf-8", errors="ignore")


def loudnorm_2pass(src: Path, dst: Path, target_i: float = -16.0, tp: float = -1.5, lra: float = 11.0, pre: str = "") -> Path:
    """两遍响度标准化：第一遍测量，第二遍用固定增益（linear=true）调到目标，不会忽大忽小。pre 是放在前面的滤镜（如高通）。"""
    chain = (pre + "," if pre else "")
    r = _ff(["-i", str(src), "-af", f"{chain}loudnorm=I={target_i}:TP={tp}:LRA={lra}:print_format=json", "-f", "null", "-"])
    m = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", r.stderr)
    if not m:
        raise RuntimeError(f"响度测量失败：{r.stderr[-800:]}")
    st = json.loads(m.group(0))
    second = (f"{chain}loudnorm=I={target_i}:TP={tp}:LRA={lra}:measured_I={st['input_i']}:measured_TP={st['input_tp']}:"
              f"measured_LRA={st['input_lra']}:measured_thresh={st['input_thresh']}:offset={st['target_offset']}:linear=true,"
              f"aresample={SR}")
    r = _ff(["-i", str(src), "-af", second, "-ar", str(SR), "-c:a", "pcm_s16le", str(dst)])
    if r.returncode:
        raise RuntimeError(f"响度标准化失败：{r.stderr[-800:]}")
    return dst


def load(path: Path, channels: int = 1, sr: int = SR) -> np.ndarray:
    r = subprocess.run([config.ffmpeg(), "-hide_banner", "-loglevel", "error", "-i", str(path), "-ac", str(channels),
                        "-ar", str(sr), "-f", "f32le", "-"], capture_output=True)
    if r.returncode:
        raise RuntimeError(r.stderr.decode("utf-8", "ignore")[-500:])
    y = np.frombuffer(r.stdout, dtype=np.float32).copy()
    return y.reshape(-1, channels) if channels > 1 else y


def loop_to(y: np.ndarray, n: int, xfade: float = 0.6) -> np.ndarray:
    """把一段音乐（[样本, 声道]）无缝循环到 n 个样本：每次接头处交叉淡化 xfade 秒。"""
    if len(y) >= n:
        return y[:n].copy()
    k = int(xfade * SR)
    out = y.copy()
    ramp = np.linspace(0, 1, k, dtype=np.float32)[:, None]
    while len(out) < n:
        head = y[:k] * ramp
        out[-k:] = out[-k:] * ramp[::-1] + head
        out = np.concatenate([out, y[k:]])
    return out[:n]


def lufs(path: Path) -> float:
    r = _ff(["-i", str(path), "-af", "loudnorm=print_format=json", "-f", "null", "-"])
    m = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", r.stderr)
    return float(json.loads(m.group(0))["input_i"]) if m else -70.0


def master_voice_bgm(voice_src: Path, bgm: Path | None, seconds: float, work: Path, voice_lufs: float = -11.0,
                     bgm_below: float = 12.0, limit_db: float = -1.0) -> Path:
    """素材剪辑成片的声音（照参考视频）：人声两遍标准化到 voice_lufs（固定增益，不抽动）；
    背景音乐无缝循环铺满全片，响度固定比人声低 bgm_below LU（参考视频约 12），不随人声压低；最后限幅。"""
    work.mkdir(parents=True, exist_ok=True)
    vraw = work / "voice_src.wav"
    r = _ff(["-i", str(voice_src), "-vn", "-ac", "2", "-ar", str(SR), "-t", f"{seconds:.3f}", "-c:a", "pcm_s16le", str(vraw)])
    if r.returncode:
        raise RuntimeError(f"取人声失败：{r.stderr[-800:]}")
    # 参考视频的人声压得很紧（响度范围约 2.6 LU）：先压缩（-23dB 以上 4:1），再固定增益调到目标响度；峰值交给最后的限幅器
    vn = loudnorm_2pass(vraw, work / "voice_norm.wav", target_i=voice_lufs, tp=0.0,
                        pre="highpass=f=60,acompressor=threshold=0.071:ratio=4:attack=10:release=150:makeup=1")
    v = load(vn, channels=2)
    n = int(seconds * SR)
    v = np.pad(v, ((0, max(0, n - len(v))), (0, 0)))[:n]
    if bgm and Path(bgm).exists():
        src = load(Path(bgm), channels=2)
        bpm = float(config.load()["render"].get("bgm_bpm") or 0)
        if bpm > 0:
            # 按小节循环：只取整数个小节（4 拍）再接回开头，节奏不会断；接头处只淡 30 毫秒
            bar = int(round(4 * 60 / bpm * SR))
            if len(src) >= 2 * bar:
                src = src[: (len(src) // bar) * bar]
            b = loop_to(src, n, xfade=0.03)
        else:
            b = loop_to(src, n)
        braw = work / "bgm_loop.wav"
        sf.write(str(braw), b, SR)
        bl = lufs(braw)
        gain = 10 ** (((voice_lufs - bgm_below) - bl) / 20) if bl > -60 else 0.0
        fade = int(min(1.5, seconds / 4) * SR)              # 结尾 1.5 秒音乐淡出
        b = b * gain
        if fade > 0:
            b[-fade:] *= np.linspace(1, 0, fade, dtype=np.float32)[:, None]
        v = v + b
    mixed = work / "mix_raw.wav"
    sf.write(str(mixed), v, SR)
    final = work / "mix.wav"
    lim = 10 ** (limit_db / 20)
    r = _ff(["-i", str(mixed), "-af", f"alimiter=limit={lim:.3f}:attack=5:release=50:level=false", "-ar", str(SR),
             "-c:a", "pcm_s16le", str(final)])
    if r.returncode:
        raise RuntimeError(f"限幅失败：{r.stderr[-800:]}")
    return final
