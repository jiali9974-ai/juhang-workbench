import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from jh import normalize


class ExposureTests(unittest.TestCase):
    def setUp(self):
        self.cfg = {"enabled": True, "exposure_range": [.47, .55], "max_ratio": 1.5, "wb": .04}

    def face(self, rgb, neutral=None, count=3):
        return {"skin": rgb, "faces": count, "neutral": neutral}

    def test_correctly_exposed_different_skin_colors_are_not_forced_to_one_rgb(self):
        for rgb in ([183, 113, 90], [165, 124, 108], [174, 129, 101]):
            c = normalize.correction(self.face(rgb), self.cfg)
            self.assertEqual(c["wb"], (1., 1., 1.))
            self.assertEqual(c["mid"][0], c["mid"][1])
            self.assertEqual(normalize.to_filter(c), "")

    def test_dark_and_bright_faces_are_corrected_with_limited_exposure(self):
        for rgb, direction in [([95, 65, 55], 1), ([230, 185, 160], -1)]:
            c = normalize.correction(self.face(rgb), self.cfg)
            m, t = c["mid"]
            self.assertGreater(direction * (t - m), 0)
            self.assertLessEqual(max(t / m, m / t), 1.501)
            self.assertTrue(.8 <= c["k"] <= 1.25)

    def test_white_balance_depends_on_neutral_scene_instead_of_person_skin(self):
        a = normalize.correction(self.face([180, 110, 85], [200, 195, 185]), self.cfg)
        b = normalize.correction(self.face([160, 125, 110], [200, 195, 185]), self.cfg)
        self.assertEqual(a["wb"], b["wb"])
        self.assertTrue(all(.96 <= v <= 1.04 for v in a["wb"]))

    def test_single_uncertain_face_does_not_set_video_exposure(self):
        self.assertIsNone(normalize.correction(self.face([80, 60, 45], count=1), self.cfg))
        c = normalize.correction(self.face([80, 60, 45], count=1), self.cfg, min_faces=1)
        self.assertEqual(c["source"], "face")

    def test_product_segment_never_borrows_face_exposure_from_the_rest_of_the_clip(self):
        segment = {"skin": None, "faces": 0, "neutral": None}
        whole = {"skin": [70, 45, 30], "faces": 5, "neutral": [195, 195, 195]}
        with patch.object(normalize, "segment_profile", return_value=segment), \
             patch.object(normalize, "clip_profile", return_value=whole), \
             patch.object(normalize, "_cfg", return_value=self.cfg):
            self.assertEqual(normalize.segment_filter(Path("watch.mov"), 10, 3), "")

    def test_face_frame_also_supplies_neutral_white_balance(self):
        normalize.segment_profile.cache_clear()
        self.addCleanup(normalize.segment_profile.cache_clear)
        with patch.object(normalize, "grab", return_value=np.zeros((16, 16, 3), np.uint8)), \
             patch.object(normalize, "skin", return_value={"rgb": [170, 125, 110]}), \
             patch.object(normalize, "neutral", return_value=[195, 190, 185]):
            prof = normalize.segment_profile("source.mov", 0, 4)
        self.assertEqual(prof["faces"], 5)
        self.assertEqual(prof["neutral"], [195., 190., 185.])

    def test_old_profile_without_face_frame_neutrals_is_remeasured(self):
        normalize.clip_profile.cache_clear()
        self.addCleanup(normalize.clip_profile.cache_clear)
        with tempfile.TemporaryDirectory() as folder:
            cache = Path(folder) / "profile.json"
            cache.write_text(json.dumps({"skin": [110, 80, 60], "faces": 10, "neutral": None}))
            with patch.object(normalize, "_cache_file", return_value=cache), \
                 patch("jh.media.probe") as probe, \
                 patch.object(normalize, "grab", return_value=np.zeros((16, 16, 3), np.uint8)), \
                 patch.object(normalize, "skin", return_value={"rgb": [170, 125, 110]}), \
                 patch.object(normalize, "neutral", return_value=[195, 190, 185]):
                probe.return_value.duration = 3
                prof = normalize.clip_profile("source.mov")
            self.assertEqual(prof["version"], normalize.PROFILE_VERSION)
            self.assertEqual(prof["neutral"], [195., 190., 185.])


if __name__ == "__main__":
    unittest.main()
