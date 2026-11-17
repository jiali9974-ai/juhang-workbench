import io
import json
import tempfile
import threading
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

import app as server
from jh import deletion, outputs
from jh.jobs import Job, JobQueue

configured_output_root = server.config.output_root


class OutputApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.root_patch = patch("jh.config.data_root", return_value=self.root)
        self.root_patch.start()
        self.addCleanup(self.root_patch.stop)
        self.output_patch = patch("jh.config.output_root", return_value=self.root / "outputs")
        self.output_patch.start()
        self.addCleanup(self.output_patch.stop)
        self.client = TestClient(server.app)

    def video(self, batch, sid, status="rendered", content=b"completed-video", title=None):
        folder = self.root / "outputs" / batch
        folder.mkdir(parents=True, exist_ok=True)
        (folder / f"{sid}.mp4").write_bytes(content)
        script = self.root / "scripts" / batch / f"{sid}.json"
        script.parent.mkdir(parents=True, exist_ok=True)
        script.write_text(json.dumps({"id": sid, "batch": batch, "title": sid if title is None else title, "status": status}), encoding="utf-8")

    def test_configured_output_directory_and_top_level_files_are_the_library(self):
        library = self.root / "independent-outputs"
        with patch("jh.config.load", return_value={"paths": {"output_root": str(library)}}):
            self.assertEqual(configured_output_root(), library)
            self.assertTrue(library.is_dir())
        with patch("jh.config.output_root", return_value=library):
            self.assertEqual(self.client.get("/api/outputs").json(), [])
            (library / "直接放入的成片.mp4").write_bytes(b"standalone-video")
            (library / "直接放入的成片_封面.jpg").write_bytes(b"cover")
            listed = self.client.get("/api/outputs").json()
            self.assertEqual([(v["batch"], v["id"]) for v in listed], [("", "直接放入的成片")])
            self.assertEqual(self.client.get("/api/root_outputs/直接放入的成片.mp4").content, b"standalone-video")
            export = self.client.post("/api/outputs/export", json={"items": [{"batch": "", "id": "直接放入的成片"}]})
            with zipfile.ZipFile(io.BytesIO(self.client.get(export.json()["url"]).content)) as archive:
                self.assertEqual(archive.namelist(), ["直接放入的成片.mp4"])
            self.assertEqual(self.client.delete("/api/root_outputs/直接放入的成片").status_code, 200)
            self.assertEqual(self.client.get("/api/outputs").json(), [])

    def test_upload_creates_a_project_and_adds_material_without_generating(self):
        material = self.root / "materials"
        material.mkdir()
        with patch("jh.config.material_root", return_value=material):
            created = self.client.post("/api/batches", json={"name": "上传创建项目"})
            self.assertEqual(created.status_code, 200)
            self.assertIsNone(created.json()["job"])
            uploaded = self.client.put("/api/batches/上传创建项目/upload?filename=sample.mp4", content=b"test-material", headers={"Content-Type": "application/octet-stream"})
            self.assertEqual(uploaded.status_code, 200)
            self.assertEqual((material / "上传创建项目" / "sample.mp4").read_bytes(), b"test-material")
            batch = self.client.get("/api/batches").json()[0]
            self.assertEqual((batch["batch"], batch["clips"], batch["scripts"], batch["outputs"]), ("上传创建项目", 1, 0, 0))
            self.assertEqual(self.client.post("/api/batches", json={"name": "上传创建项目"}).status_code, 400)

    def test_gallery_only_lists_completed_files_across_projects(self):
        self.video("项目甲", "第一条")
        self.video("项目乙", "第二条")
        self.video("项目甲", "制作中", "approved")
        self.video("项目甲", "empty", content=b"")
        self.video("项目甲", "temp_cover_tmp")
        archive = self.root / "outputs" / "项目甲" / "_old_20260101"
        archive.mkdir()
        (archive / "old.mp4").write_bytes(b"old")
        response = self.client.get("/api/outputs")
        self.assertEqual(response.status_code, 200)
        self.assertEqual({(v["batch"], v["id"]) for v in response.json()}, {("项目甲", "第一条"), ("项目乙", "第二条")})

    def test_selected_zip_keeps_unicode_names_and_cleans_up_after_download(self):
        self.video("项目甲", "同名", content=b"A", title="杭州上城区二手名表店")
        self.video("项目乙", "同名", content=b"B", title="劳力士218239白金款")
        self.video("项目甲", "未选择", content=b"excluded")
        selection = [{"batch": batch, "id": "同名"} for batch in ("项目甲", "项目乙", "项目甲")]
        response = self.client.post("/api/outputs/export", json={"items": selection})
        self.assertEqual(response.status_code, 200)
        url = response.json()["url"]
        download = self.client.get(url)
        self.assertEqual(download.status_code, 200)
        self.assertEqual(download.headers["content-type"], "application/zip")
        with zipfile.ZipFile(io.BytesIO(download.content)) as archive:
            self.assertEqual(archive.namelist(), ["项目甲/杭州上城区二手名表店.mp4", "项目乙/劳力士218239白金款.mp4"])
            self.assertEqual(archive.read("项目甲/杭州上城区二手名表店.mp4"), b"A")
            self.assertEqual(archive.read("项目乙/劳力士218239白金款.mp4"), b"B")
        self.assertTrue((self.root / "outputs" / "项目甲" / "同名.mp4").is_file())
        self.assertEqual(self.client.get(url).status_code, 404)

    def test_export_disambiguates_titles_without_overwriting_any_selected_video(self):
        titles = ["名表行情", "名表行情 (2)", "名表行情", "Watch", "watch", "名表行情"]
        selected = []
        for index, title in enumerate(titles):
            batch = "项目乙" if index == 5 else "项目甲"
            sid = f"片_{index}"
            self.video(batch, sid, title=title, content=str(index).encode())
            selected.append({"batch": batch, "id": sid})
        response = self.client.post("/api/outputs/export", json={"items": selected})
        self.assertEqual(response.status_code, 200)
        with zipfile.ZipFile(io.BytesIO(self.client.get(response.json()["url"]).content)) as archive:
            names = ["项目甲/名表行情.mp4", "项目甲/名表行情 (2).mp4", "项目甲/名表行情 (3).mp4",
                     "项目甲/Watch.mp4", "项目甲/watch (2).mp4", "项目乙/名表行情.mp4"]
            self.assertEqual(archive.namelist(), names)
            self.assertEqual([archive.read(name) for name in names], [str(i).encode() for i in range(6)])

    def test_export_titles_are_safe_to_extract_and_fall_back_to_the_id(self):
        titles = [" ../名表/行情:新低? ", "CON", "", "   ", "成片" * 100, "带扩展名.mp4"]
        selected = []
        for index, title in enumerate(titles):
            sid = f"片_{index}"
            self.video("项目", sid, title=title)
            selected.append({"batch": "项目", "id": sid})
        response = self.client.post("/api/outputs/export", json={"items": selected})
        self.assertEqual(response.status_code, 200)
        with zipfile.ZipFile(io.BytesIO(self.client.get(response.json()["url"]).content)) as archive:
            names = archive.namelist()
            self.assertEqual(names[:4], ["项目/_名表_行情_新低_.mp4", "项目/_CON.mp4", "项目/片_2.mp4", "项目/片_3.mp4"])
            self.assertEqual(names[-1], "项目/带扩展名.mp4")
            self.assertTrue(all(len(name.split("/")[-1].encode("utf-8")) <= 255 for name in names))
            destination = self.root / "extracted"
            archive.extractall(destination)
            self.assertEqual(len(list(destination.rglob("*.mp4"))), len(selected))

    def test_export_rejects_empty_missing_unfinished_and_escaping_paths(self):
        self.video("项目甲", "制作中", "approved")
        self.assertEqual(self.client.post("/api/outputs/export", json={"items": []}).status_code, 422)
        for batch, sid, expected in [("项目甲", "missing", 404), ("项目甲", "制作中", 400),
                                     ("..", "secret", 400), ("项目甲", "../secret", 400),
                                     ("C:\\Users", "secret", 400)]:
            with self.subTest(batch=batch, sid=sid):
                result = self.client.post("/api/outputs/export", json={"items": [{"batch": batch, "id": sid}]})
                self.assertEqual(result.status_code, expected)
        self.assertEqual(self.client.get("/api/exports/invalid.zip").status_code, 404)

    def test_rerendering_video_is_hidden_until_it_finishes(self):
        self.video("项目甲", "第一条")
        busy = [{"status": "running", "title": "第一条 出片"}]
        self.assertEqual(outputs.list_outputs(busy), [])
        self.assertEqual(len(outputs.list_outputs([])), 1)

    def test_delete_permanently_removes_only_selected_video_and_cover_and_keeps_script(self):
        self.video("项目甲", "删除这条", content=b"to-delete")
        self.video("项目甲", "保留这条", content=b"keep")
        cover = self.root / "outputs" / "项目甲" / "删除这条_封面.jpg"
        cover.write_bytes(b"cover")
        raw = cover.with_name("删除这条_封面原图.jpg")
        raw.write_bytes(b"original")
        raw.with_suffix(".json").write_text("{}", encoding="utf-8")
        result = self.client.delete("/api/outputs/项目甲/删除这条")
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json(), {"ok": True})
        self.assertEqual(list(self.root.rglob("删除这条.mp4")), [])
        self.assertFalse((self.root / "_recycle").exists())
        self.assertFalse(cover.exists())
        self.assertFalse(raw.exists())
        self.assertFalse(raw.with_suffix(".json").exists())
        self.assertTrue((self.root / "outputs" / "项目甲" / "保留这条.mp4").is_file())
        script = self.root / "scripts" / "项目甲" / "删除这条.json"
        self.assertEqual(json.loads(script.read_text(encoding="utf-8"))["status"], "approved")
        self.assertEqual([video["id"] for video in self.client.get("/api/outputs").json()], ["保留这条"])
        self.assertEqual(self.client.delete("/api/outputs/项目甲/删除这条").status_code, 404)

    def test_delete_rejects_busy_video_and_preserves_it(self):
        self.video("项目甲", "制作中")
        with patch.object(server.jobs, "list", return_value=[{"status": "running", "title": "制作中 出片"}]):
            self.assertEqual(self.client.delete("/api/outputs/项目甲/制作中").status_code, 409)
        self.assertTrue((self.root / "outputs" / "项目甲" / "制作中.mp4").is_file())
        self.assertEqual(self.client.delete("/api/outputs/项目甲/bad%5Cpath").status_code, 400)

    def test_delete_batch_permanently_removes_materials_and_all_its_generated_data(self):
        material = self.root / "materials"
        project = material / "项目甲"
        project.mkdir(parents=True)
        (project / "原片.mp4").write_bytes(b"source")
        other = material / "项目乙"
        other.mkdir()
        (other / "保留.mp4").write_bytes(b"keep")
        self.video("项目甲", "成片")
        self.video("项目乙", "保留成片")
        generated = ("transcripts", "scripts", "outputs", "renders", "preview", "thumbs", "voice_refs", "dub")
        for sub in generated:
            nested = self.root / sub / "项目甲" / "nested"
            nested.mkdir(parents=True, exist_ok=True)
            (nested / "fixture.bin").write_bytes(b"generated")
        cache = self.root / "clipinfo" / "项目甲.json"
        cache.parent.mkdir()
        cache.write_text("{}", encoding="utf-8")
        with patch("jh.config.material_root", return_value=material):
            result = self.client.delete("/api/batches/项目甲")
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json(), {"ok": True})
        self.assertFalse(project.exists())
        self.assertTrue((other / "保留.mp4").exists())
        self.assertTrue((self.root / "outputs" / "项目乙" / "保留成片.mp4").exists())
        for sub in generated:
            self.assertFalse((self.root / sub / "项目甲").exists())
        self.assertFalse(cache.exists())
        self.assertFalse((self.root / "_recycle").exists())

    def test_running_project_cannot_be_deleted(self):
        material = self.root / "materials"
        project = material / "项目甲"
        project.mkdir(parents=True)
        source = project / "原片.mp4"
        source.write_bytes(b"keep-busy")
        with patch("jh.config.material_root", return_value=material), \
             patch.object(server.jobs, "list", return_value=[{"status": "running", "title": "项目甲 一键出片"}]):
            self.assertEqual(self.client.delete("/api/batches/项目甲").status_code, 409)
        self.assertEqual(source.read_bytes(), b"keep-busy")

    def test_removed_image_generation_routes_are_unavailable_and_preserve_existing_files(self):
        stored = self.root / "tvc" / "existing-project" / "product.png"
        stored.parent.mkdir(parents=True)
        stored.write_bytes(b"existing-user-data")
        for method, url in [("GET", "/api/cloud/status"), ("GET", "/api/tvc"),
                            ("POST", "/api/tvc"), ("GET", "/api/tvc_presenter"),
                            ("DELETE", "/api/tvc/existing-project")]:
            with self.subTest(method=method, url=url):
                self.assertEqual(self.client.request(method, url, json={}).status_code, 404)
        self.assertEqual(stored.read_bytes(), b"existing-user-data")
        paths = self.client.get("/openapi.json").json()["paths"]
        self.assertFalse(any(path.startswith(("/api/tvc", "/api/cloud/")) for path in paths))

    def test_invalid_delete_target_is_rejected_before_any_files_are_deleted(self):
        target = self.root / "keep"
        target.mkdir()
        source = target / "keep.bin"
        source.write_bytes(b"keep")
        with self.assertRaises(ValueError):
            deletion.delete_children([(self.root, "keep"), (self.root, "..")])
        self.assertEqual(source.read_bytes(), b"keep")
        for name in ("", ".", "..", "../keep", "C:\\Users", "nested\\keep"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                deletion.child_path(self.root, name)

    def test_auto_job_reports_actual_stages_and_publishes_completed_video(self):
        queue = JobQueue()
        seen = []
        finished = threading.Event()
        script = {"id": "片_01", "batch": "项目甲", "title": "测试成片", "lines": []}

        def recognize(folder, dest, progress):
            progress(1, 1, "识别中")
            seen.append(queue.list()[0]["stage"])
            return []

        def generate(batch, transcripts, progress):
            seen.append(queue.list()[0]["stage"])
            return [script]

        def render(script, progress, on_stage):
            for stage in ("look", "cover", "look", "render"):
                on_stage(stage)
                seen.append(queue.list()[0]["stage"])
            self.video(script["batch"], script["id"], status="approved")
            return self.root / "outputs" / script["batch"] / f"{script['id']}.mp4"

        original_save = server.scriptmod.save

        def save(value):
            result = original_save(value)
            if value.get("status") == "rendered":
                finished.set()
            return result

        with patch.object(server, "jobs", queue), patch.object(server, "_batch_dir", return_value=self.root), \
             patch.object(server.asr, "transcribe_folder", side_effect=recognize), \
             patch.object(server.scriptmod, "generate", side_effect=generate), \
             patch.object(server.scriptmod, "archive_batch"), patch.object(server.scriptmod, "save", side_effect=save), \
             patch.object(server.render, "render", side_effect=render):
            response = self.client.post("/api/batches/项目甲/auto")
            self.assertEqual(response.status_code, 200)
            self.assertTrue(finished.wait(3))
            for _ in range(100):
                job = self.client.get("/api/jobs").json()[0]
                if job["status"] == "done":
                    break
                threading.Event().wait(0.01)
            self.assertEqual(seen, ["asr", "script", "look", "cover", "look", "render"])
            self.assertEqual(job["status"], "done")
            self.assertEqual(job["stage"], "done")
            self.assertTrue({"upload", "asr", "script", "look", "cover", "render"}.issubset(job["completed_stages"]))
            self.assertEqual(len(self.client.get("/api/outputs").json()), 1)

    def test_auto_publishes_each_video_while_next_is_still_rendering_and_keeps_it_on_failure(self):
        for fail_second in (False, True):
            with self.subTest(fail_second=fail_second):
                queue = JobQueue()
                second_started, release = threading.Event(), threading.Event()
                scripts = [{"id": f"逐条_{i}", "batch": "逐条项目", "title": f"第{i}条", "lines": []} for i in (1, 2)]

                def render(script, progress, on_stage):
                    on_stage("render")
                    self.video(script["batch"], script["id"], status="approved")
                    if script["id"] == "逐条_2":
                        second_started.set()
                        if not release.wait(5):
                            raise RuntimeError("fixture timed out")
                        if fail_second:
                            raise RuntimeError("second video failed")
                    return self.root / "outputs" / script["batch"] / f"{script['id']}.mp4"

                with patch.object(server, "jobs", queue), patch.object(server, "_batch_dir", return_value=self.root), \
                     patch.object(server.asr, "transcribe_folder", return_value=[]), \
                     patch.object(server.scriptmod, "generate", return_value=scripts), \
                     patch.object(server.scriptmod, "archive_batch"), patch.object(server.render, "render", side_effect=render):
                    submitted = self.client.post("/api/batches/逐条项目/auto").json()
                    try:
                        self.assertTrue(second_started.wait(3))
                        self.assertEqual(queue.jobs[submitted["id"]].status, "running")
                        library = self.client.get("/api/outputs").json()
                        self.assertEqual([video["id"] for video in library], ["逐条_1"])
                        export = self.client.post("/api/outputs/export", json={"items": [{"batch": "逐条项目", "id": "逐条_1"}]})
                        self.assertEqual(export.status_code, 200)
                        self.assertEqual(self.client.post("/api/outputs/export", json={"items": [{"batch": "逐条项目", "id": "逐条_2"}]}).status_code, 400)
                    finally:
                        release.set()
                    for _ in range(100):
                        job = queue.jobs[submitted["id"]]
                        if job.status in ("done", "error"):
                            break
                        threading.Event().wait(.01)
                    self.assertEqual(job.status, "error" if fail_second else "done")
                    self.assertEqual({video["id"] for video in self.client.get("/api/outputs").json()},
                                     {"逐条_1"} if fail_second else {"逐条_1", "逐条_2"})

    def test_failed_job_retains_the_failing_stage(self):
        queue = JobQueue()
        failed = threading.Event()

        def run(progress):
            progress.set_stage("cover")
            failed.set()
            raise RuntimeError("fixture failure")

        queue.submit("render", "test 出片", run)
        self.assertTrue(failed.wait(2))
        for _ in range(100):
            job = queue.list()[0]
            if job["status"] == "error":
                break
            threading.Event().wait(0.01)
        self.assertEqual(job["stage"], "cover")
        self.assertEqual(job["status"], "error")
        self.assertNotIn("cover", job["completed_stages"])

    def test_many_finished_jobs_do_not_hide_older_running_or_queued_jobs(self):
        queue = JobQueue()
        queue.jobs["running"] = Job(id="running", kind="auto", title="旧项目生成", status="running", created=1)
        queue.jobs["queued"] = Job(id="queued", kind="render", title="排队出片", status="queued", created=2)
        for index in range(40):
            queue.jobs[f"done-{index}"] = Job(id=f"done-{index}", kind="tts", title="已完成", status="done", created=100 + index)
        visible = queue.list(5)
        self.assertEqual(len(visible), 5)
        self.assertEqual({job["id"] for job in visible if job["status"] in ("running", "queued")}, {"running", "queued"})


if __name__ == "__main__":
    unittest.main()
