import os
import json
import re
from typing import Any, Dict, Optional

import requests

from travel_agent.tools._api import (
    env_int,
    first_list,
    first_value,
    provider_message,
)


WEATHERDT_WEATHER_CODES = {
    "00": "晴",
    "01": "多云",
    "02": "阴",
    "03": "阵雨",
    "04": "雷阵雨",
    "05": "雷阵雨伴有冰雹",
    "06": "雨夹雪",
    "07": "小雨",
    "08": "中雨",
    "09": "大雨",
    "10": "暴雨",
    "11": "大暴雨",
    "12": "特大暴雨",
    "13": "阵雪",
    "14": "小雪",
    "15": "中雪",
    "16": "大雪",
    "17": "暴雪",
    "18": "雾",
    "19": "冻雨",
    "20": "沙尘暴",
    "21": "小到中雨",
    "22": "中到大雨",
    "23": "大到暴雨",
    "24": "暴雨到大暴雨",
    "25": "大暴雨到特大暴雨",
    "26": "小到中雪",
    "27": "中到大雪",
    "28": "大到暴雪",
    "29": "浮尘",
    "30": "扬沙",
    "31": "强沙尘暴",
    "53": "霾",
}


def _weather_text(code: Any) -> Any:
    if code is None:
        return None
    text = str(code)
    return WEATHERDT_WEATHER_CODES.get(text.zfill(2), text)


def _load_area_map() -> Dict[str, str]:
    raw = os.getenv("WEATHERDT_AREA_MAP_JSON")
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    if not isinstance(parsed, dict):
        return {}
    return {str(k): str(v) for k, v in parsed.items() if str(v).strip()}


def _resolve_area(destination: str) -> Optional[str]:
    destination = destination.strip()
    if re.fullmatch(r"\d+(?:\|\d+)*", destination):
        return destination

    area_map = _load_area_map()
    return (
        area_map.get(destination)
        or area_map.get(destination.replace("市", ""))
        or os.getenv("WEATHERDT_DEFAULT_AREA")
    )


def _parse_json_response(text: str) -> Dict[str, Any]:
    stripped = text.strip()
    if not stripped:
        return {}
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        match = re.search(r"^[\w$.]+\((.*)\)\s*;?$", stripped, flags=re.DOTALL)
        if not match:
            raise
        return json.loads(match.group(1))


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


def _first_station_block(section: Any, area: str) -> Any:
    if not isinstance(section, dict):
        return None
    if area in section:
        return section[area]
    if "|" in area:
        first_area = area.split("|", 1)[0]
        if first_area in section:
            return section[first_area]
    for value in section.values():
        return value
    return None


def _first_data_block(station_block: Any) -> Any:
    if not isinstance(station_block, dict):
        return station_block
    for key, value in station_block.items():
        if key == "000":
            continue
        return value
    return station_block


def _normalize_weatherdt(raw: Dict[str, Any], area: str, days: Optional[int]) -> Dict[str, Any]:
    forecast_section = raw.get("forecast", {})
    forecast_24h = forecast_section.get("24h", {}) if isinstance(forecast_section, dict) else {}
    forecast_station = _first_station_block(forecast_24h, area)
    forecast_items = _first_data_block(forecast_station)
    if not isinstance(forecast_items, list):
        forecast_items = []

    forecast = []
    limit = days or 7
    for index, item in enumerate(forecast_items[:limit], start=1):
        if not isinstance(item, dict):
            continue
        day_weather = _weather_text(item.get("001"))
        night_weather = _weather_text(item.get("002"))
        forecast.append(
            {
                "day_index": index,
                "weather": (
                    day_weather
                    if day_weather == night_weather
                    else f"白天{day_weather or '未知'}，夜间{night_weather or '未知'}"
                ),
                "temp_max": item.get("003"),
                "temp_min": item.get("004"),
                "wind_day": item.get("005"),
                "wind_night": item.get("006"),
                "wind_dir_day": item.get("007"),
                "wind_dir_night": item.get("008"),
            }
        )

    observe_station = _first_station_block(raw.get("observe"), area)
    current = _first_data_block(observe_station)
    if not isinstance(current, dict):
        current = {}

    air_station = _first_station_block(raw.get("air"), area)
    air = _first_data_block(air_station)
    if not isinstance(air, dict):
        air = {}

    alarm_station = _first_station_block(raw.get("alarm"), area)
    alarms = _first_data_block(alarm_station)
    if not isinstance(alarms, list):
        alarms = []

    summary_parts = []
    if current:
        weather = _weather_text(current.get("001"))
        temp = current.get("002")
        if weather or temp:
            summary_parts.append(f"当前{weather or '天气未知'}，气温{temp}℃" if temp else f"当前{weather}")
    if forecast:
        first = forecast[0]
        temp_text = ""
        if first.get("temp_min") or first.get("temp_max"):
            temp_text = f"，{first.get('temp_min') or '?'}-{first.get('temp_max') or '?'}℃"
        summary_parts.append(f"近期{first.get('weather')}{temp_text}")
    if air:
        aqi = air.get("002")
        if aqi:
            summary_parts.append(f"AQI {aqi}")

    return {
        "summary": "；".join(summary_parts),
        "current": current,
        "forecast": forecast,
        "air": air,
        "alarms": alarms,
        "raw": raw,
    }


def get_weather(destination: str, days: Optional[int] = None) -> Dict[str, Any]:
    """Fetch weather from China Weather/WeatherDT through its common API."""
    if not destination:
        return {}

    url = os.getenv("WEATHERDT_URL", "http://api.weatherdt.com/common/")
    area = _resolve_area(destination)
    key = os.getenv("WEATHERDT_KEY")
    data_type = os.getenv("WEATHERDT_TYPE", "forecast|observe|alarm|air")

    if not area:
        return provider_message(
            "weatherdt",
            "config_required",
            "未配置中国天气网站号。请在 WEATHERDT_AREA_MAP_JSON 中配置目的地到 area 站号的映射，或直接传入站号。",
            required_env=("WEATHERDT_AREA_MAP_JSON",),
        )

    if not key:
        return provider_message(
            "weatherdt",
            "config_required",
            "未配置中国天气网 WeatherDT 接口密钥。",
            required_env=("WEATHERDT_KEY",),
        )

    if not url:
        return provider_message(
            "weatherdt",
            "config_required",
            "未配置中国天气网 WeatherDT 接口地址。",
            required_env=("WEATHERDT_URL",),
        )

    params: Dict[str, Any] = {
        os.getenv("WEATHERDT_AREA_PARAM", "area"): area,
        os.getenv("WEATHERDT_TYPE_PARAM", "type"): data_type,
        os.getenv("WEATHERDT_KEY_PARAM", "key"): key,
    }

    try:
        response = requests.request(
            method=os.getenv("WEATHERDT_METHOD", "GET").upper(),
            url=url,
            params=params,
            timeout=env_int("WEATHERDT_TIMEOUT", 10),
        )
        response.raise_for_status()
        raw = _parse_json_response(response.text)
    except Exception as exc:
        return provider_message("weatherdt", "error", f"中国天气网 WeatherDT 接口调用失败：{exc}")

    if isinstance(raw, dict) and raw.get("code"):
        return provider_message(
            "weatherdt",
            "error",
            f"中国天气网 WeatherDT 接口返回错误：{raw.get('code')} {raw.get('msg') or raw.get('message') or ''}".strip(),
        )

    normalized = _normalize_weatherdt(raw, area, days)
    return {
        "provider": "weatherdt",
        "status": "ok",
        "destination": destination,
        "area": area,
        "days": days,
        **normalized,
    }
