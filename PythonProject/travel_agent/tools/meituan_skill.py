import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv

from travel_agent.tools._api import (
    auth_headers,
    env_int,
    first_list,
    first_value,
    provider_message,
    request_json,
)

load_dotenv()


def _skill_url() -> Optional[str]:
    url = os.getenv("MEITUAN_SKILL_URL")
    if url:
        return url

    base_url = os.getenv("MEITUAN_SKILL_BASE_URL")
    if not base_url:
        return None

    path = os.getenv("MEITUAN_SKILL_PATH", "/skills")
    return f"{base_url.rstrip('/')}/{path.lstrip('/')}"


def _load_extra_params() -> Dict[str, Any]:
    raw = os.getenv("MEITUAN_SKILL_PARAMS_JSON")
    if not raw:
        return {}
    try:
        params = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    if not isinstance(params, dict):
        return {}
    return params


def _load_command() -> List[str]:
    raw = os.getenv("MEITUAN_SKILL_COMMAND_JSON")
    if not raw:
        return []
    try:
        command = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(command, list):
        return []
    return [str(part) for part in command if str(part).strip()]


def _token_config_path() -> Path:
    configured = os.getenv("MEITUAN_TRAVEL_CONFIG_PATH")
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".config" / "meituan-travel" / "config.json"


def _ensure_mttravel_token() -> Optional[Dict[str, Any]]:
    config_path = _token_config_path()
    if config_path.exists():
        try:
            config = json.loads(config_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            config = {}
        if isinstance(config, dict) and str(config.get("key") or "").strip():
            return None

    token = os.getenv("MEITUAN_SKILL_ACCESS_TOKEN")
    if not token:
        return provider_message(
            "meituan_travel_skill",
            "config_required",
            "未配置美团旅行助手 Token。请在美团开发者中心创建 Token 后，写入 MEITUAN_SKILL_ACCESS_TOKEN 或 ~/.config/meituan-travel/config.json。",
            required_env=("MEITUAN_SKILL_ACCESS_TOKEN",),
        )

    config_path.parent.mkdir(parents=True, exist_ok=True)
    with config_path.open("w", encoding="utf-8", newline="") as file:
        json.dump({"key": token}, file, ensure_ascii=False)
    return None


def _origin_city(payload: Dict[str, Any]) -> str:
    preferences = payload.get("preferences") or {}
    if not isinstance(preferences, dict):
        preferences = {}
    return (
        str(
            payload.get("origin_city")
            or preferences.get("origin_city")
            or preferences.get("departure_city")
            or preferences.get("departure")
            or preferences.get("出发地")
            or preferences.get("当前城市")
            or os.getenv("MEITUAN_DEFAULT_CITY")
            or "北京"
        ).strip()
        or "北京"
    )


def _query_text(payload: Dict[str, Any]) -> str:
    query = payload.get("user_query") or payload.get("query")
    if query:
        return str(query)

    destination = payload.get("destination") or ""
    keyword = payload.get("keyword") or ""
    budget = payload.get("budget")
    intent = payload.get("intent") or "travel"
    parts = [str(destination), str(keyword), str(intent)]
    if budget:
        parts.append(f"预算{budget}")
    return " ".join(part for part in parts if part).strip()


def _mttravel_cli_candidates() -> List[str]:
    configured = os.getenv("MEITUAN_TRAVEL_CLI")
    if configured:
        candidates = [configured]
        if os.name == "nt" and not Path(configured).is_absolute():
            candidates.append(str(Path.home() / "AppData" / "Roaming" / "npm" / configured))
        return candidates
    if os.name == "nt":
        npm_dir = Path.home() / "AppData" / "Roaming" / "npm"
        return [
            "mttravel.cmd",
            str(npm_dir / "mttravel.cmd"),
            "mttravel",
            str(npm_dir / "mttravel"),
        ]
    return ["mttravel"]


def _mttravel_env() -> Dict[str, str]:
    env = dict(os.environ)
    if os.name != "nt":
        return env

    extra_paths = [
        r"C:\Program Files\nodejs",
        str(Path.home() / "AppData" / "Roaming" / "npm"),
    ]
    existing_path = env.get("Path") or env.get("PATH") or ""
    missing_paths = [path for path in extra_paths if path and path not in existing_path]
    if missing_paths:
        env["Path"] = ";".join(missing_paths + [existing_path])
    return env


def _normalize_items(raw: Dict[str, Any], limit: int) -> List[Dict[str, Any]]:
    items = first_list(
        raw,
        (
            "data.items",
            "data.list",
            "data.results",
            "result.items",
            "result.list",
            "result.results",
            "items",
            "list",
            "results",
        ),
    )

    normalized: List[Dict[str, Any]] = []
    for item in items[:limit]:
        if not isinstance(item, dict):
            continue
        normalized.append(
            {
                "name": first_value(item, ("name", "title", "shop_name", "business_name")),
                "address": first_value(item, ("address", "addr", "shop_address")),
                "category": first_value(item, ("category", "category_name", "cate_name")),
                "rating": first_value(item, ("rating", "score", "avg_rating", "shop_power")),
                "avg_price": first_value(
                    item,
                    ("avg_price", "average_price", "price", "per_capita", "avgPrice"),
                ),
                "distance": first_value(item, ("distance", "distance_text")),
                "tags": first_value(item, ("tags", "tag", "recommend_tags"), []),
                "url": first_value(item, ("url", "share_url", "link", "business_url")),
            }
        )
    return normalized


def _extract_markdown_links(text: str) -> List[Dict[str, str]]:
    links: List[Dict[str, str]] = []
    seen = set()
    for match in re.finditer(r"(?<!!)\[([^\]]+)\]\((https?://[^)]+)\)", text):
        title = re.sub(r"[*_`\\]", "", match.group(1)).strip()
        url = match.group(2).strip()
        key = (title, url)
        if not title or key in seen:
            continue
        seen.add(key)
        links.append({"title": title, "url": url})
    return links


def _extract_markdown_images(text: str) -> List[Dict[str, str]]:
    images: List[Dict[str, str]] = []
    seen = set()
    for match in re.finditer(r"!\[([^\]]*)\]\((https?://[^)]+)\)", text):
        title = re.sub(r"[*_`\\]", "", match.group(1)).strip() or "image"
        url = match.group(2).strip()
        key = (title, url)
        if key in seen:
            continue
        seen.add(key)
        images.append({"title": title, "url": url})
    return images


def _build_skill_request(tool_name: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    tool_param = os.getenv("MEITUAN_SKILL_TOOL_PARAM", "tool")
    input_param = os.getenv("MEITUAN_SKILL_INPUT_PARAM", "input")
    skill_id_param = os.getenv("MEITUAN_SKILL_ID_PARAM", "skill_id")
    skill_id = os.getenv("MEITUAN_SKILL_ID", "12")

    body: Dict[str, Any] = {
        tool_param: tool_name,
        input_param: payload,
    }
    if skill_id:
        body[skill_id_param] = skill_id
    body.update(_load_extra_params())
    return body


def _invoke_mttravel_cli(
    tool_name: str,
    payload: Dict[str, Any],
    *,
    provider: str,
) -> Dict[str, Any]:
    token_error = _ensure_mttravel_token()
    if token_error:
        token_error["provider"] = provider
        return token_error

    city = _origin_city(payload)
    query = _query_text(payload)
    if not query:
        return provider_message(provider, "skipped", "缺少美团旅行助手查询内容。")

    cli_candidates = _mttravel_cli_candidates()
    last_missing: Optional[FileNotFoundError] = None
    try:
        for cli in cli_candidates:
            command = [cli, city, query]
            try:
                completed = subprocess.run(
                    command,
                    capture_output=True,
                    encoding="utf-8",
                    env=_mttravel_env(),
                    timeout=env_int("MEITUAN_SKILL_TIMEOUT", 150),
                    check=False,
                )
                break
            except FileNotFoundError as exc:
                last_missing = exc
        else:
            raise last_missing or FileNotFoundError(cli_candidates[0])
    except FileNotFoundError:
        return provider_message(
            provider,
            "config_required",
            "未找到 mttravel CLI。请先执行 npm.cmd i -g @meituan-travel/travel-cli，或配置 MEITUAN_TRAVEL_CLI。",
            required_env=("MEITUAN_TRAVEL_CLI",),
        )
    except subprocess.TimeoutExpired:
        return provider_message(provider, "timeout", "请求超时啦，当前查询人数较多，请换个问法或稍后再试。")
    except Exception as exc:
        return provider_message(provider, "error", f"美团旅行助手 CLI 执行失败：{exc}")

    stdout = completed.stdout.strip()
    stderr = completed.stderr.strip()
    auth_keywords = ("鉴权失败", "无效的访问令牌", "Token", "未设置", "access token", "key")
    if completed.returncode != 0:
        message = stderr or stdout or "mttravel 返回非 0 状态。"
        status = "auth_required" if any(keyword in message for keyword in auth_keywords) else "error"
        return provider_message(provider, status, message)

    raw: Dict[str, Any] = {"content": stdout}
    try:
        parsed = json.loads(stdout)
    except json.JSONDecodeError:
        parsed = None
    if isinstance(parsed, dict):
        raw = parsed

    return {
        "provider": provider,
        "status": "ok",
        "mode": "cli",
        "tool": tool_name,
        "city": city,
        "query": query,
        "raw": raw,
        "content": stdout,
        "links": _extract_markdown_links(stdout),
        "image_links": _extract_markdown_images(stdout),
        "items": _normalize_items(raw, env_int("MEITUAN_SKILL_LIMIT", 6)),
    }


def _invoke_http_skill(
    tool_name: str,
    payload: Dict[str, Any],
    *,
    provider: str,
) -> Dict[str, Any]:
    url = _skill_url()
    if not url:
        return provider_message(
            provider,
            "config_required",
            "未配置美团酒旅 Skill HTTP 调用入口。",
            required_env=("MEITUAN_SKILL_URL",),
        )

    method = os.getenv("MEITUAN_SKILL_METHOD", "POST").upper()
    body = _build_skill_request(tool_name, payload)

    try:
        raw = request_json(
            method,
            url,
            params=body if method == "GET" else None,
            json_body=body if method != "GET" else None,
            headers=auth_headers("MEITUAN_SKILL"),
            timeout=env_int("MEITUAN_SKILL_TIMEOUT", 10),
        )
    except Exception as exc:
        return provider_message(provider, "error", f"美团酒旅 Skill HTTP 调用失败：{exc}")

    return {
        "provider": provider,
        "status": "ok",
        "mode": "http",
        "tool": tool_name,
        "payload": payload,
        "raw": raw,
        "items": _normalize_items(raw, env_int("MEITUAN_SKILL_LIMIT", 6)),
    }


def _invoke_command_skill(
    tool_name: str,
    payload: Dict[str, Any],
    *,
    provider: str,
) -> Dict[str, Any]:
    command = _load_command()
    if not command:
        return provider_message(
            provider,
            "config_required",
            "未配置美团酒旅 Skill 本地命令。",
            required_env=("MEITUAN_SKILL_COMMAND_JSON",),
        )

    body = _build_skill_request(tool_name, payload)
    env = dict(os.environ)
    token = os.getenv("MEITUAN_SKILL_ACCESS_TOKEN")
    if token:
        env["MEITUAN_SKILL_ACCESS_TOKEN"] = token

    try:
        completed = subprocess.run(
            command,
            input=json.dumps(body, ensure_ascii=False),
            capture_output=True,
            encoding="utf-8",
            env=env,
            timeout=env_int("MEITUAN_SKILL_TIMEOUT", 30),
            check=False,
        )
    except Exception as exc:
        return provider_message(provider, "error", f"美团酒旅 Skill 本地命令执行失败：{exc}")

    if completed.returncode != 0:
        message = completed.stderr.strip() or completed.stdout.strip() or "本地 Skill 命令返回非 0 状态。"
        return provider_message(provider, "error", message)

    try:
        raw = json.loads(completed.stdout)
    except json.JSONDecodeError:
        raw = {"content": completed.stdout.strip()}

    return {
        "provider": provider,
        "status": "ok",
        "mode": "command",
        "tool": tool_name,
        "payload": payload,
        "raw": raw,
        "items": _normalize_items(raw, env_int("MEITUAN_SKILL_LIMIT", 6)),
    }


def _invoke_skill(
    tool_name: str,
    payload: Dict[str, Any],
    *,
    provider: str,
) -> Dict[str, Any]:
    mode = os.getenv("MEITUAN_SKILL_MODE", "cli").lower()
    if mode == "cli":
        return _invoke_mttravel_cli(tool_name, payload, provider=provider)
    if mode == "http":
        return _invoke_http_skill(tool_name, payload, provider=provider)
    if mode == "command":
        return _invoke_command_skill(tool_name, payload, provider=provider)

    if mode in {"auto", ""}:
        if _skill_url():
            return _invoke_http_skill(tool_name, payload, provider=provider)
        if _load_command():
            return _invoke_command_skill(tool_name, payload, provider=provider)
        return _invoke_mttravel_cli(tool_name, payload, provider=provider)

    return provider_message(
        provider,
        "config_required",
        "MEITUAN_SKILL_MODE 只支持 cli、command、http 或 auto。",
        required_env=("MEITUAN_SKILL_MODE",),
    )


def search_meituan_restaurants(
    destination: str,
    preferences: Dict[str, Any],
    *,
    keyword: str = "",
) -> Dict[str, Any]:
    food_keyword = keyword or preferences.get("food") or preferences.get("餐饮") or "本地菜"
    payload = {
        "intent": "restaurant_search",
        "destination": destination,
        "keyword": food_keyword,
        "preferences": preferences,
        "limit": env_int("MEITUAN_SKILL_LIMIT", 6),
        "user_query": f"请推荐{destination}适合旅行用餐的餐厅或餐饮区域，偏好：{food_keyword}",
    }
    tool_name = os.getenv("MEITUAN_RESTAURANT_TOOL") or os.getenv(
        "MEITUAN_TRAVEL_ASSISTANT_TOOL", "travel_assistant"
    )
    return _invoke_skill(tool_name, payload, provider="meituan_restaurant_skill")


def search_meituan_hotels(
    destination: str,
    budget: Optional[int],
    preferences: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    preferences = preferences or {}
    hotel_keyword = preferences.get("hotel") or preferences.get("住宿") or "酒店"
    payload = {
        "intent": "hotel_search",
        "destination": destination,
        "budget": budget,
        "preferences": preferences,
        "keyword": hotel_keyword,
        "limit": env_int("MEITUAN_SKILL_LIMIT", 6),
        "user_query": f"请推荐{destination}适合旅行住宿的酒店或住宿区域，预算：{budget or '未提供'}，偏好：{hotel_keyword}",
    }
    tool_name = os.getenv("MEITUAN_HOTEL_TOOL") or os.getenv(
        "MEITUAN_TRAVEL_ASSISTANT_TOOL", "travel_assistant"
    )
    return _invoke_skill(tool_name, payload, provider="meituan_hotel_skill")


def search_meituan_travel(
    destination: str,
    budget: Optional[int],
    preferences: Optional[Dict[str, Any]] = None,
    *,
    days: Optional[int] = None,
) -> Dict[str, Any]:
    preferences = preferences or {}
    food_keyword = (
        preferences.get("food")
        or preferences.get("餐饮")
        or preferences.get("美食")
        or "本地菜、特色菜"
    )
    hotel_keyword = preferences.get("hotel") or preferences.get("住宿") or "酒店"
    travel_time = preferences.get("travel_time") or preferences.get("出行时间") or ""
    people = preferences.get("people") or preferences.get("人数") or ""

    details = [
        f"目的地：{destination}",
        f"天数：{days or '未提供'}",
        f"预算：{budget or '未提供'}",
        f"餐饮偏好：{food_keyword}",
        f"住宿偏好：{hotel_keyword}",
    ]
    if travel_time:
        details.append(f"出行时间：{travel_time}")
    if people:
        details.append(f"人数：{people}")

    payload = {
        "intent": "travel_food_hotel_search",
        "destination": destination,
        "budget": budget,
        "days": days,
        "preferences": preferences,
        "keyword": f"{hotel_keyword}、{food_keyword}",
        "limit": env_int("MEITUAN_SKILL_LIMIT", 6),
        "user_query": (
            "请基于美团真实酒旅数据，推荐适合旅行规划的酒店住宿和本地餐厅，"
            "每一家酒店和餐厅都必须带美团详情页链接，方便用户后续点击跳转；"
            "餐厅请尽量给出5到6家可参考候选，覆盖午餐、晚餐、特色菜、排队或预约提醒；"
            "酒店请尽量给出3到4家可参考候选，并详细说明商圈/地址、距离景点或地铁的便利性、"
            "价格、评分、星级/档次、开业或装修时间、房型/设施亮点、适合人群、推荐理由和链接；"
            + "；".join(details)
        ),
    }
    tool_name = os.getenv("MEITUAN_TRAVEL_ASSISTANT_TOOL", "travel_assistant")
    return _invoke_skill(tool_name, payload, provider="meituan_travel_skill")
