"""
Authenticated weather (4.C.3) — Open-Meteo, no API key. Config-backed location
(default Pompano Beach, FL + °F via settings.WEATHER_*) so a future settings UI
can edit it. Server-side so the config + a short cache live in one place; the
widget just polls. Graceful: serves a recent cached reading if the upstream
blips (weather is slow-changing, so that's not a stale lie), else 503 → the
widget shows its clean offline state.
"""
import time

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.config import settings
from app.utils.logging import get_logger

logger = get_logger(__name__)

router = APIRouter(tags=["weather"])

_OPEN_METEO = "https://api.open-meteo.com/v1/forecast"

# WMO weather_code → (label, glyph). Collapsed to representative buckets.
_WMO: dict[int, tuple[str, str]] = {
    0: ("Clear", "☀️"),
    1: ("Mostly clear", "🌤️"),
    2: ("Partly cloudy", "⛅"),
    3: ("Overcast", "☁️"),
    45: ("Fog", "🌫️"),
    48: ("Fog", "🌫️"),
    51: ("Drizzle", "🌦️"),
    53: ("Drizzle", "🌦️"),
    55: ("Drizzle", "🌦️"),
    56: ("Freezing drizzle", "🌧️"),
    57: ("Freezing drizzle", "🌧️"),
    61: ("Rain", "🌧️"),
    63: ("Rain", "🌧️"),
    65: ("Heavy rain", "🌧️"),
    66: ("Freezing rain", "🌧️"),
    67: ("Freezing rain", "🌧️"),
    71: ("Snow", "🌨️"),
    73: ("Snow", "🌨️"),
    75: ("Heavy snow", "🌨️"),
    77: ("Snow grains", "🌨️"),
    80: ("Showers", "🌦️"),
    81: ("Showers", "🌦️"),
    82: ("Heavy showers", "🌦️"),
    85: ("Snow showers", "🌨️"),
    86: ("Snow showers", "🌨️"),
    95: ("Thunderstorm", "⛈️"),
    96: ("Thunderstorm", "⛈️"),
    99: ("Thunderstorm", "⛈️"),
}

_UNIT_SYMBOL = {"fahrenheit": "°F", "celsius": "°C"}


class WeatherResponse(BaseModel):
    location: str
    temp: float | None
    temp_unit: str
    condition: str
    glyph: str
    humidity: int | None
    wind: float | None
    wind_unit: str


_cache: tuple[float, WeatherResponse] | None = None
_CACHE_TTL = 600.0  # serve fresh cache for 10 min (weather changes slowly)
_STALE_MAX = 7200.0  # on upstream failure, a cached reading up to 2h old beats offline


@router.get("/weather", response_model=WeatherResponse)
async def weather() -> WeatherResponse:
    global _cache
    now = time.monotonic()
    if _cache is not None and now - _cache[0] < _CACHE_TTL:
        return _cache[1]
    try:
        params = {
            "latitude": settings.WEATHER_LAT,
            "longitude": settings.WEATHER_LON,
            "current": "temperature_2m,relative_humidity_2m,weather_code,wind_speed_10m",
            "temperature_unit": settings.WEATHER_TEMP_UNIT,
            "wind_speed_unit": settings.WEATHER_WIND_UNIT,
        }
        async with httpx.AsyncClient(timeout=6.0) as client:
            r = await client.get(_OPEN_METEO, params=params)
            r.raise_for_status()
            cur = (r.json() or {}).get("current") or {}
        label, glyph = _WMO.get(cur.get("weather_code"), ("—", "○"))
        result = WeatherResponse(
            location=settings.WEATHER_LABEL,
            temp=cur.get("temperature_2m"),
            temp_unit=_UNIT_SYMBOL.get(settings.WEATHER_TEMP_UNIT, "°"),
            condition=label,
            glyph=glyph,
            humidity=cur.get("relative_humidity_2m"),
            wind=cur.get("wind_speed_10m"),
            wind_unit=settings.WEATHER_WIND_UNIT,
        )
        _cache = (now, result)
        return result
    except Exception as exc:  # noqa: BLE001 — telemetry must degrade, not crash
        logger.warning("weather_fetch_failed", error=str(exc))
        if _cache is not None and now - _cache[0] < _STALE_MAX:
            return _cache[1]
        raise HTTPException(status_code=503, detail="weather unavailable") from exc
