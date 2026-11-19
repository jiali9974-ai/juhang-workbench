"""参考风格调色：通透中间调、自然肤色、干净的浅蓝，保留中性灰与黑白端点。"""
from __future__ import annotations

import uuid
from pathlib import Path

import cv2
import numpy as np

from . import config

VERSION = "reference-v2"
SIZE = 33
LUMA = np.array([.2126, .7152, .0722], np.float32)
CURVE = np.array([(0, 0), (.03, .025), (.12, .16), (.3, .55), (.5, .81),
                  (.72, .90), (.9, .96), (1, 1)], np.float32)


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
    shape = rgb.shape
    hsv = cv2.cvtColor(rgb.reshape((-1, 1, 3)), cv2.COLOR_RGB2HSV).reshape(shape)
    hue, saturation = hsv[..., 0].copy(), hsv[..., 1].copy()
    distance = lambda center: np.abs((hue - center + 180) % 360 - 180)
    skin = np.exp(-.5 * (distance(24) / 26) ** 2)
    blue = np.exp(-.5 * (distance(212) / 30) ** 2)
    chromatic = np.clip((saturation - .02) / .10, 0, 1)
    luma = rgb @ LUMA
    lift = np.interp(luma, CURVE[:, 0], CURVE[:, 1]) - luma
    # 蓝色不跟着肤色一起泛白，深色保留层次，高光平滑收束。
    target = luma + strength * lift * (1 - .32 * blue * chromatic)
    toned = _restore_luma(rgb, target)
    hsv = cv2.cvtColor(toned.reshape((-1, 1, 3)), cv2.COLOR_RGB2HSV).reshape(shape)
    skin_delta = np.clip((8 - hue + 180) % 360 - 180, -10, 10)
    # 肤色只向轻微红润靠拢，限制色相偏移，避免木饰面、金表被一起推成粉红。
    shift = min(1., 2 * strength) * skin * skin_delta + strength * 26 * blue
    hsv[..., 0] = (hsv[..., 0] + chromatic * shift) % 360
    hsv[..., 1] = np.clip(hsv[..., 1] * (1 + strength * chromatic * (.34 * skin + 1.5 * blue)), 0, 1)
    colored = cv2.cvtColor(hsv.reshape((-1, 1, 3)), cv2.COLOR_HSV2RGB).reshape(shape)
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
        temporary.replace(path)
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
