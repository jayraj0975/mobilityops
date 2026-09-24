"""Response models for ``/api/v1/state/*``: the live operational picture of Pune."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from mobilityops.api.schemas import Model

TimeSelector = Literal["now", "-15m", "-1h", "-6h", "today", "forecast"]
FreshnessName = Literal["LIVE", "DELAYED", "STALE", "OFFLINE", "DISABLED", "NOT_PERIODIC"]
DataClassName = Literal[
    "LIVE", "NEAR-REAL-TIME", "RECENT", "HISTORICAL", "PREDICTED", "SIMULATED", "STATIC"
]
ZoneStatus = Literal["normal", "surge", "drop"]


class SourceState(Model):
    key: str
    label: str
    provider: str
    data_class: DataClassName
    modelled: bool
    licence: str
    note: str
    enabled: bool
    disabled_reason: str | None = None
    freshness: FreshnessName
    interval_s: int | None = None
    age_s: float | None = Field(default=None, description="Since the source's own timestamp.")
    since_poll_s: float | None = Field(default=None, description="Since our last good poll.")
    last_observed_at: datetime | None = None
    last_success_at: datetime | None = None
    last_error: str | None = None
    consecutive_failures: int
    runs: int
    successes: int
    records_total: int


class WorkerState(Model):
    freshness: FreshnessName
    last_tick_at: datetime | None = None
    age_s: float | None = None
    pid: int | None = None


class Reading(Model):
    value: float
    unit: str
    observed_at: datetime
    freshness: FreshnessName
    modelled: bool


class EnvironmentBlock(Model):
    temperature: Reading | None = None
    humidity: Reading | None = None
    precipitation: Reading | None = None
    wind: Reading | None = None
    pm2_5: Reading | None = None
    pm10: Reading | None = None
    us_aqi: Reading | None = None
    attribution: str


class ZoneValue(Model):
    id: int
    actual: float | None = Field(description="Simulated pickups in the window (null for FORECAST).")
    forecast: float
    lo: float
    hi: float
    ratio: float | None = None
    z: float | None = Field(default=None, description="Standardised deviation from the forecast.")
    status: ZoneStatus
    event_id: str | None = None


class EventItem(Model):
    id: str
    zone_id: int
    zone: str
    kind: Literal["surge", "drop"]
    severity: Literal["low", "medium", "high"]
    start: datetime
    end: datetime
    actual: float
    expected: float
    score: float
    detected_at: datetime
    explanation: str
    data_class: DataClassName


class Totals(Model):
    actual: float | None
    forecast: float
    lo: float
    hi: float
    ratio: float | None


class StateSnapshot(Model):
    server_time: datetime
    selector: TimeSelector
    window_start: datetime
    window_end: datetime
    window_note: str
    data_label: str
    city: str
    timezone: str
    seq: int = Field(description="Increases whenever the operational store changes.")
    freshness: FreshnessName = Field(description="The least healthy source that applies.")
    worker: WorkerState
    demand_class: DataClassName
    forecast_model: str | None = None
    forecast_made_at: datetime | None = None
    zones: list[ZoneValue]
    totals: Totals
    events: list[EventItem]
    environment: EnvironmentBlock
    sources: list[SourceState]


class ZoneGeometry(Model):
    id: int
    name: str
    sector: str
    lat: float
    lon: float
    area_km2: float
    ring: list[list[float]]


class Geometry(Model):
    city: str
    bbox: list[float]
    attribution: str
    licence: str
    method: str
    zones: list[ZoneGeometry]


class SeriesPoint(Model):
    hour: datetime
    actual: float | None
    forecast: float | None
    lo: float | None
    hi: float | None
    partial: bool


class ZoneDetail(Model):
    id: int
    name: str
    sector: str
    server_time: datetime
    data_label: str
    series: list[SeriesPoint]
    events: list[EventItem]
    today_actual: float
    today_forecast: float


class CitySeries(Model):
    server_time: datetime
    data_label: str
    envelope_note: str
    series: list[SeriesPoint]
    today_actual: float
    today_forecast: float


class IngestionRun(Model):
    id: int
    source: str
    started_at: datetime
    finished_at: datetime
    ok: bool
    records_in: int
    records_ok: int
    duration_ms: int
    error: str | None = None


class QualityItem(Model):
    check: str
    status: Literal["PASS", "WARN", "FAIL"]
    message: str


class DatabaseInfo(Model):
    available: bool
    run_id: str | None = None
    built_at_utc: str | None = None
    window_start: str | None = None
    window_end: str | None = None
    days_behind: int | None = Field(
        default=None, description="Days between the database's last day and today (extended live)."
    )
    rows_valid: int | None = None
    synthetic: bool | None = None
    checks: list[QualityItem]


class SourceHealth(Model):
    key: str
    label: str
    freshness: FreshnessName
    runs_24h: int
    success_rate_24h: float | None
    rejected_records_24h: int
    mean_duration_ms: float | None
    last_error: str | None = None


class DataQuality(Model):
    server_time: datetime
    data_label: str
    database: DatabaseInfo
    sources: list[SourceState]
    health: list[SourceHealth]
    runs: list[IngestionRun]
    notes: list[str]


class StreamStatus(Model):
    streams: int
    max_streams: int
    published: int
    dropped_events: int
