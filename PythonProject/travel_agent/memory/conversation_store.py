import json
from pathlib import Path
from typing import Dict, List

from travel_agent.memory.redaction import redact_text


CONVERSATION_DIR = Path(__file__).with_name("conversations")
MAX_MESSAGES = 20
DEFAULT_USER_ID = "local"


def _safe_id(value: str, default: str) -> str:
    safe_value = "".join(
        char for char in str(value) if char.isalnum() or char in ("-", "_")
    ).strip()
    return safe_value or default


def _conversation_path(session_id: str, user_id: str = DEFAULT_USER_ID) -> Path:
    safe_user_id = _safe_id(user_id, DEFAULT_USER_ID)
    safe_session_id = _safe_id(session_id, "default")
    return CONVERSATION_DIR / safe_user_id / f"{safe_session_id}.json"


def load_conversation(session_id: str, user_id: str = DEFAULT_USER_ID) -> List[Dict[str, str]]:
    path = _conversation_path(session_id, user_id)
    if not path.exists() and user_id == DEFAULT_USER_ID:
        legacy_path = CONVERSATION_DIR / f"{_safe_id(session_id, 'default')}.json"
        if legacy_path.exists():
            path = legacy_path
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


def save_conversation(
    session_id: str,
    messages: List[Dict[str, str]],
    user_id: str = DEFAULT_USER_ID,
) -> None:
    trimmed = messages[-MAX_MESSAGES:]
    path = _conversation_path(session_id, user_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(trimmed, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def append_turn(
    session_id: str,
    user_input: str,
    assistant_output: str,
    user_id: str = DEFAULT_USER_ID,
) -> List[Dict[str, str]]:
    messages = load_conversation(session_id, user_id)
    messages.extend(
        [
            {"role": "user", "content": redact_text(user_input)},
            {"role": "assistant", "content": redact_text(assistant_output)},
        ]
    )
    save_conversation(session_id, messages, user_id)
    return messages[-MAX_MESSAGES:]
