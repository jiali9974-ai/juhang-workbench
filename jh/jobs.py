"""后台任务队列。GPU 只有一块，所以任务按顺序一个一个跑。"""
from __future__ import annotations

import queue
import threading
import time
import traceback
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class Job:
    id: str
    kind: str
    title: str
    status: str = "queued"          # queued / running / done / error
    progress: float = 0.0           # 0–1
    message: str = "排队中"
    result: Any = None
    error: str = ""
    created: float = field(default_factory=time.time)
    finished: float | None = None

    def to_dict(self) -> dict:
        return {k: getattr(self, k) for k in
                ("id", "kind", "title", "status", "progress", "message", "result", "error", "created", "finished")}


class JobQueue:
    def __init__(self) -> None:
        self.jobs: dict[str, Job] = {}
        self._q: "queue.Queue[tuple[Job, Callable]]" = queue.Queue()
        threading.Thread(target=self._loop, daemon=True).start()

    def submit(self, kind: str, title: str, fn: Callable[[Callable], Any]) -> Job:
        job = Job(id=uuid.uuid4().hex[:10], kind=kind, title=title)
        self.jobs[job.id] = job
        self._q.put((job, fn))
        return job

    def _loop(self) -> None:
        while True:
            job, fn = self._q.get()
            job.status, job.message = "running", "开始"

            def progress(i: int, n: int, msg: str, job=job) -> None:
                job.progress = (i / n) if n else 0.0
                job.message = msg

            try:
                job.result = fn(progress)
                job.status, job.progress = "done", 1.0
                job.message = job.message if job.message not in ("开始",) else "完成"
            except Exception as e:  # noqa: BLE001
                job.status, job.error = "error", f"{e}\n{traceback.format_exc()[-1500:]}"
                job.message = f"出错：{e}"
            finally:
                job.finished = time.time()

    def list(self, limit: int = 30) -> list[dict]:
        return [j.to_dict() for j in sorted(self.jobs.values(), key=lambda j: -j.created)[:limit]]

    def busy(self) -> bool:
        return any(j.status in ("queued", "running") for j in self.jobs.values())
