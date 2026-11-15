"""粤语配音。引擎可替换：cosyvoice3（本地）/ azure（官方云服务）。

synthesize(text) 返回 wav 路径，按文本和音色做缓存，同一句不会重复生成。
"""
from __future__ import annotations

import hashlib
import os
import sys
from functools import lru_cache
from pathlib import Path

from . import config


def _cache_path(engine: str, voice_key: str, text: str) -> Path:
    h = hashlib.md5(f"{engine}|{voice_key}|{text}".encode("utf-8")).hexdigest()[:16]
    p = config.data_root() / "tts_cache" / engine
    p.mkdir(parents=True, exist_ok=True)
    return p / f"{h}.wav"


# ---------------- CosyVoice3 ----------------

def _patch_torchaudio() -> None:
    """torchaudio 2.9+ 读写音频要靠 torchcodec，这台机器上它加载不了；wav 读写改用 soundfile。"""
    import numpy as np
    import soundfile as sf
    import torch
    import torchaudio

    if getattr(torchaudio, "_jh_patched", False):
        return

    def load(path, *args, **kwargs):
        data, sr = sf.read(str(path), dtype="float32", always_2d=True)   # (帧, 声道)
        return torch.from_numpy(np.ascontiguousarray(data.T)), sr

    def save(path, tensor, sample_rate, *args, **kwargs):
        sf.write(str(path), tensor.detach().cpu().numpy().T, int(sample_rate))

    torchaudio.load, torchaudio.save, torchaudio._jh_patched = load, save, True


@lru_cache(maxsize=1)
def _cosyvoice():
    _patch_torchaudio()
    repo = Path(config.load()["paths"]["cosyvoice_repo"])
    for p in (repo, repo / "third_party" / "Matcha-TTS"):
        if str(p) not in sys.path:
            sys.path.insert(0, str(p))
    from cosyvoice.cli.cosyvoice import AutoModel  # noqa: E402

    cfg = config.load()["tts"]["cosyvoice3"]
    return AutoModel(model_dir=str(repo / cfg["model_dir"]))


def _cosyvoice_synth(text: str, out: Path, ref_wav: Path | None = None) -> Path:
    import torch
    import torchaudio

    _patch_torchaudio()
    cfg = config.load()["tts"]["cosyvoice3"]
    repo = Path(config.load()["paths"]["cosyvoice_repo"])
    prompt = str(ref_wav) if ref_wav else cfg["prompt_wav"]
    prompt = str(prompt if Path(prompt).is_absolute() else repo / prompt)
    model = _cosyvoice()
    pieces = [r["tts_speech"] for r in model.inference_instruct2(
        text, cfg["instruct"], prompt, stream=False, speed=float(cfg.get("speed", 1.0)))]
    torchaudio.save(str(out), torch.cat(pieces, dim=1), model.sample_rate)
    return out


# ---------------- Azure ----------------

def _azure_synth(text: str, out: Path) -> Path:
    import requests

    cfg = config.load()["tts"]["azure"]
    key = config.secret(cfg["api_key_env"])
    if not key:
        raise RuntimeError(f"没有设置 Azure 语音 Key：在 secrets.yaml 里填 {cfg['api_key_env']}")
    from xml.sax.saxutils import escape

    ssml = (f"<speak version='1.0' xml:lang='zh-HK'><voice name='{cfg['voice']}'>"
            f"{escape(text)}</voice></speak>")
    r = requests.post(
        f"https://{cfg['region']}.tts.speech.microsoft.com/cognitiveservices/v1",
        headers={"Ocp-Apim-Subscription-Key": key, "Content-Type": "application/ssml+xml",
                 "X-Microsoft-OutputFormat": "riff-48khz-16bit-mono-pcm"},
        data=ssml.encode("utf-8"), timeout=60)
    r.raise_for_status()
    out.write_bytes(r.content)
    return out


# ---------------- Ming-3.0（audio.cpp 引擎，工作台自动启动） ----------------

_DIGITS = str.maketrans("0123456789", "零一二三四五六七八九")
_CN = "零一二三四五六七八九"


def _small_int(n: int) -> str:
    """0–9999 的中文读法（粤语字幕里的表径、年份以外的小数字）。"""
    if n < 10:
        return _CN[n]
    if n < 20:
        return "十" + (_CN[n % 10] if n % 10 else "")
    out, units = "", [(1000, "千"), (100, "百"), (10, "十")]
    zero = False
    for v, u in units:
        d = n // v % 10
        if d:
            out += ("零" if zero and out else "") + _CN[d] + u
            zero = False
        elif out:
            zero = True
    if n % 10:
        out += ("零" if zero else "") + _CN[n % 10]
    return out


def cantonese_tts_text(text: str) -> str:
    """配音前的读法整理：型号等 3 位以上数字逐位读（126334 → 一二六三三四），小数字读成中文（41 → 四十一）。"""
    import re

    text = re.sub(r"\d{3,}", lambda m: m.group(0).translate(_DIGITS), text)   # 型号、年份逐位读
    text = re.sub(r"\d{1,2}", lambda m: _small_int(int(m.group(0))), text)    # 表径等小数字
    return text.strip()


def _ming_payload(text: str, seed: int, ref: bytes | None) -> dict:
    import base64

    cfg = config.load()["tts"]["ming"]
    p = {"model": "ming", "input": text, "seed": str(seed),
         "options": {"template_name": "dialect", "dialect": cfg.get("dialect", "cantonese")}}
    if ref:
        p["voice_ref"] = {"type": "base64", "data": base64.b64encode(ref).decode()}
    else:
        # 不给参考声音时把说话人向量置零，否则容易跳读整句（和官方实现一致）
        p["options"]["zero_speaker_embedding"] = True
    return p


def _wav_seconds(data: bytes) -> float:
    import io
    import wave

    with wave.open(io.BytesIO(data)) as w:
        return w.getnframes() / w.getframerate()


def _ming_once(text: str, ref: bytes | None) -> bytes:
    """读得太长（拖尾、乱读）就换下一个种子重来，最多 4 次，都不行留最短的。"""
    from . import ming_engine

    seed = int(config.load()["tts"]["ming"].get("seed", 20251115))
    chars = len([c for c in text if c.isalnum()])
    limit = max(4.0, chars * 0.45)
    tried = []
    for n in range(4):
        wav = ming_engine.speech(_ming_payload(text, seed + n, ref))
        sec = _wav_seconds(wav)
        if sec <= limit:
            return wav
        tried.append((sec, wav))
    return min(tried)[1]


def _ming_voice(ref_wav: Path | None = None) -> bytes:
    """整条视频同一个声音：用参考音频（老板原声或你录的）先“说一段粤语”当锚点，之后每句都参考锚点。
    没有参考音频时，用固定种子生成一个声音。"""
    cfg = config.load()["tts"]["ming"]
    anchor_text = cfg.get("ref_text", "今日天气几好，我哋食完饭一齐去海边行下啦，你话好唔好呀？呢间茶餐厅啲嘢真系好好食。")
    user_ref = str(ref_wav) if ref_wav else (cfg.get("ref_wav") or "")
    ref_sig = hashlib.md5(Path(user_ref).read_bytes()).hexdigest() if user_ref else ""
    key = hashlib.md5((ref_sig + "|" + str(cfg.get("seed")) + "|" + anchor_text).encode()).hexdigest()[:10]
    p = config.data_root() / "tts_ref" / f"ming_cantonese_{key}.wav"
    if not p.exists():
        p.parent.mkdir(parents=True, exist_ok=True)
        ref = Path(user_ref).read_bytes() if user_ref else None
        # 用你录的声音时，先让它“说一段粤语”当锚点，后面每句参考锚点，粤语口音更稳
        p.write_bytes(_ming_once(anchor_text, ref))
    return p.read_bytes()


def _ming_synth(text: str, out: Path, ref_wav: Path | None = None, ref_lang: str | None = None) -> Path:
    cfg = config.load()["tts"]["ming"]
    if ref_wav and ref_lang == "yue":
        # 参考原声本身就是粤语：每句直接参考它，最像本人（实测声纹相似度 0.84，经过锚点只有 0.66）
        ref = Path(ref_wav).read_bytes()
    else:
        # 参考是普通话或没有参考：先用它“说一段粤语”当锚点，保证口音是粤语
        ref = _ming_voice(ref_wav) if (ref_wav or cfg.get("same_voice", True)) else None
    wav = _ming_once(cantonese_tts_text(text), ref)
    out.write_bytes(wav)
    speed = float(cfg.get("speed", 1.0))
    if abs(speed - 1.0) > 0.01:
        from . import media

        tmp = out.with_suffix(".tmp.wav")
        out.rename(tmp)
        media.run_ffmpeg(["-i", str(tmp), "-filter:a", f"atempo={speed}", str(out)])
        tmp.unlink()
    return out


def _voice_key(engine: str) -> str:
    cfg = config.load()["tts"]
    if engine == "cosyvoice3":
        c = cfg["cosyvoice3"]
        return c["prompt_wav"] + c["instruct"] + str(c.get("speed"))
    if engine == "ming":
        c = cfg["ming"]
        return f"{c.get('dialect')}|{c.get('seed')}|{c.get('speed')}|{c.get('same_voice', True)}|{c.get('ref_wav', '')}"
    return cfg["azure"]["voice"]


def synthesize(text: str, engine: str | None = None, ref_wav: Path | None = None, ref_lang: str | None = None) -> Path:
    """生成一句配音。ref_wav 是参考音色（例如从原素材截的老板原声），ref_lang 是参考原声的语种（yue/zh）。
    Azure 不支持参考音色，会忽略。"""
    engine = engine or config.load()["tts"]["engine"]
    key = _voice_key(engine)
    if ref_wav and engine in ("ming", "cosyvoice3"):
        key += "|ref:" + hashlib.md5(Path(ref_wav).read_bytes()).hexdigest() + "|" + str(ref_lang == "yue")
    out = _cache_path(engine, key, text)
    if out.exists():
        return out
    if engine == "cosyvoice3":
        return _cosyvoice_synth(text, out, ref_wav)
    if engine == "ming":
        return _ming_synth(text, out, ref_wav, ref_lang)
    if engine == "azure":
        return _azure_synth(text, out)
    raise ValueError(f"未知的配音引擎: {engine}")


def wav_duration(path: Path) -> float:
    import soundfile as sf

    info = sf.info(str(path))
    return info.frames / info.samplerate
