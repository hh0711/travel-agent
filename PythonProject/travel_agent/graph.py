import json
import os
import re
from pathlib import Path
from typing import Any, Dict

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, StateGraph

from travel_agent.memory.profile_store import load_profile
from travel_agent.state import TravelState
from travel_agent.tools.meituan_skill import search_meituan_travel
from travel_agent.tools.transport import search_transport
from travel_agent.tools.weather import get_weather
from travel_agent.tools.xiaohongshu import search_xiaohongshu


load_dotenv()

PROMPT_PATH = Path(__file__).parent / "prompts" / "system_prompt.txt"
SYSTEM_PROMPT = PROMPT_PATH.read_text(encoding="utf-8")


def _get_llm() -> ChatOpenAI:
    provider = os.getenv("LLM_PROVIDER", "deepseek").lower()
    if provider == "deepseek":
        return ChatOpenAI(
            model=os.getenv("DEEPSEEK_MODEL", "deepseek-v4-pro"),
            api_key=os.getenv("DEEPSEEK_API_KEY"),
            base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
            temperature=0.3,
        )

    return ChatOpenAI(
        model=os.getenv("OPENAI_MODEL", "gpt-5-mini"),
        api_key=os.getenv("OPENAI_API_KEY"),
        temperature=0.3,
    )


def _load_json_object(raw: str) -> Dict[str, Any]:
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if not match:
            raise
        return json.loads(match.group(0))


def parse_request(state: TravelState) -> TravelState:
    llm = _get_llm()
    prompt = f"""
{SYSTEM_PROMPT}

请把用户出游需求解析成严格 JSON，只返回 JSON，不要输出 Markdown。

字段：
- destination: 目的地，字符串，无法判断则为空字符串
- days: 出行天数，数字，无法判断则为 0
- budget: 总预算，数字或 null
- people: 出行人数，数字或 null
- preferences: 用户偏好对象，例如住宿、餐饮、交通、节奏、同行人
- need_clarification: 只有在缺少目的地或出行天数时才为 true
- question: 只有 need_clarification=true 时填写一个简短追问

规则：
- 缺少预算不要追问，按“预算未提供”继续规划
- 缺少人数不要追问，按“人数未提供”继续规划
- “三天两夜”按 3 天处理
- “端午节”“周末”可以保留在 preferences.travel_time 中

用户输入：
{state["user_input"]}
"""
    raw = llm.invoke(prompt).content
    try:
        parsed = _load_json_object(raw)
    except json.JSONDecodeError:
        return {
            "destination": "",
            "days": 0,
            "preferences": {"parse_error": raw},
            "need_clarification": True,
            "question": "请补充目的地和出行天数，我再继续生成吃住行方案。",
        }

    destination = parsed.get("destination") or ""
    days = int(parsed.get("days") or 0)
    preferences = parsed.get("preferences") or {}
    if parsed.get("people") is not None:
        preferences["people"] = parsed.get("people")

    return {
        "destination": destination,
        "days": days,
        "budget": parsed.get("budget"),
        "preferences": preferences,
        "need_clarification": not bool(destination and days),
        "question": parsed.get("question") or "请补充目的地和出行天数。",
    }


def load_user_profile(state: TravelState) -> TravelState:
    profile = load_profile()
    preferences = dict(profile)
    preferences.update(state.get("preferences") or {})
    return {"preferences": preferences}


def collect_context(state: TravelState) -> TravelState:
    destination = state.get("destination", "")
    preferences = state.get("preferences") or {}
    meituan_travel = search_meituan_travel(
        destination,
        state.get("budget"),
        preferences,
        days=state.get("days"),
    )
    return {
        "weather": get_weather(destination, state.get("days")),
        "meituan_travel": meituan_travel,
        "food_options": [meituan_travel],
        "hotel_options": [meituan_travel],
        "transport_options": search_transport(destination),
        "social_search": search_xiaohongshu(destination, preferences),
    }


def summarize_social_search(state: TravelState) -> TravelState:
    llm = _get_llm()
    social_search = state.get("social_search", {})
    if social_search.get("status") != "ok":
        return {
            "social_summary": (
                "小红书搜索未获得可用实时结果；最终行程应明确说明该部分未接入或调用失败，"
                "不要编造笔记内容。"
            )
        }

    prompt = f"""
{SYSTEM_PROMPT}

请把以下小红书搜索结果整理成旅行规划可用的简短洞察。不要编造搜索结果里没有的信息。

目的地：{state.get("destination")}
用户偏好：{json.dumps(state.get("preferences", {}), ensure_ascii=False)}
小红书搜索结果：{json.dumps(social_search, ensure_ascii=False)}

输出要求：
1. 总结高频玩法和适合放进行程的景点/街区
2. 总结高频餐饮线索和需要提前排队/预约的提醒
3. 总结住宿区域、交通动线、避坑提醒
4. 标注哪些结论来自笔记标题/摘要，哪些只是推断
5. 不输出 Markdown 表格
"""
    return {"social_summary": llm.invoke(prompt).content}


def plan_trip(state: TravelState) -> TravelState:
    llm = _get_llm()
    prompt = f"""
{SYSTEM_PROMPT}

请基于以下信息，直接生成一份可执行的吃住行推荐。不要再追问非必要信息。

用户原始需求：{state["user_input"]}
目的地：{state.get("destination")}
天数：{state.get("days")}
预算：{state.get("budget") if state.get("budget") is not None else "未提供"}
偏好：{json.dumps(state.get("preferences", {}), ensure_ascii=False)}
天气：{json.dumps(state.get("weather", {}), ensure_ascii=False)}
美团酒旅助手原始结果：{json.dumps(state.get("meituan_travel", {}), ensure_ascii=False)}
餐饮候选：{json.dumps(state.get("food_options", []), ensure_ascii=False)}
住宿候选：{json.dumps(state.get("hotel_options", []), ensure_ascii=False)}
交通候选：{json.dumps(state.get("transport_options", []), ensure_ascii=False)}
小红书搜索摘要：{state.get("social_summary", "")}

输出要求：
1. 按第 1 天、第 2 天这样的格式安排
2. 每天包含上午、午餐、下午、晚餐、住宿/返程建议
3. 每天都要结合天气、美团酒旅助手候选、小红书摘要给出取舍理由
4. 推荐住宿区域、酒店或餐厅时，优先使用美团酒旅助手原始结果里的真实名称、价格、评分、链接；不要编造接口没有返回的价格、评分、空房
5. 所有具体饭店和酒店推荐都必须保留美团对应链接，优先使用 Markdown 链接格式：[名称](美团链接)；没有链接的候选只能作为区域或类型参考，不要作为具体推荐
6. 餐厅推荐要更丰富：午餐和晚餐各给1家主推；如果美团返回了足够候选，再额外整理2到3家“可替换餐厅”，写清适合哪一餐、菜系/招牌、位置、评分/价格、美团链接和选择理由
7. 住宿建议要详细：至少给1家主推酒店，并尽量给2到3家备选；每家写清商圈/位置、交通便利性、价格、评分、档次/星级、房型或设施亮点、适合人群、优缺点和美团预订链接
8. 如果美团酒旅助手返回 content 文本，必须把其中适合本次行程且带链接的酒店和餐厅拆分到午餐、晚餐、住宿建议中
9. 给出市内交通建议
10. 如果预算已提供，给出三大类预算拆分：住宿、餐饮、交通/门票
11. 如果任一实时接口未配置或调用失败，在文末用“数据说明”简短说明，不要把它包装成真实数据
"""
    return {"plan": llm.invoke(prompt).content}


def final_answer(state: TravelState) -> TravelState:
    return {"final_answer": state.get("plan", "")}


def ask_clarification(state: TravelState) -> TravelState:
    question = state.get("question") or "请补充目的地和出行天数。"
    return {"final_answer": question}


def route_after_parse(state: TravelState) -> str:
    if not state.get("destination") or not state.get("days"):
        return "ask_clarification"
    return "load_user_profile"


builder = StateGraph(TravelState)
builder.add_node("parse_request", parse_request)
builder.add_node("load_user_profile", load_user_profile)
builder.add_node("collect_context", collect_context)
builder.add_node("summarize_social_search", summarize_social_search)
builder.add_node("plan_trip", plan_trip)
builder.add_node("final_answer", final_answer)
builder.add_node("ask_clarification", ask_clarification)

builder.add_edge(START, "parse_request")
builder.add_conditional_edges(
    "parse_request",
    route_after_parse,
    {
        "ask_clarification": "ask_clarification",
        "load_user_profile": "load_user_profile",
    },
)
builder.add_edge("load_user_profile", "collect_context")
builder.add_edge("collect_context", "summarize_social_search")
builder.add_edge("summarize_social_search", "plan_trip")
builder.add_edge("plan_trip", "final_answer")
builder.add_edge("final_answer", END)
builder.add_edge("ask_clarification", END)

graph = builder.compile()
