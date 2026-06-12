import json
import os
from typing import Any, Dict, List, Optional

from travel_agent.tools._api import (
    auth_headers,
    env_int,
    first_list,
    first_value,
    provider_message,
    request_json,
)


def _search_url() -> Optional[str]:
    url = os.getenv("XHS_SEARCH_URL")
    if url:
        return url

    base_url = os.getenv("XHS_BASE_URL")
    if not base_url:
        return None

    path = os.getenv("XHS_SEARCH_PATH", "/search")
    return f"{base_url.rstrip('/')}/{path.lstrip('/')}"


def _load_extra_params() -> Dict[str, Any]:
    raw = os.getenv("XHS_PARAMS_JSON")
    if not raw:
        return {}
    try:
        params = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    if not isinstance(params, dict):
        return {}
    return params


def _normalize_notes(raw: Dict[str, Any], limit: int) -> List[Dict[str, Any]]:
    items = first_list(
        raw,
        (
            "data.notes",
            "data.items",
            "data.list",
            "result.notes",
            "result.items",
            "result.list",
            "notes",
            "items",
        ),
    )

    notes: List[Dict[str, Any]] = []
    for item in items[:limit]:
        if not isinstance(item, dict):
            continue
        notes.append(
            {
                "title": first_value(item, ("title", "note_title", "display_title")),
                "summary": first_value(
                    item,
                    ("summary", "desc", "description", "content", "note_desc"),
                ),
                "author": first_value(item, ("author.nickname", "author", "user.nickname")),
                "liked_count": first_value(
                    item,
                    ("liked_count", "like_count", "likes", "interact_info.liked_count"),
                ),
                "collected_count": first_value(
                    item,
                    ("collected_count", "collect_count", "favorites"),
                ),
                "url": first_value(item, ("url", "share_url", "link", "note_url")),
                "publish_time": first_value(
                    item,
                    ("publish_time", "time", "create_time", "created_at"),
                ),
            }
        )
    return notes


def search_xiaohongshu(destination: str, preferences: Dict[str, Any]) -> Dict[str, Any]:
    if not destination:
        return provider_message("xiaohongshu", "skipped", "缺少目的地，未搜索小红书。")

    url = _search_url()
    if not url:
        return provider_message(
            "xiaohongshu",
            "config_required",
            "未配置小红书授权搜索接口地址。",
            required_env=("XHS_SEARCH_URL", "XHS_ACCESS_TOKEN"),
        )

    query_parts = [destination, "旅行攻略"]
    travel_time = preferences.get("travel_time") or preferences.get("出行时间")
    food_pref = preferences.get("food") or preferences.get("餐饮") or preferences.get("美食")
    hotel_pref = preferences.get("hotel") or preferences.get("住宿")
    for part in (travel_time, food_pref, hotel_pref):
        if part:
            query_parts.append(str(part))
    query = " ".join(query_parts)

    limit = env_int("XHS_LIMIT", 8)
    params: Dict[str, Any] = {
        os.getenv("XHS_QUERY_PARAM", "keyword"): query,
        os.getenv("XHS_LIMIT_PARAM", "limit"): limit,
    }
    params.update(_load_extra_params())

    api_key = os.getenv("XHS_API_KEY")
    if api_key:
        params[os.getenv("XHS_KEY_PARAM", "key")] = api_key

    method = os.getenv("XHS_METHOD", "GET").upper()
    try:
        raw = request_json(
            method,
            url,
            params=params if method == "GET" else None,
            json_body=params if method != "GET" else None,
            headers=auth_headers("XHS"),
            timeout=env_int("XHS_TIMEOUT", 10),
        )
    except Exception as exc:
        return provider_message("xiaohongshu", "error", f"小红书搜索接口调用失败：{exc}")

    return {
        "provider": "xiaohongshu",
        "status": "ok",
        "destination": destination,
        "query": query,
        "notes": _normalize_notes(raw, limit),
    }
