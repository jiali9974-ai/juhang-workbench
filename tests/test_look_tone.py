import subprocess
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import cv2
from PIL import Image

from jh import config, grading, look, skin


class LookToneTests(unittest.TestCase):
    def ffmpeg(self, args, data=None):
        result = subprocess.run(
            [config.ffmpeg(), "-hide_banner", "-loglevel", "error", *args],
            input=data, capture_output=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8", "replace"))
        return result.stdout

    def test_tone_defaults_to_thirty_five_and_other_sliders_to_fifty(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(config, "data_root", return_value=Path(folder)):
            settings = look.current()
            self.assertTrue(settings["enabled"])
            self.assertTrue(settings["normalize"])
            self.assertEqual([settings[key] for key in ("smooth", "tone", "sharpen")], [.5, .35, .5])
            self.assertEqual(look.normalize({}), settings)
            custom = {**settings, "tone": .75, "sharpen": 0}
            look.save(custom)
            self.assertEqual(look.current(), custom)

    def test_grade_file_loads_from_directory_with_spaces_quotes_and_filter_punctuation(self):
        with tempfile.TemporaryDirectory(prefix="jh grade's [sample],") as folder, \
             patch.object(config, "data_root", return_value=Path(folder)):
            tone = look.filters(look.DEFAULTS)["tone"]
            self.ffmpeg(["-f", "lavfi", "-i", "color=gray:s=32x32:d=0.1", "-vf", tone,
                         "-frames:v", "1", "-f", "null", "-"])

    def test_grade_preserves_neutral_black_white_and_highlight_detail(self):
        # A complete legal luma ramp, with neutral and skin-like chroma patches.
        source = np.empty((3, 16, 220), dtype=np.uint8)
        source[0] = np.arange(16, 236, dtype=np.uint8)
        source[1, :8], source[2, :8] = 128, 128
        source[1, 8:], source[2, 8:] = 112, 146
        previous = source[0].astype(int)
        for strength in (.5, 1):
            with self.subTest(strength=strength):
                tone = look.filters({**look.DEFAULTS, "tone": strength})["tone"]
                raw = self.ffmpeg([
                    "-f", "rawvideo", "-pixel_format", "yuv444p", "-video_size", "220x16",
                    "-color_range", "tv", "-i", "pipe:0", "-vf", tone,
                    "-frames:v", "1", "-pix_fmt", "yuv444p", "-f", "rawvideo", "pipe:1",
                ], source.tobytes())
                result = np.frombuffer(raw, np.uint8).reshape(source.shape)
                np.testing.assert_allclose(result[1:, :8], 128, atol=1)
                neutral = result[0, :8]
                self.assertTrue((neutral[:, 0] == 16).all())
                self.assertTrue((neutral[:, -1] == 235).all())
                self.assertTrue((np.diff(neutral.astype(int), axis=1) >= 0).all())
                self.assertTrue((neutral[:, :-1] < 235).all())
                self.assertTrue((neutral[:, 30:].astype(int) >= previous[:8, 30:] - 1).all())
                self.assertGreater(int(result[0, 0, 77]) - int(source[0, 0, 77]), 10)
                previous = result[0].astype(int)

    def test_natural_grade_lifts_skin_without_recoloring_clothes_products_or_gray(self):
        patches = [(140, 100, 85), (150, 170, 190), (170, 125, 35), (128, 128, 128), (225, 225, 225), (0, 0, 0), (255, 255, 255)]
        image = np.repeat(np.array(patches, np.uint8), 32, axis=0)[None].repeat(32, axis=0)
        raw = self.ffmpeg(["-f", "rawvideo", "-pixel_format", "rgb24", "-video_size", "224x32", "-i", "pipe:0",
                           "-vf", look.filters(look.DEFAULTS)["tone"], "-frames:v", "1", "-pix_fmt", "rgb24", "-f", "rawvideo", "pipe:1"], image.tobytes())
        result = np.frombuffer(raw, np.uint8).reshape(image.shape)[16, 16::32].astype(int)
        skin, blue = result[:2]
        self.assertGreater(int(skin @ grading.LUMA), int(np.array(patches[0]) @ grading.LUMA) + 10)
        self.assertLess(int(skin @ grading.LUMA), int(np.array(patches[0]) @ grading.LUMA) + 25)
        before = cv2.cvtColor(np.array(patches[:3], np.float32)[None] / 255, cv2.COLOR_RGB2HSV)[0, :, 0]
        after = cv2.cvtColor(result[:3].astype(np.float32)[None] / 255, cv2.COLOR_RGB2HSV)[0, :, 0]
        np.testing.assert_allclose(after, before, atol=3)
        self.assertGreater(int(blue[2]), int(blue[1]))
        self.assertGreater(int(blue[1]), int(blue[0]))
        gold = result[2]
        self.assertGreater(int(gold[1] - gold[2]), int(gold[0] - gold[1]))
        self.assertTrue((np.ptp(result[3:], axis=1) <= 1).all())
        self.assertLessEqual(int(result[-2].max()), 1)
        self.assertGreaterEqual(int(result[-1].min()), 254)

    def test_zero_strength_is_identity_and_varied_skin_and_product_hues_survive(self):
        colors = np.array([(95, 67, 48), (170, 110, 92), (216, 168, 146),
                           (100, 145, 190), (160, 170, 220), (170, 125, 35),
                           (35, 80, 140), (30, 110, 65)], np.float32)[None] / 255
        np.testing.assert_allclose(grading.transform(colors, 0), colors, atol=1e-6)
        before = cv2.cvtColor(colors, cv2.COLOR_RGB2HSV)[0, :, 0]
        for strength in (.25, .5, 1):
            toned = grading.transform(colors, strength)
            after = cv2.cvtColor(toned, cv2.COLOR_RGB2HSV)[0, :, 0]
            distance = np.abs((after - before + 180) % 360 - 180)
            self.assertLess(float(distance.max()), .1)

    def test_parallel_lut_publisher_can_reuse_complete_file_opened_by_another_reader(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(config, "data_root", return_value=Path(folder)):
            expected = grading.lut_file(.5)
            data = expected.read_bytes()
            # The competing file appears after our initial cache check; Windows refuses replacement while read.
            with patch.object(Path, "is_file", side_effect=[False, True]), \
                 patch.object(Path, "replace", side_effect=PermissionError("reader holds target")):
                self.assertEqual(grading.lut_file(.5), expected)
            self.assertEqual(expected.read_bytes(), data)

    def test_bt709_video_keeps_its_colors_through_the_still_preview_pipeline(self):
        patches = [(187, 131, 122), (171, 187, 241), (128, 128, 128)]
        image = np.repeat(np.array(patches, np.uint8), 32, axis=0)[None].repeat(64, axis=0)
        with tempfile.TemporaryDirectory() as folder:
            video = Path(folder) / "bt709.mkv"
            self.ffmpeg(["-f", "rawvideo", "-pixel_format", "rgb24", "-video_size", "96x64", "-i", "pipe:0",
                         "-vf", "scale=out_color_matrix=bt709:out_range=tv,format=yuv420p", "-colorspace", "bt709",
                         "-color_range", "tv", "-frames:v", "1", "-c:v", "ffv1", str(video)], image.tobytes())
            png = skin.still(["-i", str(video)], ["-f", "image2pipe", "-vcodec", "png", "-"], 96, 64, 0)
        result = np.asarray(Image.open(io.BytesIO(png)).convert("RGB"))[32, 16::32]
        np.testing.assert_allclose(result, patches, atol=3)

    def test_full_range_jpeg_stays_neutral_while_midtones_brighten(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "neutral.jpg"
            levels = [0, 64, 128, 192, 240, 255]
            image = np.repeat(np.array(levels, dtype=np.uint8), 32)
            image = np.broadcast_to(image[None, :, None], (32, 192, 3)).copy()
            Image.fromarray(image).save(path, quality=100, subsampling=0)
            for strength in (.5, 1):
                with self.subTest(strength=strength):
                    tone = look.filters({**look.DEFAULTS, "tone": strength})["tone"]
                    raw = self.ffmpeg([
                        "-i", str(path), "-vf", tone, "-frames:v", "1",
                        "-pix_fmt", "rgb24", "-f", "rawvideo", "pipe:1",
                    ])
                    result = np.frombuffer(raw, np.uint8).reshape(image.shape)
                    samples = result[16, 16::32].astype(int)
                    self.assertLessEqual(int(np.ptp(samples, axis=1).max()), 1)
                    self.assertLessEqual(int(samples[0].max()), 1)
                    self.assertGreaterEqual(int(samples[-1].min()), 254)
                    self.assertGreater(int(samples[2, 0]), 138)
                    self.assertLess(int(samples[-2, 0]), int(samples[-1, 0]))


if __name__ == "__main__":
    unittest.main()
