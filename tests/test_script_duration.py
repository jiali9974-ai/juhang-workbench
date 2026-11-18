import unittest
from unittest.mock import patch

from jh import script, script_agent


class ScriptDurationTests(unittest.TestCase):
    def test_short_and_long_scripts_survive_legacy_duration_settings(self):
        for duration in (8.0, 16.6, 90.0):
            with self.subTest(duration=duration):
                transcript = {"clip": "watch.mov", "duration": duration, "sentences": [
                    {"start": 0.0, "end": duration, "lang": "zh", "text": "这只表是百达翡丽5159，感兴趣的老板留言问价"},
                ]}
                response = {"videos": [{"title": "百达翡丽5159", "lines": [
                    {"ref": "C1-S1", "role": "product", "subtitle": "这只表是百达翡丽5159，感兴趣的老板留言问价"},
                ]}]}
                with patch.object(script_agent.config, "load", return_value={"script": {"min_seconds": 25, "max_seconds": 45}}), \
                     patch.object(script_agent, "_ask", return_value=response):
                    scripts = script_agent.generate("11.18", [transcript])
                self.assertEqual(len(scripts), 1)
                self.assertEqual(script.total_duration(scripts[0]), duration)

    def test_prompt_has_no_duration_target_even_with_legacy_settings(self):
        with patch.object(script_agent.config, "load", return_value={"script": {"min_seconds": 25, "max_seconds": 45}}):
            prompt = script_agent.system_prompt()
        self.assertIn("素材和成片都没有时长限制", prompt)
        self.assertNotIn("25–45", prompt)
        self.assertNotIn("{min_s}", prompt)
        self.assertNotIn("{max_s}", prompt)
        self.assertNotIn("凑不够的那组表不要出", prompt)

    def test_invalid_sentence_references_still_do_not_create_empty_scripts(self):
        transcript = {"clip": "watch.mov", "duration": 8.0, "sentences": [
            {"start": 0.0, "end": 8.0, "lang": "zh", "text": "介绍这只表"},
        ]}
        with patch.object(script_agent, "_ask", return_value={"videos": [{"lines": [{"ref": "C9-S9"}]}]}):
            self.assertEqual(script_agent.generate("11.18", [transcript]), [])


if __name__ == "__main__":
    unittest.main()
