import json
import sys


def main() -> None:
    payload = sys.stdin.read().strip()
    if not payload:
        print(json.dumps({"status": {"code": 400, "msg": "empty input"}}, ensure_ascii=False))
        return

    try:
        request = json.loads(payload)
    except json.JSONDecodeError:
        print(json.dumps({"status": {"code": 400, "msg": "invalid json"}}, ensure_ascii=False))
        return

    tool = request.get("tool") or request.get("skill_id") or "travel_assistant"
    user_input = request.get("input") or {}
    print(
        json.dumps(
            {
                "status": {"code": 0, "msg": "ok"},
                "tool": tool,
                "data": {"items": [], "echo": user_input},
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
