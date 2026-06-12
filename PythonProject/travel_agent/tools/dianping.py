import hashlib
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


def _business_search_url() -> Optional[str]:
    url = os.getenv("DIANPING_BUSINESS_SEARCH_URL")
    if url:
        return url

    base_url = os.getenv("DIANPING_BASE_URL")
    if not base_url:
        return None

    path = os.getenv("DIANPING_BUSINESS_SEARCH_PATH", "/v1/business/search")
    return f"{base_url.rstrip('/')}/{path.lstrip('/')}"


def _load_extra_params() -> Dict[str, Any]:
    raw = os.getenv("DIANPING_PARAMS_JSON")
    if not raw:
        return {}
    try:
        params = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    if not isinstance(params, dict):
        return {}
    return params


def _add_signature(params: Dict[str, Any]) -> Dict[str, Any]:
    secret = os.getenv("DIANPING_APP_SECRET") or os.getenv("DIANPING_API_SECRET")
    mode = os.getenv("DIANPING_SIGN_MODE", "").lower()
    if not secret or not mode:
        return params

    unsigned = {k: v for k, v in params.items() if k != os.getenv("DIANPING_SIGN_PARAM", "sign")}
    sorted_text = "".join(f"{key}{unsigned[key]}" for key in sorted(unsigned))

    if mode == "sha1_sorted_secret_suffix":
        source = f"{sorted_text}{secret}"
    elif mode == "sha1_secret_wrap":
        source = f"{secret}{sorted_text}{secret}"
    else:
        return params

    signed = dict(params)
    signed[os.getenv("DIANPING_SIGN_PARAM", "sign")] = hashlib.sha1(
        source.encode("utf-8")
    ).hexdigest().upper()
    return signed


def _normalize_businesses(raw: Dict[str, Any], limit: int) -> List[Dict[str, Any]]:
    items = first_list(
        raw,
        (
            "data.businesses",
            "data.shops",
            "data.list",
            "data.items",
            "result.businesses",
            "result.shops",
            "result.list",
            "businesses",
            "shops",
            "items",
        ),
    )

    normalized: List[Dict[str, Any]] = []
    for item in items[:limit]:
        if not isinstance(item, dict):
            continue
        normalized.append(
            {
                "name": first_value(item, ("name", "shop_name", "business_name", "title")),
                "address": first_value(item, ("address", "addr", "shop_address")),
                "category": first_value(item, ("category", "category_name", "cate_name")),
                "rating": first_value(item, ("rating", "avg_rating", "score", "shop_power")),
                "avg_price": first_value(
                    item,
                    ("avg_price", "average_price", "price", "per_capita", "avgPrice"),
                ),
                "distance": first_value(item, ("distance", "distance_text")),
                "tags": first_value(item, ("tags", "tag", "recommend_tags"), []),
                "url": first_value(item, ("url", "shop_url", "business_url", "share_url")),
            }
        )
    return normalized


def search_dianping_businesses(
    destination: str,
    *,
    category: str,
    keyword: str = "",
    limit: Optional[int] = None,
) -> Dict[str, Any]:
    if not destination:
        return provider_message("dianping", "skipped", "缺少目的地，未查询大众点评。")

    url = _business_search_url()
    if not url:
        return provider_message(
            "dianping",
            "config_required",
            "未配置大众点评商户搜索接口地址。",
            required_env=("DIANPING_BUSINESS_SEARCH_URL",),
        )

    max_results = limit or env_int("DIANPING_LIMIT", 6)
    params: Dict[str, Any] = {
        os.getenv("DIANPING_CITY_PARAM", "city"): destination,
        os.getenv("DIANPING_CATEGORY_PARAM", "category"): category,
        os.getenv("DIANPING_LIMIT_PARAM", "limit"): max_results,
    }
    if keyword:
        params[os.getenv("DIANPING_KEYWORD_PARAM", "keyword")] = keyword

    app_key = os.getenv("DIANPING_APP_KEY") or os.getenv("DIANPING_API_KEY")
    if app_key:
        params[os.getenv("DIANPING_APP_KEY_PARAM", "appkey")] = app_key

    params.update(_load_extra_params())
    params = _add_signature(params)

    method = os.getenv("DIANPING_METHOD", "GET").upper()
    try:
        raw = request_json(
            method,
            url,
            params=params if method == "GET" else None,
            json_body=params if method != "GET" else None,
            headers=auth_headers("DIANPING"),
            timeout=env_int("DIANPING_TIMEOUT", 10),
        )
    except Exception as exc:
        return provider_message("dianping", "error", f"大众点评接口调用失败：{exc}")

    return {
        "provider": "dianping",
        "status": "ok",
        "destination": destination,
        "category": category,
        "keyword": keyword,
        "items": _normalize_businesses(raw, max_results),
    }
