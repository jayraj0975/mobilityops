"""Request and response models. These are the API contract and generate the OpenAPI document."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

Day = date  # alias: a field called ``date`` would otherwise shadow the type in its own class
Metric = Literal["pickups", "dropoffs", "revenue"]
Grain = Literal["hour", "day"]
Severity = Literal["low", "medium", "high"]
Direction = Literal["surge", "drop"]


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ------------------------------------------------------------------------------ operations
class Health(Model):
    status: Literal["ok"] = "ok"


class Ready(Model):
    status: Literal["ready", "degraded"]
    components: dict[str, bool]
    hint: str | None = None


class ErrorBody(Model):
    code: str
    message: str
    request_id: str
    details: list[dict[str, str]] | None = None


class ErrorResponse(Model):
    error: ErrorBody


class Meta(Model):
    api_version: str
    mode: Literal["sample", "real"]
    data_label: str
    synthetic: bool
    data_start: datetime
    data_end: datetime = Field(description="Exclusive end of the data window (local time).")
    n_zones: int
    rows_valid: int
    run_id: str
    built_at_utc: str
    llm_configured: bool
    artifacts: dict[str, bool]
    timezone: str = "America/New_York (timestamps are naive local time)"


class QualityCheck(Model):
    name: str
    status: Literal["PASS", "WARN", "FAIL"]
    message: str
    metrics: dict[str, Any] = {}


class QualityStage(Model):
    stage: str
    overall: Literal["PASS", "WARN", "FAIL"]
    results: list[QualityCheck]


# ---------------------------------------------------------------------------------- zones
class Zone(Model):
    location_id: int
    zone: str
    borough: str
    service_zone: str | None = None
    centroid_lon: float | None = None
    centroid_lat: float | None = None


# --------------------------------------------------------------------------------- demand
class SeriesPoint(Model):
    ts: datetime
    value: float


class SeriesResponse(Model):
    zone_id: int | None
    zone_name: str | None
    grain: Grain
    metric: Metric
    start: date
    end: date
    points: list[SeriesPoint]


class TopZone(Model):
    location_id: int
    zone: str
    borough: str
    value: float
    share: float = Field(description="Share of the citywide total for the same period.")


class HourProfilePoint(Model):
    hour_of_day: int
    avg_pickups: float
    n_hours: int


class WeekdayPoint(Model):
    day_of_week: int = Field(description="Monday = 0")
    avg_daily_pickups: float
    n_days: int


class PeriodTotals(Model):
    total: float
    days: float
    per_day: float


class Comparison(Model):
    metric: str
    zone_id: int | None
    period_a: PeriodTotals
    period_b: PeriodTotals
    per_day_change: float
    per_day_change_pct: float | None
    equal_length: bool


class Volatility(Model):
    zone_id: int
    days: int
    mean_daily: float
    std_daily: float
    coefficient_of_variation: float | None


class Concentration(Model):
    top_n: int
    top_n_share: float
    herfindahl_index: float
    share_covered_by_top_100: float | None = None


class WeatherComparison(Model):
    condition: str
    zone_id: int | None
    days_with: int
    days_without: int
    mean_daily_with: float | None
    mean_daily_without: float | None
    raw_ratio: float | None
    weekday_adjusted_ratio: float | None
    caveat: str


# ------------------------------------------------------------------------------- forecast
class ForecastPoint(Model):
    hour_ts: datetime
    forecast: float
    lo: float | None = None
    hi: float | None = None
    actual: float | None = None


class BacktestForecast(Model):
    data_label: str
    zone_id: int
    zone_name: str
    date: Day
    note: str
    points: list[ForecastPoint]


class NextDayForecast(Model):
    data_label: str
    model_id: str
    target_date: date
    zone_id: int | None
    zone_name: str | None
    nominal_coverage: float
    empirical_coverage_in_evaluation: float | None
    note: str
    points: list[ForecastPoint]


class ArtifactDocument(Model):
    """A generated report served as-is (its own ``data_label`` and status wording are kept)."""

    model_config = ConfigDict(extra="allow")


# ------------------------------------------------------------------------------- anomalies
class AnomalyItem(Model):
    event_id: int
    location_id: int
    zone: str
    borough: str
    direction: Direction
    severity: Severity
    start: datetime
    end: datetime
    hours_flagged: int
    hours_span: int
    event_z: float
    peak_z: float
    actual: float
    forecast: float
    excess: float
    ratio: float | None
    scope: str
    citywide_share: float
    overlapping_events: int
    context: list[str]
    explanation: str


class AnomalyPage(Model):
    data_label: str
    accuracy_status: str
    total: int
    limit: int
    offset: int
    items: list[AnomalyItem]


# ------------------------------------------------------------------------------ optimization
class ScenarioRequest(Model):
    date: Day = Field(description="An out-of-sample day (the evaluation days).")
    start_hour: int = Field(17, ge=0, le=23)
    end_hour: int = Field(20, ge=1, le=24)
    coverage: float = Field(0.85, ge=0.3, le=1.5, description="Fleet capacity / expected demand.")
    trips_per_vehicle: float = Field(4.5, gt=0, le=50)
    max_km: float = Field(6.0, gt=0, le=25)
    max_move_share: float = Field(0.30, ge=0, le=1)
    cost_per_km: float = Field(0.02, ge=0, le=5)
    min_service_share: float | None = Field(None, gt=0, le=1)
    demand_multipliers: dict[int, float] = Field(
        default_factory=dict, description="Zone id -> demand factor (a what-if shock)."
    )

    @field_validator("demand_multipliers")
    @classmethod
    def _bounded(cls, v: dict[int, float]) -> dict[int, float]:
        if len(v) > 20:
            raise ValueError("at most 20 zone multipliers")
        for zone, factor in v.items():
            if not 0 <= factor <= 5:
                raise ValueError(f"multiplier for zone {zone} must be between 0 and 5")
        return v

    @field_validator("end_hour")
    @classmethod
    def _order(cls, v: int, info: Any) -> int:
        if "start_hour" in info.data and v <= info.data["start_hour"]:
            raise ValueError("end_hour must be greater than start_hour")
        return v


class Move(Model):
    from_zone: int
    to_zone: int
    from_name: str
    to_name: str
    vehicles: float
    km: float


class ScenarioResponse(Model):
    label: str
    data_label: str
    status: Literal["optimal", "feasible_time_limit", "infeasible", "no_solution"]
    message: str
    context: dict[str, Any]
    assumptions: dict[str, Any]
    fleet: int
    demand_total: float
    served_before: float
    served_after: float
    service_share_before: float | None
    service_share_after: float | None
    vehicles_moved: int
    km_total: float
    best_attainable_service_share: float | None
    moves: list[Move]
    solver: dict[str, Any]


# --------------------------------------------------------------------------------- analyst
class AnalystRequest(Model):
    question: str = Field(min_length=1, max_length=500)


class AnalystStatement(Model):
    kind: Literal["FACT", "INTERPRETATION", "ASSUMPTION", "LIMITATION"]
    text: str
    fact_ids: list[str]


class AnalystFact(Model):
    id: str
    label: str
    value: str


class AnalystToolTrace(Model):
    call_id: str
    name: str
    args: dict[str, Any]
    ok: bool
    error: str | None
    facts: list[AnalystFact]
    data: dict[str, Any]


class AnalystResponse(Model):
    question: str
    status: Literal["answered", "partial", "clarify", "refused", "no_data"]
    mode: str
    intent: str
    data_label: str
    statements: list[AnalystStatement]
    tools_used: list[AnalystToolTrace]
    warnings: list[str]
    grounding: dict[str, int]


class AnalystStatus(Model):
    planner: str
    llm_configured: bool
    llm_status: str
    tools: int
    note: str
