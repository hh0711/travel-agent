import json
from pathlib import Path
from typing import Any, Dict


PROFILE_PATH = Path(__file__).with_name("profile.json")


def load_profile() -> Dict[str, Any]:
    if not PROFILE_PATH.exists():
        return {}
    try:
        profile = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    if not isinstance(profile, dict):
        return {}
    return profile


def save_profile(profile: Dict[str, Any]) -> None:
    PROFILE_PATH.write_text(
        json.dumps(profile, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def update_profile(updates: Dict[str, Any]) -> Dict[str, Any]:
    profile = load_profile()
    for key, value in updates.items():
        if value not in (None, "", [], {}):
            profile[key] = value
    save_profile(profile)
    return profile
