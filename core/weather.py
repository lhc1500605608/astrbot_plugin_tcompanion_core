"""Optional weather dimension for the life line (v1.4 · Phase 2-D).

Zero-key, fail-closed. The default source is the public Open-Meteo geocoding +
forecast API (no API key required); ``weather_api_base`` overrides **both**
endpoints for self-hosted or offline-stub use. When no city is configured the
whole dimension is off and the caller behaves exactly like v1.3.0.

Privacy: results live only in an in-memory TTL cache (default 45 min); nothing
is persisted and only derived values (weather code / temperature /
precipitation) are returned.
"""

from __future__ import annotations

import asyncio
import json
import time
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from datetime import datetime, timezone

#: Official endpoints (used when ``weather_api_base`` is empty).
DEFAULT_GEOCODE_BASE = "https://geocoding-api.open-meteo.com"
DEFAULT_FORECAST_BASE = "https://api.open-meteo.com"

#: Frozen request timeout and in-memory cache TTL.
WEATHER_TIMEOUT_SEC = 3.0
WEATHER_TTL_MINUTES = 45

#: WMO weather code -> short Chinese description.
WMO_TEXT: dict[int, str] = {
    0: "晴",
    1: "多云转晴",
    2: "多云",
    3: "阴",
    45: "雾",
    48: "雾凇",
    51: "小毛毛雨",
    53: "毛毛雨",
    55: "大毛毛雨",
    61: "小雨",
    63: "中雨",
    65: "大雨",
    71: "小雪",
    73: "中雪",
    75: "大雪",
    77: "雪粒",
    80: "阵雨",
    81: "强阵雨",
    82: "暴雨",
    85: "阵雪",
    86: "强阵雪",
    95: "雷阵雨",
    96: "雷阵雨伴冰雹",
    99: "强雷暴伴冰雹",
}


@dataclass(frozen=True)
class WeatherInfo:
    """One derived weather reading (no raw payload retained)."""

    code: int
    temp: float
    precip: float
    text: str = ""
    city: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def weather_text(code: int) -> str:
    """Map a WMO weather code to a short description (``""`` when unknown)."""
    try:
        return WMO_TEXT.get(int(code), "")
    except (TypeError, ValueError):
        return ""


def _urllib_json(url: str, timeout: float) -> dict:
    request = urllib.request.Request(url, headers={"User-Agent": "tcompanion-core/1.4"})
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
        return json.loads(response.read().decode("utf-8"))


class WeatherClient:
    """Fail-closed Open-Meteo reader with an in-memory TTL cache.

    ``fetcher`` may be injected to bypass the network (tests/QA): it is an
    async callable ``(url) -> dict`` returning parsed JSON. Any exception,
    timeout, missing field or empty result yields ``None`` — never a raise.
    """

    def __init__(
        self,
        *,
        city: str = "",
        api_base: str = "",
        timeout: float = WEATHER_TIMEOUT_SEC,
        ttl_minutes: int = WEATHER_TTL_MINUTES,
        fetcher=None,
        clock=None,
    ) -> None:
        self._city = (city or "").strip()
        self._api_base = (api_base or "").strip()
        self._timeout = max(0.1, float(timeout))
        self._ttl = max(0, int(ttl_minutes)) * 60
        self._fetcher = fetcher
        self._clock = clock or time.monotonic
        self._cache: dict[str, tuple[float, dict]] = {}

    @property
    def city(self) -> str:
        return self._city

    @property
    def enabled(self) -> bool:
        """Weather is active only when a city is configured."""
        return bool(self._city)

    def clear_cache(self) -> None:
        """Drop the in-memory cache (privacy: nothing is persisted)."""
        self._cache.clear()

    async def get(self, city: str | None = None) -> dict | None:
        """Return ``{code,temp,precip,text,city}`` for ``city`` or ``None``."""
        target = (city if city is not None else self._city).strip()
        if not target:
            return None
        cached = self._cache.get(target)
        if cached is not None and (self._clock() - cached[0]) < self._ttl:
            return dict(cached[1])
        try:
            result = await asyncio.wait_for(self._fetch(target), timeout=self._timeout)
        except Exception:
            result = None
        # Only successful readings are cached; failures retry on the next call.
        if result is not None:
            self._cache[target] = (self._clock(), result)
        return result

    # -- internals ---------------------------------------------------------
    async def _fetch(self, city: str) -> dict | None:
        geo = await self._request_json(self._geocode_url(city))
        location = self._parse_location(geo)
        if location is None:
            return None
        lat, lon = location
        data = await self._request_json(self._forecast_url(lat, lon))
        return self._parse_weather(data, city)

    async def _request_json(self, url: str) -> dict:
        if self._fetcher is not None:
            return await self._fetcher(url)
        return await asyncio.to_thread(_urllib_json, url, self._timeout)

    def _geocode_url(self, city: str) -> str:
        base = (self._api_base or DEFAULT_GEOCODE_BASE).rstrip("/")
        query = urllib.parse.urlencode(
            {"name": city, "count": 1, "language": "zh", "format": "json"}
        )
        return f"{base}/v1/search?{query}"

    def _forecast_url(self, lat: float, lon: float) -> str:
        base = (self._api_base or DEFAULT_FORECAST_BASE).rstrip("/")
        query = urllib.parse.urlencode(
            {
                "latitude": lat,
                "longitude": lon,
                "current": "temperature_2m,weather_code,precipitation",
            }
        )
        return f"{base}/v1/forecast?{query}"

    @staticmethod
    def _parse_location(data) -> tuple[float, float] | None:
        try:
            results = data.get("results") or []
            first = results[0]
            return float(first["latitude"]), float(first["longitude"])
        except (AttributeError, IndexError, KeyError, TypeError, ValueError):
            return None

    @staticmethod
    def _parse_weather(data, city: str) -> dict | None:
        try:
            current = data["current"]
            code = int(current["weather_code"])
            temp = float(current["temperature_2m"])
            precip = float(current.get("precipitation") or 0.0)
        except (KeyError, TypeError, ValueError):
            return None
        return WeatherInfo(
            code=code,
            temp=round(temp, 1),
            precip=round(precip, 2),
            text=weather_text(code),
            city=city,
        ).to_dict()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
