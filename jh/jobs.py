"""后台任务队列。GPU 只有一块，所以任务按顺序一个一个跑。"""
from __future__ import annotations

import queue
import threading
import time
import traceback
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable

from . import cancellation


@dataclass
class Job:
    id: str
    kind: str
    title: str
    status: str = "queued"          # queued / running / done / error / cancelled
    cancel_requested: bool = False
    _cancel: threading.Event = field(default_factory=threading.Event, repr=False)
    progress: float = 0.0           # 0–1
    message: str = "排队中"
    stage: str | None = None
    completed_stages: list[str] = field(default_factory=list)
    result: Any = None
    error: str = ""
    created: float = field(default_factory=time.time)
    finished: float | None = None

    def to_dict(self) -> dict:
        return {k: getattr(self, k) for k in
                ("id", "kind", "title", "status", "cancel_requested", "progress", "message", "stage", "completed_stages", "result", "error", "created", "finished")}


class JobQueue:
    def __init__(self) -> None:
        self.jobs: dict[str, Job] = {}
        self._lock = threading.RLock()
        self._q: "queue.Queue[tuple[Job, Callable]]" = queue.Queue()
        threading.Thread(target=self._loop, daemon=True).start()

    def submit(self, kind: str, title: str, fn: Callable[[Callable], Any]) -> Job:
        job = Job(id=uuid.uuid4().hex[:10], kind=kind, title=title)
        job.stage = {"auto": "asr", "generate": "asr", "transcribe": "asr", "render": "look"}.get(kind)
        if job.stage:
            job.completed_stages = ["upload"]
        with self._lock:
            self.jobs[job.id] = job
        self._q.put((job, fn))
        return job

    def cancel(self, jid: str) -> dict:
        with self._lock:
            job = self.jobs[jid]
            if job.status in ("queued", "running"):
                job.cancel_requested = True
                job._cancel.set()
                if job.status == "queued":
                    job.status, job.message = "cancelled", "已取消"
                    job.finished = time.time()
                else:
                    job.message = "正在取消，等待当前处理停止"
            return job.to_dict()

    def _loop(self) -> None:
        while True:
            job, fn = self._q.get()
            with self._lock:
                if job.status == "cancelled":
                    self._q.task_done()
                    continue
                job.status, job.message = "running", "开始"

            def progress(i: int, n: int, msg: str, job=job) -> None:
                with self._lock:
                    cancellation.check()
                    job.progress = (i / n) if n else 0.0
                    job.message = msg

            def set_stage(stage: str, job=job) -> None:
                with self._lock:
                    cancellation.check()
                    if job.stage and job.stage != stage and job.stage not in job.completed_stages:
                        job.completed_stages.append(job.stage)
                    job.stage = stage

            progress.set_stage = set_stage

            try:
                with cancellation.scope(job._cancel):
                    result = fn(progress)
                    with self._lock:
                        cancellation.check()
                        job.result = result
                        if job.stage:
                            set_stage("done")
                        job.status, job.progress = "done", 1.0
                        job.message = job.message if job.message not in ("开始",) else "完成"
            except cancellation.JobCancelled:
                with self._lock:
                    job.status, job.message = "cancelled", "已取消"
            except Exception as e:  # noqa: BLE001
                with self._lock:
                    if job.cancel_requested:
                        job.status, job.message = "cancelled", "已取消"
                    else:
                        job.status, job.error = "error", f"{e}\n{traceback.format_exc()[-1500:]}"
                        job.message = f"出错：{e}"
            finally:
                with self._lock:
                    job.finished = time.time()
                self._q.task_done()

    def list(self, limit: int = 30) -> list[dict]:
        with self._lock:
            ordered = sorted(list(self.jobs.values()), key=lambda j: -j.created)
            active = [job for job in ordered if job.status in ("queued", "running")]
            finished = [job for job in ordered if job.status not in ("queued", "running")]
            visible = sorted(active + finished[:max(0, limit - len(active))], key=lambda job: -job.created)
            return [job.to_dict() for job in visible]

    def busy(self) -> bool:
        with self._lock:
            return any(j.status in ("queued", "running") for j in self.jobs.values())
