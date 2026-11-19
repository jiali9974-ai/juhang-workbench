"""画面文字、字幕样式和动态标识。相同比例坐标用于预览和 ASS 出片。"""
from __future__ import annotations

import json
import math
import re
import threading
import uuid
from pathlib import Path

from . import config, fonts

LOCK = threading.RLock()
ANIMATIONS = ("none", "fade", "pop", "pulse", "bounce", "shake")
SHAPES = {
    "arrow": "m 6 42 l 62 42 62 22 96 50 62 78 62 58 6 58",
    "circle": "m 50 4 b 75 4 96 25 96 50 96 75 75 96 50 96 25 96 4 75 4 50 4 25 25 4 50 4 m 50 13 b 30 13 13 30 13 50 13 70 30 87 50 87 70 87 87 70 87 50 87 30 70 13 50 13",
    "heart": "m 50 88 b 43 80 6 58 6 31 6 5 39 2 50 24 61 2 94 5 94 31 94 58 57 80 50 88",
    "sparkle": "m 50 2 l 63 37 98 50 63 63 50 98 37 63 2 50 37 37",
    "check": "m 8 49 l 22 35 42 55 79 15 94 29 43 84",
    "badge": "m 10 20 l 90 20 100 35 100 65 90 80 10 80 0 65 0 35",
}


def _num(value, default, low, high):
    try:
        result = float(value)
        if not math.isfinite(result):
            raise ValueError()
        return round(max(low, min(high, result)), 3)
    except (ValueError, TypeError):
        return default


def _color(value, default):
    return value.upper() if isinstance(value, str) and re.fullmatch(r"#[0-9a-fA-F]{6}", value) else default


def _from_ass(value, fallback):
    match = re.fullmatch(r"&H[0-9a-fA-F]{2}([0-9a-fA-F]{2})([0-9a-fA-F]{2})([0-9a-fA-F]{2})", str(value))
    return "#" + "".join(reversed(match.groups())).upper() if match else fallback


def defaults() -> dict:
    cfg = config.load()
    style, r = cfg["style"], cfg["render"]
    sub = style["subtitle"]
    base = {"font_id": fonts.default_id(), "size": sub["size"] * 1440 / r["width"],
            "color": _from_ass(sub["color"], "#FFFFFF"), "outline_color": _from_ass(sub["outline_color"], "#000000"),
            "outline": sub["outline"] * 1440 / r["width"], "bold": bool(style.get("font_bold")),
            "x": 50, "y": sub["y_ratio"] * 100, "enabled": True}
    elements = []
    # 把已有的固定角标迁移为可编辑文字，不改变旧项目的默认外观。
    slogan, disc = style.get("slogan", {}), style.get("disclaimer", {})
    if slogan.get("enabled", True):
        for i, column in enumerate(slogan.get("columns", [])):
            elements.append({**base, "id": f"legacy-slogan-{i}", "type": "text", "text": "\n".join(column),
                             "x": (slogan["x"] + i * slogan["column_gap"] + slogan["size"] / 2) / r["width"] * 100,
                             "y": (slogan["y"] + len(column) * slogan["size"] / 2) / r["height"] * 100,
                             "size": slogan["size"] * 1440 / r["width"], "color": _from_ass(slogan["color"], "#FFE600")})
    if disc.get("enabled", True) and disc.get("text"):
        elements.append({**base, "id": "legacy-disclaimer", "type": "text", "text": disc["text"],
                         "y": disc["y_ratio"] * 100, "size": disc["size"] * 1440 / r["width"],
                         "color": _from_ass(disc["color"], "#FFFFFF")})
    return {"subtitle": base, "elements": elements}


def normalize(data: dict, *, validate_fonts=False) -> dict:
    if not isinstance(data, dict):
        raise ValueError("画面设置必须是对象")
    base = defaults()
    known_fonts = {f["id"] for f in fonts.catalog()} if validate_fonts else None

    def layer(value, fallback):
        if not isinstance(value, dict):
            raise ValueError("画面元素格式不正确")
        font_id = str(value.get("font_id") or fallback["font_id"])
        if known_fonts is not None and font_id not in known_fonts:
            raise ValueError("所选字体已不存在，请重新选择字体")
        return {"font_id": font_id, "enabled": bool(value.get("enabled", fallback.get("enabled", True))),
                "size": _num(value.get("size"), fallback["size"], 16, 600),
                "x": _num(value.get("x"), fallback["x"], 0, 100), "y": _num(value.get("y"), fallback["y"], 0, 100),
                "color": _color(value.get("color"), fallback["color"]),
                "outline_color": _color(value.get("outline_color"), fallback["outline_color"]),
                "outline": _num(value.get("outline"), fallback["outline"], 0, 20),
                "bold": bool(value.get("bold", fallback["bold"]))}

    subtitle = layer(data.get("subtitle", base["subtitle"]), base["subtitle"])
    source = data.get("elements", base["elements"])
    if not isinstance(source, list) or len(source) > 30:
        raise ValueError("最多添加 30 个画面元素")
    elements, ids = [], set()
    for raw in source:
        item = layer(raw, {**base["subtitle"], "size": 100, "y": 30})
        key = str(raw.get("id") or uuid.uuid4().hex)
        if not re.fullmatch(r"[\w-]{1,80}", key) or key in ids:
            raise ValueError("画面元素编号无效或重复")
        ids.add(key)
        kind = raw.get("type", "text")
        if kind not in ("text", "sticker"):
            raise ValueError("不支持这个画面元素类型")
        icon = raw.get("icon", "arrow")
        animation = raw.get("animation", "none")
        if icon not in SHAPES or animation not in ANIMATIONS:
            raise ValueError("不支持这个标识或动画效果")
        start = _num(raw.get("start"), 0, 0, 86400)
        end = None if raw.get("end") is None else _num(raw["end"], start + 3, 0, 86400)
        if end is not None and end <= start:
            raise ValueError("结束时间需要晚于开始时间")
        item.update(id=key, type=kind, text=str(raw.get("text", ""))[:300], icon=icon, animation=animation,
                    start=start, end=end, rotation=_num(raw.get("rotation"), 0, -180, 180),
                    opacity=_num(raw.get("opacity"), 1, 0, 1))
        elements.append(item)
    return {"subtitle": subtitle, "elements": elements}


def _path():
    directory = config.data_root() / "settings"
    directory.mkdir(parents=True, exist_ok=True)
    return directory / "graphics.json"


def current() -> dict:
    with LOCK:
        path = _path()
        return normalize(json.loads(path.read_text(encoding="utf-8")) if path.exists() else defaults())


def save(data: dict) -> dict:
    with LOCK:
        settings = normalize(data, validate_fonts=True)
        path = _path()
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(path)
        return settings


def escape(text: str) -> str:
    # 全角转义符避免用户文字变成 ASS 指令（\N、{\pos} 等）。
    return text.replace("\\", "＼").replace("{", "｛").replace("}", "｝").replace("\r", "").replace("\n", r"\N")


def color(value: str) -> str:
    return "&H" + value[5:7] + value[3:5] + value[1:3] + "&"


def style_tags(layer: dict, width: int, family: str, weight: int = 400) -> str:
    ratio = width / 1440
    return (f"\\fn{family}\\fs{layer['size'] * ratio:.2f}\\b{max(700, weight) if layer['bold'] else weight}"
            f"\\c{color(layer['color'])}\\3c{color(layer['outline_color'])}"
            f"\\bord{layer['outline'] * ratio:.2f}\\shad0")


def _time(t: float) -> str:
    cs = max(0, round(t * 100))
    return f"{cs // 360000}:{cs // 6000 % 60:02d}:{cs // 100 % 60:02d}.{cs % 100:02d}"


def pose(animation: str, elapsed: float) -> tuple[float, float, float, float]:
    """scale、竖向位移（字号比例）、旋转、透明度；前端使用相同公式。"""
    if animation == "pulse":
        return 1 + 0.12 * math.sin(elapsed * math.tau / 1.2), 0, 0, 1
    if animation == "bounce":
        return 1, -0.12 * (1 - math.cos(elapsed * math.tau)), 0, 1
    if animation == "shake":
        return 1, 0, 10 * math.sin(elapsed * math.tau / .8), 1
    if animation == "pop":
        return min(1, .65 + elapsed / .35 * .35), 0, 0, min(1, elapsed / .15)
    if animation == "fade":
        return 1, 0, 0, min(1, elapsed / .4)
    return 1, 0, 0, 1


def events(settings: dict, total: float, width: int, height: int, catalog: dict) -> list[str]:
    result = []
    for i, item in enumerate(settings["elements"]):
        if not item["enabled"]:
            continue
        start, end = item["start"], min(total, item["end"] if item["end"] is not None else total)
        if start >= end:
            continue
        family = catalog[item["font_id"]]["family"]
        style = style_tags(item, width, family, catalog[item["font_id"]]["weight"])
        if item["type"] == "text":
            payload = escape(item["text"])
        else:
            payload = r"{\p1}" + SHAPES[item["icon"]] + r"{\p0}"
        # 插值由 libass 在每一帧完成，预览和最终视频使用同一运动轨迹。
        step = .1 if item["animation"] != "none" else max(.1, end - start)
        t = start
        while t < end - .001:
            nxt = min(end, t + step)
            transforms = []
            for stamp in (t, nxt):
                scale, dy, angle, alpha = pose(item["animation"], stamp - start)
                base = item["size"] * width / 1440
                factor = base if item["type"] == "sticker" else 100
                transforms.append((item["x"] / 100 * width, item["y"] / 100 * height + dy * base,
                                   scale * factor, item["rotation"] + angle, round(255 * (1 - alpha * item["opacity"]))))
            a, b = transforms
            ms = max(1, round((nxt - t) * 1000))
            tags = (f"\\an5{style}\\move({a[0]:.2f},{a[1]:.2f},{b[0]:.2f},{b[1]:.2f},0,{ms})"
                    f"\\fscx{a[2]:.2f}\\fscy{a[2]:.2f}\\frz{a[3]:.2f}\\alpha&H{a[4]:02X}&"
                    f"\\t(0,{ms},\\fscx{b[2]:.2f}\\fscy{b[2]:.2f}\\frz{b[3]:.2f}\\alpha&H{b[4]:02X}&)")
            if item["type"] == "sticker":
                tags += r"\bord0"
            result.append(f"Dialogue: {3+i},{_time(t)},{_time(nxt)},Sub,,0,0,0,,{{{tags}}}{payload}")
            if item["type"] == "sticker" and item["icon"] == "badge" and item["text"]:
                text = {**item, "size": item["size"] * .26, "color": "#FFFFFF", "outline": 0}
                text_tags = style_tags(text, width, family, catalog[item["font_id"]]["weight"])
                # 标签文字跟着底板一起移动、缩放和旋转。
                text_tags += (f"\\an5\\move({a[0]:.2f},{a[1]:.2f},{b[0]:.2f},{b[1]:.2f},0,{ms})"
                              f"\\fscx{a[2]/factor*100:.2f}\\fscy{a[2]/factor*100:.2f}\\frz{a[3]:.2f}\\alpha&H{a[4]:02X}&"
                              f"\\t(0,{ms},\\fscx{b[2]/factor*100:.2f}\\fscy{b[2]/factor*100:.2f}\\frz{b[3]:.2f}\\alpha&H{b[4]:02X}&)")
                result.append(f"Dialogue: {3+i},{_time(t)},{_time(nxt)},Sub,,0,0,0,,{{{text_tags}}}{escape(item['text'])}")
            t = nxt
    return result


PREVIEW_LOCK = threading.Lock()


def preview(data: dict, active_jobs: list[dict]) -> dict:
    import hashlib
    from . import cancellation, look, render

    settings = normalize(data.get("settings", current()), validate_fonts=True)
    source = look.preview_source(data.get("source"), "face", data.get("look"), active_jobs)
    image = look._preview_dir() / source["beauty"]
    renderer = hashlib.sha256(Path(__file__).read_bytes() + Path(render.__file__).read_bytes()).hexdigest()
    key = hashlib.sha256(json.dumps([settings, source["beauty"], renderer], sort_keys=True).encode()).hexdigest()[:24]
    directory = config.data_root() / "preview" / "graphics" / key
    with PREVIEW_LOCK:
        directory.mkdir(parents=True, exist_ok=True)
        output = directory / "preview.mp4"
        if not output.is_file():
            segment = render.Segment(image, 0, 6, subs=[(0, 6, "这是口播字幕预览")])
            render.build_ass([segment], 6, directory / "preview.ass", design=settings)
            fonts.snapshot(directory / "fonts")
            result = cancellation.run_process([
                config.ffmpeg(), "-nostdin", "-hide_banner", "-loglevel", "error", "-y", "-loop", "1", "-i", str(image.resolve()),
                "-vf", "subtitles=preview.ass:fontsdir=fonts", "-t", "6", "-an", "-r", "24",
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p", "-movflags", "+faststart", "preview.tmp.mp4",
            ], cwd=directory, capture_output=True, text=True, encoding="utf-8", errors="ignore")
            if result.returncode:
                raise RuntimeError(f"效果预览生成失败：{result.stderr[-1000:]}")
            (directory / "preview.tmp.mp4").replace(output)
    return {"url": f"/api/graphics/preview/{key}.mp4"}
