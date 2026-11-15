"""配音引擎对比：同样的粤语字幕、同一段老板原声做参考，比较各引擎。

用法：.venv/Scripts/python.exe tts_compare.py [引擎…]      （默认 ming cosyvoice3）
输出：data/tts_samples/对比_<引擎>.wav，终端打印对比表
指标：
  - 识别语种：SenseVoice 听生成的音频，判断是不是粤语
  - 字准确率：把听写结果和原文比对（同音字会算错，只看相对高低）
  - 声纹相似度：CAM++ 声纹，和老板原声比较（同一个人两段原声约 0.93）
"""
import difflib
import io
import sys
import time

import librosa
import numpy as np
import onnxruntime as ort
import soundfile as sf
import torch
import torchaudio.compliance.kaldi as kaldi

from jh import asr, config, ming_engine, tts

LINES = [
    "呢两只表咧，我想平五千蚊出咗佢啊",
    "一只嘅话系最新款嘅126334啊",
    "又悠闲嘅白金嘅狗牙圈都相当之锋利",
    "香槟色嘅表盘咧相当之贵气啊，中年大佬嘅挚爱",
    "如果你哋七万左右嘅预算咧，真系唔好再睇日志啦",
    "呢只表喺二手市场好难揾到㗎",
    "到时我将两只表嘅底价都发畀你哋啊",
]
REF = "voice_refs/9.23/2025_09_23_11_14_50_IMG_5840_5.07_16.06.wav"   # 老板原声（粤语，11 秒）


def main(engines):
    config.load()
    d = config.data_root()
    ref = d / REF
    camp = ort.InferenceSession(str(config.load()["paths"]["cosyvoice_repo"] + "/pretrained_models/Fun-CosyVoice3-0.5B/campplus.onnx"),
                                providers=["CPUExecutionProvider"])

    def emb(a, sr):
        a = librosa.resample(a, orig_sr=sr, target_sr=16000)
        f = kaldi.fbank(torch.from_numpy(a).unsqueeze(0), num_mel_bins=80, dither=0, sample_frequency=16000)
        f = f - f.mean(0, keepdim=True)
        e = camp.run(None, {camp.get_inputs()[0].name: f.unsqueeze(0).numpy()})[0][0]
        return e / np.linalg.norm(e)

    ra, rsr = sf.read(str(ref), dtype="float32")
    E = emb(ra, rsr)
    _, sv = asr._models()
    plain = lambda s: "".join(c for c in s if c.isalnum())
    table = []
    for engine in engines:
        sims, accs, yue, secs, gens, pieces, sr0 = [], [], 0, 0.0, 0.0, [], None
        print(f"\n===== {engine} =====", flush=True)
        for i, text in enumerate(LINES, 1):
            t = time.time()
            p = tts.synthesize(text, engine, ref, "yue")
            gens += time.time() - t
            a, sr = sf.read(str(p), dtype="float32", always_2d=True)
            a = a.mean(1)
            sr0 = sr0 or sr
            if sr != sr0:
                a = librosa.resample(a, orig_sr=sr, target_sr=sr0)
            secs += len(a) / sr0
            sims.append(float(E @ emb(a, sr0)))
            r = sv.generate(input=librosa.resample(a, orig_sr=sr0, target_sr=16000), cache={}, language="auto",
                            use_itn=True, ban_emo_unk=True)[0]
            lang, heard = asr._parse_tags(r["text"])
            yue += lang == "yue"
            target = plain(tts.cantonese_tts_text(text))
            accs.append(difflib.SequenceMatcher(None, target, plain(heard)).ratio())
            print(f"[{i}] {len(a)/sr0:4.1f}s 相似度{sims[-1]:.2f} {lang:3} 听写：{heard}", flush=True)
            pieces += [a, np.zeros(int(sr0 * 0.6), "float32")]
        sf.write(str(d / "tts_samples" / f"对比_{engine}.wav"), np.concatenate(pieces), sr0)
        table.append((engine, yue, np.mean(accs), np.mean(sims), gens / len(LINES), secs / len(LINES)))
    ming_engine.stop()
    print("\n引擎          粤语句数  字准确率  声纹相似度  每句生成用时  每句音频时长")
    for e, y, acc, sim, g, s in table:
        print(f"{e:12}  {y}/{len(LINES)}       {acc:5.1%}     {sim:.3f}       {g:5.1f}s        {s:4.1f}s")


if __name__ == "__main__":
    main(sys.argv[1:] or ["ming", "cosyvoice3"])
