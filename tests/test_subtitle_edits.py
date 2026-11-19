import copy
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient
import app as server
from jh import config, graphics, look, script


class SubtitleEditsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        replacement = patch.object(config, "data_root", return_value=self.root)
        replacement.start()
        self.addCleanup(replacement.stop)
        self.original = {"batch": "project", "id": "a", "title": "原始标题", "status": "rendered", "cover": ["封面"], "lines": [
            {"clip": "one.mov", "start": 1., "end": 3., "subtitle": "字幕一", "src_text": "原声一", "keep": "原声一", "words": [["原", 1., 1.2]]},
            {"clip": "two.mov", "start": 4., "end": 6., "subtitle": "字幕二", "src_text": "原声二", "keep": "原声二", "zoom": 1.2},
        ]}
        self.path = script.save(self.original)
        self.other = script.save({**self.original, "id": "b"})
        self.client = TestClient(server.app)

    def change(self, index=0, subtitle="修改后的字幕"):
        line = self.original["lines"][index]
        return {"index": index, "clip": line["clip"], "start": line["start"], "end": line["end"], "previous": line["subtitle"], "subtitle": subtitle}

    def test_only_caption_changes_preserve_audio_edit_fields_other_script_and_rendered_status(self):
        other_bytes = self.other.read_bytes()
        response = self.client.put("/api/batches/project/scripts/a/subtitles", json={"changes": [self.change()]})
        self.assertEqual(response.status_code, 200, response.text)
        expected = copy.deepcopy(self.original)
        expected["lines"][0]["subtitle"] = "修改后的字幕"
        self.assertEqual(script.load("project", "a"), expected)
        self.assertEqual(self.other.read_bytes(), other_bytes)

    def test_conflict_in_later_sentence_does_not_partially_save_earlier_changes(self):
        before = self.path.read_bytes()
        stale = {**self.change(1), "previous": "其他版本"}
        response = self.client.put("/api/batches/project/scripts/a/subtitles", json={"changes": [self.change(), stale]})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(self.path.read_bytes(), before)
        stale = {**self.change(), "clip": "regenerated.mov"}
        self.assertEqual(self.client.put("/api/batches/project/scripts/a/subtitles", json={"changes": [stale]}).status_code, 409)

    def test_invalid_changes_do_not_write_and_missing_script_returns_404(self):
        before = self.path.read_bytes()
        for changes in (None, {}, [self.change(), self.change()], [{**self.change(), "index": -1}], [{**self.change(), "subtitle": "a" * 2001}]):
            with self.subTest(changes=changes):
                self.assertEqual(self.client.put("/api/batches/project/scripts/a/subtitles", json={"changes": changes}).status_code, 400)
                self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(self.client.put("/api/batches/project/scripts/missing/subtitles", json={"changes": []}).status_code, 404)

    def test_selected_render_captures_settings_before_waiting_in_queue(self):
        captured = []
        def submit(kind, title, run):
            captured.append(run)
            return SimpleNamespace(to_dict=lambda: {"id": "job-a", "title": title})
        settings = {**look.DEFAULTS, "tone": .25}
        design = graphics.normalize(graphics.defaults())
        with patch.object(server.jobs, "submit", side_effect=submit), patch.object(server.render, "render", return_value=self.root / "a.mp4") as render:
            response = self.client.post("/api/batches/project/scripts/a/render", json={"look": settings, "graphics": design})
            self.assertEqual(response.status_code, 200, response.text)
            look.save({**settings, "tone": .9})
            captured[0](SimpleNamespace(set_stage=lambda *args: None))
        self.assertEqual(render.call_args.kwargs["settings"]["tone"], .25)
        self.assertEqual(render.call_args.args[0]["id"], "a")
        self.assertEqual(render.call_args.kwargs["design"], design)
        self.assertEqual(self.client.post("/api/batches/project/scripts/a/render", json={"look": None, "graphics": design}).status_code, 400)

    def test_long_caption_preview_uses_the_same_screens_as_rendering(self):
        text = "这一句口播字幕内容很长，需要按照实际出片的规则分成多屏显示"
        response = self.client.post("/api/graphics/caption", json={"text": text})
        self.assertEqual(response.status_code, 200, response.text)
        limit = config.load()["style"]["subtitle"]["max_chars_per_line"]
        chunks = response.json()["chunks"]
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(len(chunk["text"]) <= limit for chunk in chunks))
        self.assertAlmostEqual(chunks[-1]["end"], 6)
        self.assertEqual(self.client.post("/api/graphics/caption", json={"text": ""}).json()["chunks"], [])

    def test_legacy_single_and_bulk_render_endpoints_still_queue_without_settings_body(self):
        titles = []
        def submit(kind, title, run):
            titles.append(title)
            return SimpleNamespace(to_dict=lambda: {"id": title})
        with patch.object(server.jobs, "submit", side_effect=submit):
            self.assertEqual(self.client.post("/api/batches/project/scripts/a/render").status_code, 200)
            response = self.client.post("/api/batches/project/render_all", json={"all": True})
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(len(response.json()), 2)
        self.assertEqual(titles, ["a 出片", "a 出片", "b 出片"])


if __name__ == "__main__":
    unittest.main()
