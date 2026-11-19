"""封面选帧：用面部关键点、表情系数、虹膜位置与头部姿态判断看镜头及微笑。"""
from __future__ import annotations

import threading
import cv2
import numpy as np

from . import config

_landmarker = None
_lock = threading.Lock()
MODEL = "face_landmarker.task"


def metrics(img: np.ndarray) -> dict | None:
    import mediapipe as mp
    from .skin import _FACE

    global _landmarker
    h, w = img.shape[:2]
    k = min(1.0, 540 / w)
    small = cv2.resize(img, (round(w * k), round(h * k))) if k < 1 else img
    with _lock:
        if _landmarker is None:
            path = config.ROOT / "assets" / MODEL
            if not path.is_file():
                raise RuntimeError("缺少封面表情与视线模型 face_landmarker.task，请更新完整源码")
            _landmarker = mp.tasks.vision.FaceLandmarker.create_from_options(mp.tasks.vision.FaceLandmarkerOptions(
                base_options=mp.tasks.BaseOptions(model_asset_buffer=path.read_bytes()),
                num_faces=1, output_face_blendshapes=True, output_facial_transformation_matrixes=True))
        result = _landmarker.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=cv2.cvtColor(small, cv2.COLOR_BGR2RGB)))
    if not result.face_landmarks:
        return None
    sh, sw = small.shape[:2]
    p = np.array([(q.x * sw, q.y * sh) for q in result.face_landmarks[0]], np.float32)
    blend = {item.category_name: float(item.score) for item in result.face_blendshapes[0]}
    rotation = np.array(result.facial_transformation_matrixes[0])[:3, :3]
    pitch, yaw, roll = cv2.RQDecomp3x3(rotation)[0]

    def dist(a, b):
        return float(np.linalg.norm(p[a] - p[b]))

    ears = [dist(159, 145) / max(1., dist(33, 133)), dist(386, 374) / max(1., dist(362, 263))]
    mouth_width = max(1., dist(61, 291))
    mouth_y = (p[13, 1] + p[14, 1]) / 2
    gap_max = max(dist(a, b) / mouth_width for a, b in ((82, 87), (13, 14), (312, 317)))
    mouth_mask = np.zeros((sh, sw), np.uint8)
    inner = [78, 191, 80, 81, 82, 13, 312, 311, 310, 415, 308, 324, 318, 402, 317, 14, 87, 178, 88, 95]
    cv2.fillPoly(mouth_mask, [p[inner].astype(np.int32)], 1)
    mouth_pixels = small[mouth_mask > 0].astype(np.float32)
    bright_ratio = 0.
    if len(mouth_pixels) >= 8:
        high, low = mouth_pixels.max(axis=1), mouth_pixels.min(axis=1)
        bright_ratio = float(((low > 150) & (high - low < high * .18)).mean())
    iris = []
    for center, a, b in ((468, 33, 133), (473, 362, 263)):
        axis = p[b] - p[a]
        iris.append(float((p[center] - p[a]) @ axis / max(1., axis @ axis)))
    horizontal = [(blend["eyeLookInLeft"] - blend["eyeLookOutLeft"]),
                  (blend["eyeLookOutRight"] - blend["eyeLookInRight"])]
    vertical = [blend["eyeLookDownLeft"] - blend["eyeLookUpLeft"],
                blend["eyeLookDownRight"] - blend["eyeLookUpRight"]]
    smile_l, smile_r = blend["mouthSmileLeft"], blend["mouthSmileRight"]
    oval = p[_FACE]
    x0, y0 = oval.min(axis=0)
    x1, y1 = oval.max(axis=0)
    crop = cv2.cvtColor(small[max(0, int(y0)):min(sh, int(y1)), max(0, int(x0)):min(sw, int(x1))], cv2.COLOR_BGR2GRAY)
    sharp = 0.
    if crop.size:
        crop = cv2.resize(crop, (160, max(1, round(160 * crop.shape[0] / crop.shape[1]))))
        sharp = float(cv2.Laplacian(crop, cv2.CV_64F).var())
    return {
        "ear": round(min(ears), 4), "ear_diff": round(abs(ears[0] - ears[1]) / max(*ears, 1e-6), 4),
        "blink": round(max(blend["eyeBlinkLeft"], blend["eyeBlinkRight"]), 4),
        "mar": round(dist(13, 14) / mouth_width, 4), "jaw_open": round(blend["jawOpen"], 4),
        "mouth_gap_max": round(gap_max, 4), "mouth_bright_ratio": round(bright_ratio, 4),
        "mouth_press": round(max(blend["mouthPressLeft"], blend["mouthPressRight"]), 4),
        "mouth_pucker": round(blend["mouthPucker"], 4),
        "smile": round(float(mouth_y - (p[61, 1] + p[291, 1]) / 2) / mouth_width, 4),
        "smile_left": round(smile_l, 4), "smile_right": round(smile_r, 4),
        "smile_confidence": round(min(smile_l, smile_r), 4),
        "frown": round(max(blend["mouthFrownLeft"], blend["mouthFrownRight"]), 4),
        "pose_yaw": round(yaw, 2), "pose_pitch": round(pitch, 2), "roll": round(roll, 2),
        "gaze_horizontal": round(float(np.mean(horizontal)), 4), "gaze_vertical": round(float(np.mean(vertical)), 4),
        "gaze_eye_max": round(max(abs(value) for value in horizontal), 4),
        "iris_offset": round(max(abs(value - .5) for value in iris), 4),
        "sharp": round(sharp, 2), "fw": round(float(x1 - x0) / sw, 4),
        "cx": round(float(x0 + x1) / 2 / sw, 4), "cy": round(float(y0 + y1) / 2 / sh, 4),
        "top": round(float(y0) / sh, 4), "oval": (oval / k).tolist(),
    }


def mouth_natural(m: dict | None) -> bool:
    if not m:
        return False
    opening, confidence = m.get("mar", 1), m.get("smile_confidence", 0)
    obvious_grin = confidence > .78 and opening > .10
    exposed_teeth = m.get("mouth_bright_ratio", 0) > .40 and opening > .07
    return (opening <= .15 and m.get("mouth_gap_max", opening) <= .18 and m.get("jaw_open", 1) <= .22
            and not obvious_grin and not exposed_teeth and m.get("mouth_press", 0) <= .6 and m.get("mouth_pucker", 0) <= .5)


def smiling(m: dict | None) -> bool:
    if not m:
        return False
    # 识别自然、放松的轻微笑意，允许嘴唇自然分开，避免把刻意抿嘴当成微笑。
    confidence = m.get("smile_confidence", 0)
    return (mouth_natural(m) and confidence >= .20 and m.get("smile", 0) >= .015 and m.get("frown", 1) < .2
            and m.get("mouth_press", 0) <= .45 and m.get("mouth_pucker", 0) <= .40
            and abs(m.get("smile_left", 0) - m.get("smile_right", 0)) <= .3)


def problems(m: dict | None, ref: dict) -> list[str]:
    if m is None:
        return ["没有脸"]
    bad = []
    if not .14 <= m["fw"] <= .60:
        bad.append("脸太小或太大")
    if not (.20 <= m["cx"] <= .80 and .12 <= m["cy"] <= .52) or m["top"] < .04:
        bad.append("脸太靠边或头被切掉")
    if m["ear"] < max(.13, .65 * ref["ear"]) or m["blink"] > .45 or m["ear_diff"] > .40:
        bad.append("闭眼或眼睛状态不自然")
    if abs(m["pose_yaw"]) > 12:
        bad.append("脸没有朝向镜头")
    if abs(m["pose_pitch"]) > 16 or abs(m["roll"]) > 9:
        bad.append("低头、仰头或头太歪")
    horizontal = abs(m["gaze_horizontal"])
    # 接近阈值时用虹膜与正脸交叉确认，避免眼镜反光、调色让单个视线系数轻微漂移。
    centered = m["iris_offset"] <= .10 and abs(m["pose_yaw"]) <= 8
    if ((horizontal > .16 and not (horizontal <= .20 and centered)) or abs(m["gaze_vertical"]) > .18
            or m["gaze_eye_max"] > .28 or m["iris_offset"] > .20):
        bad.append("眼神没有看向镜头")
    if not mouth_natural(m):
        bad.append("张嘴说话、露齿大笑或嘴型夸张")
    if m["frown"] > .35:
        bad.append("嘴角表情不自然")
    if m["sharp"] < max(18., .4 * ref["sharp"]):
        bad.append("脸糊（在动）")
    return bad


def score(m: dict, ref: dict) -> float:
    return (6 * min(m.get("smile_confidence", 0), .6) + .4 * m.get("stable_neighbors", 0)
            + 1.5 * max(0, 1 - abs(m.get("gaze_horizontal", 1)) / .16)
            + max(0, 1 - abs(m.get("pose_yaw", 90)) / 12)
            + .5 * max(0, 1 - abs(m.get("roll", 90)) / 9)
            + .5 * min(m.get("sharp", 0) / max(ref["sharp"], 1), 1.2)
            + .5 * max(0, 1 - m.get("jaw_open", 1) / .3)
            - .5 * m.get("mouth_press", 0) - .3 * m.get("mouth_pucker", 0))
