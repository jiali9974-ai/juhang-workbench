import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from jh import asr, cancellation, config, look, media, opening, render, speech_timing


SR = 48000


def voice_audio(duration=3):
    audio = np.zeros((round(duration * SR), 2), np.float32)
    for start, end, amplitude in ((0, 1, .01), (.55, .58, .5), (1.64, 1.70, .035), (1.70, duration, .3)):
        a, b = round(start * SR), round(end * SR)
        audio[a:b] = (amplitude * np.sin(2 * np.pi * 220 * np.arange(b - a) / SR))[:, None]
    return audio


def source_segment(start=0, duration=3):
    return render.Segment(Path("source.mov"), start, duration, zoom=1,
                          a_dur=duration - .2, v_content_dur=duration - .2,
                          subs=[(0, 2.5, "当年涨得有多凶"), (2.5, duration - .2, "现在跌得惨")],
                          speech_spans=[(1.8, 2.1)],
                          source_lines=[{"id": 0, "ref": "C1-S1", "text": "当年涨得有多凶", "lang": "zh",
                                         "start": start, "end": start + duration,
                                         "words": [["当", start, start + 1.8], ["年", start + 1.8, start + 2.1],
                                                   ["涨", start + 2.1, start + 2.3]]}])


class OpeningTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.cfg = copy.deepcopy(config.load())
        self.cfg["render"].update(opening_cut={"enabled": True, "max_lead": .1, "search_seconds": 5},
                                  width=90, height=160, fps=60, encoder="libx264",
                                  segment_gap={"first_lead": .02})
        for target, value in (("load", self.cfg), ("data_root", self.root)):
            context = patch.object(config, target, return_value=value)
            context.start()
            self.addCleanup(context.stop)
        self.vad = patch.object(speech_timing, "detect", return_value=[(0, 1), (1.3, 3)])
        self.vad.start()
        self.addCleanup(self.vad.stop)
        context = patch.object(asr, "recognize_audio", return_value="当年涨得有多凶")
        self.recognize = context.start()
        self.addCleanup(context.stop)

    def trim(self, seg=None, audio=None):
        report = {}
        result = opening.trim(seg or source_segment(), lambda *args: voice_audio() if audio is None else audio,
                              report=report)
        return result, report

    def test_prepare_noise_and_false_vad_do_not_delay_the_first_word(self):
        trimmed, report = self.trim()
        self.assertAlmostEqual(trimmed.v_start, 1.62, delta=.01)
        self.assertLessEqual(report["core_start"], .1)
        self.assertEqual(report["expected_prefix"], "当年")
        self.assertEqual(report["status"], "ready")
        self.assertLessEqual(len(self.recognize.call_args.args[0]), SR)

    def test_picture_audio_subtitles_and_padding_move_together(self):
        seg = source_segment(start=10)
        seg.audio_wav = self.root / "voice.wav"
        seg.a_start = 5
        trimmed, report = self.trim(seg)
        cut = report["trimmed_seconds"]
        self.assertEqual(trimmed.v_start, round(10 + cut, 3))
        self.assertEqual(trimmed.a_start, round(5 + cut, 3))
        self.assertEqual(trimmed.v_dur, round(3 - cut, 3))
        self.assertEqual(trimmed.a_dur, round(2.8 - cut, 3))
        self.assertEqual(trimmed.v_content_dur, round(2.8 - cut, 3))
        self.assertEqual(trimmed.subs[0], (0, round(2.5 - cut, 3), "当年涨得有多凶"))
        self.assertEqual(trimmed.source_lines, seg.source_lines)
        self.assertGreater(trimmed.v_start, seg.v_start)

    def test_trusted_first_word_already_at_start_needs_no_new_recognition(self):
        seg = source_segment()
        seg.source_lines[0]["words"] = [["当", .02, .3], ["年", .3, .5]]
        result, report = self.trim(seg)
        self.assertIs(result, seg)
        self.assertEqual(report["method"], "trusted_word_time")
        self.recognize.assert_not_called()

    def test_legitimate_long_first_word_with_continuous_voice_is_not_cut(self):
        audio = np.full((3 * SR, 2), .2, np.float32)
        result, report = self.trim(audio=audio)
        self.assertEqual(result.v_start, 0)
        self.assertEqual(report["trimmed_seconds"], 0)
        self.assertEqual(report["expected_prefix"], "当")

    def test_failed_local_prefix_check_rejects_cut_and_records_reason(self):
        self.recognize.return_value = "年涨得有多凶"
        report = {}
        with self.assertRaisesRegex(ValueError, "首字复核" ):
            opening.trim(source_segment(), lambda *args: voice_audio(), report=report)
        self.assertEqual(report["status"], "rejected")
        self.assertEqual(report["trimmed_seconds"], 0)

    def test_no_speech_or_no_word_timing_does_not_pass_as_ready(self):
        report = {}
        with self.assertRaisesRegex(ValueError, "开口"):
            opening.trim(source_segment(), lambda *args: np.zeros((3 * SR, 2), np.float32), report=report)
        self.assertEqual(report["status"], "rejected")
        with self.assertRaisesRegex(ValueError, "逐字时间"):
            opening.trim(render.Segment(Path("a.mov"), 0, 2), lambda *args: voice_audio())

    def test_disabled_option_keeps_old_behavior(self):
        self.cfg["render"]["opening_cut"]["enabled"] = False
        seg = source_segment()
        result, report = self.trim(seg)
        self.assertIs(result, seg)
        self.assertEqual(report["status"], "disabled")
        self.recognize.assert_not_called()

    def test_cancelled_recognition_cannot_fall_back_to_exporting(self):
        self.recognize.side_effect = cancellation.JobCancelled()
        with self.assertRaises(cancellation.JobCancelled):
            self.trim()

    def test_encoded_unmixed_audio_is_checked_for_delayed_or_missing_speech(self):
        _, report = self.trim()
        audio = voice_audio()[round(report["trimmed_seconds"] * SR):]
        opening.check_encoded(audio[:SR], SR, report)
        self.assertEqual(report["encoded_check"], "passed")
        with self.assertRaisesRegex(ValueError, "有效讲话未及时开始"):
            opening.check_encoded(np.zeros((SR, 2), np.float32), SR, report)
        self.assertEqual(report["encoded_check"], "rejected")

    def test_plan_trims_the_actual_surviving_head_after_short_filter(self):
        first = source_segment()
        second = source_segment(start=10)
        script = {"batch": "test", "lines": []}
        with patch.object(render, "apply_speech_timing", return_value=[first, second]), \
             patch.object(render.short_segments, "filter_segments", return_value=([second], {})), \
             patch.object(render, "_clip_audio", return_value=voice_audio()):
            report = {}
            result = render.plan(script, opening_report=report)
        self.assertEqual(report["original_start"], 10)
        self.assertGreater(result[0].v_start, 11.6)
        self.assertLess(result[0].v_start, 11.7)

    def test_failed_opening_check_is_saved_without_replacing_existing_output(self):
        seg = source_segment()
        self.recognize.return_value = "年涨得有多凶"
        with patch.object(render, "apply_speech_timing", return_value=[seg]), \
             patch.object(render, "_clip_audio", return_value=voice_audio()), \
             patch.object(render, "compose_segments") as compose:
            with self.assertRaises(ValueError):
                render.render({"batch": "test", "id": "01", "lines": []})
        compose.assert_not_called()
        report = json.loads((self.root / "renders/test/01/opening_check.json").read_text(encoding="utf-8"))
        self.assertEqual(report["status"], "rejected")

    def test_opening_that_becomes_a_repeated_short_shot_checks_the_next_head(self):
        first = source_segment(duration=2.3)
        first.a_dur = first.v_content_dur = 2.3
        following = render.Segment(Path("next.mov"), 4, 1, zoom=1,
                                   source_lines=[{"words": [["涨", 4, 4.3], ["价", 4.3, 4.6]],
                                                  "id": 1, "ref": "C2-S1", "text": "涨价", "lang": "zh",
                                                  "start": 4, "end": 5}])
        self.recognize.return_value = "当年涨"
        with patch.object(render, "apply_speech_timing", return_value=[first, following]), \
             patch.object(render, "_clip_audio", return_value=voice_audio(2.3)):
            report, short_report = {}, {}
            result = render.plan({"batch": "test", "lines": []}, opening_report=report, short_report=short_report)
        self.assertEqual(result, [following])
        self.assertEqual(report["original_start"], 4)
        self.assertNotIn("threshold_dbfs", report)
        self.assertEqual(short_report["opening_rechecks"][0]["next_overlap"], "涨")

    def test_real_encoding_preserves_first_word_and_only_adds_short_lead(self):
        wav = self.root / "voice.wav"
        import soundfile as sf
        sf.write(wav, voice_audio(), SR)
        video = self.root / "source.mp4"
        media.run_ffmpeg(["-f", "lavfi", "-i", "color=c=red:s=90x160:r=60:d=3", "-i", str(wav),
                          "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", str(video)])
        seg = source_segment()
        seg.clip = video
        report = {}
        # 使用返回镜头的真实编码，再以同一份原声判定阈值复核。
        trimmed = opening.trim(seg, render._clip_audio, report=report)
        out = self.root / "trimmed.mp4"
        render.encode_segment(trimmed, out, look.normalize({"enabled": False}))
        opening.check_encoded(render._clip_audio(out, 0, 1), SR, report)
        self.assertEqual(report["encoded_check"], "passed")
        self.assertAlmostEqual(media.probe(out).duration, trimmed.v_dur, delta=.03)


if __name__ == "__main__":
    unittest.main()
