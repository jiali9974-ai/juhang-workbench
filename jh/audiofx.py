"""成片声音处理：配音清理 + 两遍响度标准化（不抽动）+ 环境声垫底 + 限幅。

一遍式 loudnorm 会边播边调音量，干净的配音会被“抽”得忽大忽小、停顿处的底噪被抬起来；
这里先量一遍、再按固定增益调到目标响度（linear），声音和配音模型原本的一样，只是音量统一了。
"""
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


def rms(y: np.ndarray) -> float:
    y = y[np.abs(y) > 1e-4]
    return float(np.sqrt(np.mean(y ** 2))) if len(y) else 0.0


def fade(y: np.ndarray, ms: float = 40) -> np.ndarray:
    n = min(len(y) // 2, int(SR * ms / 1000))
    if n > 0:
        ramp = np.linspace(0, 1, n, dtype=np.float32)
        if y.ndim > 1:
            ramp = ramp[:, None]
        y[:n] *= ramp
        y[-n:] *= ramp[::-1]
    return y


def master(voice: np.ndarray, bed: np.ndarray | None, work: Path, bed_db: float = -22.0, target_i: float = -16.0) -> Path:
    """voice：单声道配音轨；bed：立体声环境声轨（可以没有）。返回处理好的 48k 立体声 wav。"""
    work.mkdir(parents=True, exist_ok=True)
    raw = work / "voice_raw.wav"
    sf.write(str(raw), np.stack([voice, voice], axis=1), SR)       # 先变立体声再量响度（单声道复制成双声道会响 3dB）
    vn = loudnorm_2pass(raw, work / "voice_norm.wav", target_i=target_i, pre="highpass=f=70")
    out = load(vn, channels=2)
    v = out[:, 0]
    if bed is not None and rms(bed) > 0:
        n = min(len(bed), len(out))
        gain = rms(v) * 10 ** (bed_db / 20) / rms(bed)
        out[:n] += bed[:n] * gain
    mixed = work / "mix_raw.wav"
    sf.write(str(mixed), out, SR)
    final = work / "mix.wav"
    # 限幅到 -2dBFS：给 AAC 编码留余量（编码后峰值会比 wav 高一点）
    r = _ff(["-i", str(mixed), "-af", "alimiter=limit=0.79:attack=5:release=50:level=false", "-ar", str(SR), "-c:a", "pcm_s16le", str(final)])
    if r.returncode:
        raise RuntimeError(f"限幅失败：{r.stderr[-800:]}")
    return final


def replace_audio(video: Path, audio: Path, out: Path) -> Path:
    # 0:V 只取真正的画面轨：成片里可能带封面图片轨（attached_pic），带上它配 -shortest 会把视频截短
    r = _ff(["-i", str(video), "-i", str(audio), "-map", "0:V", "-map", "1:a", "-c:v", "copy", "-c:a", "aac", "-b:a", "256k",
             "-shortest", "-movflags", "+faststart", str(out)])
    if r.returncode:
        raise RuntimeError(f"替换声音失败：{r.stderr[-800:]}")
    return out


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
