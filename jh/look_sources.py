"""独立保存封面选中的原始画面，供美颜测试使用。"""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from pathlib import Path

from . import config, outputs


@dataclass(frozen=True)
class Source:
    image: Path
    normalization: str
    origin: str
    fallback: bool = False


def cover_source_path(batch: str, sid: str) -> Path:
    video = outputs.output_path(batch, sid)
    path = video.with_name(f"{sid}_封面原图.jpg")
    if path.is_symlink() or path.resolve().parent != video.parent:
        raise ValueError("封面原图路径无效")
    return path


def install_legacy_default() -> Path:
    """给仍在运行的旧版取帧接口提供默认静态图，不创建项目或改动素材。"""
    image = config.ROOT / "assets" / "beauty-default.jpg"
    if not image.is_file():
        raise FileNotFoundError("默认测试图不存在")
    directory = config.data_root() / "preview" / "look"
    directory.mkdir(parents=True, exist_ok=True)
    # 老接口总是用 -ss 从视频取帧，静态 JPEG 在部分 FFmpeg 版本中无法 seek。
    from . import look

    clip = directory / "legacy-default.mp4"
    r = config.load()["render"]
    look._ff(["-loop", "1", "-i", str(image), "-t", "1", "-r", "5",
              "-vf", f"scale={r['width']}:{r['height']}", "-pix_fmt", "yuv420p",
              "-c:v", "libx264", "-preset", "ultrafast", "-crf", "0", str(clip)])
    cache = directory / "frames__v3.json"
    frames = {kind: [{"clip": str(clip.resolve()), "t": .2}] for kind in ("face", "watch")}
    cache.write_text(json.dumps(frames, ensure_ascii=False), encoding="utf-8")
    for kind in frames:
        (directory / f"_{kind}_0_v3_orig.jpg").unlink(missing_ok=True)
    return cache


def save(clip: Path, t: float, zoom: float, destination: Path) -> None:
    """同一帧同一构图，去掉美颜、抠图和封面文字；单独记录出片使用的光线校正。"""
    import cv2
    from PIL import Image
    from . import cover, normalize

    r = config.load()["render"]
    img = cover._grab(clip, t, zoom, r["width"], r["height"], settings=None)
    correction = normalize.segment_filter(clip, t - 1, 2)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.stem}-{uuid.uuid4().hex}.jpg")
    try:
        Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB)).save(temporary, quality=98, subsampling=0)
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)
    destination.with_suffix(".json").write_text(json.dumps({
        "clip": clip.name, "t": t, "zoom": zoom, "normalization": correction,
        "normalization_policy": normalize.policy_key(),
    }, ensure_ascii=False, indent=1), encoding="utf-8")


def _read(image: Path, origin: str, fallback: bool = False) -> Source:
    from . import normalize

    normalization = ""
    policy = None
    try:
        metadata = image.with_suffix(".json")
        if not metadata.is_symlink() and metadata.resolve().parent == image.resolve().parent:
            record = json.loads(metadata.read_text(encoding="utf-8"))
            normalization = str(record.get("normalization") or "")
            policy = record.get("normalization_policy")
    except (OSError, ValueError, AttributeError):
        pass
    if policy != normalize.policy_key():
        normalization = normalize.still_filter(image)
    return Source(image, normalization, origin, fallback)


def _recover(batch: str, sid: str, destination: Path) -> bool:
    """兼容旧成片：按封面检查记录回取当时选中的帧，之后不再依赖素材。"""
    if not batch:
        return False
    try:
        data_root = config.data_root().resolve()
        record = (data_root / "renders" / batch / sid / "cover_check.json").resolve()
        if data_root not in record.parents:
            return False
        chosen = json.loads(record.read_text(encoding="utf-8"))["chosen"]
        name = chosen["clip"]
        if not isinstance(name, str) or not name or Path(name).name != name or any(c in name for c in "/\\:\x00"):
            return False
        folder = (config.material_root() / batch).resolve()
        clip = (folder / name).resolve()
        if config.material_root().resolve() not in folder.parents or clip.parent != folder or not clip.is_file():
            return False
        zoom = chosen.get("zoom")
        if zoom is None:
            # 老版本没有记录 zoom；优先使用该句显式配置的构图。
            zoom = config.load()["render"]["talk_zoom"]
            script = config.data_root() / "scripts" / batch / f"{sid}.json"
            if script.is_file():
                lines = json.loads(script.read_text(encoding="utf-8")).get("lines", [])
                line = next((line for line in lines if line.get("clip") == name and
                             float(line["start"]) <= float(chosen["t"]) <= float(line["end"])), {})
                zoom = line.get("zoom") or zoom
        save(clip, float(chosen["t"]), float(zoom), destination)
        return True
    except (OSError, ValueError, KeyError, TypeError, RuntimeError):
        return False


def resolve(source: dict | None, active_jobs: list[dict] | None = None) -> Source:
    default = config.ROOT / "assets" / "beauty-default.jpg"
    if source is None:
        if not default.is_file():
            raise RuntimeError("默认测试图不存在")
        return _read(default, "default")
    if not isinstance(source, dict):
        raise ValueError("请选择有效的成片")
    batch, sid = str(source.get("batch") or ""), str(source.get("id") or "")
    video = outputs.output_path(batch, sid)
    if not video.is_file():
        raise FileNotFoundError("成片不存在，请更新成片列表")
    if (batch, sid) not in {(v["batch"], v["id"]) for v in outputs.list_outputs(active_jobs)}:
        raise RuntimeError("成片正在生成，完成后再预览")
    image = cover_source_path(batch, sid)
    if image.is_file() or _recover(batch, sid, image):
        return _read(image, "cover")
    # 原素材已移走的旧成片不能还原封面原图，仍可以用默认图测试美颜。
    if not default.is_file():
        raise RuntimeError("封面原图和默认测试图均不可用")
    return _read(default, "default", fallback=True)
