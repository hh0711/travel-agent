from typing import Any, Dict, List, Optional, TypedDict


class TravelState(TypedDict, total=False):
    user_id: str
    session_id: str
    user_input: str
    intent: str
    intent_reason: str
    conversation_history: List[Dict[str, str]]
    destination: str
    days: int
    budget: Optional[int]
    preferences: Dict[str, Any]
    profile_updates: Dict[str, Any]
    user_profile: Dict[str, Any]
    rag_context: str
    retrieved_docs: List[Dict[str, Any]]
    weather: Dict[str, Any]
    weather_summary: str
    meituan_travel: Dict[str, Any]
    meituan_entities: Dict[str, Any]
    food_options: List[Dict[str, Any]]
    hotel_options: List[Dict[str, Any]]
    transport_options: List[Dict[str, Any]]
    social_search: Dict[str, Any]
    social_summary: str
    plan: str
    final_answer: str
    knowledge_update: Dict[str, Any]
    need_clarification: bool
    question: str
