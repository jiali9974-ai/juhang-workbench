"""用 9.23 剪辑脚本里的真实粤语字幕生成一组配音样音，拼成一个文件方便试听。

用法：.venv/Scripts/python.exe tts_samples.py ming        （或 cosyvoice3）
输出：data/tts_samples/<引擎>_样音.wav  以及每句单独的 wav
"""
import shutil
import sys
import time

import numpy as np
import soundfile as sf

from jh import config, tts

LINES = [
    "呢两只表咧，我想平五千蚊出咗佢啊",
    "一只嘅话系最新款嘅126334啊",
    "又悠闲嘅白金嘅狗牙圈都相当之锋利",
    "香槟色嘅表盘咧相当之贵气啊，中年大佬嘅挚爱",
    "如果你哋七万左右嘅预算咧，真系唔好再睇日志啦",
    # 普通话素材翻译过来的句子（原话：这只表现在二级市场很难找到）
    "呢只表喺二手市场好难揾到㗎",
    "到时我将两只表嘅底价都发畀你哋啊",
]


def main(engine: str):
    config.load()
    out_dir = config.data_root() / "tts_samples"
    out_dir.mkdir(parents=True, exist_ok=True)
    pieces, sr = [], None
    for i, text in enumerate(LINES, 1):
        t = time.time()
        wav = tts.synthesize(text, engine)
        dur = tts.wav_duration(wav)
        print(f"[{i}/{len(LINES)}] {dur:4.1f}s 音频，用时 {time.time() - t:4.1f}s  {text}", flush=True)
        shutil.copy(wav, out_dir / f"{engine}_{i:02d}.wav")
        data, rate = sf.read(str(wav), dtype="float32", always_2d=True)
        data = data.mean(axis=1)
        if sr is None:
            sr = rate
        elif rate != sr:
            # 简单重采样到同一采样率
            data = np.interp(np.linspace(0, len(data), int(len(data) * sr / rate), endpoint=False), np.arange(len(data)), data)
        pieces += [data, np.zeros(int(sr * 0.6), dtype="float32")]
    total = out_dir / f"{engine}_样音.wav"
    sf.write(str(total), np.concatenate(pieces), sr)
    print("OUT", total, flush=True)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "ming")
