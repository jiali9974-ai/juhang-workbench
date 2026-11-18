import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from jh import cover, render


class RequiredMattingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_missing_primary_model_fails_without_calling_auxiliary_detectors(self):
        with patch.object(cover, "_bire", None), patch.object(cover.config, "data_root", return_value=self.root), \
             patch.object(cover, "_cfg", return_value={}), patch.object(cover, "_model") as auxiliary:
            with self.assertRaisesRegex(RuntimeError, "BiRefNet-portrait.*缺少权重"):
                cover._person_mask(np.zeros((32, 18, 3), np.uint8))
            auxiliary.assert_not_called()
            self.assertIsNone(cover._bire)

    def test_model_failure_stops_before_candidate_scan(self):
        with patch.object(cover, "_birefnet", side_effect=RuntimeError("primary model failed")), \
             patch.object(cover, "candidates") as scan:
            with self.assertRaisesRegex(RuntimeError, "primary model failed"):
                cover.make_best_cover([], ["标题"], self.root / "cover.png")
            scan.assert_not_called()

    def test_cover_model_failure_stops_video_encoding_and_records_error(self):
        script = {"batch": "项目", "id": "第一条", "cover": ["标题"]}
        with patch.object(render.config, "data_root", return_value=self.root / "data"), \
             patch.object(render.config, "output_root", return_value=self.root / "outputs"), \
             patch.object(render.config, "load", return_value={"render": {"cover": {"enabled": True}}}), \
             patch.object(render.scriptmod, "resolved_voice_mode", return_value="original"), \
             patch.object(render, "plan", return_value=[]), patch.object(render.look, "current", return_value={}), \
             patch.object(cover, "make_best_cover", side_effect=RuntimeError("主抠图模型不可用")), \
             patch.object(render, "compose_segments") as encode:
            with self.assertRaisesRegex(RuntimeError, "已停止出片.*主抠图模型不可用"):
                render.render(script)
            encode.assert_not_called()
        self.assertIn("主抠图模型不可用", (self.root / "data/renders/项目/第一条/cover_error.txt").read_text(encoding="utf-8"))
        self.assertFalse((self.root / "outputs/项目/第一条.mp4").exists())


if __name__ == "__main__":
    unittest.main()
