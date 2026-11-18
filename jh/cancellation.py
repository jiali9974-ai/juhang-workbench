"""Cooperative job cancellation, including active FFmpeg processes."""
from __future__ import annotations

import subprocess
import threading
import time
from contextlib import contextmanager
from contextvars import ContextVar

_event: ContextVar[threading.Event | None] = ContextVar("job_cancellation", default=None)


class JobCancelled(BaseException):
    """Must bypass ordinary model fallback/error recovery handlers."""


@contextmanager
def scope(event: threading.Event):
    token = _event.set(event)
    try:
        check()
        yield
    finally:
        _event.reset(token)


def check() -> None:
    event = _event.get()
    if event is not None and event.is_set():
        raise JobCancelled()


def wait(seconds: float) -> None:
    event = _event.get()
    if event is None:
        time.sleep(seconds)
    elif event.wait(seconds):
        raise JobCancelled()


def run_process(args, **kwargs) -> subprocess.CompletedProcess:
    """Like subprocess.run(capture_output=True), with cancellation in job scope."""
    if _event.get() is None:
        return subprocess.run(args, **kwargs)
    check()
    capture = kwargs.pop("capture_output", False)
    input_data = kwargs.pop("input", None)
    if input_data is not None:
        kwargs["stdin"] = subprocess.PIPE
    if capture:
        kwargs.update(stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    with subprocess.Popen(args, **kwargs) as process:
        try:
            while True:
                check()
                try:
                    stdout, stderr = process.communicate(input=input_data, timeout=0.2)
                    check()
                    return subprocess.CompletedProcess(args, process.returncode, stdout, stderr)
                except subprocess.TimeoutExpired:
                    input_data = None
                    continue
        except BaseException:
            if process.poll() is None:
                process.terminate()
            try:
                process.communicate(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.communicate()
            raise
