"""已完成成片的目录与批量导出。"""
from __future__ import annotations

import json
import re
import time
import uuid
import zipfile
from pathlib import Path

from . import config, deletion


def output_path(batch: str, sid: str) -> Path:
    if not sid or any(part in (".", "..") or any(c in part for c in "/\\:\x00") for part in (batch, sid)):
        raise ValueError("成片编号无效")
    root = config.output_root().resolve()
    path = (root / batch / f"{sid}.mp4").resolve()
    if root not in path.parents:
        raise ValueError("成片路径无效")
    return path


def list_outputs(active_jobs: list[dict] | None = None) -> list[dict]:
    root = config.output_root()
    active = [j for j in (active_jobs or []) if j["status"] in ("running", "queued")]
    result = []
    for path in (*root.glob("*.mp4"), *root.glob("*/*.mp4")):
        batch, sid = ("" if path.parent == root else path.parent.name), path.stem
        if sid.endswith("_cover_tmp") or path.is_symlink():
            continue
        try:
            if output_path(batch, sid) != path.resolve():
                continue
            script_path = config.data_root() / "scripts" / batch / f"{sid}.json" if batch else None
            script = json.loads(script_path.read_text(encoding="utf-8")) if script_path and script_path.is_file() else None
            if script and script.get("status") != "rendered":
                continue
            if any(j["title"] == f"{sid} 出片" or (batch and not script and j["title"].startswith(f"{batch} ")) for j in active):
                continue
            stat = path.stat()
            if stat.st_size:
                item = {"batch": batch, "id": sid, "title": (script or {}).get("title") or sid,
                        "updated": stat.st_mtime, "size": stat.st_size}
                result.append(item)
        except (OSError, ValueError):
            continue
    return sorted(result, key=lambda item: (-item["updated"], item["batch"], item["id"]))


def export_path(token: str) -> Path:
    if not re.fullmatch(r"[a-f0-9]{32}", token):
        raise ValueError("导出编号无效")
    return config.data_root() / "exports" / f"{token}.zip"


def delete_output(batch: str, sid: str, active_jobs: list[dict] | None = None) -> None:
    """直接删除这条成片和封面，保留项目素材与脚本。"""
    source = output_path(batch, sid)
    if not source.is_file():
        raise FileNotFoundError("成片不存在")
    if any(job["status"] in ("running", "queued") and
           (job["title"] == f"{sid} 出片" or (batch and job["title"].startswith(f"{batch} ")))
           for job in (active_jobs or [])):
        raise RuntimeError("这条成片正在生成，完成后再删除")

    root = config.data_root().resolve()
    script_path = (root / "scripts" / batch / f"{sid}.json").resolve() if batch else None
    if script_path and root not in script_path.parents:
        raise ValueError("脚本路径无效")
    original = script_path.read_text(encoding="utf-8") if script_path and script_path.is_file() else None
    script = json.loads(original) if original else None
    deletion.delete_children([(source.parent, source.name), (source.parent, f"{sid}_封面.jpg"),
                              (source.parent, f"{sid}_封面原图.jpg"), (source.parent, f"{sid}_封面原图.json"),
                              (source.parent, f"{sid}_封面选择.json")])
    if script and script.get("status") == "rendered":
        script["status"] = "approved"
        script_path.write_text(json.dumps(script, ensure_ascii=False, indent=1), encoding="utf-8")


def _export_filename(title: str, sid: str) -> str:
    """使用成片库标题命名，替换 Windows 文件名不支持的字符。"""
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", title).strip(" .")
    if name.lower().endswith(".mp4"):
        name = name[:-4].rstrip(" .")
    name = name or sid
    if re.fullmatch(r"CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9]", name.split(".")[0], re.IGNORECASE):
        name = "_" + name
    # 留出扩展名和重名序号的空间；按 UTF-8 字节截断，中文文件名也能正常解压。
    return name.encode("utf-8")[:220].decode("utf-8", errors="ignore").rstrip(" .")


def export_outputs(items: list[tuple[str, str]], active_jobs: list[dict] | None = None) -> str:
    if not items:
        raise ValueError("请先选择成片")
    selected = list(dict.fromkeys(items))
    available = {(item["batch"], item["id"]): item for item in list_outputs(active_jobs)}
    files = []
    used_names: set[str] = set()
    for batch, sid in selected:
        path = output_path(batch, sid)
        if not path.is_file():
            raise FileNotFoundError(f"成片不存在：{sid}")
        if (batch, sid) not in available:
            raise ValueError(f"成片尚未完成：{sid}")
        stem = _export_filename(available[batch, sid]["title"], sid)
        prefix = f"{batch}/" if batch else ""
        name = f"{prefix}{stem}.mp4"
        number = 2
        while name.casefold() in used_names:
            name = f"{prefix}{stem} ({number}).mp4"
            number += 1
        used_names.add(name.casefold())
        files.append((path, name))
    token = uuid.uuid4().hex
    dest = export_path(token)
    dest.parent.mkdir(parents=True, exist_ok=True)
    for old in dest.parent.glob("*.zip"):
        try:
            if re.fullmatch(r"[a-f0-9]{32}\.zip", old.name) and old.stat().st_mtime < time.time() - 86400:
                old.unlink(missing_ok=True)
        except OSError:
            pass  # 同时下载/清理过期导出不影响本次导出。
    try:
        with zipfile.ZipFile(dest, "w", compression=zipfile.ZIP_STORED, allowZip64=True) as archive:
            for path, name in files:
                archive.write(path, name)
    except BaseException:
        dest.unlink(missing_ok=True)
        raise
    return token
