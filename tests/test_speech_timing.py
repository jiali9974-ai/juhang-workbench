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
        self.assertEqual(speech_timing.retained_ranges([], 3), [(0, 3)])

    def test_first_lead_does_not_change_padding_at_internal_cuts(self):
        self.assertEqual(speech_timing.retained_ranges([(.2, .8), (2, 2.5)], 3, first_lead=.02),
                         [(.18, .85), (1.95, 2.55)])

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
