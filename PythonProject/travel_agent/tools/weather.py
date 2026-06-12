import os
from typing import Any, Dict, Optional

from travel_agent.tools._api import (
    auth_headers,
    env_int,
    first_list,
    first_value,
    provider_message,
    request_json,
)


def _normalize_forecast(raw: Dict[str, Any]) -> Dict[str, Any]:
    forecast_items = first_list(
        raw,
        (
            "data.forecast",
            "data.forecasts",
            "data.daily",
            "data.days",
            "result.forecast",
            "result.daily",
            "forecast",
            "daily",
        ),
    )
    forecast = []
    for item in forecast_items[:7]:
        if not isinstance(item, dict):
            continue
        forecast.append(
            {
                "date": first_value(item, ("date", "predictDate", "fxDate", "day")),
                "weather": first_value(
                    item,
                    ("weather", "condition", "textDay", "dayWeather", "phenomena"),
                ),
                "temperature": first_value(
                    item,
                    ("temperature", "temp", "tempRange", "maxMinTemp"),
                ),
                "temp_min": first_value(item, ("tempMin", "temp_min", "minTemp", "min")),
                "temp_max": first_value(item, ("tempMax", "temp_max", "maxTemp", "max")),
                "wind": first_value(item, ("wind", "windDir", "windPower", "windLevel")),
                "humidity": first_value(item, ("humidity", "rh")),
                "tips": first_value(item, ("tips", "suggestion", "detail")),
            }
        )

    return {
        "summary": first_value(
            raw,
            (
                "data.summary",
                "data.condition",
                "data.weather",
                "result.summary",
                "summary",
                "message",
            ),
        ),
        "current": first_value(raw, ("data.current", "result.current", "current"), {}),
        "forecast": forecast,
    }


def get_weather(destination: str, days: Optional[int] = None) -> Dict[str, Any]:
    """Fetch weather from Moji Weather through a configurable API endpoint."""
    if not destination:
        return {}

    url = os.getenv("MOJI_WEATHER_URL")
    if not url:
        return provider_message(
            "moji_weather",
            "config_required",
            "未配置墨迹天气接口地址。",
            required_env=("MOJI_WEATHER_URL", "MOJI_API_KEY 或 MOJI_ACCESS_TOKEN"),
        )

    method = os.getenv("MOJI_METHOD", "GET").upper()
    city_param = os.getenv("MOJI_CITY_PARAM", "city")
    params: Dict[str, Any] = {city_param: destination}
    if days:
        params[os.getenv("MOJI_DAYS_PARAM", "days")] = days

    api_key = os.getenv("MOJI_API_KEY")
    if api_key:
        params[os.getenv("MOJI_KEY_PARAM", "key")] = api_key

    try:
        raw = request_json(
            method,
            url,
            params=params if method == "GET" else None,
            json_body=params if method != "GET" else None,
            headers=auth_headers("MOJI"),
            timeout=env_int("MOJI_TIMEOUT", 10),
        )
    except Exception as exc:
        return provider_message("moji_weather", "error", f"墨迹天气接口调用失败：{exc}")

    normalized = _normalize_forecast(raw)
    return {
        "provider": "moji_weather",
        "status": "ok",
        "destination": destination,
        "days": days,
        **normalized,
    }
