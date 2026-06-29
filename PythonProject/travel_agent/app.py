import os

from travel_agent.graph import graph
from travel_agent.memory.conversation_store import append_turn, load_conversation
from travel_agent.rag.obsidian_knowledge import initialize_knowledge_base, is_enabled


DEFAULT_SESSION_ID = "default"
DEFAULT_USER_ID = "local"


def main() -> None:
    user_id = os.getenv("TRAVEL_AGENT_USER_ID", DEFAULT_USER_ID)
    session_id = os.getenv("TRAVEL_AGENT_SESSION_ID", DEFAULT_SESSION_ID)
    print("旅行智能体已启动。输入 exit、quit 或 退出 结束。")
    print(f"当前用户：{user_id}，会话：{session_id}")
    if is_enabled():
        paths = initialize_knowledge_base()
        print(f"Obsidian 知识库已就绪：{paths['agent']}")

    while True:
        user_input = input("请输入出游需求：").strip()
        if not user_input:
            print("请输入目的地、天数、预算和偏好。")
            continue
        if user_input.lower() in {"exit", "quit", "q"} or user_input in {"退出", "结束"}:
            print("已结束。")
            return

        history = load_conversation(session_id, user_id)
        result = graph.invoke(
            {
                "user_id": user_id,
                "session_id": session_id,
                "user_input": user_input,
                "conversation_history": history,
            }
        )
        final_answer = result["final_answer"]
        print(final_answer)
        append_turn(session_id, user_input, final_answer, user_id)


if __name__ == "__main__":
    main()
