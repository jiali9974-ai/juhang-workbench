"""成片封面（抖音第一帧）：照参考视频的样子——
主播抠出来加一圈白色描边（贴纸感），背景用同一个画面稍微虚化，画面中间两行大字：
第一行白字黑边（卖点），第二行绿字黑边 + 绿色下划线（悬念）。封面会放在成片最开头的一两帧，同时另存一张 jpg 方便手动上传。

做封面时就把关（不是做完再挑）：
- 选帧：剪进成片的画面里每 0.2 秒取一帧，用人脸网格量眼睛睁没睁开、嘴张多大、有没有笑、脸正不正、头歪不歪、脸清不清楚、
  脸的大小和位置，不合格的帧排到后面，合格的按“自然好看”打分排序；合格的不到 6 帧，再到同一条素材没剪进成片的部分去找
  （同一次拍摄、同一身衣服，比如两句话之间嘴闭着、看着镜头的瞬间）；
- 做封面：按分数从高到低，一帧一帧在美颜调色后的高清画面上再检查一遍脸、再检查抠图（脸完整在人像里、人像大小正常），
  任何一项不合格就换下一帧重做，检查结果记在 cover_check.json；
- 抠图只要人：用 BiRefNet-portrait 人像抠图（头发细节好；没有这个模型时退回 mediapipe），
  下巴以上不限制，下巴以下只保留身体骨架范围（躯干、手臂、手）里面的部分，手里拿的表盒、桌面这些人以外的东西都不抠。
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from . import config, look


def _cfg() -> dict:
    return config.load()["render"].get("cover") or {}


def _grab(clip: Path, t: float, zoom: float, W: int, H: int, settings: dict | None = None) -> np.ndarray:
    """按出片同样的裁切（9:16 + 放大）取一帧，返回 BGR。"""
    z = max(1.0, float(zoom or 1.0))
    vf = f"crop='min(iw,ih*{W}/{H})/{z}':'min(ih,iw*{H}/{W})/{z}',scale={W}:{H}:flags=lanczos"
    effects = look.filters(settings) if settings is not None else {"normalize": False, "smooth": 0, "tone": ""}
    if effects["normalize"]:
        from . import normalize

        nf = normalize.segment_filter(clip, t - 1, 2)
        if nf:
            vf += "," + nf
    if effects["tone"]:
        vf += "," + effects["tone"]
    decode = ["-ss", f"{t:.3f}", "-i", str(clip), "-vf", vf]
    encode = ["-f", "image2pipe", "-vcodec", "png", "-"]
    if effects["smooth"]:
        from . import skin

        png = skin.still(decode, encode, W, H, effects["smooth"])
    else:
        r = subprocess.run([config.ffmpeg(), "-hide_banner", "-loglevel", "error",
                            *decode, "-frames:v", "1", *encode], capture_output=True)
        png = r.stdout
    if not png:
        raise RuntimeError(f"取不到封面画面：{clip.name} {t:.2f}s")
    return cv2.imdecode(np.frombuffer(png, np.uint8), cv2.IMREAD_COLOR)


_models: dict = {}


def _model(name: str):
    """mediapipe 模型只建一次（都是安装包里自带的，不联网；姿态模型用自带的 full 版本）。"""
    if name not in _models:
        import mediapipe as mp

        if name == "mesh":
            _models[name] = mp.solutions.face_mesh.FaceMesh(static_image_mode=True, max_num_faces=1, min_detection_confidence=0.5)
        elif name == "selfie":
            _models[name] = mp.solutions.selfie_segmentation.SelfieSegmentation(model_selection=0)
        elif name == "pose":
            _models[name] = mp.solutions.pose.Pose(static_image_mode=True, model_complexity=1, enable_segmentation=True)
        elif name == "hands":
            _models[name] = mp.solutions.hands.Hands(static_image_mode=True, max_num_hands=2, model_complexity=1,
                                                     min_detection_confidence=0.4)
    return _models[name]


# ---------------- 人脸：自然好看的检查 ----------------

def face_metrics(img: np.ndarray) -> dict | None:
    """量一帧里的脸（BGR）：眼睛睁开程度、嘴张开程度、笑、左右转头、歪头、低头、清晰度、大小和位置。没有脸返回 None。"""
    from .skin import _FACE

    h, w = img.shape[:2]
    k = min(1.0, 540 / w)
    small = cv2.resize(img, (int(w * k), int(h * k))) if k < 1 else img
    res = _model("mesh").process(cv2.cvtColor(small, cv2.COLOR_BGR2RGB))
    if not res.multi_face_landmarks:
        return None
    sh, sw = small.shape[:2]
    p = np.array([(q.x * sw, q.y * sh) for q in res.multi_face_landmarks[0].landmark], np.float32)

    def dist(i, j):
        return float(np.linalg.norm(p[i] - p[j]))

    ear_l = dist(159, 145) / max(1.0, dist(33, 133))
    ear_r = dist(386, 374) / max(1.0, dist(362, 263))
    mw = max(1.0, dist(61, 291))
    oval = p[_FACE]
    x0, y0 = oval.min(axis=0)
    x1, y1 = oval.max(axis=0)
    eye_y = (p[33, 1] + p[263, 1]) / 2
    mouth_y = (p[13, 1] + p[14, 1]) / 2
    crop = cv2.cvtColor(small[max(0, int(y0)):int(y1), max(0, int(x0)):int(x1)], cv2.COLOR_BGR2GRAY)
    sharp = 0.0
    if crop.size:
        crop = cv2.resize(crop, (160, max(1, int(160 * crop.shape[0] / max(1, crop.shape[1])))))
        sharp = float(cv2.Laplacian(crop, cv2.CV_64F).var())
    return {
        "ear": round(min(ear_l, ear_r), 3), "ear_diff": round(abs(ear_l - ear_r) / max(ear_l, ear_r, 1e-6), 3),
        "mar": round(dist(13, 14) / mw, 3),                                    # 嘴张开：上下唇内侧距离 / 嘴宽
        "smile": round(float(mouth_y - (p[61, 1] + p[291, 1]) / 2) / mw, 3),  # 嘴角比嘴中间高 = 笑
        "yaw": round(float((p[1, 0] - p[234, 0]) / max(1.0, p[454, 0] - p[234, 0])), 3),   # 0.5 = 正脸
        "roll": round(float(np.degrees(np.arctan2(p[263, 1] - p[33, 1], p[263, 0] - p[33, 0]))), 1),
        "pitch": round(float((p[1, 1] - eye_y) / max(1.0, mouth_y - eye_y)), 3),
        "sharp": round(sharp, 1),
        "fw": round(float(x1 - x0) / sw, 3), "cx": round(float(x0 + x1) / 2 / sw, 3),
        "cy": round(float(y0 + y1) / 2 / sh, 3), "top": round(float(y0) / sh, 3),
        "oval": (oval / k).tolist(),
    }


def face_problems(m: dict | None, ref: dict) -> list[str]:
    """不合格的地方（空列表 = 合格）。ref 是这条视频所有候选帧的典型值（每个人眼睛大小、画面清晰度不一样，按相对值判断）。"""
    if m is None:
        return ["没有脸"]
    bad = []
    if not 0.18 <= m["fw"] <= 0.60:
        bad.append("脸太小或太大")
    if not (0.25 <= m["cx"] <= 0.75 and 0.15 <= m["cy"] <= 0.50) or m["top"] < 0.06:
        bad.append("脸太靠边或头被切掉")
    if m["ear"] < max(0.16, 0.72 * ref["ear"]) or m["ear_diff"] > 0.35:
        bad.append("闭眼、眯眼或一只眼")
    if m["mar"] > 0.16:
        bad.append("嘴张太大（正在说话）")
    if not 0.38 <= m["yaw"] <= 0.62:
        bad.append("侧脸")
    if abs(m["roll"]) > 10:
        bad.append("头歪")
    if not 0.40 <= m["pitch"] <= 0.65:                  # 低头看表、仰头都不要（看镜头的帧约 0.48–0.60）
        bad.append("低头或仰头")
    if m["sharp"] < 0.4 * ref["sharp"]:
        bad.append("脸糊（在动）")
    return bad


def face_score(m: dict, ref: dict) -> float:
    """越自然好看分越高：眼睛有神、嘴闭着或微笑、正脸、不歪头、清楚、脸大小合适、在画面中上部。"""
    return (1.0 * min(m["ear"] / max(ref["ear"], 1e-6), 1.2)
            + 1.2 * (1 - min(m["mar"] / 0.16, 1.0))
            + 0.8 * float(np.clip(m["smile"] * 8, -0.5, 1.0))
            + 1.0 * (1 - min(abs(m["yaw"] - 0.5) / 0.12, 1.0))
            + 0.5 * (1 - min(abs(m["roll"]) / 10, 1.0))
            + 0.6 * min(m["sharp"] / max(ref["sharp"], 1e-6), 1.2)
            + 0.6 * (1 - min(abs(m["fw"] - 0.32) / 0.2, 1.0))
            - 0.5 * abs(m["cy"] - 0.32))


# ---------------- 抠图：只要人 ----------------

def _body_region(h: int, w: int, pose_lm, hands_lm, oval: np.ndarray | None, head_free: bool = False) -> np.ndarray:
    """身体骨架范围（0/1）：头（脸网格往外扩，往上留头发）、脖子和躯干（两肩往下到胯或画面底）、手臂（肩-肘-腕的粗线）、
    手（手的关键点轮廓往外扩一点；没认出手就用手腕处的小圆）。人像分割只保留这里面的部分。
    head_free：下巴以上整片都不限制（抠图模型本身能把头发和背景分开，不用再按椭圆裁，免得把头发裁掉）。"""
    reg = np.zeros((h, w), np.uint8)
    P = None
    if pose_lm is not None:
        P = np.array([(q.x * w, q.y * h, q.visibility) for q in pose_lm.landmark], np.float32)
    sw = float(np.linalg.norm(P[11, :2] - P[12, :2])) if P is not None else w * 0.35
    sw = max(sw, w * 0.15)
    # 头和头发
    if oval is not None:
        (x0, y0), (x1, y1) = oval.min(axis=0), oval.max(axis=0)
        fw, fh = x1 - x0, y1 - y0
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        cv2.ellipse(reg, (int(cx), int(cy - 0.12 * fh)), (int(0.64 * fw), int(0.74 * fh)), 0, 0, 360, 1, -1)
        chin = (cx, y1)
    elif P is not None:
        nose = P[0, :2]
        cv2.circle(reg, (int(nose[0]), int(nose[1] - 0.15 * sw)), int(0.42 * sw), 1, -1)
        chin = (nose[0], nose[1] + 0.25 * sw)
    else:
        return np.ones((h, w), np.uint8)              # 什么都认不出：不限制
    if P is None:
        if head_free:
            reg[: max(0, int(chin[1]))] = 1
        return reg

    def out(pt, ref, d):
        v = pt - ref
        return pt + v / max(1e-6, float(np.linalg.norm(v))) * d

    ls, rs = P[11, :2], P[12, :2]
    lso, rso = out(ls, rs, 0.16 * sw), out(rs, ls, 0.16 * sw)
    hips_ok = P[23, 2] > 0.5 and P[24, 2] > 0.5 and max(P[23, 1], P[24, 1]) < h
    if hips_ok:
        bottom = [out(P[23, :2], P[24, :2], 0.25 * sw), out(P[24, :2], P[23, :2], 0.25 * sw)]
    else:
        bottom = [np.array([lso[0] + np.sign(lso[0] - rso[0]) * 0.1 * sw, h]),
                  np.array([rso[0] + np.sign(rso[0] - lso[0]) * 0.1 * sw, h])]
    pts = np.array([[chin[0] - 0.3 * sw, chin[1]], [chin[0] + 0.3 * sw, chin[1]],
                    [lso[0], lso[1] - 0.12 * sw], [rso[0], rso[1] - 0.12 * sw], lso, rso, *bottom], np.float32)
    cv2.fillConvexPoly(reg, cv2.convexHull(pts.astype(np.int32)), 1)
    # 手臂
    for s_, e_, w_ in ((11, 13, 0.46), (12, 14, 0.46), (13, 15, 0.38), (14, 16, 0.38)):
        if P[s_, 2] > 0.3 and P[e_, 2] > 0.3:
            a, b = tuple(int(v) for v in P[s_, :2]), tuple(int(v) for v in P[e_, :2])
            t = max(2, int(w_ * sw))
            cv2.line(reg, a, b, 1, t)
            cv2.circle(reg, b, t // 2, 1, -1)
    # 手
    found = []
    for hl in hands_lm or []:
        hp = np.array([(q.x * w, q.y * h) for q in hl.landmark], np.float32)
        tmp = np.zeros_like(reg)
        cv2.fillConvexPoly(tmp, cv2.convexHull(hp.astype(np.int32)), 1)
        k_ = max(3, int(0.07 * sw))
        reg |= cv2.dilate(tmp, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * k_ + 1, 2 * k_ + 1)))
        found.append(hp.mean(axis=0))
    for wi, idx in ((15, (15, 17, 19, 21)), (16, (16, 18, 20, 22))):
        if P[wi, 2] > 0.3:
            c = P[list(idx), :2].mean(axis=0)
            if not any(np.linalg.norm(c - f) < 0.4 * sw for f in found):
                cv2.circle(reg, (int(c[0]), int(c[1])), int(0.2 * sw), 1, -1)
    if head_free:
        reg[: max(0, int(chin[1]))] = 1
    k_ = max(3, int(w * 0.012))                       # 衣服、头发边缘留一点余量
    return cv2.dilate(reg, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * k_ + 1, 2 * k_ + 1)))


_bire = None                                          # BiRefNet 模型（加载失败为 False）
_bire_err = ""


def _birefnet():
    """BiRefNet-portrait 人像抠图模型（MIT 许可，可商用；权重在 data/models/BiRefNet-portrait，GPU 半精度，约 1.7GB 显存）。
    第一次用要加载并预热十几秒，之后一张约 0.2 秒。没有模型、没有显卡或加载失败返回 None（退回 mediapipe 分割）。"""
    global _bire, _bire_err
    if _bire is None:
        _bire = False
        try:
            import torch
            from transformers import AutoModelForImageSegmentation

            d = config.data_root() / (_cfg().get("matting_model") or "models/BiRefNet-portrait")
            if not (d / "model.safetensors").exists():
                _bire_err = f"没有模型文件：{d}"
            elif not torch.cuda.is_available():
                _bire_err = "没有可用的显卡"
            else:
                m = AutoModelForImageSegmentation.from_pretrained(str(d), trust_remote_code=True)
                _bire = m.to("cuda").eval().half()
        except Exception as e:  # noqa: BLE001
            _bire_err = repr(e)[:300]
    return _bire or None


def _alpha_birefnet(img: np.ndarray) -> np.ndarray | None:
    """BiRefNet 抠图：整张图缩到 1024×1024 推理，输出 0–1 的透明度（头发边缘是半透明的），再放回原尺寸。"""
    m = _birefnet()
    if m is None:
        return None
    import torch

    h, w = img.shape[:2]
    x = cv2.resize(cv2.cvtColor(img, cv2.COLOR_BGR2RGB), (1024, 1024), interpolation=cv2.INTER_AREA)
    with torch.inference_mode():
        t = torch.from_numpy(x).to("cuda").permute(2, 0, 1)[None].float() / 255
        mean = torch.tensor([0.485, 0.456, 0.406], device="cuda").view(1, 3, 1, 1)
        std = torch.tensor([0.229, 0.224, 0.225], device="cuda").view(1, 3, 1, 1)
        pred = m(((t - mean) / std).half())[-1].sigmoid().float()[0, 0].cpu().numpy()
    return cv2.resize(pred, (w, h), interpolation=cv2.INTER_LINEAR)


def _person_mask(img: np.ndarray, oval: list | None = None) -> tuple[np.ndarray, dict]:
    """只抠人。抠图用 BiRefNet-portrait（头发细节好）；没有这个模型时退回 mediapipe 的人像分割。
    再用身体骨架范围限制：下巴以上不限制（保住头发），下巴以下只留身体、手臂、手——手里拿的表盒、桌面这些去掉；
    最后只留脸所在的那一块。返回 0–1 的透明度遮罩（全尺寸）和检查结果。"""
    h, w = img.shape[:2]
    sw_, sh_ = 512, int(512 * h / w)
    small = cv2.resize(img, (sw_, sh_))
    rgb = cv2.cvtColor(small, cv2.COLOR_BGR2RGB)
    pr = _model("pose").process(rgb)
    hr = _model("hands").process(rgb)
    alpha = _alpha_birefnet(img)
    used = "birefnet-portrait"
    if alpha is None:
        used = "mediapipe"
        m = _model("selfie").process(rgb).segmentation_mask
        if pr.segmentation_mask is not None:
            m = np.maximum(m, pr.segmentation_mask)
        alpha = cv2.resize(m, (w, h), interpolation=cv2.INTER_LINEAR)
    ov = np.array(oval, np.float32) * (sw_ / w) if oval is not None else None
    region = _body_region(sh_, sw_, pr.pose_landmarks, hr.multi_hand_landmarks, ov, head_free=used != "mediapipe")
    a_small = cv2.resize(alpha, (sw_, sh_), interpolation=cv2.INTER_AREA)
    hard = ((a_small > 0.5) & (region > 0)).astype(np.uint8)
    n, lab, stats, _ = cv2.connectedComponentsWithStats(hard, 8)
    if n > 1:
        keep = None
        if ov is not None:                            # 留脸所在的那一块
            c = ov.mean(axis=0).astype(int)
            keep = int(lab[min(sh_ - 1, max(0, c[1])), min(sw_ - 1, max(0, c[0]))]) or None
        keep = keep or 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
        hard = (lab == keep).astype(np.uint8)
    hard = cv2.morphologyEx(hard, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
    # 门：留下的那块稍微往外扩一点再羽化，乘到透明度上——头发边缘的半透明保留，门外的东西去掉
    gate = cv2.resize(cv2.dilate(hard, np.ones((5, 5), np.uint8)).astype(np.float32), (w, h), interpolation=cv2.INTER_LINEAR)
    gate = cv2.GaussianBlur(gate, (0, 0), 2.0)
    soft = np.clip(alpha * gate, 0, 1).astype(np.float32)
    info = {"area": round(float((soft > 0.5).mean()), 3), "pose": pr.pose_landmarks is not None,
            "hands": len(hr.multi_hand_landmarks or []), "model": used}
    if used == "mediapipe" and _bire_err:
        info["model_note"] = _bire_err
    if oval is not None:
        face = np.zeros((h, w), np.uint8)
        cv2.fillPoly(face, [np.array(oval, np.int32)], 1)
        info["face_in"] = round(float((soft[face > 0] > 0.5).mean()), 3)
    return soft, info


def mask_problems(info: dict) -> list[str]:
    bad = []
    if info.get("face_in", 1.0) < 0.97:
        bad.append("脸没有完整抠出来")
    if not 0.06 <= info["area"] <= 0.75:
        bad.append("人像大小不正常")
    if not info["pose"]:
        bad.append("认不出身体（可能把别的东西抠进来）")
    return bad


def _font(size: int) -> ImageFont.FreeTypeFont:
    st = config.load()["style"]
    path = Path(st["font_dir"]) / st.get("font_file", "SourceHanSansCN-Heavy.otf")
    return ImageFont.truetype(str(path), size)


def _fit_size(text: str, max_w: int, size: int) -> int:
    while size > 40:
        l, t, r, b = _font(size).getbbox(text, stroke_width=max(4, size // 12))
        if r - l <= max_w:
            return size
        size -= 4
    return size


def make_cover(clip: Path, t: float, zoom: float, lines: list[str], out_png: Path,
               *, settings: dict | None = None) -> Path:
    c = _cfg()
    r = config.load()["render"]
    W, H = r["width"], r["height"]
    img = _grab(clip, t, zoom, W, H, settings=look.current() if settings is None else settings)
    m = face_metrics(img)
    mask, _ = _person_mask(img, m["oval"] if m else None)
    return compose(img, mask, lines, out_png)


def compose(img: np.ndarray, mask: np.ndarray, lines: list[str], out_png: Path) -> Path:
    """封面合成：虚化背景 + 抠出来的人（白描边）+ 两行大字。"""
    c = _cfg()
    H, W = img.shape[:2]

    # 背景：同一画面稍微虚化、压暗一点，让人物和字跳出来
    bg = cv2.GaussianBlur(img, (0, 0), float(c.get("bg_blur", 6)))
    bg = (bg.astype(np.float32) * float(c.get("bg_dim", 0.92))).astype(np.uint8)
    # 白色描边：人物遮罩向外扩一圈
    ow = int(W * float(c.get("outline_ratio", 0.016)))
    ring = cv2.dilate((mask > 0.5).astype(np.uint8), cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * ow + 1, 2 * ow + 1)))
    ring = cv2.GaussianBlur(ring.astype(np.float32), (0, 0), 1.5)[..., None]
    out = bg.astype(np.float32) * (1 - ring) + 255.0 * ring
    m3 = mask[..., None]
    out = out * (1 - m3) + img.astype(np.float32) * m3
    pil = Image.fromarray(cv2.cvtColor(np.clip(out, 0, 255).astype(np.uint8), cv2.COLOR_BGR2RGB))

    # 两行标题
    d = ImageDraw.Draw(pil)
    base = int(W * float(c.get("char_ratio", 0.08)))
    max_w = int(W * 0.92)
    lines = [x for x in lines if x][:2]
    colors = [tuple(c.get("line1_color", [255, 255, 255])), tuple(c.get("line2_color", [12, 241, 41]))]
    centers = [float(c.get("line1_y", 0.469)), float(c.get("line2_y", 0.527))]
    for i, text in enumerate(lines):
        size = _fit_size(text, max_w, base)
        f = _font(size)
        sw = max(4, size // 11)
        l, tp, rt, bt = f.getbbox(text, stroke_width=sw)
        x = (W - (rt - l)) // 2 - l
        y = int(H * centers[i]) - (bt + tp) // 2
        # 软阴影
        shadow = Image.new("L", pil.size, 0)
        ImageDraw.Draw(shadow).text((x + sw, y + sw), text, font=f, fill=150, stroke_width=sw, stroke_fill=150)
        shadow = shadow.filter(__import__("PIL.ImageFilter", fromlist=["GaussianBlur"]).GaussianBlur(sw))
        pil.paste((0, 0, 0), (0, 0), shadow)
        d.text((x, y), text, font=f, fill=colors[i], stroke_width=sw, stroke_fill=(0, 0, 0))
        if i == 1 and c.get("underline", True):            # 第二行下面一条绿色下划线（黑边）
            uy = y + bt + int(H * 0.006)
            uh = max(6, int(H * 0.005))
            x0, x1 = x + l - int(W * 0.01), x + rt + int(W * 0.01)
            d.rectangle([x0 - 4, uy - 4, x1 + 4, uy + uh + 4], fill=(0, 0, 0))
            d.rectangle([x0, uy, x1, uy + uh], fill=colors[1])
    out_png.parent.mkdir(parents=True, exist_ok=True)
    pil.save(str(out_png))
    return out_png


def _scan(clip: Path, start: float, dur: float, zoom: float, step: float, skip: list[tuple[float, float]] = ()) -> list[dict]:
    """一段画面里每 step 秒取一帧（540×960，和成片同样的构图），量脸。skip 里的时间段跳过（已经量过的）。"""
    w, h = 540, 960
    z = max(1.0, float(zoom or 1.0))
    vf = f"crop='min(iw,ih*{w}/{h})/{z}':'min(ih,iw*{h}/{w})/{z}',scale={w}:{h}:flags=area,fps={1 / step:.4f}"
    r = subprocess.run([config.ffmpeg(), "-hide_banner", "-loglevel", "error", "-ss", f"{start:.3f}", "-t", f"{dur:.3f}",
                        "-i", str(clip), "-vf", vf, "-f", "rawvideo", "-pix_fmt", "bgr24", "-"], capture_output=True)
    out = []
    for i in range(len(r.stdout) // (w * h * 3)):
        t = round(start + i * step, 3)
        if t > start + dur - 0.3 or any(a - 0.1 <= t <= b + 0.1 for a, b in skip):
            continue                                    # 最后 0.3 秒不要（太靠近结尾，做封面时可能取不到这一帧）
        m = face_metrics(np.frombuffer(r.stdout, np.uint8, w * h * 3, i * w * h * 3).reshape(h, w, 3))
        if m:
            m.update(clip=str(clip), t=t, zoom=z)
            out.append(m)
    return out


def _ref(cands: list[dict]) -> dict:
    """这条视频的典型值：所有候选帧里眼睛睁开程度、清晰度的 80 分位（每个人眼睛大小、每批素材清晰度不同，按相对值判断）。"""
    return {"ear": float(np.percentile([m["ear"] for m in cands], 80)) if cands else 0.25,
            "sharp": float(np.percentile([m["sharp"] for m in cands], 80)) if cands else 0.0}


def candidates(segs, step: float = 0.2, want: int = 6) -> tuple[list[dict], dict]:
    """封面候选帧：先在剪进成片的画面里每 0.2 秒取一帧量脸；合格的不到 want 帧，
    再到这些素材里没剪进成片的部分去找（同一次拍摄、同一身衣服，比如两句话之间嘴闭着、看着镜头的瞬间）。"""
    from . import media

    out = []
    used: dict[str, list[tuple[float, float]]] = {}
    for s in segs:
        out += _scan(s.clip, s.v_start, s.v_dur, s.zoom, step)
        used.setdefault(str(s.clip), []).append((s.v_start, s.v_start + s.v_dur))
    ref = _ref(out)
    if sum(1 for m in out if not face_problems(m, ref)) < want:
        talk = float(config.load()["render"].get("talk_zoom", 1.0))
        for clip, spans in used.items():
            out += _scan(Path(clip), 0.0, media.probe(Path(clip)).duration, talk, 0.25, spans)
            if sum(1 for m in out if not face_problems(m, ref)) >= want * 2:
                break                                   # 够挑了就不再找，省时间
    return out, ref


def make_best_cover(segs, lines: list[str], out_png: Path, *, settings: dict | None = None, max_tries: int = 8) -> Path:
    """做封面，边做边检查：候选帧按“自然好看”排好，从最好的开始，在美颜调色后的高清画面上再检查脸和抠图，
    不合格就换下一帧重做（同一条素材 0.4 秒内只试一次）。都不合格时用问题最少的那一次。检查记录写在 cover_check.json。"""
    import json

    r = config.load()["render"]
    W, H = r["width"], r["height"]
    settings = look.current() if settings is None else settings
    cands, ref = candidates(segs)
    log: dict = {"candidates": len(cands), "ref": {k: round(v, 3) for k, v in ref.items()}, "tries": []}
    ranked = sorted(((not face_problems(m, ref), face_score(m, ref), m) for m in cands),
                    key=lambda x: (x[0], x[1]), reverse=True)
    log["passed_first_check"] = sum(1 for x in ranked if x[0])
    tried = []                                          # (问题数, -分数, 画面, 遮罩, 记录)
    for _, sc, m in ranked:
        if len(tried) >= max_tries:
            break
        if any(e["clip"] == Path(m["clip"]).name and abs(e["t"] - m["t"]) < 0.4 for *_, e in tried):
            continue
        try:
            img = _grab(Path(m["clip"]), m["t"], m["zoom"], W, H, settings=settings)
        except RuntimeError as e:                       # 这一帧取不到：算不合格，换下一帧
            log["tries"].append({"clip": Path(m["clip"]).name, "t": m["t"], "problems": [f"取不到这一帧：{e}"[:120]]})
            continue
        fm = face_metrics(img)
        problems = face_problems(fm, {"ear": ref["ear"], "sharp": 0.0})   # 高清图上不再比清晰度（候选时已经比过）
        mask, info = _person_mask(img, fm["oval"] if fm else None)
        problems += mask_problems(info)
        entry = {"clip": Path(m["clip"]).name, "t": m["t"], "score": round(sc, 3), "problems": problems, "mask": info,
                 "face": {k: v for k, v in (fm or {}).items() if k != "oval"}}
        log["tries"].append(entry)
        tried.append((len(problems), -sc, img, mask, entry))
        if not problems:
            break
    if tried:
        tried.sort(key=lambda x: (x[0], x[1]))
        _, _, img, mask, entry = tried[0]
        log["chosen"] = {"clip": entry["clip"], "t": entry["t"], "ok": not entry["problems"]}
        compose(img, mask, lines, out_png)
    else:                                               # 整条视频都没量到脸：用第一段
        s = segs[0]
        log["chosen"] = {"clip": s.clip.name, "t": s.v_start, "ok": False, "note": "没有找到脸"}
        make_cover(s.clip, s.v_start + min(1.0, s.v_dur / 2), s.zoom, lines, out_png, settings=settings)
    out_png.with_name("cover_check.json").write_text(json.dumps(log, ensure_ascii=False, indent=1), encoding="utf-8")
    return out_png


def pick_frame(segs, talk_zoom: float = 1.0) -> tuple:
    """封面用哪一帧（只选不做）：候选帧里最自然好看的那一帧。没有脸就用第一段。返回 (素材, 时间, 放大倍数)。"""
    cands, ref = candidates(segs)
    if cands:
        best = max(cands, key=lambda m: (not face_problems(m, ref), face_score(m, ref)))
        return Path(best["clip"]), best["t"], best["zoom"]
    s = segs[0]
    return s.clip, s.v_start + min(1.0, s.v_dur / 2), s.zoom
