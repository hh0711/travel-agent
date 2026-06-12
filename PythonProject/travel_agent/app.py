from travel_agent.graph import graph


def main() -> None:
    user_input = input("请输入出游需求：").strip()
    if not user_input:
        print("请输入目的地、天数、预算和偏好。")
        return

    result = graph.invoke({"user_input": user_input})
    print(result["final_answer"])


if __name__ == "__main__":
    main()

