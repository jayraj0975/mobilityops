"""Open-Meteo adapters: current weather, modelled air quality, and ERA5 history.

Endpoints and response shapes were checked against the live service on 2026-09-24 (see
docs/PUNE_DATA_SOURCES.md). Open-Meteo's free tier is for non-commercial use with attribution
(CC BY 4.0), which is how this project uses it.

"Current" here is the latest step of Open-Meteo's model blend at a coordinate, not a station
reading; air quality is a CAMS atmospheric-composition model on a coarse grid. Both are labelled
NEAR-REAL-TIME and the air-quality values carry ``modelled=True``.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from datetime import UTC, date, datetime
from typing import Any
from zoneinfo import ZoneInfo

import httpx
import pandas as pd

from mobilityops.pune.sources.base import USER_AGENT, Observation, SourceError

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
AIR_URL = "https://air-quality-api.open-meteo.com/v1/air-quality"
ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
TZ = "Asia/Kolkata"
ATTRIBUTION = "Weather data by Open-Meteo.com (CC BY 4.0)"

WEATHER_VARS = ("temperature_2m", "relative_humidity_2m", "precipitation", "wind_speed_10m")
AIR_VARS = ("pm2_5", "pm10", "us_aqi")
UNITS = {
    "temperature_2m": "°C",
    "relative_humidity_2m": "%",
    "precipitation": "mm",
    "wind_speed_10m": "km/h",
    "pm2_5": "µg/m³",
    "pm10": "µg/m³",
    "us_aqi": "index",
}
# Plausible physical ranges for Pune; a value outside is a bad reading, not a rare event.
RANGES: dict[str, tuple[float, float]] = {
    "temperature_2m": (0.0, 50.0),
    "relative_humidity_2m": (0.0, 100.0),
    "precipitation": (0.0, 300.0),
    "wind_speed_10m": (0.0, 200.0),
    "pm2_5": (0.0, 1000.0),
    "pm10": (0.0, 2000.0),
    "us_aqi": (0.0, 500.0),
}
MAX_ARCHIVE_DAYS = 800


def _coord_params(points: Sequence[tuple[float, float]]) -> dict[str, str]:
    return {
        "latitude": ",".join(f"{lat:.4f}" for lat, _ in points),
        "longitude": ",".join(f"{lon:.4f}" for _, lon in points),
    }


def _get(client: httpx.Client, url: str, params: dict[str, str]) -> Any:
    try:
        resp = client.get(url, params=params, headers={"User-Agent": USER_AGENT}, timeout=20)
    except httpx.HTTPError as exc:
        raise SourceError(f"{url.split('/')[2]} unreachable: {exc.__class__.__name__}") from exc
    if resp.status_code != 200:
        raise SourceError(f"{url.split('/')[2]} answered HTTP {resp.status_code}")
    try:
        return resp.json()
    except ValueError as exc:
        raise SourceError(f"{url.split('/')[2]} returned invalid JSON") from exc


def _local_to_utc(text: str) -> datetime:
    """Open-Meteo times are naive local (we ask for Asia/Kolkata); return aware UTC."""
    try:
        return datetime.fromisoformat(text).replace(tzinfo=ZoneInfo(TZ)).astimezone(UTC)
    except ValueError as exc:
        raise SourceError(f"unparseable timestamp {text!r}") from exc


def _valid(metric: str, value: Any) -> float | None:
    if value is None or isinstance(value, bool) or not isinstance(value, int | float):
        return None
    v = float(value)
    lo, hi = RANGES[metric]
    return v if math.isfinite(v) and lo <= v <= hi else None


def parse_current(
    payload: Any,
    points: Sequence[tuple[float, float]],
    variables: Sequence[str],
    *,
    source: str,
    received_at: datetime,
    modelled: bool,
) -> list[Observation]:
    """Turn a ``current=`` response (one object per requested point) into observations.

    Values outside their physical range or missing are dropped (the caller sees fewer records and
    the ingestion run records the shortfall); a payload with no usable value at all is an error.
    """
    blocks = payload if isinstance(payload, list) else [payload]
    if len(blocks) != len(points):
        raise SourceError(f"asked for {len(points)} points, got {len(blocks)}")
    out: list[Observation] = []
    for (lat, lon), block in zip(points, blocks, strict=True):
        cur = block.get("current") if isinstance(block, dict) else None
        if not isinstance(cur, dict) or "time" not in cur:
            raise SourceError("response has no current block")
        observed = _local_to_utc(str(cur["time"]))
        for var in variables:
            v = _valid(var, cur.get(var))
            if v is None:
                continue
            out.append(
                Observation(
                    source=source,
                    metric=var,
                    value=v,
                    unit=UNITS[var],
                    observed_at=observed,
                    received_at=received_at,
                    lat=lat,
                    lon=lon,
                    data_class="NEAR-REAL-TIME",
                    modelled=modelled,
                )
            )
    if not out:
        raise SourceError("no usable values in the response")
    return out


def fetch_current_weather(
    client: httpx.Client, points: Sequence[tuple[float, float]]
) -> list[Observation]:
    payload = _get(
        client,
        FORECAST_URL,
        {**_coord_params(points), "current": ",".join(WEATHER_VARS), "timezone": TZ},
    )
    return parse_current(
        payload,
        points,
        WEATHER_VARS,
        source="open-meteo-forecast",
        received_at=datetime.now(UTC),
        modelled=True,  # a model blend at the coordinate, not an instrument
    )


def fetch_current_air(
    client: httpx.Client, points: Sequence[tuple[float, float]]
) -> list[Observation]:
    payload = _get(
        client,
        AIR_URL,
        {**_coord_params(points), "current": ",".join(AIR_VARS), "timezone": TZ},
    )
    return parse_current(
        payload,
        points,
        AIR_VARS,
        source="open-meteo-air-quality",
        received_at=datetime.now(UTC),
        modelled=True,
    )


def parse_archive(payload: Any) -> pd.DataFrame:
    """Hourly history as a frame: ``hour_ts`` (naive local), temperature, precipitation, humidity.

    Missing values stay NaN: an hour with no reading is unknown, not zero.
    """
    hourly = payload.get("hourly") if isinstance(payload, dict) else None
    if not isinstance(hourly, dict) or "time" not in hourly:
        raise SourceError("archive response has no hourly block")
    frame = pd.DataFrame({"hour_ts": pd.to_datetime(hourly["time"], errors="coerce")})
    if frame["hour_ts"].isna().any():
        raise SourceError("archive response has unparseable timestamps")
    for var in ("temperature_2m", "precipitation", "relative_humidity_2m"):
        col = pd.to_numeric(pd.Series(hourly.get(var, [None] * len(frame))), errors="coerce")
        lo, hi = RANGES[var]
        frame[var] = col.where((col >= lo) & (col <= hi))
    if frame["hour_ts"].duplicated().any():
        raise SourceError("archive response has duplicate hours")
    return frame


def fetch_archive(
    client: httpx.Client, lat: float, lon: float, start: date, end: date
) -> pd.DataFrame:
    """ERA5 reanalysis for [start, end] inclusive. HISTORICAL: it lags real time by days."""
    if end < start:
        raise ValueError("end before start")
    if (end - start).days > MAX_ARCHIVE_DAYS:
        raise ValueError(f"at most {MAX_ARCHIVE_DAYS} days per request")
    payload = _get(
        client,
        ARCHIVE_URL,
        {
            **_coord_params([(lat, lon)]),
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "hourly": "temperature_2m,precipitation,relative_humidity_2m",
            "timezone": TZ,
        },
    )
    return parse_archive(payload)
