import copy
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
import soundfile as sf

from jh import config, look, media, render, speech_timing


class SpeechTimingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.cfg = copy.deepcopy(config.load())
        self.cfg["render"].update(width=90, height=160, fps=60, encoder="libx264",
                                  segment_gap={"first_lead": .02, "lead": .05, "tail": .05, "final_tail": .2},
                                  silence_cut={"threshold": 1.0})
        for target, value in [("load", lambda: self.cfg), ("data_root", lambda: self.root)]:
            replacement = patch.object(config, target, value)
            replacement.start()
            self.addCleanup(replacement.stop)

    def test_only_gaps_strictly_greater_than_one_second_are_cut(self):
        self.assertEqual(speech_timing.retained_ranges([(.2, .8), (1.8, 2.4)], 3), [(.15, 2.45)])
        self.assertEqual(speech_timing.retained_ranges([(.2, .8), (1.801, 2.4)], 3), [(.15, .85), (1.751, 2.45)])
        self.assertEqual(speech_timing.retained_ranges([(.2, .8), (1.2, 1.5), (2.6, 3)], 4),
                         [(.15, 1.55), (2.55, 3.05)])

    def test_unsorted_overlapping_voice_regions_do_not_create_false_cuts(self):
        self.assertEqual(speech_timing.retained_ranges([(1, 2), (.2, 1.2), (.4, .3)], 3), [(.15, 2.05)])
        self.assertEqual(speech_timing.retained_ranges([], 3), [])

    def test_first_lead_does_not_change_padding_at_internal_cuts(self):
        self.assertEqual(speech_timing.retained_ranges([(.2, .8), (2, 2.5)], 3, first_lead=.02),
                         [(.18, .85), (1.95, 2.55)])

    def test_short_deleted_words_cut_video_even_without_a_long_silence(self):
        line = {"clip": "source.mov", "start": 0, "end": 2.7, "src_text": "这只嗯表", "keep": "这只表",
                "subtitle": "这只表", "zoom": 1,
                "words": [["这", 0, .6], ["只", .6, 1.2], ["嗯", 1.2, 1.5], ["表", 1.5, 2.7]]}
        cleaned = self.root / "cleaned.wav"
        with patch.object(render, "tighten", return_value=(0, 2.7)), \
             patch.object(render, "clean_audio", return_value=cleaned), \
             patch.object(render, "apply_speech_timing", side_effect=lambda segs, progress: segs):
            first, last = render.plan({"batch": "test", "lines": [line]})
        self.assertEqual((first.v_start, first.v_dur, first.a_start), (0, 1.2, 0))
        self.assertEqual((last.v_start, last.v_dur, last.a_start), (1.5, 1.2, 1.5))
        self.assertEqual(first.audio_wav, cleaned)
        self.assertEqual(last.audio_wav, cleaned)
        self.assertEqual(first.subs, [(0, 1.2, "这只表")])
        self.assertEqual(last.subs, [(0, 1.2, "这只表")])

    def test_plan_drops_the_protected_point_four_five_second_fragment_after_silence_cut(self):
        self.cfg["render"]["silence_cut"]["threshold"] = .35
        line = {"clip": "source.mov", "start": 3.56, "end": 7.31, "src_text": "来我店里", "keep": "我店里",
                "subtitle": "我店里", "zoom": 1,
                "words": [["来", 3.56, 4.31], ["我", 4.31, 5.15], ["店", 5.15, 5.45], ["里", 5.45, 7.31]]}
        cleaned = self.root / "cleaned.wav"
        with patch.object(render, "tighten", return_value=(4.31, 7.31)), \
             patch.object(render, "clean_audio", return_value=cleaned), \
             patch.object(render, "_clip_audio", return_value=np.ones((144000, 2), np.float32)), \
             patch.object(speech_timing, "detect", return_value=[(.78, 3)]):
            actual, = render.plan({"batch": "test", "lines": [line]})
        self.assertEqual((actual.v_start, actual.a_start, actual.v_dur), (5.04, .73, 2.47))
        self.assertEqual((actual.a_dur, actual.v_content_dur), (2.27, 2.27))
        self.assertEqual(actual.audio_wav, cleaned)
        self.assertEqual(actual.subs, [(0, 2.27, "我店里")])

    def test_plan_filters_final_shots_at_point_seven_seconds_and_retimes_captions(self):
        line = {"clip": "source.mov", "start": 0, "end": 4, "src_text": "原话", "keep": "原话",
                "subtitle": "原话", "zoom": 1}
        candidates = [render.Segment(self.root / "source.mov", index * 10, duration, zoom=1,
                                     audio_wav=self.root / "voice.wav", a_start=index * 10,
                                     subs=[(0, duration, text)])
                      for index, (duration, text) in enumerate([(.45, "删除甲"), (.7, "保留甲"),
                                                               (.699, "删除乙"), (.701, "保留乙")])]
        for trim in ("audio", "cut"):
            with self.subTest(trim=trim):
                self.cfg["render"]["slip_trim"] = trim
                with patch.object(render, "line_words", return_value=None), \
                     patch.object(render, "tighten", return_value=(0, 4)), \
                     patch.object(render, "opening_start", return_value=0), \
                     patch.object(render, "clean_audio", return_value=self.root / "voice.wav"), \
                     patch.object(render, "apply_speech_timing", return_value=candidates):
                    kept = render.plan({"batch": "test", "lines": [line]})
                self.assertEqual(kept, [candidates[1], candidates[3]])
                captions = self.root / "filtered.ass"
                render.build_ass(kept, sum(seg.v_dur for seg in kept), captions)
                text = captions.read_text(encoding="utf-8")
                self.assertNotIn("删除甲", text)
                self.assertNotIn("删除乙", text)
                self.assertIn("Dialogue: 2,0:00:00.00,0:00:00.70,", text)
                self.assertIn("Dialogue: 2,0:00:00.70,0:00:01.40,", text)

    def test_plan_stops_when_all_final_shots_are_short(self):
        for duration in (.45, .699):
            with self.subTest(duration=duration), \
                 patch.object(render, "apply_speech_timing", return_value=[render.Segment(self.root / "source.mov", 0, duration)]), \
                 self.assertRaisesRegex(ValueError, r"裁剪后的片段均不足 0\.7 秒"):
                render.plan({"batch": "test", "lines": []})

    def test_no_voice_segments_are_dropped_and_padding_uses_first_and_last_survivors(self):
        segs = [render.Segment(self.root / "source.mp4", start, 1) for start in (0, 1, 2)]
        with patch.object(render, "_clip_audio", return_value=np.ones((48000, 2), np.float32)), \
             patch.object(speech_timing, "detect", side_effect=[[], [(.2, .7)], []]):
            result = render.apply_speech_timing(segs)
        self.assertEqual(len(result), 1)
        self.assertEqual((result[0].v_start, result[0].v_dur), (1.18, .72))
        with patch.object(render, "_clip_audio", return_value=np.zeros((48000, 2), np.float32)):
            self.assertEqual(render.apply_speech_timing(segs), [])

    def test_keep_alignment_failure_cannot_fall_back_to_restoring_source_words(self):
        for words, keep in (([["好", 0, .3]], "很好"), ([["重复", 0, .3]], "复")):
            with self.subTest(words=words), self.assertRaises(ValueError):
                render.keep_pieces({"clip": "a.mov", "start": 0, "end": .3, "keep": keep}, words)
        with self.assertRaisesRegex(ValueError, "缺少逐字时间"):
            render.keep_pieces({"clip": "a.mov", "start": 0, "end": 1, "keep": "好", "src_text": "嗯好"}, None)

    def test_retained_padding_never_passes_source_boundary(self):
        self.assertEqual(speech_timing.retained_ranges([(.2, 1)], 1), [(.15, 1)])
        self.assertEqual(render.subtract_ranges(0, 2, [(.8, 1.2), (.6, 1)]), [(0, .6), (1.2, 2)])

    def test_subsecond_idle_gap_is_cut_at_configured_threshold(self):
        self.assertEqual(speech_timing.retained_ranges([(.1, .5), (.9, 1.2)], 2, threshold=.35),
                         [(.05, .55), (.85, 1.25)])
        self.assertEqual(speech_timing.retained_ranges([(.1, .5), (.85, 1.2)], 2, threshold=.35), [(.05, 1.25)])

    def test_vad_cannot_cut_off_an_aligned_quiet_last_word(self):
        seg = render.Segment(self.root / "source.mov", 2, 1, speech_spans=[(.1, .6), (.6, .95)])
        with patch.object(render, "_clip_audio", return_value=np.ones((48000, 2), np.float32)), \
             patch.object(speech_timing, "detect", return_value=[(.1, .6)]):
            actual, = render.apply_speech_timing([seg])
        self.assertAlmostEqual(actual.v_start + actual.v_dur, 3.15)
        self.assertEqual(actual.speech_spans[-1], (.52, .87))
        with patch.object(render, "_clip_audio", return_value=np.zeros((48000, 2), np.float32)):
            self.assertEqual(render.apply_speech_timing([seg]), [])

    def test_word_protection_does_not_restore_an_internal_idle_gap(self):
        words = [(.1, .2), (.2, .9), (1.5, 1.8), (1.8, 1.9)]
        seg = render.Segment(self.root / "source.mov", 0, 2, speech_spans=render.boundary_word_spans(words, 0, 2))
        self.cfg["render"]["silence_cut"]["threshold"] = .35
        with patch.object(render, "_clip_audio", return_value=np.ones((96000, 2), np.float32)), \
             patch.object(speech_timing, "detect", return_value=[(.1, .4), (1.5, 1.9)]):
            first, last = render.apply_speech_timing([seg])
        self.assertAlmostEqual(first.v_start + first.v_dur, .45)
        self.assertEqual(last.v_start, 1.45)

    def test_final_segment_has_point_two_seconds_and_internal_tail_stays_point_zero_five(self):
        for explicit in (True, False):
            with self.subTest(explicit_config=explicit):
                if not explicit:
                    self.cfg["render"]["segment_gap"].pop("final_tail")
                segs = [render.Segment(self.root / "a.mp4", 10, 2), render.Segment(self.root / "b.mp4", 20, 2)]
                with patch.object(render, "_clip_audio", return_value=np.ones((96000, 2), np.float32)), \
                     patch.object(speech_timing, "detect", return_value=[(.1, 1.5)]):
                    result = render.apply_speech_timing(segs)
                self.assertAlmostEqual(result[0].v_start, 10.08)
                self.assertAlmostEqual(result[1].v_start, 20.05)
                self.assertAlmostEqual(result[0].v_start + result[0].v_dur, 11.55)
                self.assertAlmostEqual(result[1].v_start + result[1].v_dur, 21.7)

    def test_split_moves_video_audio_and_subtitles_together(self):
        seg = render.Segment(self.root / "video.mp4", 10, 3, audio_wav=self.root / "voice.wav", a_start=5,
                             subs=[(.2, .8, "第一句"), (2.01, 2.6, "第二句")], zoom=1.2)
        with patch.object(render, "_clip_audio", return_value=np.ones((144000, 2), np.float32)) as audio, \
             patch.object(speech_timing, "detect", return_value=[(.2, .8), (2.01, 2.6)]):
            first, last = render.apply_speech_timing([seg])
        audio.assert_called_once_with(seg.audio_wav, 5, 3)
        self.assertEqual((first.v_start, first.a_start, first.v_dur), (10.18, 5.18, .67))
        self.assertEqual((last.v_start, last.a_start, last.v_dur), (11.96, 6.96, .84))
        self.assertEqual(first.subs, [(.02, .62, "第一句")])
        self.assertEqual(last.subs, [(.05, .64, "第二句")])
        self.assertEqual(last.zoom, 1.2)
        self.assertEqual(seg.a_start, 5)  # 原计划不被原地改写。

    def test_final_syllable_is_not_shortened_by_old_dragged_word_rule(self):
        line = {"start": 1, "end": 2.4, "keep": "好啊"}
        words = [["好", 1, 1.3], ["啊", 1.3, 2.4]]
        self.assertAlmostEqual(render.keep_pieces(line, words)[-1][1], 1.82)
        self.assertAlmostEqual(render.keep_pieces(line, words, final=True)[-1][1], 2.52)

    def test_previous_sentence_tail_cannot_restore_a_deleted_restart(self):
        previous = {"clip": "a.mov", "start": .3, "end": .9, "keep": "高",
                    "words": [["高", .3, .8], ["。", .8, .9]]}
        retry = {"clip": "a.mov", "start": .9, "end": 3, "keep": "这只表",
                 "words": [["这", .9, 1.3], ["只", 1.3, 1.5], ["表", 1.5, 1.7],
                           ["是", 1.7, 2], ["，", 2, 2.1], ["这", 2.1, 2.5],
                           ["只", 2.5, 2.7], ["表", 2.7, 3]]}
        script = {"batch": "test", "lines": [previous, retry]}
        first, last = render._script_keep_pieces(script)
        self.assertEqual(first[1][-1][1], .8)  # 旧的 .12 秒句尾余量会带入下一句错误的“这”。
        self.assertEqual(last[1][0][0], 2.1)  # 即使口误中间有标点，也不能回取已删的字。
        retry["clip"] = "b.mov"
        self.assertEqual(render._script_keep_pieces(script)[0][1][-1][1], .92)

    def test_next_sentence_lead_cannot_restore_a_deleted_suffix(self):
        previous = {"clip": "a.mov", "start": 0, "end": 1, "keep": "很好",
                    "words": [["很", 0, .3], ["好", .3, .6], ["这", .6, .9], ["，", .9, 1]]}
        following = {"clip": "a.mov", "start": 1, "end": 1.8, "keep": "这只表",
                     "words": [["这", 1, 1.3], ["只", 1.3, 1.5], ["表", 1.5, 1.8]]}
        first, last = render._script_keep_pieces({"batch": "test", "lines": [previous, following]})
        self.assertEqual(first[1][-1][1], .6)
        self.assertEqual(last[1][0][0], 1)

    def test_audio_fades_never_leak_deleted_speech_outside_retained_intervals(self):
        sr = render.AUDIO_SR
        with patch.object(render, "_clip_audio", return_value=np.ones((sr, 2), np.float32)), \
             patch.object(render, "room_tone", return_value=np.zeros((sr, 2), np.float32)):
            wav = render.clean_audio("test", self.root / "source.mov", 0, 1, [(.2, .4)])
        audio, _ = sf.read(wav)
        self.assertEqual(float(np.max(np.abs(audio[:round(.2 * sr)]))), 0)
        self.assertEqual(float(np.max(np.abs(audio[round(.4 * sr):]))), 0)
        self.assertLess(abs(float(audio[round(.2 * sr), 0])), .01)  # 边界从零起淡入，避免硬截产生爆音。
        self.assertLess(abs(float(audio[round(.4 * sr) - 1, 0])), .01)
        self.assertGreater(float(np.mean(audio[round(.22 * sr):round(.38 * sr)])), .99)

    def test_extended_final_padding_does_not_import_the_next_unselected_word(self):
        seg = render.Segment(self.root / "video.mp4", 10, 1)
        with patch.object(render, "_clip_audio", return_value=np.ones((48000, 2), np.float32)), \
             patch.object(speech_timing, "detect", return_value=[(.02, 1)]):
            last = render.apply_speech_timing([seg])[0]
        self.assertEqual(last.v_dur, 1.2)
        self.assertEqual(last.a_dur, 1)
        self.assertEqual(last.v_content_dur, 1)

    def test_final_blank_freezes_retained_picture_instead_of_importing_deleted_frames(self):
        video, wav = self.root / "colors.mp4", self.root / "voice.wav"
        sf.write(wav, np.full((24000, 2), .1, np.float32), 48000)
        media.run_ffmpeg(["-f", "lavfi", "-i", "color=c=red:s=90x160:r=60:d=0.5",
                          "-f", "lavfi", "-i", "color=c=blue:s=90x160:r=60:d=0.5",
                          "-filter_complex", "[0:v][1:v]concat=n=2:v=1:a=0[v]", "-map", "[v]",
                          "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(video)])
        with patch.object(speech_timing, "detect", return_value=[(.02, .5)]):
            seg, = render.apply_speech_timing([render.Segment(video, 0, .5, audio_wav=wav, zoom=1)])
        output = self.root / "frozen.mp4"
        render.encode_segment(seg, output, look.normalize({"enabled": False}))
        import cv2
        capture = cv2.VideoCapture(str(output))
        try:
            capture.set(cv2.CAP_PROP_POS_MSEC, 600)
            ok, frame = capture.read()
        finally:
            capture.release()
        self.assertTrue(ok)
        self.assertGreater(float(frame[:, :, 2].mean()), 220)
        self.assertLess(float(frame[:, :, 0].mean()), 20)

    def test_detector_bounds_its_output_and_reuses_audio_analysis(self):
        detector = SimpleNamespace(generate=lambda **kwargs: [{"value": [[-1, 50], [100, 500], [700, 1200], [1500, 2000]]}])
        audio = np.full((48000, 2), .1, np.float32)
        with patch.object(speech_timing, "_detector", return_value=detector) as factory:
            self.assertEqual(speech_timing.detect(audio, 48000), [(.1, .5), (.7, 1)])
            self.assertEqual(speech_timing.detect(audio, 48000), [(.1, .5), (.7, 1)])
            self.assertEqual(factory.call_count, 1)
            self.assertEqual(speech_timing.detect(np.zeros_like(audio), 48000), [])
            self.assertEqual(factory.call_count, 1)

    def test_real_encoding_uses_the_split_audio_offset_and_preserves_final_silence(self):
        sr = 48000
        waveform = np.zeros((3 * sr, 2), np.float32)
        for a, b, hz in [(.2, .8, 440), (2.01, 2.6, 880)]:
            start, end = round(a * sr), round(b * sr)
            samples = .25 * np.sin(2 * np.pi * hz * np.arange(end - start) / sr)
            waveform[start:end] = samples[:, None]
        wav, video = self.root / "voice.wav", self.root / "video.mp4"
        sf.write(wav, waveform, sr)
        media.run_ffmpeg(["-f", "lavfi", "-i", "color=c=blue:s=90x160:r=60:d=3",
                          "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(video)])
        seg = render.Segment(video, 0, 3, audio_wav=wav, zoom=1)
        with patch.object(speech_timing, "detect", return_value=[(.2, .8), (2.01, 2.6)]):
            parts = render.apply_speech_timing([seg])
        out = self.root / "last.mp4"
        render.encode_segment(parts[-1], out, look.normalize({"enabled": False}))
        self.assertAlmostEqual(media.probe(out).duration, .84, delta=1 / 60 + .002)
        audio = render._clip_audio(out).mean(axis=1)
        section = audio[round(.12 * sr):round(.4 * sr)]
        frequencies = np.fft.rfftfreq(len(section), 1 / sr)
        peak = frequencies[np.argmax(np.abs(np.fft.rfft(section)))]
        self.assertAlmostEqual(peak, 880, delta=10)  # 错用音轨开头会变成 440 Hz。
        self.assertLess(float(np.sqrt(np.mean(audio[-round(.15 * sr):] ** 2))), .005)


if __name__ == "__main__":
    unittest.main()
