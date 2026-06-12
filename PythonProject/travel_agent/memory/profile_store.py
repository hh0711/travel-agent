import json
from pathlib import Path
from typing import Any, Dict


PROFILE_PATH = Path(__file__).with_name("profile.json")


def load_profile() -> Dict[str, Any]:
    if not PROFILE_PATH.exists():
        return {}
    return json.loads(PROFILE_PATH.read_text(encoding="utf-8"))


def save_profile(profile: Dict[str, Any]) -> None:
    PROFILE_PATH.write_text(
        json.dumps(profile, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

