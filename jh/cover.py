"""成片封面（抖音第一帧）：照参考视频的样子——
主播抠出来加一圈白色描边（贴纸感），背景用同一个画面稍微虚化，画面中间两行大字：
第一行白字黑边（卖点），第二行绿字黑边 + 绿色下划线（悬念）。封面会放在成片最开头的一两帧，同时另存一张 jpg 方便手动上传。

做封面时就把关（不是做完再挑）：
- 选帧：按原始视频 PTS 每约 0.2 秒扫描成片关联的完整原素材，用表情系数、双眼位置和头部姿态判断看镜头与自然、放松的轻微笑意。
  在笑容起止过渡及优选瞬间附近约每 0.025 秒细找，看镜头 60 分、嘴角微扬 30 分、清晰度 10 分，允许自然露齿。
  找不到理想帧时，按脸朝向、表情自然度和清晰度择优，继续完成出片；
- 做封面：优选帧统一用原始高清画面复查眼神、表情与自然嘴型，再排名、应用美颜调色并检查抠图（脸完整、人像大小正常），
  抠图不合适时使用优选原画面加标题，检查结果记在 cover_check.json；
- 抠图只要人：只使用 BiRefNet-portrait 人像抠图（含头发细节），不可用时明确报错，
  下巴以上不限制，下巴以下只保留身体骨架范围（躯干、手臂、手）里面的部分，手里拿的表盒、桌面这些人以外的东西都不抠。
"""
from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from . import cancellation, config, cover_faces, look

SELECTOR = "camera-natural-fallback-v8"


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
    decode = ["-ss", f"{max(0., t - .000002):.6f}", "-i", str(clip), "-vf", vf]
    encode = ["-f", "image2pipe", "-vcodec", "png", "-"]
    if effects["smooth"]:
        from . import skin

        png = skin.still(decode, encode, W, H, effects["smooth"])
    else:
        r = cancellation.run_process([config.ffmpeg(), "-hide_banner", "-loglevel", "error",
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

        if name == "pose":
            _models[name] = mp.solutions.pose.Pose(static_image_mode=True, model_complexity=1, enable_segmentation=False)
        elif name == "hands":
            _models[name] = mp.solutions.hands.Hands(static_image_mode=True, max_num_hands=2, model_complexity=1,
                                                     min_detection_confidence=0.4)
    return _models[name]


# ---------------- 人脸：自然好看的检查 ----------------

def face_metrics(img: np.ndarray) -> dict | None:
    return cover_faces.metrics(img)


def face_problems(m: dict | None, ref: dict) -> list[str]:
    return cover_faces.problems(m, ref)


def face_score(m: dict, ref: dict) -> float:
    return cover_faces.score(m, ref)


def _face_rank(m: dict, ref: dict) -> tuple[float, int]:
    # 稳定性只在总分相同时比较，不能越过看镜头、微笑和清晰度的权重。
    return face_score(m, ref), m.get("stable_neighbors", 0)


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


_bire = None                                          # 只缓存成功加载的 BiRefNet 模型


def _birefnet():
    """BiRefNet-portrait 人像抠图模型（MIT 许可，可商用；权重在 data/models/BiRefNet-portrait，GPU 半精度，约 1.7GB 显存）。
    没有模型、没有显卡或加载失败时明确报错；不切换到其他抠图模型。"""
    global _bire
    if _bire is None:
        d = config.data_root() / (_cfg().get("matting_model") or "models/BiRefNet-portrait")
        if not (d / "model.safetensors").is_file():
            raise RuntimeError(f"BiRefNet-portrait 抠图模型缺少权重：{d}")
        try:
            import torch
            from transformers import AutoModelForImageSegmentation

            if not torch.cuda.is_available():
                raise RuntimeError("没有可用的 NVIDIA GPU，请在带卡模式下生成封面")
            m = AutoModelForImageSegmentation.from_pretrained(str(d), trust_remote_code=True, local_files_only=True)
            _bire = m.to("cuda").eval().half()
        except Exception as e:  # noqa: BLE001
            raise RuntimeError(f"BiRefNet-portrait 抠图模型加载失败：{e}") from e
    return _bire


def _alpha_birefnet(img: np.ndarray) -> np.ndarray:
    """BiRefNet 抠图：整张图缩到 1024×1024 推理，输出 0–1 的透明度（头发边缘是半透明的），再放回原尺寸。"""
    m = _birefnet()
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
    """只使用 BiRefNet-portrait 抠人（包括头发细节），模型不可用时停止并报错。
    再用身体骨架范围限制：下巴以上不限制（保住头发），下巴以下只留身体、手臂、手——手里拿的表盒、桌面这些去掉；
    最后只留脸所在的那一块。返回 0–1 的透明度遮罩（全尺寸）和检查结果。"""
    alpha = _alpha_birefnet(img)
    h, w = img.shape[:2]
    sw_, sh_ = 512, int(512 * h / w)
    small = cv2.resize(img, (sw_, sh_))
    rgb = cv2.cvtColor(small, cv2.COLOR_BGR2RGB)
    pr = _model("pose").process(rgb)
    hr = _model("hands").process(rgb)
    ov = np.array(oval, np.float32) * (sw_ / w) if oval is not None else None
    region = _body_region(sh_, sw_, pr.pose_landmarks, hr.multi_hand_landmarks, ov, head_free=True)
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
            "hands": len(hr.multi_hand_landmarks or []), "model": "birefnet-portrait"}
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
    """逐帧解码、按原始 PTS 抽样，避免 fps 重采样时间与最后取出的高清帧错位。"""
    import av

    w, h, z = 540, 960, max(1., float(zoom or 1.))
    out, next_time = [], start
    with av.open(str(clip)) as container:
        video = container.streams.video[0]
        origin = float(container.start_time or 0) / av.time_base
        seek_time = max(video.start_time or 0, int((start + origin) / video.time_base))
        container.seek(seek_time, stream=video, backward=True)
        for frame in container.decode(video):
            cancellation.check()
            if frame.pts is None:
                continue
            t = float(frame.pts * frame.time_base) - origin
            if t > start + dur - .025:
                break
            if t + 1e-6 < next_time:
                continue
            while next_time <= t + 1e-6:
                next_time += step
            if any(a - .025 <= t <= b + .025 for a, b in skip):
                continue
            rotation = round(frame.rotation) % 360
            rw, rh = (frame.height, frame.width) if rotation in (90, 270) else (frame.width, frame.height)
            scale = min(1., max(w / rw, h / rh) * z)
            img = frame.reformat(width=max(2, round(frame.width * scale)), height=max(2, round(frame.height * scale)), format="bgr24").to_ndarray()
            if rotation == 270:
                img = cv2.rotate(img, cv2.ROTATE_90_CLOCKWISE)
            elif rotation == 90:
                img = cv2.rotate(img, cv2.ROTATE_90_COUNTERCLOCKWISE)
            elif rotation == 180:
                img = cv2.rotate(img, cv2.ROTATE_180)
            ih, iw = img.shape[:2]
            cw, ch = round(min(iw, ih * w / h) / z), round(min(ih, iw * h / w) / z)
            x, y = (iw - cw) // 2, (ih - ch) // 2
            img = cv2.resize(img[y:y + ch, x:x + cw], (w, h), interpolation=cv2.INTER_AREA)
            m = face_metrics(img)
            if m:
                m.update(clip=str(clip), t=round(t, 6), zoom=z)
                out.append(m)
    return out


def _ref(cands: list[dict]) -> dict:
    """这条视频的典型值：所有候选帧里眼睛睁开程度、清晰度的 80 分位（每个人眼睛大小、每批素材清晰度不同，按相对值判断）。"""
    return {"ear": float(np.percentile([m["ear"] for m in cands], 80)) if cands else 0.25,
            "sharp": float(np.percentile([m["sharp"] for m in cands], 80)) if cands else 0.0}


def _refinement_centers(cands: list[dict], ref: dict) -> list[dict]:
    """优先细查轻微笑意，以及一段笑容的起止过渡，避免只盯着大笑的峰值。"""
    camera = [m for m in cands if not [p for p in face_problems(m, ref) if p != cover_faces.MOUTH_PROBLEM]]
    centers = []

    def add(m):
        if not any(old["clip"] == m["clip"] and old["zoom"] == m["zoom"] and abs(old["t"] - m["t"]) < .25 for old in centers):
            centers.append(m)

    gentle = sorted((m for m in camera if cover_faces.mouth_natural(m)),
                    key=lambda m: _face_rank(m, ref), reverse=True)
    for m in gentle:
        add(m)
        if len(centers) >= 2:
            break
    groups = {}
    for m in camera:
        if m["smile_confidence"] >= .15:
            groups.setdefault((m["clip"], m["zoom"]), []).append(m)
    runs = []
    for group in groups.values():
        current = []
        for m in sorted(group, key=lambda m: m["t"]):
            if current and m["t"] - current[-1]["t"] > .40:
                runs.append(current)
                current = []
            current.append(m)
        if current:
            runs.append(current)
    for run in sorted(runs, key=lambda items: max(_face_rank(m, ref) for m in items), reverse=True):
        add(run[0])
        if len(centers) < 6:
            add(run[-1])
        if len(centers) >= 6:
            break
    for m in gentle:
        if len(centers) >= 8:
            break
        add(m)
    # 理想帧不足时仍细查最接近镜头、表情最自然的瞬间，不能因硬门槛而完全跳过精扫。
    for m in sorted(cands, key=lambda m: cover_faces.fallback_score(m, ref), reverse=True):
        if len(centers) >= 8:
            break
        add(m)
    return centers[:8]


def candidates(segs, step: float = 0.2) -> tuple[list[dict], dict]:
    """完整扫描成片关联的原素材，涵盖拍摄前后笑意，再细查过渡瞬间。"""
    from . import media

    out = []
    used = {}
    for segment in segs:
        used.setdefault(str(segment.clip), []).append(segment)
    talk = float(config.load()["render"].get("talk_zoom", 1.0))
    for clip, segments in used.items():
        # 每个原素材只完整解码一次；不会因片内已有几个候选就漏掉拍摄前后的好表情。
        out += _scan(Path(clip), 0., media.probe(Path(clip)).duration, talk, step)
        zooms = {}
        for segment in segments:
            zoom = max(1., float(segment.zoom or 1.))
            if abs(zoom - talk) > .02:
                zooms.setdefault(zoom, []).append((segment.v_start, segment.v_start + segment.v_dur))
        for zoom, spans in zooms.items():
            merged = []
            for start, end in sorted(spans):
                if merged and start <= merged[-1][1] + .1:
                    merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
                else:
                    merged.append((start, end))
            for start, end in merged:
                out += _scan(Path(clip), start, end - start, zoom, step)
    # 把精扫预算用在自然笑意和表情过渡，而非单纯追求最高的笑容系数。
    ref = _ref(out)
    for m in _refinement_centers(out, ref):
        start = max(0., m["t"] - .35)
        out += _scan(Path(m["clip"]), start, .72, m["zoom"], .025)
    # 同一个原始视频帧可能来自粗扫和精扫；只保留一次。
    out = list({(m["clip"], m["zoom"], m["t"]): m for m in out}.values())
    ref = _ref(out)
    groups = {}
    for m in out:
        groups.setdefault((m["clip"], m["zoom"]), []).append(m)
    for group in groups.values():
        group.sort(key=lambda m: m["t"])
        for i, m in enumerate(group):
            neighbors = group[max(0, i - 2):i] + group[i + 1:i + 3]
            m["stable_neighbors"] = min(2, sum(1 for other in neighbors if abs(other["t"] - m["t"]) <= .26
                                                  and not face_problems(other, ref) and cover_faces.smiling(other) == cover_faces.smiling(m)))
    return out, ref


def _scene_candidates(segs) -> list[dict]:
    """没有检测到人脸时，对多个时刻比较画面细节，仍产出带标题的原画面封面。"""
    from . import media

    rows, seen = [], set()
    for segment in segs:
        clip = Path(segment.clip)
        if str(clip) in seen:
            continue
        seen.add(str(clip))
        duration = media.probe(clip).duration
        for fraction in (.10, .30, .50, .70, .90):
            cancellation.check()
            t = max(0., min(duration - .05, duration * fraction))
            try:
                image = _grab(clip, t, 1., 540, 960)
            except RuntimeError:
                continue
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
            # 避免黑场或白场凭噪点入选；所有时刻都无法识别人脸时按有效细节选。
            sharp = float(cv2.Laplacian(gray, cv2.CV_64F).var())
            sharp *= float(((gray > 12) & (gray < 244)).mean())
            rows.append({"clip": str(clip), "t": t, "zoom": 1., "sharp": sharp, "scene": True})
    return rows


def _diverse_candidates(ranked: list[dict], limit: int) -> list[dict]:
    diverse, neighbors = [], []
    for m in ranked:
        if any(old["clip"] == m["clip"] and old["zoom"] == m["zoom"] and abs(old["t"] - m["t"]) < .20 for old in diverse):
            neighbors.append(m)
        else:
            diverse.append(m)
    return (diverse + neighbors)[:limit]


def make_best_cover(segs, lines: list[str], out_png: Path, *, settings: dict | None = None,
                    max_tries: int = 12, source_out: Path | None = None) -> Path:
    """优选看镜头的自然微笑；没有理想帧时选最自然的正面画面，继续出片。"""
    import json

    _birefnet()
    r = config.load()["render"]
    W, H = r["width"], r["height"]
    settings = look.current() if settings is None else settings
    cands, ref = candidates(segs)
    if not cands:
        cands = _scene_candidates(segs)
        ref = {"ear": .25, "sharp": float(np.percentile([m["sharp"] for m in cands], 80)) if cands else 0.}
    preferred = sorted((m for m in cands if not m.get("scene") and not face_problems(m, ref)),
                       key=lambda m: _face_rank(m, ref), reverse=True)
    fallback = sorted(cands, key=lambda m: cover_faces.fallback_score(m, ref), reverse=True)
    log = {"selector": SELECTOR, "score_weights": cover_faces.SCORE_WEIGHTS,
           "fallback_weights": {"camera": 60., "naturalness": 30., "sharpness": 10.},
           "candidates": len(cands), "ref": ref, "passed_first_check": len(preferred),
           "smile_candidates": sum(cover_faces.smiling(m) for m in preferred), "tries": []}
    out_png.parent.mkdir(parents=True, exist_ok=True)
    record = out_png.with_name("cover_check.json")
    cache = {}

    def publish(m, fm, entry, image, mask, *, relaxed, composition):
        log["chosen"] = {"clip": entry["clip"], "t": m["t"], "zoom": m["zoom"], "ok": True,
                         "mode": entry["expression"], "mouth_policy": "upturned_corners_teeth_allowed",
                         "selection_policy": "best_available" if relaxed else "preferred",
                         "composition": composition, "score": entry["hd_score"],
                         "score_parts": entry["hd_score_parts"], "note": ""}
        compose(image, mask, lines, out_png)
        if source_out is not None:
            from . import look_sources
            look_sources.save(Path(m["clip"]), m["t"], m["zoom"], source_out)
        record.write_text(json.dumps(log, ensure_ascii=False, indent=1), encoding="utf-8")
        return out_png

    for relaxed, pool in ((False, preferred), (True, fallback)):
        reviewed = []
        for m in _diverse_candidates(pool, max(1, max_tries)):
            cancellation.check()
            key = m["clip"], m["t"], m["zoom"]
            entry = {"clip": Path(m["clip"]).name, "t": m["t"], "zoom": m["zoom"],
                     "selection_policy": "best_available" if relaxed else "preferred"}
            log["tries"].append(entry)
            try:
                if key not in cache:
                    original = _grab(Path(m["clip"]), m["t"], m["zoom"], W, H)
                    cache[key] = face_metrics(original)
            except RuntimeError as e:
                entry["problems"] = [f"取不到这一帧：{e}"[:160]]
                continue
            fm = cache[key]
            problems = face_problems(fm, {**ref, "sharp": 0.})
            entry.update(problems=problems, face={k: v for k, v in (fm or {}).items() if k != "oval"})
            if problems and not relaxed:
                continue
            # 高清未识别人脸时仍可使用粗扫选中画面；抠图依据只采用高清识别结果。
            hd = {**(fm or m), "stable_neighbors": m.get("stable_neighbors", 0)}
            entry["expression"] = "scene" if hd.get("scene") else ("smile" if cover_faces.smiling(hd) else "natural")
            reviewed.append((m, hd, fm, entry))
        hd_sharp = [hd.get("sharp", 0.) for _, hd, _, _ in reviewed]
        hd_ref = {**ref, "sharp": float(np.percentile(hd_sharp, 80)) if hd_sharp else 0.}
        scorer = cover_faces.fallback_parts if relaxed else cover_faces.score_parts
        for _, hd, _, entry in reviewed:
            parts = scorer(hd, hd_ref)
            entry.update(hd_score=round(sum(parts.values()), 3), hd_score_parts={k: round(v, 3) for k, v in parts.items()})
        log["fallback_hd_ref" if relaxed else "hd_ref"] = hd_ref
        log["fallback_hd_candidates" if relaxed else "passed_hd_check"] = len(reviewed)
        if not relaxed:
            log["hd_smile_candidates"] = sum(entry["expression"] == "smile" for _, _, _, entry in reviewed)
        ranked = sorted(reviewed, key=lambda item: (sum(scorer(item[1], hd_ref).values()), item[1].get("stable_neighbors", 0)), reverse=True)
        for m, hd, fm, entry in ranked:
            cancellation.check()
            try:
                image = _grab(Path(m["clip"]), m["t"], m["zoom"], W, H, settings=settings)
            except RuntimeError as e:
                entry["problems"].append(str(e)[:160])
                continue
            if fm:
                mask, info = _person_mask(image, fm.get("oval"))
                entry["mask"] = info
                mask_issues = mask_problems(info)
                entry["problems"].extend(mask_issues)
                if not mask_issues:
                    return publish(m, fm, entry, image, mask, relaxed=relaxed, composition="portrait")
            if relaxed:
                return publish(m, fm, entry, image, np.ones(image.shape[:2], np.float32),
                               relaxed=True, composition="original_frame")
    log["error"] = "没有可读取的封面画面，请检查原素材是否完整"
    record.write_text(json.dumps(log, ensure_ascii=False, indent=1), encoding="utf-8")
    raise RuntimeError(log["error"])


def pick_frame(segs, talk_zoom: float = 1.0) -> tuple:
    """优先理想帧，没有时按朝向、自然度和清晰度择优。"""
    cands, ref = candidates(segs)
    eligible = [m for m in cands if not face_problems(m, ref)]
    if eligible:
        best = max(eligible, key=lambda m: _face_rank(m, ref))
    else:
        cands = cands or _scene_candidates(segs)
        if not cands:
            raise RuntimeError("没有可读取的封面画面，请检查原素材是否完整")
        best = max(cands, key=lambda m: cover_faces.fallback_score(m, ref))
    return Path(best["clip"]), best["t"], best["zoom"]
