import subprocess
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
from PIL import Image

from jh import config, look, skin


class LookToneTests(unittest.TestCase):
    def ffmpeg(self, args, data=None):
        result = subprocess.run(
            [config.ffmpeg(), "-hide_banner", "-loglevel", "error", *args],
            input=data, capture_output=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8", "replace"))
        return result.stdout

    def test_new_settings_and_missing_sliders_default_to_fifty(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(config, "data_root", return_value=Path(folder)):
            settings = look.current()
            self.assertTrue(settings["enabled"])
            self.assertTrue(settings["normalize"])
            self.assertEqual([settings[key] for key in ("smooth", "tone", "sharpen")], [.5, .5, .5])
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

    def test_reference_grade_enriches_skin_and_blue_without_tinting_gray(self):
        patches = [(140, 100, 85), (150, 170, 190), (170, 125, 35), (128, 128, 128), (225, 225, 225), (0, 0, 0), (255, 255, 255)]
        image = np.repeat(np.array(patches, np.uint8), 32, axis=0)[None].repeat(32, axis=0)
        raw = self.ffmpeg(["-f", "rawvideo", "-pixel_format", "rgb24", "-video_size", "224x32", "-i", "pipe:0",
                           "-vf", look.filters(look.DEFAULTS)["tone"], "-frames:v", "1", "-pix_fmt", "rgb24", "-f", "rawvideo", "pipe:1"], image.tobytes())
        result = np.frombuffer(raw, np.uint8).reshape(image.shape)[16, 16::32].astype(int)
        skin, blue = result[:2]
        self.assertGreater(int(skin[0]), 175)
        self.assertGreater(int(skin[0] - skin[1]), 45)
        self.assertLess(int(skin[1] - skin[2]), 18)
        self.assertGreater(int(blue[2] - blue[0]), 48)
        gold = result[2]
        self.assertGreater(int(gold[1] - gold[2]), int(gold[0] - gold[1]))
        self.assertTrue((np.ptp(result[3:], axis=1) <= 1).all())
        self.assertLessEqual(int(result[-2].max()), 1)
        self.assertGreaterEqual(int(result[-1].min()), 254)

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
