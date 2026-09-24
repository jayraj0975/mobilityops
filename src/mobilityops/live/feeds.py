"""Genuinely live public feeds: Citi Bike station availability and current Central Park weather.

Both are free, keyless public APIs, fetched only while a viewer is connected and cached in between.
Each feed reports its own freshness (``as_of`` is the time the *publisher* says the data is from,
not the time we fetched it) and, when a fetch fails, keeps the last good data and says so instead of
showing stale numbers as current.

* Citi Bike: the GBFS feed (``station_status.json`` and ``station_information.json``).
* Weather: National Weather Service, station KNYC (Central Park), latest observation.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import httpx

from mobilityops.log import get_logger

log = get_logger("live.feeds")

CITIBIKE_STATUS_URL = "https://gbfs.citibikenyc.com/gbfs/en/station_status.json"
CITIBIKE_INFO_URL = "https://gbfs.citibikenyc.com/gbfs/en/station_information.json"
NWS_URL = "https://api.weather.gov/stations/KNYC/observations/latest"
USER_AGENT = "mobilityops (https://github.com/jayraj0975/mobilityops)"
HISTORY_POINTS = 180  # about three hours at one poll a minute
LIST_SIZE = 5
FETCH_TIMEOUT = 15.0

SOURCES = {
    "citibike": "Citi Bike GBFS feed (https://gbfs.citibikenyc.com/), public and keyless",
    "weather": "National Weather Service, station KNYC (Central Park), api.weather.gov",
}


def _iso(ts: float | None) -> str | None:
    return None if ts is None else datetime.fromtimestamp(ts, UTC).isoformat()


def _num(x: Any) -> float | None:
    return float(x) if isinstance(x, int | float) and not isinstance(x, bool) else None


def summarize_citibike(status: dict[str, Any], info: dict[str, Any]) -> dict[str, Any]:
    """Network-wide availability from the two GBFS documents.

    A station counts as *active* when it is installed and renting. ``bikes`` sums the bikes
    available at active stations (this figure already includes e-bikes; ``ebikes`` is the e-bike
    part of it). ``empty`` and ``full`` count active stations with no bike, or no free dock.
    """
    meta = {s["station_id"]: s for s in info.get("data", {}).get("stations", [])}
    rows = status.get("data", {}).get("stations", [])
    active = [s for s in rows if s.get("is_installed") and s.get("is_renting")]
    bikes = sum(int(s.get("num_bikes_available") or 0) for s in active)
    ebikes = sum(int(s.get("num_ebikes_available") or 0) for s in active)
    docks = sum(int(s.get("num_docks_available") or 0) for s in active)

    def named(s: dict[str, Any]) -> dict[str, Any]:
        m = meta.get(s["station_id"], {})
        return {
            "name": m.get("name", s["station_id"]),
            "capacity": int(m.get("capacity") or 0),
            "bikes": int(s.get("num_bikes_available") or 0),
            "docks": int(s.get("num_docks_available") or 0),
        }

    empty = [named(s) for s in active if int(s.get("num_bikes_available") or 0) == 0]
    full = [named(s) for s in active if int(s.get("num_docks_available") or 0) == 0]
    key = lambda d: -d["capacity"]  # noqa: E731  (largest stations matter most)
    return {
        "stations": len(rows),
        "active": len(active),
        "offline": len(rows) - len(active),
        "bikes": bikes,
        "ebikes": ebikes,
        "docks": docks,
        "empty": len(empty),
        "full": len(full),
        "largest_empty": sorted(empty, key=key)[:LIST_SIZE],
        "largest_full": sorted(full, key=key)[:LIST_SIZE],
    }


def summarize_weather(obs: dict[str, Any]) -> dict[str, Any]:
    p = obs.get("properties", {})

    def val(name: str) -> float | None:
        return _num((p.get(name) or {}).get("value"))

    return {
        "description": p.get("textDescription") or None,
        "temperature_c": val("temperature"),
        "wind_kmh": val("windSpeed"),
        "humidity_pct": val("relativeHumidity"),
        "precipitation_last_hour_mm": val("precipitationLastHour"),
        "station": "KNYC (Central Park)",
    }


@dataclass
class FeedState:
    name: str
    status: str = "starting"  # starting | ok | unavailable
    as_of: str | None = None
    fetched_at: str | None = None
    error: str | None = None
    data: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": "feed",
            "feed": self.name,
            "status": self.status,
            "source": SOURCES[self.name],
            "as_of": self.as_of,
            "fetched_at": self.fetched_at,
            "error": self.error,
            "data": self.data,
        }


@dataclass
class LiveFeeds:
    """Poll both feeds; keep the last good data; remember a short availability history."""

    client: httpx.AsyncClient
    citibike: FeedState = field(default_factory=lambda: FeedState("citibike"))
    weather: FeedState = field(default_factory=lambda: FeedState("weather"))
    history: deque[dict[str, Any]] = field(default_factory=lambda: deque(maxlen=HISTORY_POINTS))
    _info: dict[str, Any] | None = None
    _info_at: float = 0.0

    async def _get(self, url: str) -> dict[str, Any]:
        r = await self.client.get(
            url,
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
            timeout=FETCH_TIMEOUT,
        )
        r.raise_for_status()
        body = r.json()
        if not isinstance(body, dict):
            raise ValueError("unexpected response shape")
        return body

    def _fail(self, state: FeedState, exc: Exception) -> None:
        state.status = "unavailable"
        state.error = f"{type(exc).__name__}: {exc}"[:200]
        log.warning("feed fetch failed", extra={"ctx": {"feed": state.name, "error": state.error}})

    async def poll_citibike(self, now: float) -> FeedState:
        s = self.citibike
        try:
            if self._info is None or now - self._info_at > 3600:  # station names change rarely
                self._info = await self._get(CITIBIKE_INFO_URL)
                self._info_at = now
            status = await self._get(CITIBIKE_STATUS_URL)
            s.data = summarize_citibike(status, self._info)
            s.as_of = _iso(_num(status.get("last_updated")))
            s.fetched_at = _iso(now)
            s.status, s.error = "ok", None
            self.history.append(
                {
                    "ts": s.as_of or s.fetched_at,
                    "bikes": s.data["bikes"],
                    "docks": s.data["docks"],
                    "empty": s.data["empty"],
                }
            )
        except Exception as exc:
            self._fail(s, exc)
        return s

    async def poll_weather(self, now: float) -> FeedState:
        s = self.weather
        try:
            obs = await self._get(NWS_URL)
            s.data = summarize_weather(obs)
            s.as_of = (obs.get("properties") or {}).get("timestamp")
            s.fetched_at = _iso(now)
            s.status, s.error = "ok", None
        except Exception as exc:
            self._fail(s, exc)
        return s

    def snapshot(self) -> dict[str, Any]:
        return {
            "citibike": self.citibike.to_dict(),
            "weather": self.weather.to_dict(),
            "history": list(self.history),
        }
