import os
import shutil
import tempfile
import unittest
from pathlib import Path

from travel_agent.graph import _get_weather_with_fallback
from travel_agent.memory.conversation_store import append_turn, load_conversation
from travel_agent.memory.profile_store import load_profile, update_profile
from travel_agent.memory.redaction import redact_data, redact_text
from travel_agent.rag.obsidian_knowledge import (
    initialize_knowledge_base,
    retrieve_knowledge,
    save_turn_knowledge,
)
from travel_agent.tools.meituan_parser import extract_meituan_entities


class CoreBehaviorTest(unittest.TestCase):
    def test_extract_meituan_entities(self) -> None:
        result = extract_meituan_entities(
            {
                "status": "ok",
                "content": """
                [苏州花惜美拾酒店](https://hotel.example) 美团真实评分4.8 ¥1XX起
                [松鼠桂鱼](https://food.example) 苏帮菜经典
                [拙政园](https://spot.example) 江南园林
                """,
            }
        )
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["hotels"][0]["title"], "苏州花惜美拾酒店")
        self.assertEqual(result["restaurants"][0]["title"], "松鼠桂鱼")
        self.assertEqual(result["scenic_spots"][0]["title"], "拙政园")

    def test_weather_fallback_from_meituan(self) -> None:
        weather = _get_weather_with_fallback(
            "苏州",
            2,
            {"content": "6月27日多云29度，6月28日晴天28度"},
            {
                "provider": "weatherdt",
                "status": "config_required",
                "message": "missing",
            },
        )
        self.assertEqual(weather["provider"], "meituan_travel_weather")
        self.assertIn("6月27日多云，29℃", weather["summary"])

    def test_redaction(self) -> None:
        self.assertIn("[REDACTED_PHONE]", redact_text("电话 13812345678"))
        redacted = redact_data({"access_token": "abc", "nested": {"phone": "13812345678"}})
        self.assertEqual(redacted["access_token"], "[REDACTED]")
        self.assertEqual(redacted["nested"]["phone"], "[REDACTED_PHONE]")

    def test_user_scoped_memory(self) -> None:
        user_id = "test_user_scope"
        session_id = "test_session_scope"
        try:
            update_profile({"food": "本地菜"}, user_id)
            self.assertEqual(load_profile(user_id)["food"], "本地菜")

            append_turn(session_id, "我喜欢少辣", "已记录", user_id)
            history = load_conversation(session_id, user_id)
            self.assertEqual(history[-2]["content"], "我喜欢少辣")
            self.assertEqual(load_conversation(session_id, "another_user"), [])
        finally:
            base = Path(__file__).parents[1] / "travel_agent" / "memory"
            shutil.rmtree(base / "conversations" / user_id, ignore_errors=True)
            profile_path = base / "profiles" / f"{user_id}.json"
            if profile_path.exists():
                profile_path.unlink()

    def test_obsidian_rag_write_and_retrieve(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            old_path = os.environ.get("OBSIDIAN_VAULT_PATH")
            os.environ["OBSIDIAN_VAULT_PATH"] = tmpdir
            try:
                initialize_knowledge_base()
                Path(tmpdir, "10_Cities", "苏州.md").write_text(
                    "# 苏州\n\n## 经典路线\n拙政园 -> 平江路\n",
                    encoding="utf-8",
                )
                retrieved = retrieve_knowledge(query="苏州两日游", destination="苏州")
                self.assertTrue(retrieved["documents"])

                saved = save_turn_knowledge(
                    {
                        "user_id": "u1",
                        "session_id": "s1",
                        "user_input": "苏州两日游",
                        "destination": "苏州",
                        "days": 2,
                        "weather": {"status": "ok", "provider": "test"},
                        "meituan_travel": {"status": "ok"},
                        "social_search": {"status": "config_required"},
                        "transport_options": [],
                    },
                    "测试回答 access_token=secret123456789012345678901234567890",
                )
                self.assertTrue(Path(saved["trip_note_path"]).exists())
                self.assertIn("[REDACTED]", Path(saved["trip_note_path"]).read_text(encoding="utf-8"))
            finally:
                if old_path is None:
                    os.environ.pop("OBSIDIAN_VAULT_PATH", None)
                else:
                    os.environ["OBSIDIAN_VAULT_PATH"] = old_path


if __name__ == "__main__":
    unittest.main()
