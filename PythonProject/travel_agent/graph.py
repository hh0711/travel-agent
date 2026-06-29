import json
import os
import re
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, StateGraph

from travel_agent.memory.profile_store import load_profile, update_profile
from travel_agent.rag.obsidian_knowledge import retrieve_knowledge, save_turn_knowledge
from travel_agent.state import TravelState
from travel_agent.tools.meituan_skill import search_meituan_travel
from travel_agent.tools.meituan_parser import extract_meituan_entities, meituan_content
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


def _conversation_prompt(history: List[Dict[str, str]], limit: int = 8) -> str:
    if not history:
        return "无"

    lines = []
    for message in history[-limit:]:
        role = "用户" if message.get("role") == "user" else "助手"
        content = str(message.get("content", "")).strip()
        if not content:
            continue
        if len(content) > 900:
            content = content[:900] + "..."
        lines.append(f"{role}: {content}")
    return "\n".join(lines) or "无"


def _last_assistant_message(history: List[Dict[str, str]]) -> str:
    for message in reversed(history):
        if message.get("role") == "assistant" and message.get("content"):
            return str(message["content"])
    return ""


def detect_intent(state: TravelState) -> TravelState:
    llm = _get_llm()
    prompt = f"""
{SYSTEM_PROMPT}

请判断用户当前输入的问答意图，只返回 JSON，不要输出 Markdown。

可选 intent：
- trip_plan: 生成新的完整旅行行程
- modify_plan: 基于上一轮方案修改行程
- ask_detail: 追问上一轮方案中的酒店、餐厅、景点、交通或理由
- compare_options: 比较两个或多个目的地、区域、酒店、餐厅、路线
- save_preference: 明确要求记住/保存长期偏好
- knowledge_qa: 询问旅行知识库、城市经验、规则、避坑，不需要实时工具

返回字段：
- intent: 上述枚举之一
- reason: 简短原因

最近对话：
{_conversation_prompt(state.get("conversation_history", []))}

用户输入：
{state["user_input"]}
"""
    try:
        parsed = _load_json_object(llm.invoke(prompt).content)
    except json.JSONDecodeError:
        parsed = {}
    intent = str(parsed.get("intent") or "trip_plan")
    if intent not in {
        "trip_plan",
        "modify_plan",
        "ask_detail",
        "compare_options",
        "save_preference",
        "knowledge_qa",
    }:
        intent = "trip_plan"
    return {"intent": intent, "intent_reason": str(parsed.get("reason") or "")}


def parse_request(state: TravelState) -> TravelState:
    llm = _get_llm()
    prompt = f"""
{SYSTEM_PROMPT}

请结合最近对话，把用户当前出游需求解析成严格 JSON，只返回 JSON，不要输出 Markdown。

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
- 如果当前输入是“预算改成1000”“不要太累”“住宿换好一点”这类追问或调整，请从最近对话继承目的地、天数等仍然有效的信息
- 当前输入明确修改的信息优先于最近对话

最近对话：
{_conversation_prompt(state.get("conversation_history", []))}

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
    profile = load_profile(state.get("user_id", "local"))
    preferences = dict(profile)
    preferences.update(state.get("preferences") or {})
    return {"preferences": preferences, "user_profile": profile}


def update_user_profile(state: TravelState) -> TravelState:
    llm = _get_llm()
    prompt = f"""
{SYSTEM_PROMPT}

请从用户当前输入和最近对话中抽取适合长期保存的稳定旅行偏好，只返回 JSON，不要输出 Markdown。

只保存较稳定、可复用到未来旅行规划的偏好，例如：
- origin_city: 常用出发城市
- food: 餐饮口味或忌口
- hotel: 住宿偏好
- pace: 行程节奏偏好
- transport: 交通偏好
- budget_style: 消费风格
- companions: 常见同行人

不要保存一次性信息，例如本次目的地、具体日期、一次性预算、临时天气、某次行程的酒店名称。
如果没有新的长期偏好，返回空对象 {{}}。
当前已有用户画像：{json.dumps(state.get("user_profile", {}), ensure_ascii=False)}
最近对话：
{_conversation_prompt(state.get("conversation_history", []))}

当前输入：
{state["user_input"]}
"""
    try:
        updates = _load_json_object(llm.invoke(prompt).content)
    except json.JSONDecodeError:
        updates = {}
    if not isinstance(updates, dict):
        updates = {}

    user_id = state.get("user_id", "local")
    saved_profile = update_profile(updates, user_id) if updates else state.get("user_profile", {})
    preferences = dict(saved_profile)
    preferences.update(state.get("preferences") or {})
    return {
        "profile_updates": updates,
        "user_profile": saved_profile,
        "preferences": preferences,
    }


def retrieve_obsidian_context(state: TravelState) -> TravelState:
    result = retrieve_knowledge(
        query=state.get("user_input", ""),
        destination=state.get("destination", ""),
        preferences=state.get("preferences", {}),
    )
    return {
        "rag_context": result.get("context", ""),
        "retrieved_docs": result.get("documents", []),
    }


def _has_weather_data(weather: Dict[str, Any]) -> bool:
    if weather.get("status") != "ok":
        return False
    return bool(weather.get("summary") or weather.get("current") or weather.get("forecast"))


def _meituan_content(meituan_travel: Dict[str, Any]) -> str:
    return meituan_content(meituan_travel)


def _chinese_day_number(raw: str) -> Optional[int]:
    text = raw.strip()
    if text.isdigit():
        return int(text)

    values = {
        "一": 1,
        "二": 2,
        "两": 2,
        "三": 3,
        "四": 4,
        "五": 5,
        "六": 6,
        "七": 7,
        "八": 8,
        "九": 9,
        "十": 10,
    }
    if text in values:
        return values[text]
    if text.startswith("十") and len(text) == 2:
        return 10 + values.get(text[1], 0)
    if text.endswith("十") and len(text) == 2:
        return values.get(text[0], 0) * 10
    if "十" in text and len(text) == 3:
        left, right = text.split("十", 1)
        return values.get(left, 0) * 10 + values.get(right, 0)
    return None


def _date_range_from_meituan(text: str, limit: Optional[int]) -> List[str]:
    match = re.search(r"(\d{1,2})月(\d{1,2})\s*[-~至到]\s*(\d{1,2})日", text)
    if not match:
        return []

    month = int(match.group(1))
    start_day = int(match.group(2))
    end_day = int(match.group(3))
    year = date.today().year
    try:
        start = date(year, month, start_day)
        end = date(year, month, end_day)
    except ValueError:
        return []
    if end < start:
        return []

    max_days = limit or 7
    dates = []
    current = start
    while current <= end and len(dates) < max_days:
        dates.append(f"{current.month}月{current.day}日")
        current += timedelta(days=1)
    return dates


def _weather_from_meituan(
    meituan_travel: Dict[str, Any],
    destination: str,
    days: Optional[int],
    weatherdt_result: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    text = _meituan_content(meituan_travel)
    if not text:
        return None

    weather_terms = (
        "雷阵雨|雨夹雪|小到中雨|中到大雨|大到暴雨|小到中雪|中到大雪|大到暴雪|"
        "晴天?|多云|阴天?|阵雨|小雨|中雨|大雨|暴雨|小雪|中雪|大雪|雾|霾"
    )
    forecast: List[Dict[str, Any]] = []
    seen = set()
    date_range = _date_range_from_meituan(text, days)

    dated_pattern = re.compile(
        rf"(?P<date>\d{{1,2}}月\d{{1,2}}日)[^，。；\n]{{0,30}}?"
        rf"(?P<weather>{weather_terms})[^，。；\n\d]{{0,12}}?"
        rf"(?P<temp>\d{{1,2}})\s*(?:度|℃)"
    )
    for match in dated_pattern.finditer(text):
        item_date = match.group("date")
        key = ("date", item_date)
        if key in seen:
            continue
        seen.add(key)
        forecast.append(
            {
                "date": item_date,
                "weather": match.group("weather"),
                "temperature": f"{match.group('temp')}℃",
                "source_text": match.group(0),
            }
        )

    day_pattern = re.compile(
        rf"(?:第\s*(?P<cn>[一二两三四五六七八九十\d]+)\s*天|DAY\s*(?P<day>\d+))"
        rf"[^，。；\n]{{0,20}}?(?P<weather>{weather_terms})"
        rf"[^，。；\n\d]{{0,12}}?(?P<temp>\d{{1,2}})\s*(?:度|℃)",
        flags=re.IGNORECASE,
    )
    for match in day_pattern.finditer(text):
        day_number = int(match.group("day")) if match.group("day") else _chinese_day_number(match.group("cn"))
        if not day_number:
            continue
        key = ("day", day_number)
        if key in seen:
            continue
        seen.add(key)
        item: Dict[str, Any] = {
            "day_index": day_number,
            "weather": match.group("weather"),
            "temperature": f"{match.group('temp')}℃",
            "source_text": match.group(0),
        }
        if 0 < day_number <= len(date_range):
            item["date"] = date_range[day_number - 1]
        forecast.append(item)

    if not forecast:
        return None

    forecast = forecast[: days or len(forecast)]
    summary_parts = []
    for index, item in enumerate(forecast, start=1):
        label = item.get("date") or f"第{item.get('day_index') or index}天"
        summary_parts.append(f"{label}{item.get('weather')}，{item.get('temperature')}")

    return {
        "provider": "meituan_travel_weather",
        "status": "ok",
        "destination": destination,
        "source": "meituan_travel_cli",
        "fallback_from": weatherdt_result,
        "summary": "；".join(summary_parts),
        "forecast": forecast,
    }


def _get_weather_with_fallback(
    destination: str,
    days: Optional[int],
    meituan_travel: Dict[str, Any],
    weatherdt_result: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    weather = weatherdt_result if weatherdt_result is not None else get_weather(destination, days)
    if _has_weather_data(weather):
        return weather

    fallback = _weather_from_meituan(meituan_travel, destination, days, weather)
    if fallback:
        return fallback
    return weather


def _weather_prompt_text(weather: Dict[str, Any]) -> str:
    if not weather:
        return "无可用天气数据"

    provider = weather.get("provider") or "unknown"
    summary = weather.get("summary") or ""
    forecast = weather.get("forecast") or []
    forecast_text = []
    if isinstance(forecast, list):
        for item in forecast[:7]:
            if not isinstance(item, dict):
                continue
            parts = []
            label = item.get("date") or f"第{item.get('day_index') or len(forecast_text) + 1}天"
            parts.append(str(label))
            if item.get("weather"):
                parts.append(str(item.get("weather")))
            if item.get("temperature"):
                parts.append(str(item.get("temperature")))
            forecast_text.append("，".join(parts))

    lines = [f"来源：{provider}"]
    if summary:
        lines.append(f"摘要：{summary}")
    if forecast_text:
        lines.append("预报：" + "；".join(forecast_text))
    if provider == "meituan_travel_weather":
        lines.append("说明：WeatherDT 未返回可用天气，以上天气来自美团酒旅助手返回的天气日期数据。")
    return "\n".join(lines)


def _finalize_plan_text(plan: str, weather: Dict[str, Any]) -> str:
    if not plan:
        return plan

    if weather.get("provider") != "meituan_travel_weather":
        return plan

    summary = weather.get("summary") or "美团酒旅助手返回了可用天气日期数据"
    note = f"天气说明：WeatherDT 未返回可用数据，已使用美团酒旅助手返回的天气日期数据作为依据：{summary}。"
    plan = re.sub(
        r"由于天气接口未配置，无法获取实时天气，出行前请自行查看天气预报。",
        note,
        plan,
        count=1,
    )
    if note not in plan:
        plan = plan.rstrip() + "\n\n" + note
    return plan


def collect_context(state: TravelState) -> TravelState:
    destination = state.get("destination", "")
    preferences = state.get("preferences") or {}
    weatherdt_result = get_weather(destination, state.get("days"))
    meituan_travel = search_meituan_travel(
        destination,
        state.get("budget"),
        preferences,
        days=state.get("days"),
    )
    weather = _get_weather_with_fallback(
        destination,
        state.get("days"),
        meituan_travel,
        weatherdt_result,
    )
    meituan_entities = extract_meituan_entities(meituan_travel)
    return {
        "weather": weather,
        "weather_summary": _weather_prompt_text(weather),
        "meituan_travel": meituan_travel,
        "meituan_entities": meituan_entities,
        "food_options": meituan_entities.get("restaurants") or [meituan_travel],
        "hotel_options": meituan_entities.get("hotels") or [meituan_travel],
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


def answer_lightweight_question(state: TravelState) -> TravelState:
    llm = _get_llm()
    intent = state.get("intent", "knowledge_qa")
    prompt = f"""
{SYSTEM_PROMPT}

请回答用户的当前问题。这个分支用于轻量问答，不调用实时美团/天气工具。

意图：{intent}
意图原因：{state.get("intent_reason", "")}
最近对话：
{_conversation_prompt(state.get("conversation_history", []))}
上一轮助手回答：
{_last_assistant_message(state.get("conversation_history", [])) or "无"}
用户当前输入：{state["user_input"]}
长期用户偏好：{json.dumps(state.get("user_profile", {}), ensure_ascii=False)}
本轮新保存的长期偏好：{json.dumps(state.get("profile_updates", {}), ensure_ascii=False)}
Obsidian RAG 检索上下文：
{state.get("rag_context") or "无相关知识库内容"}

回答要求：
1. 如果是 save_preference，简短确认已保存哪些偏好，不要生成完整行程
2. 如果是 ask_detail 或 compare_options，优先基于上一轮回答和知识库回答，除非用户明确要求重新规划
3. 如果是 knowledge_qa，回答要标明“知识库经验/历史沉淀”或“用户偏好”来源
4. 不要编造实时价格、评分、营业状态、库存；需要实时数据时提醒用户发起完整规划
5. 默认输出简洁答案，只有用户要求详细时再展开
"""
    return {"plan": llm.invoke(prompt).content}


def plan_trip(state: TravelState) -> TravelState:
    llm = _get_llm()
    prompt = f"""
{SYSTEM_PROMPT}

请基于以下信息，直接生成一份可执行的吃住行推荐。不要再追问非必要信息。

最近对话：
{_conversation_prompt(state.get("conversation_history", []))}
意图：{state.get("intent")}
上一轮助手回答：
{_last_assistant_message(state.get("conversation_history", [])) or "无"}
用户原始需求：{state["user_input"]}
目的地：{state.get("destination")}
天数：{state.get("days")}
预算：{state.get("budget") if state.get("budget") is not None else "未提供"}
长期用户偏好：{json.dumps(state.get("user_profile", {}), ensure_ascii=False)}
本轮新保存的长期偏好：{json.dumps(state.get("profile_updates", {}), ensure_ascii=False)}
偏好：{json.dumps(state.get("preferences", {}), ensure_ascii=False)}
天气：{json.dumps(state.get("weather", {}), ensure_ascii=False)}
美团酒旅助手原始结果：{json.dumps(state.get("meituan_travel", {}), ensure_ascii=False)}
美团结构化结果：{json.dumps(state.get("meituan_entities", {}), ensure_ascii=False)}
餐饮候选：{json.dumps(state.get("food_options", []), ensure_ascii=False)}
住宿候选：{json.dumps(state.get("hotel_options", []), ensure_ascii=False)}
交通候选：{json.dumps(state.get("transport_options", []), ensure_ascii=False)}
小红书搜索摘要：{state.get("social_summary", "")}
Obsidian RAG 检索上下文：
{state.get("rag_context") or "无相关知识库内容"}

输出要求：
1. 按第 1 天、第 2 天这样的格式安排
2. 每天包含上午、午餐、下午、晚餐、住宿/返程建议
3. 每天都要结合天气、美团酒旅助手候选、小红书摘要给出取舍理由
4. 推荐住宿区域、酒店或餐厅时，优先使用“美团结构化结果”里的真实名称、价格、评分、链接；不要编造接口没有返回的价格、评分、空房
5. 所有具体饭店和酒店推荐都必须保留美团对应链接，优先使用 Markdown 链接格式：[名称](美团链接)；没有链接的候选只能作为区域或类型参考，不要作为具体推荐
6. 餐厅推荐要更丰富：午餐和晚餐各给1家主推；如果美团返回了足够候选，再额外整理2到3家“可替换餐厅”，写清适合哪一餐、菜系/招牌、位置、评分/价格、美团链接和选择理由
7. 住宿建议要详细：至少给1家主推酒店，并尽量给2到3家备选；每家写清商圈/位置、交通便利性、价格、评分、档次/星级、房型或设施亮点、适合人群、优缺点和美团预订链接
8. 如果美团酒旅助手返回 content 文本，必须把其中适合本次行程且带链接的酒店和餐厅拆分到午餐、晚餐、住宿建议中
9. 给出市内交通建议
10. 如果预算已提供，给出三大类预算拆分：住宿、餐饮、交通/门票
11. 如果任一实时接口未配置或调用失败，在文末用“数据说明”简短说明，不要把它包装成真实数据
12. 如果天气 provider 是 meituan_travel_weather，说明 WeatherDT 未返回可用数据，但已使用美团酒旅助手返回的天气日期数据作为天气依据，不要再说天气完全缺失
13. 使用 Obsidian RAG 内容时必须标注它是“知识库经验/历史沉淀”，不要把其中的旧价格、旧评分、旧营业时间当作实时数据
14. 如果意图是 modify_plan，要明确说明相对上一轮方案改了什么，并尽量复用上一轮仍然有效的信息
"""
    return {"plan": llm.invoke(prompt).content}


def final_answer(state: TravelState) -> TravelState:
    answer = _finalize_plan_text(state.get("plan", ""), state.get("weather", {}))
    try:
        knowledge_update = save_turn_knowledge({**state, "final_answer": answer}, answer)
    except Exception as exc:
        knowledge_update = {"enabled": False, "error": str(exc)}

    if knowledge_update.get("enabled"):
        suggestions = knowledge_update.get("suggestions") or []
        suggestion_text = "\n".join(f"- {item}" for item in suggestions[:3])
        answer = (
            answer.rstrip()
            + "\n\n## 知识库更新\n"
            + f"- 已写入行程笔记：{knowledge_update.get('trip_note_path')}\n"
            + f"- 已更新城市笔记：{knowledge_update.get('city_note_path')}\n"
            + f"- 完善建议清单：{knowledge_update.get('suggestions_path')}\n"
        )
        if suggestion_text:
            answer += "\n本次建议优先补充：\n" + suggestion_text

    return {"final_answer": answer, "knowledge_update": knowledge_update}


def ask_clarification(state: TravelState) -> TravelState:
    question = state.get("question") or "请补充目的地和出行天数。"
    return {"final_answer": question}


def route_after_parse(state: TravelState) -> str:
    if state.get("intent") in {"save_preference", "knowledge_qa", "ask_detail", "compare_options"}:
        return "load_user_profile"
    if not state.get("destination") or not state.get("days"):
        return "ask_clarification"
    return "load_user_profile"


def route_after_retrieve(state: TravelState) -> str:
    if state.get("intent") in {"save_preference", "knowledge_qa", "ask_detail", "compare_options"}:
        return "answer_lightweight_question"
    return "collect_context"


builder = StateGraph(TravelState)
builder.add_node("detect_intent", detect_intent)
builder.add_node("parse_request", parse_request)
builder.add_node("load_user_profile", load_user_profile)
builder.add_node("update_user_profile", update_user_profile)
builder.add_node("retrieve_obsidian_context", retrieve_obsidian_context)
builder.add_node("collect_context", collect_context)
builder.add_node("summarize_social_search", summarize_social_search)
builder.add_node("answer_lightweight_question", answer_lightweight_question)
builder.add_node("plan_trip", plan_trip)
builder.add_node("final_answer", final_answer)
builder.add_node("ask_clarification", ask_clarification)

builder.add_edge(START, "detect_intent")
builder.add_edge("detect_intent", "parse_request")
builder.add_conditional_edges(
    "parse_request",
    route_after_parse,
    {
        "ask_clarification": "ask_clarification",
        "load_user_profile": "load_user_profile",
    },
)
builder.add_edge("load_user_profile", "update_user_profile")
builder.add_edge("update_user_profile", "retrieve_obsidian_context")
builder.add_conditional_edges(
    "retrieve_obsidian_context",
    route_after_retrieve,
    {
        "answer_lightweight_question": "answer_lightweight_question",
        "collect_context": "collect_context",
    },
)
builder.add_edge("collect_context", "summarize_social_search")
builder.add_edge("summarize_social_search", "plan_trip")
builder.add_edge("answer_lightweight_question", "final_answer")
builder.add_edge("plan_trip", "final_answer")
builder.add_edge("final_answer", END)
builder.add_edge("ask_clarification", END)

graph = builder.compile()
