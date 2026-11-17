"""直接删除指定项目的文件，删除前先核对全部目标都位于配置目录内。"""
from __future__ import annotations

import shutil
from pathlib import Path


def child_path(root: Path, name: str) -> Path:
    if not name or name in (".", "..") or any(char in name for char in '/\\:\x00'):
        raise ValueError("删除目标名称无效")
    base = root.resolve()
    target = base / name
    resolved = target.resolve()
    if base not in resolved.parents or target.is_symlink() or getattr(target, "is_junction", lambda: False)():
        raise ValueError("删除目标超出指定目录或是目录链接")
    return resolved


def delete_children(children: list[tuple[Path, str]]) -> None:
    # 先验证整组路径，再执行删除，防止后面的无效路径造成前面的项目数据被部分删除。
    targets = [child_path(root, name) for root, name in children]
    for target in targets:
        if target.is_dir():
            shutil.rmtree(target)
        else:
            target.unlink(missing_ok=True)
