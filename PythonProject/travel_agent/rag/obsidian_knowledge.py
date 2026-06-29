import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from travel_agent.memory.redaction import redact_data, redact_json_text, redact_text


DEFAULT_VAULT_PATH = "/Users/jimchen/Documents/travel-agent"
MAX_EMBEDDED_PLAN_CHARS = 12000


def vault_path() -> Path:
    return Path(os.getenv("OBSIDIAN_VAULT_PATH", DEFAULT_VAULT_PATH)).expanduser()


def is_enabled() -> bool:
    return os.getenv("OBSIDIAN_KB_ENABLED", "true").lower() not in {"0", "false", "no"}


def _slug(text: str, default: str = "unknown") -> str:
    cleaned = re.sub(r"[\\/:*?\"<>|#^\[\]]+", "-", text.strip())
    cleaned = re.sub(r"\s+", "-", cleaned).strip("-")
    return cleaned or default


def _write_if_missing(path: Path, content: str) -> None:
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _append_section(path: Path, title: str, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    section = f"\n\n## {title}\n\n{content.strip()}\n"
    path.write_text(existing.rstrip() + section, encoding="utf-8")


def _json_block(data: Any) -> str:
    return "```json\n" + redact_json_text(data, indent=2) + "\n```"


def _status(data: Any) -> str:
    if not data:
        return "missing"
    if not isinstance(data, dict):
        return "ok"
    return str(data.get("status") or data.get("provider") or "unknown")


def _meituan_links(meituan_travel: Dict[str, Any], limit: int = 12) -> List[Dict[str, str]]:
    links = meituan_travel.get("links")
    if isinstance(links, list):
        return [link for link in links[:limit] if isinstance(link, dict)]
    return []


def _markdown_files(root: Path) -> Iterable[Path]:
    for path in root.rglob("*.md"):
        if ".obsidian" in path.parts:
            continue
        yield path


def _search_terms(*values: Any) -> List[str]:
    text = " ".join(str(value) for value in values if value)
    terms = re.findall(r"[\u4e00-\u9fff]{2,}|[A-Za-z0-9_]{2,}", text)
    seen = set()
    result = []
    for term in terms:
        normalized = term.lower()
        if normalized in seen:
            continue
        seen.add(normalized)
        result.append(term)
    return result[:24]


def _score_text(text: str, terms: List[str]) -> int:
    lower_text = text.lower()
    score = 0
    for term in terms:
        score += lower_text.count(term.lower())
    return score


def _snippet(text: str, terms: List[str], max_chars: int = 700) -> str:
    lower_text = text.lower()
    first_index = -1
    for term in terms:
        index = lower_text.find(term.lower())
        if index != -1 and (first_index == -1 or index < first_index):
            first_index = index
    if first_index == -1:
        return text[:max_chars].strip()
    start = max(first_index - 180, 0)
    end = min(start + max_chars, len(text))
    return text[start:end].strip()


def retrieve_knowledge(
    *,
    query: str,
    destination: str = "",
    preferences: Optional[Dict[str, Any]] = None,
    limit: int = 5,
) -> Dict[str, Any]:
    if not is_enabled():
        return {"enabled": False, "context": "", "documents": []}

    initialize_knowledge_base()
    root = vault_path()
    terms = _search_terms(query, destination, json.dumps(preferences or {}, ensure_ascii=False))
    if not terms:
        return {"enabled": True, "context": "", "documents": []}

    scored = []
    for path in _markdown_files(root):
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        score = _score_text(text, terms)
        if destination and destination in path.stem:
            score += 5
        if path.parts and "50_Planning_Rules" in path.parts:
            score += 2
        if score <= 0:
            continue
        scored.append((score, path, text))

    scored.sort(key=lambda item: item[0], reverse=True)
    documents = []
    for score, path, text in scored[:limit]:
        documents.append(
            {
                "path": str(path),
                "title": path.stem,
                "score": score,
                "snippet": _snippet(text, terms),
            }
        )

    context_parts = []
    for doc in documents:
        context_parts.append(
            f"来源：{doc['path']}\n标题：{doc['title']}\n片段：{doc['snippet']}"
        )
    return {
        "enabled": True,
        "terms": terms,
        "context": "\n\n---\n\n".join(context_parts),
        "documents": documents,
    }


def initialize_knowledge_base() -> Dict[str, str]:
    root = vault_path()
    root.mkdir(parents=True, exist_ok=True)

    dirs = {
        "inbox": root / "00_Inbox",
        "cities": root / "10_Cities",
        "trips": root / "20_Trips",
        "preferences": root / "30_User_Preferences",
        "sources": root / "40_Data_Sources",
        "rules": root / "50_Planning_Rules",
        "templates": root / "90_Templates",
        "agent": root / "_TravelAgent",
    }
    for path in dirs.values():
        path.mkdir(parents=True, exist_ok=True)

    _write_if_missing(
        dirs["templates"] / "城市攻略模板.md",
        """# {{城市}}攻略

## 适合人群

## 经典路线

## 雨天备选

## 本地美食

## 住宿区域

## 交通动线

## 避坑提醒
""",
    )
    _write_if_missing(
        dirs["templates"] / "行程沉淀模板.md",
        """# {{目的地}}行程沉淀

## 用户需求

## 可复用经验

## 实时数据来源

## 后续待补充
""",
    )
    _write_if_missing(
        dirs["rules"] / "旅行规划规则.md",
        """# 旅行规划规则

## 数据优先级

1. 美团 CLI、WeatherDT 等实时接口返回的数据。
2. Obsidian 知识库中已验证的城市经验和规划规则。
3. 用户长期偏好和历史对话。
4. LLM 常识推理。

## 约束

- 不把知识库中的旧价格、旧评分、旧营业时间当作实时数据。
- 具体酒店、餐厅、价格、评分、链接优先使用实时工具返回。
- 没有链接的餐厅或酒店只能作为区域或类型参考。
- 每天行程避免过密，短途旅行优先顺路和少换乘。
""",
    )
    suggestions_path = dirs["agent"] / "知识库完善建议.md"
    _write_if_missing(
        suggestions_path,
        """# 知识库完善建议

## 主动建设清单

- [ ] 为常用目的地补充城市攻略笔记，例如苏州、杭州、上海、南京、北京。
- [ ] 为不同旅行类型补充规则：亲子游、老人同行、情侣周末、预算优先、美食优先。
- [ ] 将真实工具不能稳定返回的经验类内容沉淀到 `50_Planning_Rules/`。
- [ ] 将用户确认过的偏好整理到 `30_User_Preferences/`。
- [ ] 定期检查 `20_Trips/` 中的行程沉淀，把可复用经验迁移到城市攻略或规则库。
- [ ] 不在知识库中保存 API key、token、身份证、手机号等敏感信息。
""",
    )
    return {name: str(path) for name, path in dirs.items()}


def _knowledge_suggestions(state: Dict[str, Any]) -> List[str]:
    suggestions = []
    destination = state.get("destination") or "当前目的地"
    weather = state.get("weather") or {}
    social = state.get("social_search") or {}
    meituan = state.get("meituan_travel") or {}

    if weather.get("provider") == "meituan_travel_weather":
        suggestions.append(f"为{destination}补充 WeatherDT 站号和天气接口配置，减少对美团文本天气的依赖。")
    elif weather.get("status") != "ok":
        suggestions.append(f"补充{destination}天气数据来源，或在城市攻略中加入雨天/高温备选路线。")

    if social.get("status") != "ok":
        suggestions.append(f"补充{destination}小红书/本地游记摘要，沉淀热门玩法、避坑和排队提醒。")

    if meituan.get("status") == "ok":
        links = _meituan_links(meituan)
        if links:
            suggestions.append(f"复核本次美团返回的{len(links)}个链接，把长期有效的街区、景点动线沉淀到城市攻略。")
    else:
        suggestions.append("检查美团 CLI/token 可用性；没有实时链接时，不要把具体商户作为主推。")

    preferences = state.get("preferences") or {}
    if preferences:
        suggestions.append("把用户多次出现的稳定偏好迁移到用户偏好笔记，避免只停留在单次行程里。")

    return suggestions[:6]


def save_turn_knowledge(state: Dict[str, Any], final_answer: str) -> Dict[str, Any]:
    if not is_enabled():
        return {"enabled": False}

    paths = initialize_knowledge_base()
    root = vault_path()
    now = datetime.now()
    safe_state = redact_data(state)
    safe_answer = redact_text(final_answer)
    destination = str(safe_state.get("destination") or "未识别目的地")
    user_id = str(safe_state.get("user_id") or "local")
    session_id = str(safe_state.get("session_id") or "default")
    filename = (
        f"{now.strftime('%Y%m%d-%H%M%S')}-{_slug(destination)}-"
        f"{_slug(user_id)}-{_slug(session_id)}.md"
    )
    trip_path = root / "20_Trips" / filename

    meituan = safe_state.get("meituan_travel") or {}
    links = _meituan_links(meituan)
    suggestions = _knowledge_suggestions(state)
    retrieved_docs = safe_state.get("retrieved_docs") or []
    frontmatter = {
        "created": now.isoformat(timespec="seconds"),
        "type": "travel-agent-turn",
        "destination": destination,
        "user_id": user_id,
        "session_id": session_id,
        "intent": safe_state.get("intent"),
        "days": safe_state.get("days"),
        "budget": safe_state.get("budget"),
        "weather_provider": (safe_state.get("weather") or {}).get("provider"),
        "meituan_status": _status(meituan),
        "social_status": _status(safe_state.get("social_search") or {}),
        "tags": ["travel-agent", "auto-knowledge", _slug(destination)],
    }

    plan_text = safe_answer
    if len(plan_text) > MAX_EMBEDDED_PLAN_CHARS:
        plan_text = plan_text[:MAX_EMBEDDED_PLAN_CHARS] + "\n\n...（已截断，完整回答见对话记录）"

    content = f"""---
{redact_json_text(frontmatter, indent=2)}
---

# {destination} 行程沉淀 - {now.strftime('%Y-%m-%d %H:%M')}

## 用户需求

{safe_state.get("user_input", "")}

## 解析结果

- 目的地：{destination}
- 天数：{safe_state.get("days") or "未提供"}
- 预算：{safe_state.get("budget") if safe_state.get("budget") is not None else "未提供"}
- 偏好：{json.dumps(safe_state.get("preferences", {}), ensure_ascii=False)}

## 数据来源状态

- 天气：{_status(safe_state.get("weather") or {})}
- 美团酒旅：{_status(meituan)}
- 小红书：{_status(safe_state.get("social_search") or {})}
- 交通：{_status(safe_state.get("transport_options") or {})}

## 天气摘要

{safe_state.get("weather_summary") or json.dumps(safe_state.get("weather", {}), ensure_ascii=False)}

## 美团链接摘录

{chr(10).join(f"- [{link.get('title', '链接')}]({link.get('url')})" for link in links) if links else "本次未解析出 Markdown 链接。"}

## 本轮 RAG 检索命中的知识库

{chr(10).join(f"- [[{Path(str(doc.get('path', ''))).stem}]]：{doc.get('path')}（score={doc.get('score')}）" for doc in retrieved_docs if isinstance(doc, dict)) if retrieved_docs else "本轮没有命中已有 Obsidian 知识。"}

## 本轮保存的用户偏好

{_json_block(safe_state.get("profile_updates", {}))}

## 可复用经验

- 本次规划中真实价格、评分、链接来自实时工具，后续不要把它们当作长期固定事实。
- 可以长期复用的是路线顺序、街区组合、雨天/高温备选、用户偏好和选择理由。

## 知识库完善建议

{chr(10).join(f"- [ ] {item}" for item in suggestions) if suggestions else "- [ ] 暂无新的完善建议。"}

## 最终回答快照

{plan_text}
"""
    trip_path.write_text(content, encoding="utf-8")

    city_path = root / "10_Cities" / f"{_slug(destination)}.md"
    if not city_path.exists():
        city_path.write_text(
            f"# {destination}\n\n## 城市概览\n\n## 经典路线\n\n## 美食线索\n\n## 住宿区域\n\n## 交通动线\n\n## 避坑提醒\n",
            encoding="utf-8",
        )
    _append_section(
        city_path,
        f"自动沉淀 {now.strftime('%Y-%m-%d %H:%M')}",
        f"""来源：[[{trip_path.stem}]]

- 用户需求：{safe_state.get("user_input", "")}
- 天气摘要：{safe_state.get("weather_summary") or "无"}
- 美团状态：{_status(meituan)}
- 可复用方向：路线顺序、街区组合、用户偏好、工具缺口。
""",
    )

    suggestions_path = Path(paths["agent"]) / "知识库完善建议.md"
    _append_section(
        suggestions_path,
        f"自动建议 {now.strftime('%Y-%m-%d %H:%M')} - {destination}",
        "\n".join(f"- [ ] {item}" for item in suggestions) if suggestions else "- [ ] 暂无新的完善建议。",
    )

    return {
        "enabled": True,
        "trip_note_path": str(trip_path),
        "city_note_path": str(city_path),
        "suggestions_path": str(suggestions_path),
        "suggestions": suggestions,
    }


def main() -> None:
    paths = initialize_knowledge_base()
    print("Obsidian knowledge base initialized:")
    for name, path in paths.items():
        print(f"- {name}: {path}")


if __name__ == "__main__":
    main()
