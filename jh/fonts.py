"""浏览器和 libass 共用的字体库；用户字体存放在共享数据目录。"""
from __future__ import annotations

import hashlib
import os
import re
import shutil
import struct
import sys
import tempfile
import xml.etree.ElementTree as ET
from functools import lru_cache
from pathlib import Path

from PIL import ImageFont

from . import config

MAX_BYTES = 25 * 1024 * 1024
BUILTINS = {
    "SourceHanSansCN-Regular.otf": "黑体（思源）",
    "SourceHanSansCN-Bold.otf": "黑体 · 粗体（思源）",
    "SourceHanSansCN-Heavy.otf": "黑体 · 特粗（思源）",
    "SourceHanSerifCN-Regular.otf": "宋体（思源）",
    "SourceHanSerifCN-Bold.otf": "宋体 · 粗体（思源）",
    "LXGWWenKai-Regular.ttf": "楷体（霞鹜文楷）",
    "ZhuqueFangsong-Regular.ttf": "仿宋（朱雀仿宋）",
    "ChillRoundFRegular.otf": "圆体（寒蝉全圆体）",
    "ZCOOLXiaoWei-Regular.ttf": "站酷小薇体",
    "ZCOOLKuaiLe-Regular.ttf": "站酷快乐体",
}


def _directory() -> Path:
    directory = config.data_root() / "fonts"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _family(path: Path, fallback: str) -> tuple[str, int]:
    """FreeType 在 Windows 可能把中文字体家族名读成问号，直接读取 Unicode name 表。"""
    data = path.read_bytes()
    candidates, weight = [], 400
    count = struct.unpack_from(">H", data, 4)[0]
    for i in range(count):
        tag, _, offset, _ = struct.unpack_from(">4sIII", data, 12 + i * 16)
        if tag == b"OS/2":
            weight = max(100, min(900, struct.unpack_from(">H", data, offset + 4)[0]))
        if tag != b"name":
            continue
        _, records, strings = struct.unpack_from(">HHH", data, offset)
        for j in range(records):
            platform, encoding, language, name, length, start = struct.unpack_from(">HHHHHH", data, offset + 6 + j * 12)
            if name not in (1, 16) or platform not in (0, 3):
                continue
            raw = data[offset + strings + start:offset + strings + start + length]
            try:
                text = raw.decode("utf-16-be")
            except UnicodeError:
                continue
            # ASS 的 \fn 标签会把半角括号当作语法；优先使用字体自身的安全别名。
            score = (not re.search(r"[,{}\\()\r\n]", text), language == 1033, name == 1, platform == 3)
            candidates.append((score, text))
    return (max(candidates)[1] if candidates else fallback), weight


def _info(path: Path, builtin: bool) -> dict:
    font = ImageFont.truetype(str(path), 100)
    family, style = font.getname()
    family, weight = _family(path, family)
    if re.search(r"[,{}\\()\r\n]", family):
        raise ValueError("字体名称包含不支持的字符")
    ascent, descent = font.getmetrics()
    return {"id": path.stem, "name": BUILTINS.get(path.name, family),
            "family": family, "builtin": builtin, "file": path.name,
            "preview_scale": round(100 / max(1, ascent + descent), 6), "weight": weight}


@lru_cache(maxsize=128)
def _cached_info(path: str, modified: int, size: int, builtin: bool) -> dict:
    return _info(Path(path), builtin)


def catalog() -> list[dict]:
    result = []
    order = {name: i for i, name in enumerate(BUILTINS)}
    for directory, builtin in ((config.ROOT / "fonts", True), (_directory(), False)):
        for path in sorted(directory.iterdir(), key=lambda path: (order.get(path.name, len(order)), path.name)):
            if path.suffix.lower() in (".ttf", ".otf") and path.is_file():
                try:
                    stat = path.stat()
                    result.append(dict(_cached_info(str(path), stat.st_mtime_ns, stat.st_size, builtin)))
                except (OSError, ValueError, struct.error):
                    continue
    return result


def resolve(font_id: str) -> tuple[Path, dict]:
    for item in catalog():
        if item["id"] == font_id:
            directory = config.ROOT / "fonts" if item["builtin"] else _directory()
            return directory / item["file"], item
    raise ValueError("找不到所选字体，请重新选择或上传字体")


def default_id() -> str:
    return "SourceHanSansCN-Heavy"


async def receive(filename: str, stream) -> dict:
    suffix = Path(filename).suffix.lower()
    if suffix not in (".ttf", ".otf"):
        raise ValueError("请上传 TTF 或 OTF 字体文件")
    directory = _directory()
    with tempfile.NamedTemporaryFile(dir=directory, suffix=suffix, delete=False) as f:
        temporary = Path(f.name)
        try:
            digest, size = hashlib.sha256(), 0
            async for chunk in stream:
                size += len(chunk)
                if size > MAX_BYTES:
                    raise ValueError("字体文件不能超过 25 MB")
                digest.update(chunk)
                f.write(chunk)
        except BaseException:
            f.close()
            temporary.unlink(missing_ok=True)
            raise
    try:
        _info(temporary, False)  # 必须能被实际渲染引擎读取
        target = directory / f"user-{digest.hexdigest()[:24]}{suffix}"
        temporary.replace(target)
        return _info(target, False)
    except (OSError, struct.error) as e:
        raise ValueError("无法读取这个字体文件，请换一个有效的 TTF 或 OTF 文件") from e
    finally:
        temporary.unlink(missing_ok=True)


def delete(font_id: str, settings: dict) -> None:
    path, item = resolve(font_id)
    if item["builtin"]:
        raise ValueError("内置字体随工作台提供，不能删除")
    used = [settings["subtitle"], *settings["elements"]]
    if any(layer.get("font_id") == font_id for layer in used):
        raise ValueError("这个字体正在使用，请先为字幕或文字换字体并保存，再删除")
    path.unlink()


def snapshot(directory: Path, font_ids: set[str] | None = None) -> None:
    """只复制本次文字所用字体，并保留默认字体供缺字回退。"""
    directory.mkdir(parents=True, exist_ok=True)
    selected = None if font_ids is None else font_ids | {default_id()}
    for item in catalog():
        if selected is not None and item["id"] not in selected:
            continue
        path = (config.ROOT / "fonts" if item["builtin"] else _directory()) / item["file"]
        shutil.copy2(path, directory / path.name)


def render_env(directory: Path) -> dict[str, str] | None:
    """Linux Fontconfig 也需要看到快照目录，才能为粤语缺字找到回退字体。"""
    if not sys.platform.startswith("linux"):
        return None
    directory = directory.resolve()
    root = ET.Element("fontconfig")
    ET.SubElement(root, "include", ignore_missing="yes").text = "/etc/fonts/fonts.conf"
    ET.SubElement(root, "dir").text = str(directory)
    ET.SubElement(root, "cachedir").text = str(directory.parent / "font-cache")
    edit = ET.SubElement(ET.SubElement(root, "match", target="pattern"), "edit", name="family", mode="append_last")
    ET.SubElement(edit, "string").text = resolve(default_id())[1]["family"]
    path = directory.parent / "fonts.conf"
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)
    return {**os.environ, "FONTCONFIG_FILE": str(path)}
