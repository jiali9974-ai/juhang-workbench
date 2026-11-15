"""产品图生视频用到的三个云端 ComfyUI 工作流（API 格式）。

节点和参数照云端 ComfyUI 官方模板：
  - image_qwen_image_2_1_image_edit.json   Qwen-Image 2.1（带参考图）
  - blueprints/Image to Video (MiniMax H3).json   H3 首尾帧（fl2va）
"""
from __future__ import annotations

import random

from . import config


def _c() -> dict:
    return config.load()["tvc"]


def h3_frames(seconds: float) -> int:
    """H3 固定 24fps，帧数要对齐到 17k+5（和官方蓝图的公式一样）。"""
    n = max(5, round(seconds * 24))
    return n + (5 - n % 17) % 17


def caption_graph(image_name: str, instruction: str, max_length: int = 700) -> dict:
    """Qwen3-VL 看产品图，输出文字描述。"""
    return {
        "1": {"class_type": "LoadImage", "inputs": {"image": image_name}},
        "2": {"class_type": "CLIPLoader", "inputs": {"clip_name": _c()["caption_clip"], "type": "qwen_image", "device": "default"}},
        "3": {"class_type": "TextGenerate", "inputs": {"clip": ["2", 0], "prompt": instruction, "max_length": max_length,
                                                       "sampling_mode": "off", "image": ["1", 0]}},
        "4": {"class_type": "PreviewAny", "inputs": {"source": ["3", 0]}},
    }


def keyframe_graph(prompt: str, ref_images: list[str], prefix: str, seed: int | None = None,
                   negative: str = "", width: int | None = None, height: int | None = None) -> dict:
    """Qwen-Image 2.1：带产品参考图生成一张分镜关键帧。"""
    q = _c()["qwen"]
    w, h = width or _c()["width"], height or _c()["height"]
    g = {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": q["unet"], "weight_dtype": "default"}},
        "2": {"class_type": "QwenImage21Cache", "inputs": {"model": ["1", 0], "device": "auto", "dtype": "default"}},
        "3": {"class_type": "CLIPLoader", "inputs": {"clip_name": q["clip"], "type": "qwen_image", "device": "default"}},
        "4": {"class_type": "VAELoader", "inputs": {"vae_name": q["vae"]}},
        "6": {"class_type": "TextEncodeQwenImage21", "inputs": {"clip": ["3", 0], "vae": ["4", 0], "prompt": prompt,
                                                                "negative_prompt": negative, "resolution": 1024}},
        "7": {"class_type": "EmptyLatentImage", "inputs": {"width": w, "height": h, "batch_size": 1}},
        "8": {"class_type": "KSampler", "inputs": {"model": ["2", 0], "positive": ["6", 0], "negative": ["6", 1],
                                                   "latent_image": ["7", 0], "seed": seed if seed is not None else random.randrange(1 << 48),
                                                   "steps": q["steps"], "cfg": q["cfg"], "sampler_name": "euler",
                                                   "scheduler": "simple", "denoise": 1.0}},
        "9": {"class_type": "VAEDecode", "inputs": {"samples": ["8", 0], "vae": ["4", 0]}},
        "10": {"class_type": "SaveImage", "inputs": {"images": ["9", 0], "filename_prefix": prefix}},
    }
    for i, name in enumerate(ref_images, 1):     # 参考图：第 1 张是产品原图
        g[f"r{i}"] = {"class_type": "LoadImage", "inputs": {"image": name}}
        g["6"]["inputs"][f"images.image_{i}"] = [f"r{i}", 0]
    return g


def h3_graph(prompt: str, first_frame: str, last_frame: str | None, seconds: float, prefix: str,
             seed: int | None = None, width: int | None = None, height: int | None = None) -> dict:
    """MiniMax H3 首尾帧生音视频（fl2va）。"""
    h = _c()["h3"]
    w, hh = width or _c()["width"], height or _c()["height"]
    turbo = h.get("use_turbo", True)
    g = {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": h["unet"], "weight_dtype": "default"}},
        "3": {"class_type": "CLIPLoader", "inputs": {"clip_name": h["clip"], "type": "minimax", "device": "default"}},
        "4": {"class_type": "VAELoader", "inputs": {"vae_name": h["video_vae"]}},
        "5": {"class_type": "VAELoader", "inputs": {"vae_name": h["audio_vae"]}},
        "6": {"class_type": "LoadImage", "inputs": {"image": first_frame}},
        "8": {"class_type": "MiniMaxH3ImageToVideo", "inputs": {"clip": ["3", 0], "vae": ["4", 0], "prompt": prompt,
                                                                "width": w, "height": hh, "length": h3_frames(seconds),
                                                                "first_frame": ["6", 0]}},
        "9": {"class_type": "KSamplerSelect", "inputs": {"sampler_name": "res_multistep"}},
        "10": {"class_type": "BasicScheduler", "inputs": {"model": ["2" if turbo else "1", 0], "scheduler": "simple",
                                                          "steps": h["steps_turbo"] if turbo else h["steps_full"], "denoise": 1.0}},
        "11": {"class_type": "RandomNoise", "inputs": {"noise_seed": seed if seed is not None else random.randrange(1 << 48)}},
        "12": {"class_type": "BasicGuider", "inputs": {"model": ["2" if turbo else "1", 0], "conditioning": ["8", 0]}},
        "13": {"class_type": "SamplerCustomAdvanced", "inputs": {"noise": ["11", 0], "guider": ["12", 0], "sampler": ["9", 0],
                                                                 "sigmas": ["10", 0], "latent_image": ["8", 1]}},
        "14": {"class_type": "VAEDecode", "inputs": {"samples": ["13", 0], "vae": ["4", 0]}},
        "15": {"class_type": "VAEDecodeAudio", "inputs": {"samples": ["13", 0], "vae": ["5", 0]}},
        "16": {"class_type": "CreateVideo", "inputs": {"images": ["14", 0], "audio": ["15", 0], "fps": 24}},
        "17": {"class_type": "SaveVideo", "inputs": {"video": ["16", 0], "filename_prefix": prefix, "format": "auto", "codec": "auto"}},
    }
    if turbo:
        g["2"] = {"class_type": "LoraLoaderModelOnly", "inputs": {"model": ["1", 0], "lora_name": h["turbo_lora"], "strength_model": 1.0}}
    if last_frame:
        g["7"] = {"class_type": "LoadImage", "inputs": {"image": last_frame}}
        g["8"]["inputs"]["last_frame"] = ["7", 0]
    return g
