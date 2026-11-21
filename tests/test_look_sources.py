import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
from PIL import Image
from fastapi.testclient import TestClient

import app as server
from jh import config, cover, look, look_sources, normalize


class LookSourceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        ffmpeg = config.ffmpeg()
        settings = {"render": {"width": 180, "height": 320, "talk_zoom": 1.0, "product_zoom": 1.0}, "paths": {"ffmpeg": ffmpeg}}
        for target, value in [("ROOT", self.root), ("data_root", lambda: self.root / "data"),
                              ("output_root", lambda: self.root / "outputs"),
                              ("material_root", lambda: self.root / "materials"), ("load", lambda: settings)]:
            replacement = patch.object(config, target, value)
            replacement.start()
            self.addCleanup(replacement.stop)
        (self.root / "assets").mkdir()
        Image.new("RGB", (180, 320), (80, 90, 110)).save(self.root / "assets" / "beauty-default.jpg")
        self.client = TestClient(server.app)
        self.off = {"enabled": False}

    def video(self, batch="项目", sid="成片"):
        folder = self.root / "outputs" / batch
        folder.mkdir(parents=True, exist_ok=True)
        (folder / f"{sid}.mp4").write_bytes(b"completed")
        return {"batch": batch, "id": sid}

    def preview(self, source, settings=None):
        return self.client.post("/api/look/preview", json={"source": source, "kind": "face", "settings": settings or self.off})

    def test_default_works_without_projects_or_outputs_and_disabled_is_identical(self):
        response = self.preview(None)
        self.assertEqual(response.status_code, 200, response.text)
        result = response.json()
        self.assertEqual((result["source"], result["fallback"]), ("default", False))
        original = self.client.get(f"/api/look/file/{result['original']}")
        beauty = self.client.get(f"/api/look/file/{result['beauty']}")
        self.assertEqual(original.status_code, 200)
        self.assertEqual(original.content, beauty.content)
        self.assertFalse((self.root / "materials").exists())

    def test_legacy_interface_reads_default_image_without_a_material_project(self):
        cache = look_sources.install_legacy_default()
        frames = json.loads(cache.read_text(encoding="utf-8"))
        self.assertEqual(frames["face"][0]["clip"], str((self.root / "data" / "preview" / "look" / "legacy-default.mp4").resolve()))
        result = look.preview("", "watch", self.off)
        self.assertTrue((look._preview_dir() / result["original"]).is_file())
        self.assertTrue((look._preview_dir() / result["beauty"]).is_file())
        self.assertFalse((self.root / "materials").exists())

    def test_completed_cover_source_survives_missing_material_and_is_not_composited_cover(self):
        selected = self.video()
        raw = look_sources.cover_source_path(**{"batch": selected["batch"], "sid": selected["id"]})
        Image.new("RGB", (180, 320), (160, 45, 30)).save(raw)
        Image.new("RGB", (180, 320), (10, 200, 240)).save(raw.with_name("成片_封面.jpg"))
        response = self.preview(selected)
        self.assertEqual(response.status_code, 200, response.text)
        result = response.json()
        self.assertEqual((result["source"], result["fallback"]), ("cover", False))
        image = np.asarray(Image.open(look._preview_dir() / result["original"]))
        self.assertGreater(float(image[:, :, 0].mean()), 150)
        self.assertLess(float(image[:, :, 1].mean()), 50)

    def test_tone_changes_real_pixels_and_repeated_preview_reuses_files(self):
        settings = {"enabled": True, "normalize": False, "smooth": 0, "tone": 1, "sharpen": 0}
        with patch.object(look, "_ff", wraps=look._ff) as ffmpeg:
            first = self.preview(None, settings).json()
            second = self.preview(None, settings).json()
            self.assertEqual(first, second)
            self.assertEqual(ffmpeg.call_count, 2)
        original = np.asarray(Image.open(look._preview_dir() / first["original"]), dtype=float)
        beauty = np.asarray(Image.open(look._preview_dir() / first["beauty"]), dtype=float)
        self.assertGreater(float(np.abs(beauty - original).mean()), 10)

    def test_changed_filter_invalidates_preview_even_when_sliders_stay_the_same(self):
        settings = {"enabled": True, "normalize": False, "smooth": 0, "tone": .5, "sharpen": 0}
        with patch.object(look, "_ff", wraps=look._ff) as ffmpeg:
            first = self.preview(None, settings).json()
            effects = {**look.filters(settings), "tone": "eq=brightness=0.03"}
            with patch.object(look, "filters", return_value=effects):
                second = self.preview(None, settings).json()
            self.assertEqual(first["original"], second["original"])
            self.assertNotEqual(first["beauty"], second["beauty"])
            self.assertEqual(ffmpeg.call_count, 3)

    def test_saved_jpeg_uses_video_range_before_applying_saved_lighting_correction(self):
        selected = self.video()
        raw = look_sources.cover_source_path(selected["batch"], selected["id"])
        Image.new("RGB", (180, 320), (50, 50, 50)).save(raw, quality=100)
        raw.with_suffix(".json").write_text(json.dumps({"normalization": "lutyuv=y='16+2*(val-16)':u=val:v=val",
            "normalization_policy": normalize.policy_key()}), encoding="utf-8")
        settings = {"enabled": True, "normalize": True, "smooth": 0, "tone": 0, "sharpen": 0}
        response = self.preview(selected, settings)
        self.assertEqual(response.status_code, 200, response.text)
        image = np.asarray(Image.open(look._preview_dir() / response.json()["beauty"]), dtype=float)
        # 黑点不变的曝光翻倍：RGB 50 应到约 100，而不是把 JPEG 数值当作 16–235 得到偏暗结果。
        np.testing.assert_allclose(image[100, 100], 100, atol=2)

    def test_old_video_without_original_falls_back_honestly_and_invalid_sources_are_rejected(self):
        result = self.preview(self.video()).json()
        self.assertEqual((result["source"], result["fallback"]), ("default", True))
        self.assertEqual(self.preview({"batch": "项目", "id": "missing"}).status_code, 404)
        self.assertEqual(self.preview({"batch": "..", "id": "secret"}).status_code, 400)
        self.assertEqual(self.preview({"batch": "项目", "id": "../secret"}).status_code, 400)
        self.assertEqual(self.preview("invalid").status_code, 400)
        with patch.object(server.jobs, "list", return_value=[{"status": "running", "title": "成片 出片"}]):
            self.assertEqual(self.preview({"batch": "项目", "id": "成片"}).status_code, 400)

    def test_old_cover_recovers_exact_selected_time_and_then_uses_saved_original(self):
        selected = self.video()
        clip = self.root / "materials" / "项目" / "原片.MOV"
        clip.parent.mkdir(parents=True)
        clip.touch()
        record = self.root / "data" / "renders" / "项目" / "成片" / "cover_check.json"
        record.parent.mkdir(parents=True)
        record.write_text(json.dumps({"chosen": {"clip": clip.name, "t": 4.68, "zoom": 1.1}}), encoding="utf-8")

        def save_image(clip, t, zoom, destination):
            Image.new("RGB", (180, 320), "red").save(destination)
            destination.with_suffix(".json").write_text(json.dumps({"normalization": "eq=brightness=0.03",
                "normalization_policy": normalize.policy_key()}), encoding="utf-8")

        with patch.object(look_sources, "save", side_effect=save_image) as save:
            first = look_sources.resolve(selected)
            save.assert_called_once_with(clip.resolve(), 4.68, 1.1, first.image)
            clip.unlink()
            self.assertEqual(look_sources.resolve(selected), first)
            self.assertEqual(first.normalization, "eq=brightness=0.03")
            self.assertEqual(save.call_count, 1)

    def test_new_cover_saves_the_chosen_frame_before_cutout_with_exact_zoom(self):
        seg = SimpleNamespace(clip=self.root / "source.MOV", v_start=1.2, v_dur=6, zoom=1.05)
        destination = self.root / "cover.png"
        source_out = self.root / "raw.jpg"
        frame = np.zeros((320, 180, 3), dtype=np.uint8)
        candidate = {"clip": str(seg.clip), "t": 3.75, "zoom": 1.15}
        with patch.object(cover, "_birefnet", return_value=object()), \
             patch.object(cover, "candidates", return_value=([candidate], {"ear": .3})), \
             patch.object(cover, "face_problems", return_value=[]), patch.object(cover, "face_score", return_value=1), \
             patch.object(cover, "face_metrics", return_value={}), patch.object(cover, "_grab", return_value=frame), \
             patch.object(cover, "_person_mask", return_value=(np.zeros((320, 180)), {})), \
             patch.object(cover, "mask_problems", return_value=[]), patch.object(cover, "compose"), \
             patch.object(look_sources, "save") as save:
            cover.make_best_cover([seg], ["标题"], destination, settings=self.off, source_out=source_out)
        save.assert_called_once_with(seg.clip, 3.75, 1.15, source_out)
        chosen = json.loads(destination.with_name("cover_check.json").read_text(encoding="utf-8"))["chosen"]
        self.assertEqual((chosen["t"], chosen["zoom"]), (3.75, 1.15))

    def test_unreadable_source_does_not_publish_an_arbitrary_frame(self):
        seg = SimpleNamespace(clip=self.root / "source.MOV", v_start=2.2, v_dur=.8, zoom=1.05)
        destination = self.root / "cover.png"
        source_out = self.root / "raw.jpg"
        with patch.object(cover, "_birefnet", return_value=object()), \
             patch.object(cover, "candidates", return_value=([], {})), patch.object(cover, "_scene_candidates", return_value=[]), \
             patch.object(look_sources, "save") as save:
            with self.assertRaisesRegex(RuntimeError, "没有可读取的封面画面"):
                cover.make_best_cover([seg], [], destination, settings=self.off, source_out=source_out)
        save.assert_not_called()
        record = json.loads(destination.with_name("cover_check.json").read_text(encoding="utf-8"))
        self.assertNotIn("chosen", record)

    def test_saved_source_has_no_beauty_and_keeps_lighting_for_future_previews(self):
        clip, destination = self.root / "source.MOV", self.root / "saved.jpg"
        frame = np.full((320, 180, 3), [30, 45, 160], dtype=np.uint8)
        with patch.object(cover, "_grab", return_value=frame) as grab, \
             patch.object(normalize, "segment_filter", return_value="eq=brightness=0.03"):
            look_sources.save(clip, 3.75, 1.15, destination)
        grab.assert_called_once_with(clip, 3.75, 1.15, 180, 320, settings=None)
        saved = np.asarray(Image.open(destination))
        self.assertGreater(float(saved[:, :, 0].mean()), 150)
        self.assertEqual(look_sources._read(destination, "cover").normalization, "eq=brightness=0.03")

    def test_old_saved_fixed_skin_correction_is_recomputed_from_the_original_image(self):
        image = self.root / "assets" / "beauty-default.jpg"
        image.with_suffix(".json").write_text(json.dumps({"normalization": "eq=brightness=0.5"}), encoding="utf-8")
        with patch.object(normalize, "still_filter", return_value="eq=brightness=0.03") as recompute:
            source = look_sources._read(image, "default")
        recompute.assert_called_once_with(image)
        self.assertEqual(source.normalization, "eq=brightness=0.03")


if __name__ == "__main__":
    unittest.main()
