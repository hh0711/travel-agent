from typing import Any, Dict, List, Optional

from travel_agent.tools.meituan_skill import search_meituan_hotels


def search_hotels(
    destination: str,
    budget: Optional[int],
    preferences: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """Search hotels through Meituan Skills."""
    if not destination:
        return []

    result = search_meituan_hotels(destination, budget, preferences)
    return [result]
