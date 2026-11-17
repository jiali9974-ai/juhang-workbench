"""按素材统一亮度和白平衡。

不同天、不同地方拍的素材光线不一样（实测 9.23 那批人脸比 1234 亮很多，1234 自己每条之间也差不少）。
出片时先量每条素材里老板脸上皮肤的亮度和颜色，把它拉到同一个基准，再套统一的美颜调色。
这样不管素材原来是什么光线，成片的肤色和亮度都差不多。

- 基准是 1234 这批素材的典型肤色。美颜调色就是照这批调的，照参考视频对过亮度，所以拉到这个基准再调色就和参考视频一致。
- 每段在段内量几帧人脸算校正值，整段用同一个值，不会闪。量不到人脸的段（手表特写）用整条素材有人脸的画面量出来的值
  （同一次拍摄灯光一样；实测同一条里没人脸和有人脸的画面亮度中位数只差 0–16%）。
- 亮度像调相机曝光：中间调拉到目标，纯白还是纯白、纯黑还是纯黑，颜色浓度跟着亮度一起变，不会压暗后变艳。
- 白平衡只校一半、每个通道最多 ±6%：不同人肤色本来就不同，只去掉明显的偏色。
- 从头到尾都没拍到脸的素材：只按画面里接近白色的地方轻微校白平衡，不动亮度。
"""
from __future__ import annotations

import json
import subprocess
import threading
from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np

from . import config

W, H = 540, 960                         # 测光用的画面大小（够看清脸，速度快）
FRAMES = 10                             # 每条素材均匀取多少帧测光
LUMA = np.array([0.2126, 0.7152, 0.0722])
_lock = threading.Lock()
_mesh = None


def _cfg() -> dict:
    n = dict(config.load()["render"].get("normalize") or {})
    n.setdefault("enabled", True)
    n.setdefault("target_skin", [137.5, 99.0, 84.0])        # 1234 那批 41 条素材脸上皮肤的中位数 RGB（调色前）
    n.setdefault("max_ratio", 1.8)                          # 皮肤亮度最多提亮到 1.8 倍 / 压暗到 1/1.8
    n.setdefault("wb", 0.06)                                # 白平衡每个通道最多校 ±6%
    return n


def _framing(zoom: float) -> str:
    return (f"crop='min(iw,ih*{W}/{H})/{zoom}':'min(ih,iw*{H}/{W})/{zoom}',"
            f"scale={W}:{H}:flags=area")


def grab(clip: Path, t: float, zoom: float = 1.0) -> np.ndarray | None:
    """取一帧 RGB（裁成成片的构图，缩小到 540×960）。"""
    r = subprocess.run([config.ffmpeg(), "-hide_banner", "-loglevel", "error", "-ss", f"{max(0.0, t):.3f}",
                        "-i", str(clip), "-frames:v", "1", "-vf", _framing(zoom), "-f", "rawvideo",
                        "-pix_fmt", "rgb24", "-"], capture_output=True)
    if len(r.stdout) != W * H * 3:
        return None
    return np.frombuffer(r.stdout, np.uint8).reshape(H, W, 3)


def _face_mesh():
    global _mesh
    if _mesh is None:
        from mediapipe.python.solutions.face_mesh import FaceMesh

        _mesh = FaceMesh(static_image_mode=True, max_num_faces=1, min_detection_confidence=0.6)
    return _mesh


def skin(img: np.ndarray) -> dict | None:
    """脸上皮肤的典型颜色：脸的轮廓里去掉眼睛、眉毛、嘴、鼻孔和额头最上面（头发），
    再去掉最亮（反光）和最暗（胡子、阴影）的部分，取中位数。没有脸、脸太小就返回 None。"""
    from .skin import _FACE, _FEATURES

    with _lock:
        res = _face_mesh().process(img)
    if not res.multi_face_landmarks:
        return None
    h, w = img.shape[:2]
    pts = np.array([(p.x * w, p.y * h) for p in res.multi_face_landmarks[0].landmark], np.float32)
    fw = float(np.ptp(pts[_FACE, 0]))
    if fw < w * 0.12:
        return None
    mask = np.zeros((h, w), np.uint8)
    cv2.fillPoly(mask, [np.rint(pts[_FACE]).astype(np.int32)], 255)
    top, bottom = pts[_FACE, 1].min(), pts[_FACE, 1].max()
    mask[: int(top + (bottom - top) * 0.22)] = 0
    for frac, feats in _FEATURES:
        prot = np.zeros_like(mask)
        for f in feats:
            cv2.fillConvexPoly(prot, cv2.convexHull(np.rint(pts[f]).astype(np.int32)), 255)
        k = max(3, round(fw * (frac + 0.03)))
        mask[cv2.dilate(prot, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * k + 1, 2 * k + 1))) != 0] = 0
    px = img[mask != 0].astype(np.float32)
    if len(px) < 300:
        return None
    y = px @ LUMA.astype(np.float32)
    lo, hi = np.percentile(y, [15, 85])
    px = px[(y >= lo) & (y <= hi)]
    return {"rgb": [round(float(v), 2) for v in np.median(px, axis=0)], "face_w": round(fw / w, 3)}


def neutral(img: np.ndarray) -> list[float] | None:
    """画面里接近白色、灰色的亮处（白墙、白桌面）的平均颜色，用来估白平衡。"""
    f = img.astype(np.float32)
    y = f @ LUMA.astype(np.float32)
    mx, mn = f.max(axis=2), f.min(axis=2)
    sel = ((mx - mn) / np.maximum(mx, 1) < 0.18) & (y > 120) & (mx < 250)
    if sel.sum() < W * H * 0.02:
        return None
    return [round(float(v), 2) for v in f[sel].mean(axis=0)]


def _times(start: float, dur: float, n: int) -> list[float]:
    return [start + dur * (i + 0.5) / n for i in range(n)]


def _cache_file(clip: Path) -> Path:
    return config.data_root() / "clipinfo" / "normalize" / (clip.parent.name + "__" + clip.stem + ".json")


@lru_cache(maxsize=512)
def clip_profile(clip: str) -> dict:
    """整条素材的灯光：均匀取 10 帧，有脸的帧取皮肤颜色中位数，没脸的帧取白色处颜色中位数。结果存盘缓存。"""
    from . import media

    p = Path(clip)
    cache = _cache_file(p)
    if cache.exists():
        return json.loads(cache.read_text(encoding="utf-8"))
    skins, neutrals = [], []
    for t in _times(0, media.probe(p).duration, FRAMES):
        img = grab(p, t)
        if img is None:
            continue
        s = skin(img)
        if s:
            skins.append(s["rgb"])
        else:
            n = neutral(img)
            if n:
                neutrals.append(n)
    out = {"skin": np.median(skins, axis=0).round(2).tolist() if skins else None, "faces": len(skins),
           "neutral": np.median(neutrals, axis=0).round(2).tolist() if neutrals else None}
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(out), encoding="utf-8")
    return out


@lru_cache(maxsize=1024)
def segment_profile(clip: str, start: float, dur: float, frames: int = 5) -> dict:
    """一段画面的灯光：段内均匀取几帧量皮肤颜色。同一条素材前后光线也可能变（相机自动曝光），所以按段量更准。"""
    skins = []
    for t in _times(start, max(dur, 0.1), frames):
        img = grab(Path(clip), t)
        s = skin(img) if img is not None else None
        if s:
            skins.append(s["rgb"])
    return {"skin": np.median(skins, axis=0).round(2).tolist() if skins else None, "faces": len(skins), "neutral": None}


def correction(prof: dict, cfg: dict | None = None) -> dict | None:
    """算校正值：{"wb": (r, g, b) 三个通道的系数, "mid": (皮肤亮度, 目标亮度) 0–1, "k": 颜色浓度跟着亮度变的倍数}。
    不用校正返回 None。"""
    cfg = cfg or _cfg()
    if not cfg["enabled"]:
        return None
    if prof.get("skin") and prof.get("faces", 0) >= 2:
        t = np.array(cfg["target_skin"], np.float64)
        m = np.maximum(np.array(prof["skin"], np.float64), 1)
        # 白平衡：每个人肤色本来就不一样（1234 和 9.x 出镜的不是同一个人），所以只校一半、最多 ±wb，只去掉明显的偏色
        wb = (t / m) / (LUMA @ t / (LUMA @ m))
        wb = 1 + 0.5 * (wb / (LUMA @ wb) - 1)
        wb = np.clip(wb, 1 - cfg["wb"], 1 + cfg["wb"])
        my, ty = float(LUMA @ m) / 255, float(LUMA @ t) / 255
        r = cfg["max_ratio"]
        ty = float(np.clip(ty, my / r, my * r))
        k = float(np.clip(ty / my, 0.8, 1.25))
        return {"wb": tuple(round(float(v), 4) for v in wb), "mid": (round(my, 4), round(ty, 4)), "k": round(k, 4),
                "source": "face"}
    if prof.get("neutral"):
        m = np.maximum(np.array(prof["neutral"], np.float64), 1)
        wb = (LUMA @ m) / m
        wb = np.clip(1 + 0.5 * (wb / (LUMA @ wb) - 1), 0.94, 1.06)
        return {"wb": tuple(round(float(v), 4) for v in wb), "mid": None, "source": "neutral"}
    return None


def to_filter(c: dict | None) -> str:
    """校正值变成 FFmpeg 滤镜。
    亮度：在 YUV 上改亮度通道，用一条过 (0,0)、(皮肤亮度→目标亮度)、(1,1) 的平滑曲线 y = x / (c·(1−x) + 1)，
    纯白还是纯白、纯黑还是纯黑；颜色浓度（U、V 离开中性灰的量）按同样的倍数缩放，效果像调相机曝光，压暗时不会变得更艳、更橙。
    白平衡：RGB 每个通道乘一个系数。差别很小的部分不加。"""
    if not c:
        return ""
    out = []
    mid = c.get("mid")
    if mid and abs(mid[1] - mid[0]) >= 0.005:
        m, t = mid
        cc = (m / t - 1) / (1 - m)
        x = "clip((val-16)/219,0,1)"
        k = c.get("k", 1.0)
        out.append(f"lutyuv=y='16+219*{x}/({cc:.5f}*(1-{x})+1)':u='128+(val-128)*{k:.4f}':v='128+(val-128)*{k:.4f}'")
    wb = c.get("wb")
    if wb and max(abs(v - 1) for v in wb) >= 0.01:
        out.append(f"colorchannelmixer=rr={wb[0]:.4f}:gg={wb[1]:.4f}:bb={wb[2]:.4f}")
    return ",".join(out)


def clip_filter(clip: Path) -> str:
    """整条素材的统一亮度/白平衡滤镜。量不出来就返回空字符串，不影响出片。"""
    try:
        return to_filter(correction(clip_profile(str(clip))))
    except Exception:  # noqa: BLE001
        return ""


def segment_filter(clip: Path, start: float, dur: float) -> str:
    """这一段的统一亮度/白平衡滤镜：段里量得到人脸就按这段的肤色校；量不到（手表特写）就用整条素材的。
    出片、预览、封面都用这个。量不出来返回空字符串，不影响出片。"""
    try:
        prof = segment_profile(str(clip), round(float(start), 2), round(float(dur), 2))
        if not (prof["skin"] and prof["faces"] >= 2):
            prof = clip_profile(str(clip))
        return to_filter(correction(prof))
    except Exception:  # noqa: BLE001
        return ""
