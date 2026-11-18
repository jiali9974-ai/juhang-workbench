"""Stream uploads and make retries of the same queue item idempotent."""
from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path
from typing import AsyncIterable
from weakref import WeakValueDictionary

from fastapi import HTTPException

_locks: WeakValueDictionary[str, asyncio.Lock] = WeakValueDictionary()


async def receive(folder: Path, data_root: Path, name: str, chunks: AsyncIterable[bytes], *,
                  upload_id: str | None = None, expected_size: int | None = None) -> dict:
    if expected_size is not None and expected_size <= 0:
        raise HTTPException(400, "文件是空的")
    if upload_id is not None and not 1 <= len(upload_id) <= 128:
        raise HTTPException(400, "上传编号无效")
    lock = _locks.setdefault(str(folder.resolve()), asyncio.Lock())
    async with lock:
        receipt = None
        if upload_id:
            digest = hashlib.sha256(upload_id.encode()).hexdigest()
            receipt = data_root / "upload_receipts" / folder.name / f"{digest}.json"
            try:
                saved = json.loads(receipt.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                saved = None
            if isinstance(saved, dict):
                if saved.get("name") != name or (expected_size is not None and saved.get("size") != expected_size):
                    raise HTTPException(409, "该上传编号属于另一份素材，请重新选择视频")
                clip = saved.get("clip", "")
                if isinstance(clip, str) and clip and clip == Path(clip).name:
                    completed = folder / clip
                    if completed.is_file():
                        stat = completed.stat()
                        if stat.st_size == saved.get("size") and stat.st_mtime_ns == saved.get("mtime_ns"):
                            return {"clip": clip, "size": stat.st_size}

        target = folder / name
        index = 1
        while target.exists():
            index += 1
            target = folder / f"{Path(name).stem}_{index}{Path(name).suffix}"
        part = target.with_suffix(target.suffix + ".part")
        size = 0
        try:
            with part.open("wb") as output:
                async for chunk in chunks:
                    output.write(chunk)
                    size += len(chunk)
            if not size:
                raise HTTPException(400, "文件是空的")
            if expected_size is not None and size != expected_size:
                raise HTTPException(400, "上传不完整，请重试这条视频")
            part.rename(target)
            if receipt is not None:
                receipt.parent.mkdir(parents=True, exist_ok=True)
                saved = {"name": name, "clip": target.name, "size": size, "mtime_ns": target.stat().st_mtime_ns}
                temporary = receipt.with_suffix(".next")
                temporary.write_text(json.dumps(saved, ensure_ascii=False), encoding="utf-8")
                temporary.replace(receipt)
        except BaseException:
            part.unlink(missing_ok=True)
            raise
        return {"clip": target.name, "size": size}
