"""MET Norway locationforecast: an independent second provider for weather now and hourly rain.

Added after the first deployment on a shared cloud address, where Open-Meteo's forecast host
answered HTTP 429 to every request: one provider is a single point of failure. Data from MET
Norway (api.met.no), licensed CC BY 4.0 / NLOD 2.0 with attribution; their terms require an
identifying User-Agent, which every request sends.

``compact`` returns an hourly timeseries. Its first entry describes the current hour: instant
values (temperature, humidity, wind) and the precipitation expected in the next hour. Those are
model values, so they are labelled MODELLED, and the rain is a forecast for the coming hour, not a
measurement; the source registry says so.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

import httpx
import pandas as pd

from mobilityops.pune.sources.base import USER_AGENT, Observation, SourceError
from mobilityops.pune.sources.openmeteo import RANGES, TZ, UNITS

URL = "https://api.met.no/weatherapi/locationforecast/2.0/compact"
ATTRIBUTION = "Weather data from MET Norway (CC BY 4.0)"
SOURCE = "metno-forecast"
MS_TO_KMH = 3.6


def _valid(metric: str, value: Any) -> float | None:
    if value is None or isinstance(value, bool) or not isinstance(value, int | float):
        return None
    v = float(value)
    lo, hi = RANGES[metric]
    return v if lo <= v <= hi else None


def _series(payload: Any) -> list[dict[str, Any]]:
    ts = payload.get("properties", {}).get("timeseries") if isinstance(payload, dict) else None
    if not isinstance(ts, list) or not ts:
        raise SourceError("MET Norway response has no timeseries")
    return ts


def _when(text: Any) -> datetime:
    try:
        return datetime.fromisoformat(str(text).replace("Z", "+00:00")).astimezone(UTC)
    except ValueError as exc:
        raise SourceError(f"unparseable timestamp {text!r}") from exc


def parse_current(payload: Any, lat: float, lon: float, received_at: datetime) -> list[Observation]:
    """Observations for the current hour (the first timeseries entry)."""
    first = _series(payload)[0]
    observed = _when(first.get("time"))
    data = first.get("data", {})
    inst = data.get("instant", {}).get("details", {})
    wind = inst.get("wind_speed")
    values = {
        "temperature_2m": inst.get("air_temperature"),
        "relative_humidity_2m": inst.get("relative_humidity"),
        "wind_speed_10m": wind * MS_TO_KMH if isinstance(wind, int | float) else None,
        "precipitation": data.get("next_1_hours", {})
        .get("details", {})
        .get("precipitation_amount"),
    }
    out = []
    for metric, raw in values.items():
        v = _valid(metric, raw)
        if v is None:
            continue
        out.append(
            Observation(
                source=SOURCE,
                metric=metric,
                value=round(v, 2),
                unit=UNITS[metric],
                observed_at=observed,
                received_at=received_at,
                lat=lat,
                lon=lon,
                data_class="NEAR-REAL-TIME",
                modelled=True,
            )
        )
    if not out:
        raise SourceError("no usable values in the MET Norway response")
    return out


def parse_rain(payload: Any) -> pd.DataFrame:
    """Hourly precipitation expected for each hour from now on: ``hour_ts`` (naive Asia/Kolkata)
    and ``precipitation``. These are forecasts for the hours that have not happened yet."""
    tz = ZoneInfo(TZ)
    rows = []
    for entry in _series(payload):
        amount = (
            entry.get("data", {})
            .get("next_1_hours", {})
            .get("details", {})
            .get("precipitation_amount")
        )
        v = _valid("precipitation", amount)
        if v is None:
            continue
        local = _when(entry.get("time")).astimezone(tz).replace(tzinfo=None)
        rows.append((pd.Timestamp(local), v))
    return pd.DataFrame(rows, columns=["hour_ts", "precipitation"])


def fetch(client: httpx.Client, lat: float, lon: float) -> Any:
    try:
        resp = client.get(
            URL,
            params={"lat": f"{lat:.4f}", "lon": f"{lon:.4f}"},
            headers={"User-Agent": USER_AGENT},
            timeout=20,
        )
    except httpx.HTTPError as exc:
        raise SourceError(f"api.met.no unreachable: {exc.__class__.__name__}") from exc
    if resp.status_code != 200:
        raise SourceError(f"api.met.no answered HTTP {resp.status_code}")
    try:
        return resp.json()
    except ValueError as exc:
        raise SourceError("api.met.no returned invalid JSON") from exc
