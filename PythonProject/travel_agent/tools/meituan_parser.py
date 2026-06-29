import re
from typing import Any, Dict, List, Optional


HOTEL_KEYWORDS = ("酒店", "民宿", "客栈", "宾馆", "住宿", "驿舍", "hotel")
FOOD_KEYWORDS = (
    "餐",
    "菜",
    "面",
    "鱼",
    "鸡",
    "饭",
    "小吃",
    "烧饼",
    "点心",
    "咖啡",
    "茶",
    "馆",
    "楼",
)
SCENIC_KEYWORDS = (
    "园",
    "街",
    "寺",
    "湖",
    "山",
    "博物馆",
    "景区",
    "古镇",
    "公园",
    "塔",
)


def meituan_content(meituan_travel: Dict[str, Any]) -> str:
    content = meituan_travel.get("content")
    if content:
        return str(content)

    raw = meituan_travel.get("raw")
    if isinstance(raw, dict) and raw.get("content"):
        return str(raw["content"])
    return ""


def markdown_links(text: str) -> List[Dict[str, str]]:
    links: List[Dict[str, str]] = []
    seen = set()
    for match in re.finditer(r"(?<!!)\[([^\]]+)\]\((https?://[^)]+)\)", text):
        title = re.sub(r"[*_`\\]", "", match.group(1)).strip()
        url = match.group(2).strip()
        key = (title, url)
        if not title or key in seen:
            continue
        seen.add(key)
        links.append({"title": title, "url": url, "context": _context(text, match.start())})
    return links


def _context(text: str, index: int, window: int = 180) -> str:
    start = max(index - window, 0)
    end = min(index + window, len(text))
    return re.sub(r"\s+", " ", text[start:end]).strip()


def _has_any(text: str, keywords: tuple[str, ...]) -> bool:
    lower_text = text.lower()
    return any(keyword.lower() in lower_text for keyword in keywords)


def _category(link: Dict[str, str]) -> str:
    title = link.get("title", "")
    context = link.get("context", "")
    if _has_any(title, HOTEL_KEYWORDS):
        return "hotels"
    if _has_any(title, FOOD_KEYWORDS):
        return "restaurants"
    if _has_any(title, SCENIC_KEYWORDS):
        return "scenic_spots"

    text = f"{title} {context}"
    if _has_any(text, HOTEL_KEYWORDS):
        return "hotels"
    if _has_any(text, FOOD_KEYWORDS):
        return "restaurants"
    if _has_any(text, SCENIC_KEYWORDS):
        return "scenic_spots"
    return "other_links"


def _nearby_value(context: str, pattern: str) -> Optional[str]:
    match = re.search(pattern, context)
    if not match:
        return None
    return match.group(1).strip()


def _enrich_link(link: Dict[str, str]) -> Dict[str, Any]:
    context = link.get("context", "")
    return {
        **link,
        "rating": _nearby_value(context, r"((?:美团)?(?:真实)?评分\s*\d(?:\.\d)?|\d(?:\.\d)?分)"),
        "price": _nearby_value(context, r"([¥￥]\s*\d*X*\d*(?:起)?(?:/晚)?)"),
        "source": "meituan_cli",
    }


def extract_meituan_entities(meituan_travel: Dict[str, Any]) -> Dict[str, Any]:
    text = meituan_content(meituan_travel)
    source_links = meituan_travel.get("links")
    if isinstance(source_links, list) and source_links:
        links = [
            {
                "title": str(link.get("title", "")),
                "url": str(link.get("url", "")),
                "context": _context(text, text.find(str(link.get("title", "")))),
            }
            for link in source_links
            if isinstance(link, dict) and link.get("url")
        ]
    else:
        links = markdown_links(text)

    entities: Dict[str, Any] = {
        "status": meituan_travel.get("status"),
        "hotels": [],
        "restaurants": [],
        "scenic_spots": [],
        "other_links": [],
        "all_links": [],
    }
    for link in links:
        enriched = _enrich_link(link)
        category = _category(enriched)
        entities[category].append(enriched)
        entities["all_links"].append(enriched)

    return entities
