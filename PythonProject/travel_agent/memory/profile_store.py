import json
from pathlib import Path
from typing import Any, Dict


PROFILE_PATH = Path(__file__).with_name("profile.json")
PROFILE_DIR = Path(__file__).with_name("profiles")
DEFAULT_USER_ID = "local"


def _safe_user_id(user_id: str) -> str:
    safe_user_id = "".join(
        char for char in str(user_id) if char.isalnum() or char in ("-", "_")
    ).strip()
    return safe_user_id or DEFAULT_USER_ID


def _profile_path(user_id: str = DEFAULT_USER_ID) -> Path:
    return PROFILE_DIR / f"{_safe_user_id(user_id)}.json"


def load_profile(user_id: str = DEFAULT_USER_ID) -> Dict[str, Any]:
    path = _profile_path(user_id)
    if not path.exists() and user_id == DEFAULT_USER_ID and PROFILE_PATH.exists():
        path = PROFILE_PATH
    if not path.exists():
        return {}
    try:
        profile = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    if not isinstance(profile, dict):
        return {}
    return profile


def save_profile(profile: Dict[str, Any], user_id: str = DEFAULT_USER_ID) -> None:
    path = _profile_path(user_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(profile, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def update_profile(updates: Dict[str, Any], user_id: str = DEFAULT_USER_ID) -> Dict[str, Any]:
    profile = load_profile(user_id)
    for key, value in updates.items():
        if value not in (None, "", [], {}):
            profile[key] = value
    save_profile(profile, user_id)
    return profile
