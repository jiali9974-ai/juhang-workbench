"""按片段温和校正曝光与白平衡，保留不同人物的肤色。

人脸亮度落在正常区间时不拉齐；明显过暗或过亮才向区间边界校正。
白平衡取自场景中性亮处，不用另一人的肤色 RGB 推算。每段只用一组校正值，
避免逐帧闪动；手表特写只校白平衡，不借用口播人脸的曝光。
"""
from __future__ import annotations

import json
import hashlib
import threading
from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np

from . import cancellation, config

W, H = 540, 960                         # 测光用的画面大小（够看清脸，速度快）
FRAMES = 10                             # 每条素材均匀取多少帧测光
PROFILE_VERSION = 2                     # 中性亮处现在包含有人脸的画面
POLICY_VERSION = "adaptive-v1"
LUMA = np.array([0.2126, 0.7152, 0.0722])
_lock = threading.Lock()
_mesh = None


def _cfg() -> dict:
    n = dict(config.load()["render"].get("normalize") or {})
    n.setdefault("enabled", True)
    n.setdefault("exposure_range", [.47, .55])              # 调色前人脸亮度区间，不统一肤色
    n.setdefault("max_ratio", 1.5)                          # 曝光校正上限
    n.setdefault("wb", 0.04)
    return n


def _framing(zoom: float) -> str:
    return (f"crop='min(iw,ih*{W}/{H})/{zoom}':'min(ih,iw*{H}/{W})/{zoom}',"
            f"scale={W}:{H}:flags=area")


def grab(clip: Path, t: float, zoom: float = 1.0) -> np.ndarray | None:
    """取一帧 RGB（裁成成片的构图，缩小到 540×960）。"""
    r = cancellation.run_process([config.ffmpeg(), "-hide_banner", "-loglevel", "error", "-ss", f"{max(0.0, t):.3f}",
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
        cached = json.loads(cache.read_text(encoding="utf-8"))
        if cached.get("version") == PROFILE_VERSION:
            return cached
    skins, neutrals = [], []
    for t in _times(0, media.probe(p).duration, FRAMES):
        img = grab(p, t)
        if img is None:
            continue
        s = skin(img)
        if s:
            skins.append(s["rgb"])
        n = neutral(img)
        if n:
            neutrals.append(n)
    out = {"skin": np.median(skins, axis=0).round(2).tolist() if skins else None, "faces": len(skins),
           "neutral": np.median(neutrals, axis=0).round(2).tolist() if neutrals else None,
           "version": PROFILE_VERSION}
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(out), encoding="utf-8")
    return out


@lru_cache(maxsize=1024)
def segment_profile(clip: str, start: float, dur: float, frames: int = 5) -> dict:
    """一段画面的灯光：段内均匀取几帧量皮肤颜色。同一条素材前后光线也可能变（相机自动曝光），所以按段量更准。"""
    skins, neutrals = [], []
    for t in _times(start, max(dur, 0.1), frames):
        img = grab(Path(clip), t)
        s = skin(img) if img is not None else None
        if s:
            skins.append(s["rgb"])
        n = neutral(img) if img is not None else None
        if n:
            neutrals.append(n)
    return {"skin": np.median(skins, axis=0).round(2).tolist() if skins else None, "faces": len(skins),
            "neutral": np.median(neutrals, axis=0).round(2).tolist() if neutrals else None}


def correction(prof: dict, cfg: dict | None = None, *, min_faces: int = 2) -> dict | None:
    """算校正值：{"wb": (r, g, b) 三个通道的系数, "mid": (皮肤亮度, 目标亮度) 0–1, "k": 颜色浓度跟着亮度变的倍数}。
    不用校正返回 None。"""
    cfg = cfg or _cfg()
    if not cfg["enabled"]:
        return None
    wb = np.ones(3, np.float64)
    if prof.get("neutral"):
        m = np.maximum(np.array(prof["neutral"], np.float64), 1)
        wb = (LUMA @ m) / m
        wb = np.clip(1 + 0.5 * (wb / (LUMA @ wb) - 1), 1 - cfg["wb"], 1 + cfg["wb"])
    wb = tuple(round(float(v), 4) for v in wb)
    if prof.get("skin") and prof.get("faces", 0) >= min_faces:
        m = np.maximum(np.array(prof["skin"], np.float64), 1)
        my = float(LUMA @ m) / 255
        ty = float(np.clip(my, *cfg["exposure_range"]))
        r = cfg["max_ratio"]
        ty = float(np.clip(ty, my / r, my * r))
        k = float(np.clip(ty / my, 0.8, 1.25))
        return {"wb": wb, "mid": (round(my, 4), round(ty, 4)), "k": round(k, 4),
                "source": "face"}
    if prof.get("neutral"):
        return {"wb": wb, "mid": None, "source": "neutral"}
    return None


def policy_key() -> str:
    """已保存的预览校正只在算法和配置一致时复用。"""
    payload = json.dumps([POLICY_VERSION, _cfg()], sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


@lru_cache(maxsize=128)
def _image_profile(path: str, modified: int, size: int) -> dict:
    from PIL import Image

    with Image.open(path) as source:
        img = np.asarray(source.convert("RGB").resize((W, H)))
    s = skin(img)
    return {"skin": s["rgb"] if s else None, "faces": int(s is not None), "neutral": neutral(img)}


def still_filter(image: Path) -> str:
    """旧封面原图仍能独立预览；旧版本光线参数按原图重算，不再沿用固定肤色目标。"""
    stat = image.stat()
    prof = _image_profile(str(image), stat.st_mtime_ns, stat.st_size)
    return to_filter(correction(prof, min_faces=1))


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
    """按段测光；无人脸特写只校白平衡，不能借用整条素材的人脸曝光。
    出片、预览、封面都用这个。量不出来返回空字符串，不影响出片。"""
    try:
        prof = segment_profile(str(clip), round(float(start), 2), round(float(dur), 2))
        if not (prof["skin"] and prof["faces"] >= 2) and not prof.get("neutral"):
            prof = {**prof, "neutral": clip_profile(str(clip)).get("neutral")}
        return to_filter(correction(prof))
    except Exception:  # noqa: BLE001
        return ""
