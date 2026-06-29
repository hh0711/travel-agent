import json
import re
from typing import Any


SECRET_KEYS = (
    "api_key",
    "apikey",
    "access_token",
    "token",
    "secret",
    "password",
    "key",
)


def redact_text(text: str) -> str:
    redacted = str(text)
    redacted = re.sub(r"1[3-9]\d{9}", "[REDACTED_PHONE]", redacted)
    redacted = re.sub(r"\b\d{17}[\dXx]\b", "[REDACTED_ID]", redacted)
    redacted = re.sub(
        r"(?i)\b(api[_-]?key|access[_-]?token|token|secret|password)\s*[:=]\s*[^\s,，;；]+",
        r"\1=[REDACTED]",
        redacted,
    )
    redacted = re.sub(r"\b[A-Za-z0-9_\-]{32,}\b", "[REDACTED_SECRET]", redacted)
    return redacted


def redact_data(data: Any) -> Any:
    if isinstance(data, dict):
        result = {}
        for key, value in data.items():
            key_text = str(key)
            if any(secret in key_text.lower() for secret in SECRET_KEYS):
                result[key] = "[REDACTED]"
            else:
                result[key] = redact_data(value)
        return result
    if isinstance(data, list):
        return [redact_data(item) for item in data]
    if isinstance(data, str):
        return redact_text(data)
    return data


def redact_json_text(data: Any, *, indent: int = 2) -> str:
    return json.dumps(redact_data(data), ensure_ascii=False, indent=indent)
