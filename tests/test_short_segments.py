import copy
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from jh import cancellation, config, llm, render, short_segments, speech_timing


def source(index, words, *, text=None, start=None, end=None, lang="zh"):
    return {"id": index, "ref": f"C1-S{index + 1}", "text": text or "".join(w[0] for w in words or []),
            "lang": lang, "start": start if start is not None else words[0][1],
            "end": end if end is not None else words[-1][2], "words": words}


def segment(text, duration=.4, index=0, start=0, lang="zh"):
    return render.Segment(Path("source.mov"), start, duration, zoom=1,
                          source_lines=[source(index, [[text, start, start + duration]], lang=lang)],
                          subs=[(0, duration, "不应拿这条完整字幕判断短段文字")])


class ShortSegmentTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.cfg = copy.deepcopy(config.load())
        self.cfg["render"]["short_segment_filter"] = {"enabled": True}
        self.cfg["render"]["opening_cut"] = {"enabled": False}
        for target, value in (("load", self.cfg), ("data_root", self.root)):
            mock = patch.object(config, target, return_value=value)
            mock.start()
            self.addCleanup(mock.stop)
        model = patch.object(llm, "chat", side_effect=AssertionError("短段规则不得调用大模型"))
        self.chat = model.start()
        self.addCleanup(model.stop)

    def tearDown(self):
        self.chat.assert_not_called()

    def test_no_repeated_character_keeps_short_speech_and_original_boundaries(self):
        line = source(0, [["这只表", 0, 1], ["不是", 2, 2.4], ["全新的", 3, 4]])
        segs = [render.Segment(Path("a.mov"), a, b - a, source_lines=[line])
                for a, b in ((0, 1), (2, 2.4), (3, 4))]
        before = [(s.v_start, s.v_dur, s.a_start) for s in segs]
        kept, report = short_segments.filter_segments(segs)
        self.assertEqual(kept, segs)
        self.assertEqual([(s.v_start, s.v_dur, s.a_start) for s in kept], before)
        self.assertEqual(report["candidates"][0]["text"], "不是")
        self.assertEqual(report["candidates"][0]["previous_overlap"], "")
        self.assertEqual(report["candidates"][0]["next_overlap"], "")
        self.assertEqual(report["kept"], 1)

    def test_only_continuous_overlap_at_either_join_deletes_the_short_segment(self):
        for left, right, previous, following in (("劳力士这只", "很值", "这只", ""),
                                                  ("推荐购买", "表盘好看", "", "表"),
                                                  ("劳力士这只", "表盘好看", "这只", "表")):
            with self.subTest(left=left, right=right):
                segs = [segment(left, 1, 0), segment("这只表", .4, 1), segment(right, 1, 2)]
                kept, report = short_segments.filter_segments(segs)
                self.assertEqual(kept, [segs[0], segs[2]])
                row, = report["candidates"]
                self.assertEqual(row["previous_overlap"], previous)
                self.assertEqual(row["next_overlap"], following)
                self.assertFalse(row["retained"])

    def test_single_repeated_boundary_character_inside_one_source_sentence_is_deleted(self):
        line = source(0, [["这只是", 0, 1], ["是", 1.5, 1.8]])
        segs = [render.Segment(Path("a.mov"), a, b - a, source_lines=[line])
                for a, b in ((0, 1), (1.5, 1.8))]
        kept, report = short_segments.filter_segments(segs)
        self.assertEqual(kept, segs[:1])
        self.assertEqual(report["candidates"][0]["previous_overlap"], "是")

    def test_shared_characters_away_from_the_join_are_not_duplicates(self):
        for previous, short, following in (("劳力士手表", "这只表", "值得入手"),
                                             ("这只表很好", "表", "这表便宜"),
                                             ("预算一万", "126", "36")):
            with self.subTest(text=short):
                segs = [segment(previous, 1, 0), segment(short, .3, 1), segment(following, 1, 2)]
                kept, report = short_segments.filter_segments(segs)
                self.assertEqual(kept, segs)
                self.assertEqual(report["candidates"][0]["previous_overlap"], "")
                self.assertEqual(report["candidates"][0]["next_overlap"], "")

    def test_multicharacter_repeated_phrase_at_a_join_is_deleted(self):
        segs = [segment("推荐这只", 1, 0), segment("这只", .3, 1), segment("表很漂亮", 1, 2)]
        kept, report = short_segments.filter_segments(segs)
        self.assertEqual(kept, [segs[0], segs[2]])
        self.assertEqual(report["candidates"][0]["previous_overlap"], "这只")

    def test_only_immediate_neighbors_are_compared(self):
        segs = [segment("甲", 1, 0), segment("乙", 1, 1), segment("甲", .3, 2), segment("丙", 1, 3)]
        kept, report = short_segments.filter_segments(segs)
        self.assertEqual(kept, segs)
        self.assertEqual(report["candidates"][0]["before"][0]["text"], "乙")
        self.assertEqual(report["candidates"][0]["after"][0]["text"], "丙")

    def test_consecutive_short_segments_use_the_same_original_timeline(self):
        segs = [segment("甲", 1, 0), segment("甲乙", .3, 1), segment("乙丙", .3, 2), segment("丁", 1, 3)]
        kept, report = short_segments.filter_segments(segs)
        self.assertEqual(kept, [segs[0], segs[3]])
        self.assertEqual(report["deleted"], 2)
        self.assertEqual(report["candidates"][1]["previous_overlap"], "乙")

    def test_punctuation_spaces_and_whole_sentence_subtitles_do_not_count(self):
        segs = [segment("值得入手，！", 1, 0), segment("好价 ，！", .3, 1), segment("快嚟睇吓，！", 1, 2, lang="yue")]
        kept, report = short_segments.filter_segments(segs)
        self.assertEqual(kept, segs)
        self.assertEqual(report["candidates"][0]["previous_overlap"], "")
        self.assertEqual(report["candidates"][0]["next_overlap"], "")

    def test_punctuation_between_repeated_boundary_words_is_ignored(self):
        segs = [segment("这只，", 1, 0), segment(" 这只！", .3, 1)]
        kept, report = short_segments.filter_segments(segs)
        self.assertEqual(kept, segs[:1])
        self.assertEqual(report["candidates"][0]["previous_overlap"], "这只")

    def test_numbers_and_case_insensitive_english_count_as_characters(self):
        for short, neighbor, expected in (("ROLEX", "rolex", "rolex"),
                                            ("126", "6334", "6"), ("唔系", "系全新", "系")):
            with self.subTest(text=short):
                segs = [segment(short), segment(neighbor, 1, 1)]
                kept, report = short_segments.filter_segments(segs)
                self.assertEqual(kept, segs[1:])
                self.assertEqual(report["candidates"][0]["next_overlap"], expected)

    def test_threshold_and_opt_out_keep_legacy_behavior(self):
        segs = [segment("表", .699, 0), segment("表", .7, 1), segment("表", .701, 2)]
        kept, report = short_segments.filter_segments(segs)
        self.assertEqual(kept, segs[1:])
        self.assertEqual(report["deleted"], 1)
        self.cfg["render"]["short_segment_filter"]["enabled"] = False
        segs = [segment("甲", .3), segment("乙", .7, 1)]
        self.assertEqual(short_segments.filter_segments(segs)[0], segs[1:])

    def test_missing_or_unmapped_words_are_kept_without_using_sentence_text(self):
        unknown = segment("原话")
        unknown.source_lines = [source(0, None, text="原话", start=0, end=1)]
        unmapped = segment("后面的原话", 1)
        unmapped.v_start, unmapped.v_dur = 2, .3
        for seg in (unknown, unmapped, render.Segment(Path("a.mov"), 0, .3)):
            with self.subTest(seg=seg):
                kept, report = short_segments.filter_segments([seg])
                self.assertEqual(kept, [seg])
                self.assertEqual(report["candidates"][0]["text"], "")
                self.assertTrue(report["candidates"][0]["retained"])

    def test_frozen_tail_is_not_read_as_source_speech(self):
        seg = segment("尾字", 1)
        seg.v_content_dur = 0
        self.assertEqual(short_segments.describe(seg, 0)["text"], "")

    def test_deleted_segment_captions_are_removed_and_later_captions_retimed(self):
        segs = [segment("这只表", 1, 0), segment("表", .3, 1), segment("全新", .7, 2)]
        for seg, text in zip(segs, ("这只表", "应删除的字幕", "全新")):
            seg.subs = [(0, seg.v_dur, text)]
        kept, _ = short_segments.filter_segments(segs)
        path = self.root / "subtitles.ass"
        render.build_ass(kept, 1.7, path)
        captions = path.read_text(encoding="utf-8")
        self.assertNotIn("应删除的字幕", captions)
        self.assertIn("Dialogue: 2,0:00:01.00,0:00:01.70,", captions)

    def test_silence_split_preserves_word_mapping_and_never_restores_keep_deletions(self):
        self.cfg["render"].update(silence_cut={"threshold": .35},
                                  segment_gap={"first_lead": .02, "lead": .05, "tail": .05, "final_tail": .2})
        line = {"clip": "a.mov", "start": 0, "end": 4, "src_text": "这只嗯表不是全新的", "keep": "这只表不是全新的",
                "subtitle": "这只表不是全新的", "zoom": 1,
                "words": [["这只", 0, 1], ["嗯", 1, 1.3], ["表", 1.3, 2],
                          ["不是", 2.5, 2.8], ["全新的", 3.3, 4]]}
        report = {}
        with patch.object(render, "tighten", return_value=(0, 4)), \
             patch.object(render, "_clip_audio", side_effect=[np.ones((48000, 2), np.float32), np.ones((129600, 2), np.float32)]), \
             patch.object(speech_timing, "detect", side_effect=[[(0, 1)], [(0, .7), (1.2, 1.5), (2, 2.7)]]):
            kept = render.plan({"batch": "test", "lines": [line]}, short_report=report)
        text = "".join(short_segments.describe(seg, i)["text"] for i, seg in enumerate(kept))
        self.assertEqual(text, "这只表不是全新的")
        self.assertNotIn("嗯", str([s.source_lines for s in kept]))
        self.assertTrue(any(row["text"] == "不是" and row["retained"] for row in report["candidates"]))
        self.assertTrue(all(seg.v_start >= 1.3 or seg.v_start + seg.v_dur <= 1.0 for seg in kept))

    def test_no_voice_cannot_be_restored_by_selected_words(self):
        with patch.object(render, "_clip_audio", return_value=np.zeros((19200, 2), np.float32)):
            self.assertEqual(render.apply_speech_timing([segment("不是")]), [])

    def test_cancellation_does_not_fall_back_to_rendering(self):
        event = threading.Event()
        with cancellation.scope(event):
            event.set()
            with self.assertRaises(cancellation.JobCancelled):
                short_segments.filter_segments([segment("不是")])

    def test_review_is_saved_even_when_all_candidates_are_deleted(self):
        self.cfg["render"]["cover"] = {"enabled": False}
        with patch.object(render, "apply_speech_timing", return_value=[segment("表"), segment("表", index=1)]), \
             self.assertRaisesRegex(ValueError, "均被短段规则过滤"):
            render.render({"batch": "test", "id": "01", "lines": []})
        report = json.loads((self.root / "renders/test/01/short_segment_review.json").read_text(encoding="utf-8"))
        self.assertEqual(report["deleted"], 2)
        self.assertEqual(report["candidates"][0]["next_overlap"], "表")


if __name__ == "__main__":
    unittest.main()
