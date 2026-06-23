import json
from pathlib import Path
from typing import Dict, List


CONVERSATION_DIR = Path(__file__).with_name("conversations")
MAX_MESSAGES = 20


def _conversation_path(session_id: str) -> Path:
    safe_session_id = "".join(
        char for char in session_id if char.isalnum() or char in ("-", "_")
    ).strip()
    if not safe_session_id:
        safe_session_id = "default"
    return CONVERSATION_DIR / f"{safe_session_id}.json"


def load_conversation(session_id: str) -> List[Dict[str, str]]:
    path = _conversation_path(session_id)
    if not path.exists():
        return []
    try:
        messages = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    if not isinstance(messages, list):
        return []
    return [
        {"role": str(item.get("role", "")), "content": str(item.get("content", ""))}
        for item in messages
        if isinstance(item, dict) and item.get("role") and item.get("content")
    ][-MAX_MESSAGES:]


def save_conversation(session_id: str, messages: List[Dict[str, str]]) -> None:
    CONVERSATION_DIR.mkdir(parents=True, exist_ok=True)
    trimmed = messages[-MAX_MESSAGES:]
    _conversation_path(session_id).write_text(
        json.dumps(trimmed, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def append_turn(session_id: str, user_input: str, assistant_output: str) -> List[Dict[str, str]]:
    messages = load_conversation(session_id)
    messages.extend(
        [
            {"role": "user", "content": user_input},
            {"role": "assistant", "content": assistant_output},
        ]
    )
    save_conversation(session_id, messages)
    return messages[-MAX_MESSAGES:]
