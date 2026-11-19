import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

from jh import config, cover, cover_faces, outputs


def face(**changes):
    return {"ear": .28, "ear_diff": .04, "blink": .1, "mar": .01, "jaw_open": .02, "smile": .04,
            "mouth_gap_max": .02, "mouth_bright_ratio": 0.,
            "smile_confidence": .6, "smile_left": .63, "smile_right": .6, "frown": 0.,
            "pose_yaw": 2., "pose_pitch": 5., "roll": 2., "gaze_horizontal": .05, "gaze_vertical": .04,
            "gaze_eye_max": .1, "iris_offset": .08, "sharp": 200., "fw": .25, "cx": .5, "cy": .32, "top": .2,
            "oval": [[2, 2], [8, 2], [8, 8], [2, 8]], **changes}


class CoverSelectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.ref = {"ear": .3, "sharp": 200.}

    def test_camera_facing_smile_is_qualified_but_head_direction_alone_is_not_enough(self):
        self.assertEqual(cover_faces.problems(face(), self.ref), [])
        self.assertTrue(cover_faces.smiling(face()))
        for change, problem in [({"gaze_horizontal": .3}, "眼神没有看向镜头"),
                                ({"gaze_vertical": .5}, "眼神没有看向镜头"),
                                ({"iris_offset": .3}, "眼神没有看向镜头"),
                                ({"pose_yaw": 30}, "脸没有朝向镜头"),
                                ({"blink": .7}, "闭眼或眼睛状态不自然"),
                                ({"jaw_open": .5}, "嘴唇未闭合或可见牙齿")]:
            with self.subTest(change=change):
                self.assertIn(problem, cover_faces.problems(face(**change), self.ref))
        # 即使微笑分很高，也不能选露牙或张嘴的帧。
        self.assertIn("嘴唇未闭合或可见牙齿", cover_faces.problems(face(mar=.20, jaw_open=.23), self.ref))
        self.assertFalse(cover_faces.smiling(face(mar=.18, smile_confidence=.9)))
        self.assertFalse(cover_faces.smiling(face(mouth_gap_max=.08)))
        self.assertFalse(cover_faces.smiling(face(mouth_bright_ratio=.4)))
        self.assertEqual(cover_faces.problems(face(gaze_horizontal=.18, iris_offset=.08), self.ref), [])
        self.assertIn("眼神没有看向镜头", cover_faces.problems(face(gaze_horizontal=.18, iris_offset=.17), self.ref))
        self.assertFalse(cover_faces.smiling(face(smile_confidence=.42, jaw_open=.25)))
        self.assertFalse(cover_faces.smiling(face(smile_confidence=.05, smile_left=.05, smile_right=.05)))

    def test_true_smile_outranks_sharper_neutral_face_and_looking_away_is_never_selected(self):
        neutral = face(t=1., clip="a.mov", zoom=1., smile_confidence=.05, smile_left=.05, smile_right=.05, sharp=500.)
        smile = face(t=2., clip="a.mov", zoom=1., sharp=150.)
        away = face(t=3., clip="a.mov", zoom=1., gaze_horizontal=.4, smile_confidence=.95)
        with patch.object(cover, "candidates", return_value=([neutral, away, smile], self.ref)):
            self.assertEqual(cover.pick_frame([])[1], 2.)
        with patch.object(cover, "candidates", return_value=([away], self.ref)):
            with self.assertRaisesRegex(RuntimeError, "没有看向镜头"):
                cover.pick_frame([])

    def test_natural_face_fallback_has_explicit_note_and_only_passed_face_is_matted(self):
        seg = SimpleNamespace(clip=self.root / "a.mov")
        candidate = face(t=2., clip=str(seg.clip), zoom=1., smile_confidence=.05, smile_left=.05, smile_right=.05)
        image = np.zeros((16, 9, 3), np.uint8)
        with patch.object(cover, "_birefnet"), patch.object(cover, "candidates", return_value=([candidate], self.ref)), \
             patch.object(cover, "_grab", return_value=image), patch.object(cover, "face_metrics", return_value=candidate), \
             patch.object(cover, "_person_mask", return_value=(np.ones((16, 9)), {"area": .3, "pose": True, "face_in": 1.})) as mask, \
             patch.object(cover, "compose"):
            cover.make_best_cover([seg], ["标题"], self.root / "cover.png", settings={})
        mask.assert_called_once()
        chosen = json.loads((self.root / "cover_check.json").read_text(encoding="utf-8"))["chosen"]
        self.assertEqual(chosen["mode"], "natural")
        self.assertIn("未找到看向镜头且不露齿微笑", chosen["note"])
        self.assertEqual(chosen["mouth_policy"], "closed_lip")

    def test_failed_hd_face_does_not_get_composited_or_matted(self):
        candidate = face(t=1., clip="a.mov", zoom=1.)
        with patch.object(cover, "_birefnet"), patch.object(cover, "candidates", return_value=([candidate], self.ref)), \
             patch.object(cover, "_grab", return_value=np.zeros((16, 9, 3), np.uint8)), \
             patch.object(cover, "face_metrics", return_value=face(gaze_horizontal=.6)), \
             patch.object(cover, "_person_mask") as mask, patch.object(cover, "compose") as compose:
            with self.assertRaisesRegex(RuntimeError, "未找到看向镜头"):
                cover.make_best_cover([], [], self.root / "cover.png", settings={})
        mask.assert_not_called()
        compose.assert_not_called()

    def test_original_pts_extracts_the_same_frame_after_sampling(self):
        path = self.root / "timing.mkv"
        result = subprocess.run([config.ffmpeg(), "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i", "color=black:s=96x160:r=12:d=1.2",
                                 "-vf", "format=rgb24,geq=r='N*16':g=0:b=0", "-c:v", "ffv1", str(path)], capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr.decode(errors="replace"))
        with patch.object(cover, "face_metrics", side_effect=lambda image: {"red": float(image[:, :, 2].mean())}):
            samples = cover._scan(path, .13, .9, 1., .2)
        self.assertGreaterEqual(len(samples), 3)
        for sample in samples[:3]:
            image = cover._grab(path, sample["t"], 1., 540, 960)
            self.assertAlmostEqual(float(image[:, :, 2].mean()), sample["red"], delta=3)
        # 视频比音频晚开始时，仍按文件播放时间定位，不能把视频流起点当成零。
        offset = self.root / "offset.mkv"
        result = subprocess.run([config.ffmpeg(), "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i", "anullsrc=r=48000:cl=mono",
                                 "-itsoffset", "0.25", "-i", str(path), "-map", "1:v", "-map", "0:a", "-c:v", "copy", "-c:a", "pcm_s16le", "-t", "1.5", str(offset)], capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr.decode(errors="replace"))
        with patch.object(cover, "face_metrics", side_effect=lambda image: {"red": float(image[:, :, 2].mean())}):
            delayed = cover._scan(offset, .13, .9, 1., .2)
        self.assertGreaterEqual(delayed[0]["t"], .249)
        for sample in delayed[:3]:
            image = cover._grab(offset, sample["t"], 1., 540, 960)
            self.assertAlmostEqual(float(image[:, :, 2].mean()), sample["red"], delta=3)

    def test_cover_note_does_not_hide_video_when_metadata_is_missing_or_corrupt_and_is_deleted_with_it(self):
        video = self.root / "a.mp4"
        video.write_bytes(b"published-video")
        note = self.root / "a_封面选择.json"
        with patch.object(outputs.config, "output_root", return_value=self.root), patch.object(outputs.config, "data_root", return_value=self.root / "data"):
            self.assertNotIn("cover_note", outputs.list_outputs()[0])
            note.write_text('{"note":"没有微笑，采用自然表情"}', encoding="utf-8")
            self.assertIn("没有微笑", outputs.list_outputs()[0]["cover_note"])
            note.write_text("not-json")
            self.assertEqual(len(outputs.list_outputs()), 1)
            outputs.delete_output("", "a")
        self.assertFalse(note.exists())


if __name__ == "__main__":
    unittest.main()
