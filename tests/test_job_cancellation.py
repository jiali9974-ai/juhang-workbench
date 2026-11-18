import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

import app as server
from jh import cancellation, llm, media, render
from jh.jobs import JobQueue


def finished(job):
    deadline = time.monotonic() + 5
    while job.finished is None and time.monotonic() < deadline:
        time.sleep(0.01)
    if job.finished is None:
        raise AssertionError("任务未结束")


class JobCancellationTests(unittest.TestCase):
    def test_cancellable_process_preserves_binary_input_and_output_on_success(self):
        with cancellation.scope(threading.Event()):
            result = cancellation.run_process(
                [sys.executable, "-c", "import sys,time; time.sleep(.3); sys.stdout.buffer.write(sys.stdin.buffer.read())"],
                input=b"frame" * 100000, capture_output=True,
            )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, b"frame" * 100000)

    def test_cancel_queued_skips_work_and_running_stays_busy_until_stopped(self):
        queue = JobQueue()
        started, release, next_ran, skipped = (threading.Event() for _ in range(4))
        self.addCleanup(release.set)

        def run(progress):
            started.set()
            release.wait(5)  # 模拟不可中断的当前模型调用。
            progress(1, 1, "模型返回")

        current = queue.submit("auto", "运行中", run)
        self.assertTrue(started.wait(2))
        queued = queue.submit("render", "排队中", lambda p: skipped.set())
        following = queue.submit("render", "后续任务", lambda p: next_ran.set())
        with patch.object(server, "jobs", queue):
            client = TestClient(server.app)
            cancelled = client.post(f"/api/jobs/{queued.id}/cancel")
            self.assertEqual(cancelled.json()["status"], "cancelled")
            stopping = client.post(f"/api/jobs/{current.id}/cancel").json()
            self.assertEqual(stopping["status"], "running")
            self.assertTrue(stopping["cancel_requested"])
            self.assertTrue(queue.busy())
            self.assertEqual(client.post("/api/jobs/missing/cancel").status_code, 404)
        release.set()
        finished(current)
        finished(following)
        self.assertEqual(current.status, "cancelled")
        self.assertEqual(current.error, "")
        self.assertNotIn("asr", current.completed_stages)
        self.assertFalse(skipped.is_set())
        self.assertTrue(next_ran.is_set())
        self.assertEqual(following.status, "done")
        self.assertFalse(queue.busy())
        # 已结束的任务重复取消，不改变结果或结束时间。
        previous = following.to_dict()
        self.assertEqual(queue.cancel(following.id), previous)

    def test_cancel_interrupts_active_child_process_and_worker_continues(self):
        queue = JobQueue()
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / "started"
            late = Path(directory) / "should-not-exist"
            program = ("from pathlib import Path; import sys,time; "
                       "Path(sys.argv[1]).write_text('ready'); time.sleep(20); "
                       "Path(sys.argv[2]).write_text('late')")
            job = queue.submit("render", "长编码", lambda p: cancellation.run_process(
                [sys.executable, "-c", program, str(marker), str(late)], capture_output=True))
            deadline = time.monotonic() + 3
            while not marker.exists() and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertTrue(marker.exists())
            queue.cancel(job.id)
            finished(job)
            self.assertEqual(job.status, "cancelled")
            self.assertFalse(late.exists())
            following = queue.submit("render", "继续", lambda p: "ready")
            finished(following)
            self.assertEqual(following.result, "ready")

    def test_cancelled_model_response_never_retries_or_returns_generated_script(self):
        event = threading.Event()

        def respond(**kwargs):
            event.set()
            raise RuntimeError("502 upstream")

        from types import SimpleNamespace
        client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=respond)))
        with patch.object(llm, "_client", return_value=client), patch.object(llm, "models", return_value=["primary", "fallback"]):
            with self.assertRaises(cancellation.JobCancelled), cancellation.scope(event):
                llm.chat([])

    def test_cancelled_ffmpeg_does_not_replace_existing_file_or_leave_partial_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "cached.wav"
            target.write_bytes(b"original")

            def stop(command, **kwargs):
                Path(command[-1]).write_bytes(b"partial")
                raise cancellation.JobCancelled()

            with patch.object(cancellation, "run_process", side_effect=stop):
                with self.assertRaises(cancellation.JobCancelled):
                    media.run_ffmpeg(["-i", "source.mp4", str(target)])
            self.assertEqual(target.read_bytes(), b"original")
            self.assertEqual(list(Path(directory).iterdir()), [target])

    def test_cancelled_rerender_keeps_old_video_and_never_publishes_partial_video(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "outputs" / "项目"
            output.mkdir(parents=True)
            target = output / "片.mp4"
            target.write_bytes(b"old-completed-video")
            old_cover = output / "片_封面.jpg"
            old_cover.write_bytes(b"old-cover")
            old_source = output / "片_封面原图.jpg"
            old_source.write_bytes(b"old-source")

            def make_cover(segs, lines, destination, **kwargs):
                from PIL import Image
                Image.new("RGB", (4, 4)).save(destination)
                kwargs["source_out"].write_bytes(b"new-source")
                return destination

            def stop(segs, work, pending, *args, **kwargs):
                pending.write_bytes(b"partial-new-video")
                raise cancellation.JobCancelled()

            def complete(segs, work, pending, *args, **kwargs):
                pending.write_bytes(b"new-completed-video")
                return 1.0

            with patch.object(render.config, "data_root", return_value=root / "data"), \
                 patch.object(render.config, "output_root", return_value=root / "outputs"), \
                 patch.object(render.config, "load", return_value={"render": {"cover": {"enabled": True}}}), \
                 patch("jh.cover.make_best_cover", side_effect=make_cover), \
                 patch.object(render.look, "current", return_value={}), \
                 patch.object(render, "plan", return_value=[]), \
                 patch.object(render, "compose_segments", side_effect=stop):
                with self.assertRaises(cancellation.JobCancelled):
                    render.render({"batch": "项目", "id": "片", "cover": ["新封面"]})
            self.assertEqual(target.read_bytes(), b"old-completed-video")
            self.assertEqual(old_cover.read_bytes(), b"old-cover")
            self.assertEqual(old_source.read_bytes(), b"old-source")
            self.assertEqual(set(output.iterdir()), {target, old_cover, old_source})

            # 同一路径正常完成后，视频和封面一起发布，临时目录不会进入成片库。
            with patch.object(render.config, "data_root", return_value=root / "data"), \
                 patch.object(render.config, "output_root", return_value=root / "outputs"), \
                 patch.object(render.config, "load", return_value={"render": {"cover": {"enabled": True}}}), \
                 patch("jh.cover.make_best_cover", side_effect=make_cover), \
                 patch.object(render.look, "current", return_value={}), \
                 patch.object(render, "plan", return_value=[]), \
                 patch.object(render, "embed_cover"), \
                 patch.object(render, "compose_segments", side_effect=complete):
                result = render.render({"batch": "项目", "id": "片", "cover": ["新封面"]})
            self.assertEqual(result, target)
            self.assertEqual(target.read_bytes(), b"new-completed-video")
            self.assertEqual(old_source.read_bytes(), b"new-source")
            self.assertNotEqual(old_cover.read_bytes(), b"old-cover")
            self.assertEqual(set(output.iterdir()), {target, old_cover, old_source})


if __name__ == "__main__":
    unittest.main()
