import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
from PIL import Image

from jh import config, look


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

    def test_brightening_preserves_chroma_black_white_and_highlight_detail(self):
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
                np.testing.assert_array_equal(result[1:], source[1:])
                self.assertTrue((result[0, :, 0] == 16).all())
                self.assertTrue((result[0, :, -1] == 235).all())
                self.assertTrue((np.diff(result[0].astype(int), axis=1) >= 0).all())
                self.assertTrue((result[0, :, :-1] < 235).all())
                self.assertTrue((result[0].astype(int) >= previous).all())
                self.assertGreater(int(result[0, 0, 77]) - int(source[0, 0, 77]), 10)
                previous = result[0].astype(int)

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
