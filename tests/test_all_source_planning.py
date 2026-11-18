import json
import tempfile
from pathlib import Path
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from jh import llm, script_agent


class AllSourcePlanningTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        replacement = patch.object(script_agent.config, "data_root", return_value=Path(temp.name))
        replacement.start()
        self.addCleanup(replacement.stop)

    def transcripts(self, count=75):
        return [{"clip": f"原片_{index:03d}.mov", "duration": 60, "sentences": [
            {"start": 0.0, "end": 60.0, "lang": "zh", "text": f"这只表的独有配件编号是{10000 + index}，请完整保留这项信息"},
        ]} for index in range(1, count + 1)]

    def test_all_75_sources_exceeding_20_minutes_enter_one_plan_and_can_be_used(self):
        transcripts = self.transcripts()
        response = {"videos": [{"title": "全部配件信息", "lines": [
            {"ref": f"C{index}-S1", "subtitle": item["sentences"][0]["text"], "role": "product"}
            for index, item in enumerate(transcripts, 1)
        ]}]}
        with patch.object(script_agent.llm, "chat", return_value=json.dumps(response)) as chat:
            scripts = script_agent.generate("全部素材", transcripts)
        chat.assert_called_once()
        messages = chat.call_args.args[0]
        body = messages[1]["content"]
        for index, item in enumerate(transcripts, 1):
            self.assertIn(f"### 素材 C{index}：{item['clip']}", body)
            self.assertIn(item["sentences"][0]["text"], body)
        self.assertNotIn("同一组内容不要再出", body)
        self.assertIsNone(chat.call_args.kwargs["max_tokens"])
        self.assertEqual(len(scripts), 1)
        self.assertEqual(len(scripts[0]["lines"]), 75)
        self.assertEqual({line["clip"] for line in scripts[0]["lines"]}, {item["clip"] for item in transcripts})

    def test_similar_words_with_different_facts_and_selected_sources_survive(self):
        transcripts = self.transcripts(3)
        # 后两条即使原话相同也保留模型的来源选择，不由文字相似度二次删句。
        transcripts[2]["sentences"][0]["text"] = transcripts[1]["sentences"][0]["text"]
        result = {"videos": [{"lines": [
            {"ref": "C1-S1"}, {"ref": "C2-S1"}, {"ref": "C3-S1"}, {"ref": "C2-S1"}, {"ref": "C99-S1"},
        ]}]}
        with patch.object(script_agent, "_ask", return_value=result):
            scripts = script_agent.generate("来源", transcripts)
        self.assertEqual([line["ref"] for line in scripts[0]["lines"]], ["C1-S1", "C2-S1", "C3-S1"])

    def test_prompt_requires_full_source_coverage_and_has_no_source_or_supplement_count_cap(self):
        prompt = script_agent.system_prompt()
        self.assertIn("先完整扫描所有素材和所有识别句子", prompt)
        self.assertIn("不设置素材数量上限", prompt)
        self.assertIn("不限制补充句数", prompt)
        self.assertIn("覆盖：回看每一条原素材的有效信息清单", prompt)
        self.assertNotIn("最多用 3 条素材", prompt)
        self.assertNotIn("最多用 4 条素材", prompt)
        self.assertNotIn("可以借一两句", prompt)
        self.assertNotIn("通常聚焦 1–2 只表", prompt)

    def test_empty_input_does_not_call_a_model(self):
        with patch.object(script_agent.llm, "chat") as chat:
            with self.assertRaisesRegex(RuntimeError, "没有有效口播"):
                script_agent.generate("空项目", [])
        chat.assert_not_called()

    def test_model_context_error_is_reported_without_truncating_or_retrying_partial_sources(self):
        transcripts = self.transcripts()
        with patch.object(script_agent.llm, "chat", side_effect=RuntimeError("context length exceeded")) as chat:
            with self.assertRaisesRegex(RuntimeError, "context length exceeded"):
                script_agent.generate("全部素材", transcripts)
        chat.assert_called_once()
        self.assertIn(transcripts[-1]["sentences"][0]["text"], chat.call_args.args[0][1]["content"])

    def test_unlimited_script_request_omits_output_budget_and_other_callers_keep_their_budget(self):
        create = Mock(return_value=SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))]))
        client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
        with patch.object(llm, "_client", return_value=client), patch.object(llm, "models", return_value=["primary"]):
            self.assertEqual(llm.chat([], max_tokens=None), "ok")
            self.assertNotIn("max_completion_tokens", create.call_args.kwargs)
            self.assertNotIn("max_tokens", create.call_args.kwargs)
            self.assertEqual(llm.chat([], max_tokens=2400), "ok")
            self.assertEqual(create.call_args.kwargs["max_completion_tokens"], 2400)


if __name__ == "__main__":
    unittest.main()
