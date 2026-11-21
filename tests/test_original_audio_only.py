import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

import app as server
from jh import config, pipeline, render, script, script_agent


class OriginalAudioTests(unittest.TestCase):
    def test_old_dubbing_choice_cannot_replace_source_audio(self):
        cfg = copy.deepcopy(config.load())
        line = {"clip": "source.mov", "start": 1, "end": 3, "src_lang": "zh",
                "src_text": "这是原声", "keep": "这是原声", "subtitle": "这是原声", "zoom": 1}
        old_script = {"batch": "项目", "voice_mode": "tts_all", "tts_engine": "ming", "lines": [line]}
        for trim in ("audio", "cut"):
            with self.subTest(trim=trim):
                cfg["render"]["slip_trim"] = trim
                with patch.object(config, "load", return_value=cfg), \
                     patch.object(script, "fill_keep", return_value=False), \
                     patch.object(render, "line_words", return_value=None), \
                     patch.object(render, "tighten", return_value=(1, 3)), \
                     patch.object(render, "apply_speech_timing", side_effect=lambda segs, progress: segs):
                    segments = render.plan(copy.deepcopy(old_script))
                self.assertEqual(len(segments), 1)
                self.assertEqual(segments[0].clip.name, "source.mov")
                self.assertIsNone(segments[0].audio_wav)
                self.assertIn("这是原声", [text for _, _, text in segments[0].subs])

    def test_saving_from_old_browser_removes_retired_settings(self):
        with tempfile.TemporaryDirectory() as temporary, patch.object(config, "data_root", return_value=Path(temporary)):
            value = {"batch": "项目", "id": "01", "title": "原声剪辑", "lines": [],
                     "voice_mode": "tts_all", "tts_engine": "ming", "voice_source": "fixed",
                     "voice_ref": {"clip": "old.wav"}, "resolved_voice": "tts_all"}
            saved = json.loads(script.save(value).read_text(encoding="utf-8"))
            self.assertEqual(saved, {"batch": "项目", "id": "01", "title": "原声剪辑", "lines": []})

    def test_removed_routes_and_settings_cannot_restart_a_voice_engine(self):
        client = TestClient(server.app)
        for method, url in (("post", "/api/tts/preview"), ("get", "/api/tts/engines"),
                            ("get", "/api/tts/file"), ("get", "/api/voice_ref_file"),
                            ("post", "/api/batches/test/dub_full"), ("get", "/api/batches/test/dubs"),
                            ("get", "/api/batches/test/scripts/01/voice_ref")):
            with self.subTest(url=url):
                self.assertEqual(client.request(method, url).status_code, 404)
        for key in ("tts.engine", "tts.ming.model", "script.dub_mandarin", "dub.demucs_model"):
            with self.subTest(key=key):
                self.assertEqual(client.put("/api/pipeline", json={"changes": {key: "old-model"}}).status_code, 400)
        with patch.object(pipeline, "llm_models", return_value=([], "")):
            flow = client.get("/api/pipeline").json()
        self.assertEqual([branch["id"] for branch in flow["branches"]], ["clip"])
        self.assertEqual([step["id"] for step in flow["branches"][0]["steps"]],
                         ["upload", "asr", "script", "look", "cover", "render"])
        self.assertNotIn("tts", client.get("/api/info").json())
        prompt = script_agent.system_prompt()
        self.assertIn("不要翻译成粤语", prompt)
        self.assertNotIn("字幕同时也是配音文案", prompt)


if __name__ == "__main__":
    unittest.main()
