"""封面选帧：用面部关键点、表情系数、虹膜位置与头部姿态判断看镜头及微笑。"""
from __future__ import annotations

import threading
import cv2
import numpy as np

from . import config

_landmarker = None
_lock = threading.Lock()
MODEL = "face_landmarker.task"
SCORE_WEIGHTS = {"camera": 60., "smile": 30., "sharpness": 10.}
MOUTH_PROBLEM = "张嘴说话或嘴型夸张"


def metrics(img: np.ndarray) -> dict | None:
    import mediapipe as mp
    from .skin import _FACE

    global _landmarker
    h, w = img.shape[:2]
    # 高清复检保留足够眼部细节；整帧一律压到 540 会让眼镜后的虹膜只剩几个像素。
    k = min(1.0, 960 / w)
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
    iris, iris_y, iris_valid = [], [], True
    for center, a, b, upper, lower in ((468, 33, 133, 159, 145), (473, 362, 263, 386, 374)):
        axis = p[b] - p[a]
        iris.append(float((p[center] - p[a]) @ axis / max(1., axis @ axis)))
        vertical_axis = p[lower] - p[upper]
        iris_y.append(float((p[center] - p[upper]) @ vertical_axis / max(.01, vertical_axis @ vertical_axis)))
        iris_valid = iris_valid and dist(a, b) >= 8 and dist(upper, lower) >= 1.5
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
        "iris_horizontal": [round(value, 4) for value in iris],
        "iris_vertical": [round(value, 4) for value in iris_y], "iris_valid": bool(iris_valid),
        "sharp": round(sharp, 2), "fw": round(float(x1 - x0) / sw, 4),
        "cx": round(float(x0 + x1) / 2 / sw, 4), "cy": round(float(y0 + y1) / 2 / sh, 4),
        "top": round(float(y0) / sh, 4), "oval": (oval / k).tolist(),
    }


def _raised_corners(m: dict) -> bool:
    # 嘴角必须实际微扬；只有张嘴、牙齿亮或单侧表情系数高，不能当成微笑。
    return (m.get("smile_confidence", 0) >= .20 and m.get("smile", 0) >= .015 and m.get("frown", 1) < .2
            and m.get("mouth_press", 0) <= .45 and m.get("mouth_pucker", 0) <= .40
            and abs(m.get("smile_left", 0) - m.get("smile_right", 0)) <= .3)


def mouth_natural(m: dict | None) -> bool:
    if not m:
        return False
    opening = m.get("mar", 1)
    # 嘴角微扬时允许自然露齿，不按牙齿亮度或笑容系数排除；仍限制明显张嘴说话或夸张嘴型。
    smiling_limits = _raised_corners(m)
    return (opening <= (.22 if smiling_limits else .15)
            and m.get("mouth_gap_max", opening) <= (.25 if smiling_limits else .18)
            and m.get("jaw_open", 1) <= (.26 if smiling_limits else .22)
            and m.get("mouth_press", 0) <= .6 and m.get("mouth_pucker", 0) <= .5)


def smiling(m: dict | None) -> bool:
    if not m:
        return False
    return mouth_natural(m) and _raised_corners(m)


def camera_facing(m: dict) -> bool:
    """镜头朝向的外观证据，不把动画表情系数当成校准过的视线角度。"""
    if m.get("iris_valid") and len(m.get("iris_horizontal", [])) == len(m.get("iris_vertical", [])) == 2:
        x, y = m["iris_horizontal"], m["iris_vertical"]
        # 同时检查两只眼，不能只靠一只眼或平均值掩盖明显偏视。
        centered = all(.30 <= value <= .70 for value in x) and all(.25 <= value <= .75 for value in y)
        # 眼镜可能让虹膜关键点仍落在眼眶中央；表情系数与位置或低头姿态互相印证时排除偏视。
        extreme = ((abs(m["gaze_horizontal"]) > .30 and max(abs(value - .5) for value in x) > .10)
                   or (abs(m["gaze_vertical"]) > .45 and max(abs(value - .5) for value in y) > .08)
                   or (m.get("pose_pitch", 0) > 12 and m["gaze_vertical"] > .16))
        return centered and not extreme and abs(m.get("pose_yaw", 90)) <= 12 and abs(m.get("pose_pitch", 90)) <= 16
    # 眼部像素不足时保留较保守的判断，不把无法判断的眼神算作已确认。
    horizontal = abs(m.get("gaze_horizontal", 1))
    centered = m.get("iris_offset", 1) <= .10 and abs(m.get("pose_yaw", 90)) <= 8
    return ((horizontal <= .16 or (horizontal <= .20 and centered)) and abs(m.get("gaze_vertical", 1)) <= .18
            and m.get("gaze_eye_max", 1) <= .28 and m.get("iris_offset", 1) <= .20)


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
    if not camera_facing(m):
        bad.append("眼神没有看向镜头")
    if not mouth_natural(m):
        bad.append(MOUTH_PROBLEM)
    if m["frown"] > .35:
        bad.append("嘴角表情不自然")
    if m["sharp"] < max(18., .4 * ref["sharp"]):
        bad.append("脸糊（在动）")
    return bad


def score_parts(m: dict, ref: dict) -> dict[str, float]:
    """统一百分制：看向镜头 60、嘴角微扬 30、清晰度 10。"""
    camera = 0.
    if camera_facing(m):
        if m.get("iris_valid") and len(m.get("iris_horizontal", [])) == len(m.get("iris_vertical", [])) == 2:
            # 与合格检查一致，优先使用双眼的水平、垂直位置，取偏移更明显的一只眼。
            offset = max(max(abs(value - .5) / .20 for value in m["iris_horizontal"]),
                         max(abs(value - .5) / .25 for value in m["iris_vertical"]))
            # 不把动画系数换算成视线角度，只用它补充偏视证据，避免关键点误差给低头帧高分。
            animation = max(abs(m.get("gaze_horizontal", 1)) / .60, abs(m.get("gaze_vertical", 1)) / .75,
                            m.get("gaze_eye_max", 1) / .60)
            offset = max(offset, max(0., min(1., (animation - .20) / .80)))
        else:
            offset = max(abs(m.get("gaze_horizontal", 1)) / .20, abs(m.get("gaze_vertical", 1)) / .18,
                         m.get("gaze_eye_max", 1) / .28, m.get("iris_offset", 1) / .20)
        camera = (.75 * max(0., 1 - offset)
                  + .15 * max(0., 1 - abs(m.get("pose_yaw", 90)) / 12)
                  + .10 * max(0., 1 - abs(m.get("pose_pitch", 90)) / 16))
    # 轻微上扬就获得微笑分，不继续奖励更大的笑容，也不惩罚自然露齿。
    return {"camera": SCORE_WEIGHTS["camera"] * camera,
            "smile": SCORE_WEIGHTS["smile"] * float(smiling(m)),
            "sharpness": SCORE_WEIGHTS["sharpness"] * max(0., min(m.get("sharp", 0) / max(ref.get("sharp", 18.), 18.), 1.))}


def score(m: dict, ref: dict) -> float:
    return sum(score_parts(m, ref).values())


def fallback_parts(m: dict, ref: dict) -> dict[str, float]:
    """没有理想帧时连续评分，面向镜头最重要，放松自然的嘴型不必带微笑。"""
    if m.get("scene"):
        camera, natural = 0., 0.
    else:
        yaw = max(0., 1 - abs(m.get("pose_yaw", 90)) / 45)
        pitch = max(0., 1 - abs(m.get("pose_pitch", 90)) / 35)
        eye_offset = max(abs(m.get("gaze_horizontal", 1)), abs(m.get("gaze_vertical", 1)))
        # 水平正脸不能抵消明显低头；两个方向共同决定朝向，避免更清晰的低头帧胜过看镜头的帧。
        camera = (yaw * pitch) ** .5 * (.70 + .30 * max(0., 1 - eye_offset))
        eyes = max(0., 1 - max(m.get("blink", 1), m.get("ear_diff", 1)))
        mouth = max(0., 1 - max(m.get("mar", 1) / .5, m.get("jaw_open", 1) / .6,
                                m.get("mouth_press", 0), m.get("mouth_pucker", 0)))
        expression = .8 * max(0., 1 - m.get("frown", 1)) + .2 * float(smiling(m))
        natural = .30 * eyes + .50 * mouth + .20 * expression
        # 半闭眼会明显影响自然度；连续扣分，仍保留所有画面参与择优，不产生新的出片门槛。
        natural *= max(.25, 1 - 2 * max(0., m.get("blink", 1) - .45))
    return {"camera": 60 * camera, "naturalness": 30 * natural,
            "sharpness": 10 * max(0., min(m.get("sharp", 0) / max(ref.get("sharp", 18.), 18.), 1.))}


def fallback_score(m: dict, ref: dict) -> float:
    return sum(fallback_parts(m, ref).values())
