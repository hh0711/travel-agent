from typing import Any, Dict, List

from travel_agent.tools.meituan_skill import search_meituan_restaurants


def search_food(destination: str, preferences: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Search restaurants through Meituan Skills."""
    if not destination:
        return []

    food_pref = preferences.get("food") or preferences.get("餐饮") or preferences.get("美食")
    keyword = food_pref.strip() if isinstance(food_pref, str) and food_pref.strip() else "本地菜、特色菜"
    result = search_meituan_restaurants(
        destination,
        preferences,
        keyword=keyword,
    )
    return [result]
