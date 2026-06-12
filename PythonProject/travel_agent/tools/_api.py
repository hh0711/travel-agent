import json
import os
from typing import Any, Dict, Iterable, List, Optional

import requests


def env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def provider_message(
    provider: str,
    status: str,
    message: str,
    required_env: Optional[Iterable[str]] = None,
) -> Dict[str, Any]:
    result: Dict[str, Any] = {
        "provider": provider,
        "status": status,
        "message": message,
    }
    if required_env:
        result["required_env"] = list(required_env)
    return result


def request_json(
    method: str,
    url: str,
    *,
    params: Optional[Dict[str, Any]] = None,
    json_body: Optional[Dict[str, Any]] = None,
    headers: Optional[Dict[str, str]] = None,
    timeout: int = 10,
) -> Dict[str, Any]:
    response = requests.request(
        method=method.upper(),
        url=url,
        params=params,
        json=json_body,
        headers=headers,
        timeout=timeout,
    )
    response.raise_for_status()
    if not response.content:
        return {}
    return response.json()


def get_by_path(data: Any, path: str) -> Any:
    current = data
    for part in path.split("."):
        if isinstance(current, dict) and part in current:
            current = current[part]
            continue
        return None
    return current


def first_list(data: Any, paths: Iterable[str]) -> List[Any]:
    for path in paths:
        value = get_by_path(data, path)
        if isinstance(value, list):
            return value
    if isinstance(data, list):
        return data
    return []


def first_value(item: Dict[str, Any], keys: Iterable[str], default: Any = None) -> Any:
    for key in keys:
        value = get_by_path(item, key)
        if value not in (None, ""):
            return value
    return default


def compact_json(data: Any, max_chars: int = 1800) -> str:
    text = json.dumps(data, ensure_ascii=False)
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 3] + "..."


def auth_headers(prefix: str) -> Dict[str, str]:
    headers: Dict[str, str] = {}
    token = os.getenv(f"{prefix}_ACCESS_TOKEN")
    if token:
        scheme = os.getenv(f"{prefix}_AUTH_SCHEME", "Bearer")
        headers["Authorization"] = f"{scheme} {token}".strip()

    key = os.getenv(f"{prefix}_API_KEY")
    key_header = os.getenv(f"{prefix}_KEY_HEADER")
    if key and key_header:
        headers[key_header] = key

    headers_json = os.getenv(f"{prefix}_HEADERS_JSON")
    if headers_json:
        try:
            extra_headers = json.loads(headers_json)
        except json.JSONDecodeError:
            extra_headers = {}
        if isinstance(extra_headers, dict):
            headers.update({str(k): str(v) for k, v in extra_headers.items()})
    return headers
