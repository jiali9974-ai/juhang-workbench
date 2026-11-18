import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import app as server
from jh import script_agent


class ScriptRecoveryTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        replacement = patch.object(script_agent.config, "data_root", return_value=self.root)
        replacement.start()
        self.addCleanup(replacement.stop)
        self.body = "### 素材 C1\nC1-S1 [0.0-8.0] 8.0秒 (zh) 介绍这只表，喜欢的老板留言问价"
        self.valid = {"videos": [{"title": "名表", "lines": [{"ref": "C1-S1"}]}]}

    def test_empty_and_wrong_fields_are_retried_with_feedback_and_raw_responses_saved(self):
        responses = [json.dumps({"videos": []}), json.dumps({"scripts": []}), json.dumps(self.valid)]
        with patch.object(script_agent, "system_prompt", return_value="剪辑规则"), \
             patch.object(script_agent.llm, "chat", side_effect=responses) as chat:
            self.assertEqual(script_agent._ask("3.20蓝", self.body, []), self.valid)
        self.assertEqual(chat.call_count, 3)
        self.assertIn("videos 为空", chat.call_args_list[1].args[0][1]["content"])
        self.assertIn("必须返回包含 videos 数组", chat.call_args_list[2].args[0][1]["content"])
        folder, = (self.root / "script_runs" / "3.20蓝").iterdir()
        for attempt, response in enumerate(responses, 1):
            self.assertEqual((folder / f"response-{attempt}.txt").read_text(encoding="utf-8"), response)
            request = json.loads((folder / f"request-{attempt}.json").read_text(encoding="utf-8"))
            self.assertEqual(request["batch"], "3.20蓝")
            self.assertIn(self.body, request["messages"][1]["content"])
        self.assertEqual(json.loads((folder / "validation-3.json").read_text())["status"], "accepted")

    def test_invalid_or_partly_invalid_references_and_malformed_lines_are_rejected(self):
        invalid = [None, [], {}, {"videos": "bad"}, {"videos": [None]}, {"videos": [{}]},
                   {"videos": [{"lines": []}]}, {"videos": [{"lines": ["C1-S1"]}]},
                   {"videos": [{"lines": [{"ref": "C9-S1"}]}]},
                   {"videos": [{"lines": [{"ref": "C1-S1"}, {"ref": "C2-S1"}]}]}]
        for payload in invalid:
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                script_agent._validate_response(payload, {"C1-S1"})
        self.assertEqual(script_agent._validate_response(self.valid, {"C1-S1"}), self.valid)

    def test_empty_results_exhaust_retries_and_explain_failure_instead_of_succeeding(self):
        with patch.object(script_agent, "system_prompt", return_value="剪辑规则"), \
             patch.object(script_agent.llm, "chat", return_value='{"videos": [], "empty_reason": "只有闲聊"}') as chat:
            with self.assertRaisesRegex(RuntimeError, "连续 3 次.*只有闲聊.*诊断编号"):
                script_agent._ask("3.20蓝", self.body, [])
        self.assertEqual(chat.call_count, 3)

    def test_truncated_json_and_invalid_reference_recover_on_retry(self):
        with patch.object(script_agent, "system_prompt", return_value="剪辑规则"), \
             patch.object(script_agent.llm, "chat", side_effect=[
                 '{"videos": [', '{"videos": [{"lines": [{"ref": "C99-S1"}]}]}', json.dumps(self.valid),
             ]) as chat:
            self.assertEqual(script_agent._ask("3.20蓝", self.body, []), self.valid)
        self.assertIn("C99-S1", chat.call_args.args[0][1]["content"])

    def test_no_speech_fails_before_requesting_a_script(self):
        for transcripts in ([], [{"clip": "silent.mp4", "duration": 5, "sentences": []}],
                            [{"clip": "silent.mp4", "duration": 5, "sentences": [{"text": "……"}]}]):
            with self.subTest(transcripts=transcripts), patch.object(script_agent.llm, "chat") as chat:
                with self.assertRaisesRegex(RuntimeError, "没有有效口播"):
                    script_agent.generate("无口播", transcripts)
                chat.assert_not_called()

    def test_both_generation_endpoints_preserve_existing_scripts_and_videos_on_empty_result(self):
        scripts = self.root / "scripts" / "原项目"
        outputs = self.root / "outputs" / "原项目"
        scripts.mkdir(parents=True)
        outputs.mkdir(parents=True)
        (scripts / "old.json").write_text("old-script")
        (outputs / "old.mp4").write_bytes(b"old-video")
        for endpoint in (server.generate, server.auto):
            with self.subTest(endpoint=endpoint.__name__), \
                 patch.object(server, "_batch_dir", return_value=self.root), \
                 patch.object(server.asr, "transcribe_folder", return_value=[]), \
                 patch.object(server.scriptmod, "generate", return_value=[]), \
                 patch.object(server.scriptmod, "archive_batch") as archive, \
                 patch.object(server.scriptmod, "save") as save, \
                 patch.object(server.render, "render") as render, \
                 patch.object(server.jobs, "submit") as submit:
                endpoint("原项目")
                run = submit.call_args.args[2]
                with self.assertRaisesRegex(RuntimeError, "没有生成有效剪辑脚本"):
                    run(Mock())
                archive.assert_not_called()
                save.assert_not_called()
                render.assert_not_called()
            self.assertEqual((scripts / "old.json").read_text(), "old-script")
            self.assertEqual((outputs / "old.mp4").read_bytes(), b"old-video")


if __name__ == "__main__":
    unittest.main()
