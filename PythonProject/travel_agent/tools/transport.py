from typing import Any, Dict, List


def search_transport(destination: str) -> List[Dict[str, Any]]:
    """Placeholder transport planning tool."""
    if not destination:
        return []
    return [
        {
            "type": "市内交通",
            "suggestion": "优先选择地铁/打车组合，减少换乘时间",
        }
    ]

