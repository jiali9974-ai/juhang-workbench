"""自然调色：轻提中间调，保留人物、服饰和手表的原有色相与高光。"""
from __future__ import annotations

import uuid
from pathlib import Path

import numpy as np

from . import config

VERSION = "natural-v4"
SIZE = 33
LUMA = np.array([.2126, .7152, .0722], np.float32)
CURVE = np.array([(0, 0), (.03, .03), (.12, .15), (.3, .43), (.5, .64),
                  (.72, .80), (.9, .925), (1, 1)], np.float32)


def _restore_luma(rgb: np.ndarray, target: np.ndarray) -> np.ndarray:
    """保持目标亮度，接近黑白边界时平滑收缩色度，避免单通道剪切偏色。"""
    chroma = rgb - (rgb @ LUMA)[..., None]
    high = np.maximum(chroma.max(axis=-1), 1e-6)
    low = np.minimum(chroma.min(axis=-1), -1e-6)
    scale = np.minimum(1, np.minimum((1 - target) / high, target / -low))
    return np.clip(target[..., None] + chroma * scale[..., None], 0, 1).astype(np.float32)


def transform(rgb: np.ndarray, strength: float) -> np.ndarray:
    """生成 LUT 用的 RGB→RGB 映射；逐像素处理，不改变构图或纹理。"""
    rgb = np.asarray(rgb, np.float32)
    strength = float(np.clip(strength, 0, 1))
    luma = rgb @ LUMA
    lift = np.interp(luma, CURVE[:, 0], CURVE[:, 1]) - luma
    target = luma + strength * lift
    # 只补偿提亮造成的轻微褪色，不把不同肤色拉成粉红，也不旋转蓝表盘和金表的颜色。
    chroma = rgb - luma[..., None]
    compensation = np.minimum(1.10, np.power(np.maximum(target, 1e-6) / np.maximum(luma, 1e-6), .25))
    colored = luma[..., None] + chroma * compensation[..., None]
    return _restore_luma(colored, target)


def lut_file(strength: float) -> Path:
    """一次生成、后续复用；原子发布，预览和出片共用同一份映射。"""
    strength = round(float(np.clip(strength, 0, 1)), 3)
    directory = config.data_root() / "cache" / "look"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{VERSION}-{round(strength * 1000):04d}.cube"
    if path.is_file():
        return path
    levels = np.linspace(0, 1, SIZE, dtype=np.float32)
    b, g, r = np.meshgrid(levels, levels, levels, indexing="ij")
    # .cube 文件要求红通道变化最快，蓝通道变化最慢。
    colors = transform(np.stack([r, g, b], axis=-1), strength).reshape((-1, 3))
    temporary = path.with_name(f".{path.stem}-{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("w", encoding="ascii", newline="\n") as stream:
            stream.write(f'TITLE "Juhang {VERSION}"\nLUT_3D_SIZE {SIZE}\nDOMAIN_MIN 0 0 0\nDOMAIN_MAX 1 1 1\n')
            np.savetxt(stream, colors, fmt="%.7f")
        try:
            temporary.replace(path)
        except PermissionError:
            # Windows 上并发预览可能正在读取另一请求刚发布的同版本 LUT。
            # 文件已原子发布且内容由版本和强度唯一确定，可以复用；其他写入错误仍上抛。
            if not path.is_file():
                raise
    finally:
        temporary.unlink(missing_ok=True)
    return path


def tone_filter(strength: float) -> str:
    path = lut_file(strength).resolve().as_posix()
    # 先转义选项值，再转义滤镜图；不使用 shell 引号，兼容盘符、引号和方括号目录。
    path = "".join("\\" + char if char in "\\':" else char for char in path)
    path = "".join("\\" + char if char in "\\'[],;" else char for char in path)
    return (f"scale=in_range=auto:out_range=full,format=gbrp,lut3d=file={path}:interp=tetrahedral,"
            "scale=in_range=full:out_range=tv:out_color_matrix=bt709,format=yuv444p,"
            "setparams=range=limited:colorspace=bt709:color_primaries=bt709:color_trc=bt709")
