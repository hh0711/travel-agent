from typing import Any, Dict, List, Optional, TypedDict


class TravelState(TypedDict, total=False):
    session_id: str
    user_input: str
    conversation_history: List[Dict[str, str]]
    destination: str
    days: int
    budget: Optional[int]
    preferences: Dict[str, Any]
    profile_updates: Dict[str, Any]
    user_profile: Dict[str, Any]
    weather: Dict[str, Any]
    weather_summary: str
    meituan_travel: Dict[str, Any]
    food_options: List[Dict[str, Any]]
    hotel_options: List[Dict[str, Any]]
    transport_options: List[Dict[str, Any]]
    social_search: Dict[str, Any]
    social_summary: str
    plan: str
    final_answer: str
    need_clarification: bool
    question: str
