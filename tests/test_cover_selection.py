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
            "iris_horizontal": [.48, .52], "iris_vertical": [.47, .51], "iris_valid": True,
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
        for change, problem in [({"gaze_horizontal": .3, "iris_horizontal": [.8, .8]}, "眼神没有看向镜头"),
                                ({"gaze_vertical": .5, "iris_vertical": [.95, 1.1]}, "眼神没有看向镜头"),
                                ({"iris_horizontal": [.1, .8]}, "眼神没有看向镜头"),
                                ({"pose_yaw": 30}, "脸没有朝向镜头"),
                                ({"blink": .7}, "闭眼或眼睛状态不自然"),
                                ({"jaw_open": .5}, "张嘴说话或嘴型夸张")]:
            with self.subTest(change=change):
                self.assertIn(problem, cover_faces.problems(face(**change), self.ref))
        # 嘴角微扬时可以自然露齿；明显张嘴说话、夸张嘴型和抿嘴仍应排除。
        gentle = face(mar=.07, mouth_gap_max=.09, jaw_open=.10, smile_confidence=.45, smile_left=.47, smile_right=.45)
        self.assertTrue(cover_faces.smiling(gentle))
        self.assertEqual(cover_faces.problems(gentle, self.ref), [])
        self.assertIn("张嘴说话或嘴型夸张", cover_faces.problems(face(mar=.30, mouth_gap_max=.33, jaw_open=.4), self.ref))
        self.assertFalse(cover_faces.smiling(face(mouth_press=.8)))
        self.assertFalse(cover_faces.smiling(face(mouth_pucker=.7)))
        self.assertTrue(cover_faces.smiling(face(mouth_bright_ratio=.6, mar=.1)))
        self.assertEqual(cover_faces.problems(face(gaze_vertical=.28), self.ref), [])
        self.assertIn("眼神没有看向镜头", cover_faces.problems(face(iris_vertical=[.8, .82]), self.ref))
        self.assertIn("眼神没有看向镜头", cover_faces.problems(face(gaze_vertical=.28, iris_valid=False), self.ref))
        self.assertEqual(cover_faces.problems(face(gaze_horizontal=.18, iris_offset=.08, iris_valid=False), self.ref), [])
        self.assertIn("眼神没有看向镜头", cover_faces.problems(face(gaze_horizontal=.18, iris_offset=.17, iris_valid=False), self.ref))
        self.assertFalse(cover_faces.smiling(face(smile_confidence=.42, jaw_open=.35)))
        self.assertFalse(cover_faces.smiling(face(smile_confidence=.05, smile_left=.05, smile_right=.05)))

    def test_upturned_corners_allow_teeth_without_rewarding_a_bigger_smile(self):
        gentle = face(smile=.02, smile_confidence=.22, smile_left=.24, smile_right=.22)
        toothy = face(smile=.02, smile_confidence=.9, smile_left=.92, smile_right=.9,
                      mar=.18, mouth_gap_max=.21, jaw_open=.24, mouth_bright_ratio=.8)
        for candidate in (gentle, toothy):
            with self.subTest(candidate=candidate):
                self.assertTrue(cover_faces.smiling(candidate))
                self.assertEqual(cover_faces.problems(candidate, self.ref), [])
        self.assertEqual(cover.face_score(gentle, self.ref), cover.face_score(toothy, self.ref))
        for change in ({"smile": 0.}, {"smile": -.02}, {"frown": .3},
                       {"smile_left": .9, "smile_right": .22}):
            with self.subTest(change=change):
                self.assertFalse(cover_faces.smiling({**toothy, **change}))

    def test_camera_priority_uses_both_eyes_and_both_axes_before_smile_and_sharpness(self):
        direct = face(t=1., clip="a.mov", zoom=1., iris_horizontal=[.5, .5], iris_vertical=[.5, .5],
                      pose_yaw=0., pose_pitch=0., smile_confidence=.05, smile_left=.05, smile_right=.05, sharp=100.)
        for change in ({"iris_horizontal": [.5, .69]}, {"iris_vertical": [.5, .74]}):
            smile = face(t=2., clip="a.mov", zoom=1., pose_yaw=0., pose_pitch=0., sharp=500.,
                         iris_horizontal=[.5, .5], iris_vertical=[.5, .5])
            smile.update(change)
            with self.subTest(change=change):
                self.assertEqual(cover_faces.problems(smile, self.ref), [])
                self.assertGreater(cover.face_score(direct, self.ref), cover.face_score(smile, self.ref))
                with patch.object(cover, "candidates", return_value=([smile, direct], self.ref)):
                    self.assertEqual(cover.pick_frame([])[1], 1.)

    def test_clearer_frame_wins_when_gaze_and_smile_match(self):
        soft = face(t=1., clip="a.mov", zoom=1., sharp=100., stable_neighbors=2)
        clear = face(t=2., clip="a.mov", zoom=1., sharp=200., stable_neighbors=0)
        with patch.object(cover, "candidates", return_value=([soft, clear], self.ref)):
            self.assertEqual(cover.pick_frame([])[1], 2.)

    def test_glasses_do_not_hide_downward_or_sideways_gaze(self):
        # 来自高清复评的实际误选：虹膜点仍在眼眶范围内，但另一个证据确认视线偏开。
        cases = [
            {"pose_yaw": 10.17, "pose_pitch": 15.73, "gaze_horizontal": -.0048, "gaze_vertical": .189,
             "iris_horizontal": [.4672, .5597], "iris_vertical": [.3924, .4003]},
            {"pose_yaw": 9.62, "pose_pitch": 12.94, "gaze_horizontal": -.5204, "gaze_vertical": .3487,
             "iris_horizontal": [.5509, .6573], "iris_vertical": [.5255, .3522]},
            {"pose_yaw": 2.86, "pose_pitch": -1.39, "gaze_horizontal": -.1266, "gaze_vertical": .5261,
             "iris_horizontal": [.4682, .5633], "iris_vertical": [.4005, .3977]},
        ]
        for values in cases:
            with self.subTest(values=values):
                self.assertIn("眼神没有看向镜头", cover_faces.problems(face(**values), self.ref))
        direct = face(pose_yaw=.84, pose_pitch=1.81, gaze_horizontal=-.0579, gaze_vertical=.2711,
                      iris_horizontal=[.4489, .5477], iris_vertical=[.5108, .5559])
        self.assertEqual(cover_faces.problems(direct, self.ref), [])

    def test_true_smile_outranks_sharper_neutral_face_and_prefers_direct_gaze(self):
        neutral = face(t=1., clip="a.mov", zoom=1., smile_confidence=.05, smile_left=.05, smile_right=.05, sharp=500.)
        smile = face(t=2., clip="a.mov", zoom=1., sharp=150.)
        away = face(t=3., clip="a.mov", zoom=1., gaze_horizontal=.4, iris_horizontal=[.8, .8], smile_confidence=.95)
        with patch.object(cover, "candidates", return_value=([neutral, away, smile], self.ref)):
            self.assertEqual(cover.pick_frame([])[1], 2.)
        with patch.object(cover, "candidates", return_value=([away], self.ref)):
            self.assertEqual(cover.pick_frame([])[1], 3.)

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
        self.assertEqual(chosen["note"], "")
        self.assertEqual(chosen["mouth_policy"], "upturned_corners_teeth_allowed")

    def test_hd_smile_is_checked_before_falling_back_to_the_first_neutral_frame(self):
        raw_a = face(t=1., clip="a.mov", zoom=1.)
        raw_b = face(t=2., clip="a.mov", zoom=1., sharp=150.)
        neutral = face(smile_confidence=.03, smile_left=.03, smile_right=.03)
        smile = face(smile_confidence=.45, smile_left=.47, smile_right=.45)
        with patch.object(cover, "_birefnet"), patch.object(cover, "candidates", return_value=([raw_a, raw_b], self.ref)), \
             patch.object(cover, "_grab", return_value=np.zeros((16, 9, 3), np.uint8)), \
             patch.object(cover, "face_metrics", side_effect=[neutral, smile]), \
             patch.object(cover, "_person_mask", return_value=(np.ones((16, 9)), {"area": .3, "pose": True, "face_in": 1.})) as mask, \
             patch.object(cover, "compose"):
            cover.make_best_cover([], ["标题"], self.root / "cover.png", settings={})
        mask.assert_called_once()
        chosen = json.loads((self.root / "cover_check.json").read_text(encoding="utf-8"))["chosen"]
        self.assertEqual(chosen["t"], 2.)
        self.assertEqual(chosen["mode"], "smile")

    def test_camera_priority_applies_to_shortlist_and_hd_review(self):
        direct = face(t=1., clip="a.mov", zoom=1., iris_horizontal=[.5, .5], iris_vertical=[.5, .5],
                      pose_yaw=0., pose_pitch=0., smile_confidence=.05, smile_left=.05, smile_right=.05, sharp=100.)
        smile = face(t=2., clip="a.mov", zoom=1., iris_horizontal=[.5, .69], iris_vertical=[.5, .5],
                     pose_yaw=0., pose_pitch=0., sharp=500., mar=.18, mouth_gap_max=.21,
                     jaw_open=.24, mouth_bright_ratio=.8)
        for max_tries in (1, 12):
            with self.subTest(max_tries=max_tries), \
                 patch.object(cover, "_birefnet"), patch.object(cover, "candidates", return_value=([smile, direct], self.ref)), \
                 patch.object(cover, "_grab", return_value=np.zeros((16, 9, 3), np.uint8)), \
                 patch.object(cover, "face_metrics", side_effect=[direct, smile]), \
                 patch.object(cover, "_person_mask", return_value=(np.ones((16, 9)), {"area": .3, "pose": True, "face_in": 1.})) as mask, \
                 patch.object(cover, "compose"):
                cover.make_best_cover([], ["标题"], self.root / "cover.png", settings={}, max_tries=max_tries)
                record = json.loads((self.root / "cover_check.json").read_text(encoding="utf-8"))
                chosen = record["chosen"]
                self.assertEqual(chosen["t"], 1.)
                self.assertEqual(chosen["mode"], "natural")
                self.assertEqual(record["score_weights"], {"camera": 60., "smile": 30., "sharpness": 10.})
                self.assertAlmostEqual(sum(chosen["score_parts"].values()), chosen["score"], places=2)
                if max_tries > 1:
                    self.assertEqual(chosen["note"], "")
                mask.assert_called_once()

    def test_hd_clarity_is_compared_against_hd_frames_instead_of_coarse_reference(self):
        raw_a = face(t=1., clip="a.mov", zoom=1.)
        raw_b = face(t=2., clip="a.mov", zoom=1.)
        soft_hd, clear_hd = face(sharp=400.), face(sharp=800.)
        with patch.object(cover, "_birefnet"), patch.object(cover, "candidates", return_value=([raw_a, raw_b], self.ref)), \
             patch.object(cover, "_grab", return_value=np.zeros((16, 9, 3), np.uint8)), \
             patch.object(cover, "face_metrics", side_effect=[soft_hd, clear_hd]), \
             patch.object(cover, "_person_mask", return_value=(np.ones((16, 9)), {"area": .3, "pose": True, "face_in": 1.})), \
             patch.object(cover, "compose"):
            cover.make_best_cover([], ["标题"], self.root / "cover.png", settings={})
        record = json.loads((self.root / "cover_check.json").read_text(encoding="utf-8"))
        self.assertEqual(record["chosen"]["t"], 2.)
        self.assertGreater(record["tries"][1]["hd_score_parts"]["sharpness"], record["tries"][0]["hd_score_parts"]["sharpness"])

    def test_relaxed_smile_with_clearer_camera_gaze_outranks_intense_smile(self):
        gentle = face(smile_confidence=.3, smile_left=.32, smile_right=.3, gaze_horizontal=.03, pose_yaw=2., mar=.06)
        stronger = face(smile_confidence=.7, smile_left=.72, smile_right=.7, gaze_horizontal=.15, pose_yaw=6., mar=.12)
        self.assertTrue(cover_faces.smiling(gentle))
        self.assertTrue(cover_faces.smiling(stronger))
        self.assertEqual(cover_faces.problems(gentle, self.ref), [])
        self.assertEqual(cover_faces.problems(stronger, self.ref), [])
        self.assertGreater(cover.face_score(gentle, self.ref), cover.face_score(stronger, self.ref))

    def test_dense_scan_includes_smile_onset_and_end_instead_of_only_the_peak(self):
        rows = []
        for i, confidence in enumerate([.2, .5, .9, .9, .5, .2]):
            rows.append(face(t=1 + i * .2, clip="a.mov", zoom=1., smile_confidence=confidence,
                             smile_left=confidence, smile_right=confidence, mar=.20, jaw_open=.25))
        centers = cover._refinement_centers(rows, self.ref)
        self.assertIn(1., [m["t"] for m in centers])
        self.assertIn(2., [m["t"] for m in centers])

    def test_full_source_is_searched_even_when_selected_range_already_has_candidates(self):
        segment = SimpleNamespace(clip=Path("source.mov"), v_start=10., v_dur=3., zoom=1.)
        rows = [face(t=1., clip="source.mov", zoom=1.), face(t=11., clip="source.mov", zoom=1.)]
        with patch.object(cover, "_scan", return_value=rows) as scan, \
             patch("jh.media.probe", return_value=SimpleNamespace(duration=30.)):
            cover.candidates([segment])
        self.assertEqual(scan.call_args_list[0].args[:3], (Path("source.mov"), 0., 30.))

    def test_failed_hd_gaze_uses_best_available_instead_of_stopping(self):
        candidate = face(t=1., clip="a.mov", zoom=1.)
        with patch.object(cover, "_birefnet"), patch.object(cover, "candidates", return_value=([candidate], self.ref)), \
             patch.object(cover, "_grab", return_value=np.zeros((16, 9, 3), np.uint8)), \
             patch.object(cover, "face_metrics", return_value=face(gaze_horizontal=.6, iris_horizontal=[.8, .8])), \
             patch.object(cover, "_person_mask", return_value=(np.ones((16, 9)), {"area": .3, "pose": True, "face_in": 1.})) as mask, \
             patch.object(cover, "compose") as compose:
            cover.make_best_cover([], [], self.root / "cover.png", settings={})
        mask.assert_called_once()
        compose.assert_called_once()
        chosen = json.loads((self.root / "cover_check.json").read_text(encoding="utf-8"))["chosen"]
        self.assertEqual(chosen["selection_policy"], "best_available")
        self.assertEqual(chosen["note"], "")

    def test_fallback_prefers_natural_front_face_over_sharper_sideways_smile(self):
        front = face(t=1., clip="a.mov", zoom=1., pose_yaw=14., pose_pitch=5., sharp=100.,
                     smile_confidence=.05, smile_left=.05, smile_right=.05)
        side = face(t=2., clip="a.mov", zoom=1., pose_yaw=45., sharp=500.)
        with patch.object(cover, "candidates", return_value=([side, front], self.ref)):
            self.assertEqual(cover.pick_frame([])[1], 1.)

    def test_fallback_does_not_reward_a_half_closed_eye_in_exchange_for_a_slightly_straighter_head(self):
        closed = face(pose_yaw=6.53, pose_pitch=16.42, blink=.514, mar=.0338, gaze_vertical=.4274)
        open_eyes = face(pose_yaw=20.77, pose_pitch=-5.74, blink=.3298, mar=.0078, gaze_vertical=.209)
        self.assertGreater(cover_faces.fallback_score(open_eyes, self.ref), cover_faces.fallback_score(closed, self.ref))

    def test_fallback_front_gaze_outranks_a_sharp_downward_face(self):
        down = face(pose_yaw=.54, pose_pitch=24.83, sharp=1735.51, gaze_vertical=-.3441, blink=.0886)
        front = face(pose_yaw=-.48, pose_pitch=2.55, sharp=647.36, gaze_vertical=.3039, blink=.2296)
        ref = {**self.ref, "sharp": 1603.11}
        self.assertGreater(cover_faces.fallback_score(front, ref), cover_faces.fallback_score(down, ref))

    def test_failed_cutout_uses_selected_original_frame_and_still_saves_source(self):
        candidate = face(t=1., clip="a.mov", zoom=1., pose_yaw=14.)
        with patch.object(cover, "_birefnet"), patch.object(cover, "candidates", return_value=([candidate], self.ref)), \
             patch.object(cover, "_grab", return_value=np.zeros((16, 9, 3), np.uint8)), \
             patch.object(cover, "face_metrics", return_value=candidate), \
             patch.object(cover, "_person_mask", return_value=(np.zeros((16, 9)), {"area": .02, "face_in": .4, "pose": False})), \
             patch.object(cover, "compose") as compose, patch("jh.look_sources.save") as save:
            cover.make_best_cover([], ["标题"], self.root / "cover.png", settings={}, source_out=self.root / "raw.jpg")
        self.assertTrue(np.all(compose.call_args.args[1] == 1))
        save.assert_called_once()
        chosen = json.loads((self.root / "cover_check.json").read_text(encoding="utf-8"))["chosen"]
        self.assertEqual(chosen["composition"], "original_frame")

    def test_no_detected_face_compares_scene_frames_and_finishes_cover(self):
        rows = [{"clip": "a.mov", "t": 1., "zoom": 1., "sharp": 20., "scene": True},
                {"clip": "a.mov", "t": 2., "zoom": 1., "sharp": 80., "scene": True}]
        with patch.object(cover, "_birefnet"), patch.object(cover, "candidates", return_value=([], self.ref)), \
             patch.object(cover, "_scene_candidates", return_value=rows), \
             patch.object(cover, "_grab", return_value=np.zeros((16, 9, 3), np.uint8)), \
             patch.object(cover, "face_metrics", return_value=None), patch.object(cover, "_person_mask") as mask, \
             patch.object(cover, "compose") as compose:
            cover.make_best_cover([], ["标题"], self.root / "cover.png", settings={})
        mask.assert_not_called()
        compose.assert_called_once()
        chosen = json.loads((self.root / "cover_check.json").read_text(encoding="utf-8"))["chosen"]
        self.assertEqual((chosen["t"], chosen["mode"], chosen["composition"]), (2., "scene", "original_frame"))

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

    def test_cover_diagnostics_are_not_shown_in_output_list_and_are_deleted_with_video(self):
        video = self.root / "a.mp4"
        video.write_bytes(b"published-video")
        note = self.root / "a_封面选择.json"
        with patch.object(outputs.config, "output_root", return_value=self.root), patch.object(outputs.config, "data_root", return_value=self.root / "data"):
            self.assertNotIn("cover_note", outputs.list_outputs()[0])
            note.write_text('{"note":"没有微笑，采用自然表情"}', encoding="utf-8")
            self.assertNotIn("cover_note", outputs.list_outputs()[0])
            note.write_text("not-json")
            self.assertEqual(len(outputs.list_outputs()), 1)
            outputs.delete_output("", "a")
        self.assertFalse(note.exists())


if __name__ == "__main__":
    unittest.main()
