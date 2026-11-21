import copy
import json
import re
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import av
import numpy as np
from fastapi.testclient import TestClient

import app as server
from jh import config, fonts, graphics, render


class GraphicsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.cfg = copy.deepcopy(config.load())
        self.cfg["render"].update(width=360, height=640, fps=24)
        self.cfg["style"]["slogan"]["enabled"] = False
        self.cfg["style"]["disclaimer"]["enabled"] = False
        for target, replacement in (("jh.config.load", self.cfg), ("jh.config.data_root", self.root)):
            mock = patch(target, return_value=replacement)
            mock.start()
            self.addCleanup(mock.stop)
        self.client = TestClient(server.app)

    def design(self, **changes):
        settings = graphics.normalize(graphics.defaults())
        element = {**settings["subtitle"], "id": "text-one", "type": "text", "text": "名表行情", "x": 35, "y": 28,
                   "size": 110, "start": .2, "end": 2, **changes}
        settings["elements"] = [element]
        return graphics.normalize(settings)

    def test_settings_survive_reload_and_bad_fonts_or_ids_cannot_overwrite_them(self):
        expected = self.design(text="到店试戴", x=20, y=30, size=160, animation="fade")
        response = self.client.put("/api/graphics", json=expected)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.client.get("/api/graphics").json()["settings"], expected)
        for patch_ in ({"font_id": "does-not-exist"}, {"id": "../bad"}, {"end": 0}, {"type": "bad"}, {"animation": "bad"}):
            broken = copy.deepcopy(expected)
            broken["elements"][0].update(patch_)
            self.assertEqual(self.client.put("/api/graphics", json=broken).status_code, 400)
            self.assertEqual(graphics.current(), expected)
        empty = copy.deepcopy(expected)
        empty["elements"] = []
        self.client.put("/api/graphics", json=empty).raise_for_status()
        self.assertEqual(graphics.current()["elements"], [])

    def test_font_upload_real_file_serving_use_protection_and_delete(self):
        source = config.ROOT / "fonts" / "ZCOOLKuaiLe-Regular.ttf"
        body = source.read_bytes()
        self.assertEqual(self.client.post("/api/fonts?filename=bad.ttf", content=b"not-a-font").status_code, 400)
        self.assertEqual(self.client.post("/api/fonts?filename=bad.exe", content=body).status_code, 400)
        response = self.client.post("/api/fonts?filename=字体.ttf", content=body)
        self.assertEqual(response.status_code, 200, response.text)
        item = response.json()["font"]
        self.assertFalse(item["builtin"])
        self.assertEqual(self.client.get(f"/api/fonts/{item['id']}/file").content, body)
        expected = self.design(font_id=item["id"])
        self.client.put("/api/graphics", json=expected).raise_for_status()
        self.assertEqual(self.client.delete(f"/api/fonts/{item['id']}").status_code, 400)
        expected["elements"] = []
        self.client.put("/api/graphics", json=expected).raise_for_status()
        self.assertEqual(self.client.delete(f"/api/fonts/{item['id']}").status_code, 200)
        self.assertEqual(self.client.get(f"/api/fonts/{item['id']}/file").status_code, 404)
        self.assertEqual(self.client.delete("/api/fonts/SourceHanSansCN-Heavy").status_code, 400)

    def test_builtin_fonts_render_selected_faces_and_keep_only_needed_files(self):
        items = self.client.get("/api/graphics").json()["fonts"]
        builtin = [item for item in items if item["builtin"]]
        self.assertEqual({item["file"] for item in builtin}, set(fonts.BUILTINS))
        sources = json.loads((config.ROOT / "fonts" / "sources.json").read_text(encoding="utf-8"))
        postscript = {item["file"]: item["postscript_name"] for item in sources["fonts"]}
        pictures = set()
        for item in builtin:
            with self.subTest(font=item["id"]):
                directory = self.root / item["id"]
                directory.mkdir()
                settings = graphics.normalize(graphics.defaults())
                settings["subtitle"].update(font_id=item["id"], size=100, outline=0)
                segment = render.Segment(Path("unused"), 0, 1, subs=[(0, 1, "巨航名表嘅哋啲喎")])
                render.build_ass([segment], 1, directory / "sample.ass", design=settings)
                fonts.snapshot(directory / "fonts", {item["id"]})
                expected = {item["file"], fonts.resolve(fonts.default_id())[0].name}
                self.assertEqual({path.name for path in (directory / "fonts").iterdir()}, expected)
                result = subprocess.run([
                    config.ffmpeg(), "-nostdin", "-v", "info", "-f", "lavfi", "-i", "color=black:s=360x640:d=1",
                    "-vf", "subtitles=sample.ass:fontsdir=fonts", "-frames:v", "1", "-pix_fmt", "rgb24", "-f", "rawvideo", "pipe:1",
                ], cwd=directory, capture_output=True)
                log = result.stderr.decode("utf-8", "replace")
                self.assertEqual(result.returncode, 0, log)
                selected = postscript.get(item["file"], item["id"])
                self.assertRegex(log, rf"fontselect:.*-> .*{re.escape(selected)}(?:,|\s|$)")
                self.assertNotIn("failed to find any fallback", log)
                self.assertGreater(max(result.stdout), 200)
                pictures.add(result.stdout)
        self.assertEqual(len(pictures), len(builtin))
        self.assertEqual(list((self.root / "fonts").iterdir()), [])

    def test_english_metadata_is_used_instead_of_windows_question_marks(self):
        catalog = {font["id"]: font for font in fonts.catalog()}
        self.assertEqual(catalog["ZCOOLXiaoWei-Regular"]["family"], "ZCOOL XiaoWei")
        self.assertGreaterEqual(catalog["SourceHanSansCN-Heavy"]["weight"], 700)

    def test_ass_applies_caption_settings_and_escapes_user_commands_but_keeps_line_breaks(self):
        settings = self.design(text="{\\pos(0,0)}\n第二行", x=20, y=30)
        settings["subtitle"].update(x=25, y=65, font_id="ZCOOLKuaiLe-Regular", color="#00FF00")
        self.cfg["style"]["subtitle"].update(lines=2, max_chars_per_line=6)
        path = self.root / "video.ass"
        render.build_ass([render.Segment(Path("unused"), 0, 3, subs=[(0, 3, "这是需要换行显示的口播字幕")])], 3, path, design=settings)
        text = path.read_text(encoding="utf-8")
        self.assertIn(r"\pos(90,416)", text)
        self.assertIn(r"\fnZCOOL KuaiLe", text)
        self.assertIn(r"\c&H00FF00&", text)
        self.assertIn("｛＼pos(0,0)｝\\N第二行", text)
        self.assertIn(r"\N", text.split("Dialogue: 2,")[1])
        self.assertNotIn("＼N", text)

    def test_native_video_obeys_sticker_position_time_window_and_animation(self):
        settings = self.design(type="sticker", icon="arrow", text="", x=50, y=40, size=300,
                               color="#FF0000", animation="bounce", start=.3, end=1.4)
        settings["subtitle"]["enabled"] = False
        render.build_ass([render.Segment(Path("unused"), 0, 2)], 2, self.root / "video.ass", design=settings)
        fonts.snapshot(self.root / "fonts")
        output = self.root / "actual.mp4"
        result = subprocess.run([config.ffmpeg(), "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i", "color=black:s=360x640:r=24:d=2",
                                 "-vf", "subtitles=video.ass:fontsdir=fonts", "-an", "-c:v", "libx264", "-preset", "ultrafast", str(output)],
                                cwd=self.root, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr.decode(errors="replace"))
        frames = []
        with av.open(str(output)) as video:
            frames = [frame.to_ndarray(format="rgb24") for frame in video.decode(video=0)]
        def red_center(frame):
            mask = (frame[:, :, 0] > 160) & (frame[:, :, 1] < 60) & (frame[:, :, 2] < 60)
            y, x = np.where(mask)
            return (float(x.mean()), float(y.mean())) if len(x) else None
        self.assertIsNone(red_center(frames[0]))
        self.assertIsNone(red_center(frames[-1]))
        a, b = red_center(frames[10]), red_center(frames[19])
        self.assertIsNotNone(a)
        self.assertAlmostEqual(a[0], 180, delta=12)
        self.assertAlmostEqual(a[1], 256, delta=25)
        self.assertGreater(abs(a[1] - b[1]), 8)


if __name__ == "__main__":
    unittest.main()
