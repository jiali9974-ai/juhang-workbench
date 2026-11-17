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
                                  segment_gap={"first_lead": .02, "lead": .02, "tail": .02, "final_tail": .1},
                                  silence_cut={"threshold": 1.0})
        for target, value in [("load", lambda: self.cfg), ("data_root", lambda: self.root)]:
            replacement = patch.object(config, target, value)
            replacement.start()
            self.addCleanup(replacement.stop)

    def test_only_gaps_strictly_greater_than_one_second_are_cut(self):
        self.assertEqual(speech_timing.retained_ranges([(.2, .8), (1.8, 2.4)], 3), [(.18, 2.42)])
        self.assertEqual(speech_timing.retained_ranges([(.2, .8), (1.801, 2.4)], 3), [(.18, .82), (1.781, 2.42)])
        self.assertEqual(speech_timing.retained_ranges([(.2, .8), (1.2, 1.5), (2.6, 3)], 4),
                         [(.18, 1.52), (2.58, 3.02)])

    def test_unsorted_overlapping_voice_regions_do_not_create_false_cuts(self):
        self.assertEqual(speech_timing.retained_ranges([(1, 2), (.2, 1.2), (.4, .3)], 3), [(.18, 2.02)])
        self.assertEqual(speech_timing.retained_ranges([], 3), [(0, 3)])

    def test_first_lead_does_not_change_padding_at_internal_cuts(self):
        self.assertEqual(speech_timing.retained_ranges([(.2, .8), (2, 2.5)], 3, first_lead=.05),
                         [(.15, .82), (1.98, 2.52)])

    def test_only_the_final_segment_has_one_tenth_second_after_speech(self):
        segs = [render.Segment(self.root / "a.mp4", 10, 2), render.Segment(self.root / "b.mp4", 20, 2)]
        with patch.object(render, "_clip_audio", return_value=np.ones((96000, 2), np.float32)), \
             patch.object(speech_timing, "detect", return_value=[(.1, 1.5)]):
            result = render.apply_speech_timing(segs)
        self.assertAlmostEqual(result[0].v_start + result[0].v_dur, 11.52)
        self.assertAlmostEqual(result[1].v_start + result[1].v_dur, 21.6)

    def test_split_moves_video_audio_and_subtitles_together(self):
        seg = render.Segment(self.root / "video.mp4", 10, 3, tts_wav=self.root / "voice.wav", a_start=5,
                             subs=[(.2, .8, "第一句"), (2.01, 2.6, "第二句")], zoom=1.2)
        with patch.object(render, "_clip_audio", return_value=np.ones((144000, 2), np.float32)) as audio, \
             patch.object(speech_timing, "detect", return_value=[(.2, .8), (2.01, 2.6)]):
            first, last = render.apply_speech_timing([seg])
        audio.assert_called_once_with(seg.tts_wav, 5, 3)
        self.assertEqual((first.v_start, first.a_start, first.v_dur), (10.18, 5.18, .64))
        self.assertEqual((last.v_start, last.a_start, last.v_dur), (11.99, 6.99, .71))
        self.assertEqual(first.subs, [(.02, .62, "第一句")])
        self.assertEqual(last.subs, [(.02, .61, "第二句")])
        self.assertEqual(last.zoom, 1.2)
        self.assertEqual(seg.a_start, 5)  # 原计划不被原地改写。

    def test_final_syllable_is_not_shortened_by_old_dragged_word_rule(self):
        line = {"start": 1, "end": 2.4, "keep": "好啊"}
        words = [["好", 1, 1.3], ["啊", 1.3, 2.4]]
        self.assertAlmostEqual(render.keep_pieces(line, words)[-1][1], 1.82)
        self.assertAlmostEqual(render.keep_pieces(line, words, final=True)[-1][1], 2.52)

    def test_extended_final_padding_does_not_import_the_next_unselected_word(self):
        seg = render.Segment(self.root / "video.mp4", 10, 1)
        with patch.object(render, "_clip_audio", return_value=np.ones((48000, 2), np.float32)), \
             patch.object(speech_timing, "detect", return_value=[(.02, 1)]):
            last = render.apply_speech_timing([seg])[0]
        self.assertEqual(last.v_dur, 1.1)
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
        seg = render.Segment(video, 0, 3, tts_wav=wav, zoom=1)
        with patch.object(speech_timing, "detect", return_value=[(.2, .8), (2.01, 2.6)]):
            parts = render.apply_speech_timing([seg])
        out = self.root / "last.mp4"
        render.encode_segment(parts[-1], out, look.normalize({"enabled": False}))
        self.assertAlmostEqual(media.probe(out).duration, .71, delta=1 / 60 + .002)
        audio = render._clip_audio(out).mean(axis=1)
        section = audio[round(.12 * sr):round(.4 * sr)]
        frequencies = np.fft.rfftfreq(len(section), 1 / sr)
        peak = frequencies[np.argmax(np.abs(np.fft.rfft(section)))]
        self.assertAlmostEqual(peak, 880, delta=10)  # 错用音轨开头会变成 440 Hz。
        self.assertLess(float(np.sqrt(np.mean(audio[-round(.06 * sr):] ** 2))), .005)


if __name__ == "__main__":
    unittest.main()
