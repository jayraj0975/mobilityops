"""The analyst's tools: read-only, deterministic, validated and bounded.

An analyst answer is only as trustworthy as what its tools return, so every tool

* validates its arguments (Pydantic, bounded ranges and sizes),
* never writes, never accepts free-form SQL, code or file paths,
* returns *facts*: named values with a display string. Answer sentences are built from facts, and
  the grounding check (``guard.py``) refuses numbers that are not in a fact,
* reports expected failures (unknown zone, no data, artifact not generated) as a result with
  ``ok=False`` and a message, never as an exception.
"""

from __future__ import annotations

import difflib
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any, Literal

import numpy as np
import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from mobilityops.analyst.glossary import lookup
from mobilityops.analytics.queries import AnalyticsError
from mobilityops.api.services import NotReady, Services
from mobilityops.log import get_logger
from mobilityops.optimization.model import RebalanceParams
from mobilityops.optimization.run import scenario_report
from mobilityops.optimization.scenario import Window

MAX_ROWS = 25
log = get_logger("analyst.tools")


# ------------------------------------------------------------------------------ results
@dataclass(frozen=True)
class Fact:
    id: str  # "<call id>.<key>", cited by answer statements
    label: str
    value: float | str | None
    display: str


@dataclass
class ToolResult:
    call_id: str
    name: str
    args: dict[str, Any]
    ok: bool
    error: str | None = None
    data: dict[str, Any] = field(default_factory=dict)
    facts: dict[str, Fact] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)  # limitations the answer must carry
    candidates: list[str] = field(default_factory=list)  # for ambiguous references

    def add(
        self, key: str, label: str, value: float | str | None, display: str | None = None
    ) -> str:
        fid = f"{self.call_id}.{key}"
        shown = display if display is not None else ("n/a" if value is None else str(value))
        self.facts[fid] = Fact(fid, label, value, shown)
        return fid


def span(start: date, end_exclusive: date) -> str:
    """Inclusive display of a half-open date range."""
    last = end_exclusive - timedelta(days=1)
    return str(start) if last <= start else f"{start} to {last}"


def rows(df: pd.DataFrame) -> list[dict[str, Any]]:
    """DataFrame -> list of dicts with string keys (pandas' stubs type keys too loosely)."""
    return [{str(k): v for k, v in r.items()} for r in df.to_dict("records")]


def extreme_row(df: pd.DataFrame, col: str, *, largest: bool = True) -> dict[str, Any]:
    ordered = df.sort_values(col, ascending=not largest)
    return rows(ordered.head(1))[0]


def n(x: float | None, digits: int = 0) -> str:
    return "n/a" if x is None or (isinstance(x, float) and np.isnan(x)) else f"{x:,.{digits}f}"


def pct(x: float | None, digits: int = 1) -> str:
    return (
        "n/a" if x is None or (isinstance(x, float) and np.isnan(x)) else f"{100 * x:.{digits}f}%"
    )


# ---------------------------------------------------------------------------- arguments
class Args(BaseModel):
    model_config = ConfigDict(extra="forbid")


Zone = str | int | None
Metric = Literal["pickups", "dropoffs", "revenue"]


class NoArgs(Args):
    pass


class ZoneMetricsArgs(Args):
    zone: str | int
    start: date
    end: date


class TopZonesArgs(Args):
    start: date
    end: date
    metric: Metric = "pickups"
    limit: int = Field(5, ge=1, le=20)
    ascending: bool = False


class CompareArgs(Args):
    a_start: date
    a_end: date
    b_start: date
    b_end: date
    zone: Zone = None
    metric: Metric = "pickups"


class ProfileArgs(Args):
    start: date
    end: date
    zone: Zone = None


class WeatherArgs(Args):
    start: date
    end: date
    condition: Literal["rain", "snow", "freezing"] = "rain"
    zone: Zone = None


class ForecastArgs(Args):
    zone: Zone = None
    mode: Literal["next_day", "backtest"] = "next_day"
    day: date | None = None


class AnomalyArgs(Args):
    severity: Literal["low", "medium", "high"] | None = None
    direction: Literal["surge", "drop"] | None = None
    zone: Zone = None
    start: date | None = None
    end: date | None = None
    limit: int = Field(5, ge=1, le=10)


class ExplainArgs(Args):
    rank: int = Field(1, ge=1, le=500, description="1 = largest event")
    zone: Zone = None
    day: date | None = None


class ScenarioArgs(Args):
    day: date
    start_hour: int = Field(17, ge=0, le=23)
    end_hour: int = Field(20, ge=1, le=24)
    coverage: float = Field(0.85, ge=0.3, le=1.5)
    min_service_share: float | None = Field(None, gt=0, le=1)
    multipliers: dict[int, float] = Field(default_factory=dict)


class GlossaryArgs(Args):
    term: str = Field(min_length=1, max_length=60)


# ------------------------------------------------------------------------------ zones
@dataclass(frozen=True)
class ZoneRef:
    id: int
    name: str


def resolve_zone(ref: str | int, zones: pd.DataFrame) -> ZoneRef | list[str]:
    """Resolve a zone by id or name. Returns candidates (a list) when ambiguous or unknown."""
    if isinstance(ref, int) or (isinstance(ref, str) and ref.strip().isdigit()):
        zid = int(ref)
        row = zones[zones["location_id"] == zid]
        return ZoneRef(zid, str(row["zone"].iloc[0])) if len(row) else []
    text = re.sub(r"\s+", " ", str(ref).strip().lower())
    names = {int(r["location_id"]): str(r["zone"]) for r in rows(zones)}
    lower = {i: nm.lower() for i, nm in names.items()}
    exact = [i for i, nm in lower.items() if nm == text]
    if len(exact) == 1:
        return ZoneRef(exact[0], names[exact[0]])
    contained = [i for i, nm in lower.items() if text in nm or nm in text]
    if len(contained) == 1:
        return ZoneRef(contained[0], names[contained[0]])
    if len(contained) > 1:
        return [names[i] for i in contained[:6]]
    close = difflib.get_close_matches(text, list(lower.values()), n=4, cutoff=0.6)
    inv = {v: k for k, v in lower.items()}
    if len(close) == 1:
        return ZoneRef(inv[close[0]], names[inv[close[0]]])
    return [names[inv[c]] for c in close]


# ------------------------------------------------------------------------------ registry
Tool = Callable[["ToolContext", ToolResult, Any], None]


@dataclass
class ToolContext:
    services: Services

    def zone(self, ref: Zone, result: ToolResult) -> ZoneRef | None:
        """Resolve an optional zone reference; on failure fill in ``result`` and return None."""
        if ref is None:
            return None
        found = resolve_zone(ref, self.services.analytics().zones())
        if isinstance(found, ZoneRef):
            return found
        result.ok = False
        result.candidates = found
        result.error = (
            f"'{ref}' matches several zones: {', '.join(found)}"
            if len(found) > 1
            else (f"did you mean {found[0]}?" if found else f"no zone matches '{ref}'")
        )
        return None


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    args: type[Args]
    run: Tool

    def schema(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.args.model_json_schema(),
        }


# --------------------------------------------------------------------------- the tools
def _data_overview(ctx: ToolContext, r: ToolResult, a: NoArgs) -> None:
    rng = ctx.services.analytics().data_range()
    r.data = {
        "mode": rng.mode,
        "start": str(rng.start.date()),
        "end_exclusive": str(rng.end.date()),
        "zones": rng.n_zones,
        "rows": rng.rows_valid,
        "run_id": rng.run_id,
    }
    r.add("label", "Data label", ctx.services.data_label)
    r.add("start", "First day of data", str(rng.start.date()))
    r.add("end", "Last day of data", str((rng.end - timedelta(days=1)).date()))
    r.add("zones", "Taxi zones", rng.n_zones, n(rng.n_zones))
    r.add("trips", "Valid trips after cleaning", rng.rows_valid, n(rng.rows_valid))
    r.notes.append(
        "Yellow-taxi trips only (no green cabs, for-hire vehicles or ride-hail); timestamps are "
        "New York local time."
    )
    if rng.synthetic:
        r.notes.append("This is TEST / SYNTHETIC DATA, not real-world demand.")


def _zone_metrics(ctx: ToolContext, r: ToolResult, a: ZoneMetricsArgs) -> None:
    z = ctx.zone(a.zone, r)
    if z is None:
        return
    an = ctx.services.analytics()
    series = an.demand_series(a.start, a.end, zone_id=z.id, grain="day", metric="pickups")
    total = float(series["value"].sum())
    days = len(series)
    peak = extreme_row(series, "value")
    vol = an.volatility(a.start, a.end, z.id) if days >= 2 else None
    top = an.top_zones(a.start, a.end, limit=100)
    rank_row = top[top["location_id"] == z.id]
    r.data = {
        "zone": z.name,
        "zone_id": z.id,
        "total_pickups": total,
        "days": days,
        "peak_day": str(pd.Timestamp(peak["ts"]).date()),
        "peak_day_pickups": float(peak["value"]),
        "rank": int(rank_row.index[0]) + 1 if len(rank_row) else None,
        "share": float(rank_row["share"].iloc[0]) if len(rank_row) else None,
    }
    r.add("zone", "Zone", z.name)
    r.add("period", "Period", span(a.start, a.end))
    r.add("total", f"Pickups in {z.name}", total, n(total))
    r.add("days", "Days covered", days, n(days))
    r.add("per_day", "Average pickups per day", total / days, n(total / days))
    r.add("peak_day", "Busiest day", r.data["peak_day"])
    r.add(
        "peak_day_value",
        "Pickups on the busiest day",
        float(peak["value"]),
        n(float(peak["value"])),
    )
    if r.data["rank"]:
        r.add("rank", "Rank by pickups among all zones", r.data["rank"], n(r.data["rank"]))
        r.add("share", "Share of all pickups", r.data["share"], pct(r.data["share"]))
    else:
        r.notes.append("The zone is outside the top 100 by pickups for this period.")
    if vol and vol["coefficient_of_variation"] is not None:
        r.add("cv", "Day-to-day variability (std / mean)", vol["coefficient_of_variation"],
              n(vol["coefficient_of_variation"], 2))  # fmt: skip


def _top_zones(ctx: ToolContext, r: ToolResult, a: TopZonesArgs) -> None:
    df = ctx.services.analytics().top_zones(
        a.start, a.end, metric=a.metric, limit=a.limit, ascending=a.ascending
    )
    r.data = {"metric": a.metric, "rows": df.head(MAX_ROWS).to_dict("records")}
    r.add("period", "Period", span(a.start, a.end))
    for i, row in enumerate(rows(df), start=1):
        value, share = float(row["value"]), float(row["share"])
        r.add(f"r{i}.zone", f"Rank {i} zone", f"{row['zone']} ({row['borough']})")
        r.add(f"r{i}.value", f"{a.metric} in rank {i} zone", value, n(value))
        r.add(f"r{i}.share", f"Share of citywide {a.metric}, rank {i}", share, pct(share))


def _compare(ctx: ToolContext, r: ToolResult, a: CompareArgs) -> None:
    z = ctx.zone(a.zone, r)
    if a.zone is not None and z is None:
        return
    d = ctx.services.analytics().compare_periods(
        a.a_start, a.a_end, a.b_start, a.b_end, zone_id=z.id if z else None, metric=a.metric
    )
    r.data = d
    who = z.name if z else "the whole city"
    r.add("scope", "Scope", who)
    r.add("a_period", "Period A", span(a.a_start, a.a_end))
    r.add("b_period", "Period B", span(a.b_start, a.b_end))
    r.add("a_total", f"{a.metric} in period A", d["period_a"]["total"], n(d["period_a"]["total"]))
    r.add("b_total", f"{a.metric} in period B", d["period_b"]["total"], n(d["period_b"]["total"]))
    r.add("a_days", "Days in period A", d["period_a"]["days"], n(d["period_a"]["days"], 0))
    r.add("b_days", "Days in period B", d["period_b"]["days"], n(d["period_b"]["days"], 0))
    r.add("a_per_day", "Per day in period A", d["period_a"]["per_day"], n(d["period_a"]["per_day"]))
    r.add("b_per_day", "Per day in period B", d["period_b"]["per_day"], n(d["period_b"]["per_day"]))
    if d["per_day_change_pct"] is not None:
        r.add(
            "change_pct",
            "Change in per-day level, A to B",
            d["per_day_change_pct"],
            pct(d["per_day_change_pct"]),
        )
    if not d["equal_length"]:
        r.notes.append("The two periods have different lengths, so per-day figures are compared.")


def _profile(ctx: ToolContext, r: ToolResult, a: ProfileArgs) -> None:
    z = ctx.zone(a.zone, r)
    if a.zone is not None and z is None:
        return
    df = ctx.services.analytics().hourly_profile(a.start, a.end, zone_id=z.id if z else None)
    peak = extreme_row(df, "avg_pickups")
    low = extreme_row(df, "avg_pickups", largest=False)
    r.data = {"profile": df.to_dict("records")}
    r.add("scope", "Scope", z.name if z else "the whole city")
    r.add("peak_hour", "Busiest hour of day", f"{int(peak['hour_of_day']):02d}:00")
    r.add(
        "peak_avg",
        "Average pickups in the busiest hour",
        float(peak["avg_pickups"]),
        n(float(peak["avg_pickups"])),
    )
    r.add("low_hour", "Quietest hour of day", f"{int(low['hour_of_day']):02d}:00")
    r.add(
        "low_avg",
        "Average pickups in the quietest hour",
        float(low["avg_pickups"]),
        n(float(low["avg_pickups"])),
    )


def _weather(ctx: ToolContext, r: ToolResult, a: WeatherArgs) -> None:
    z = ctx.zone(a.zone, r)
    if a.zone is not None and z is None:
        return
    d = ctx.services.analytics().weather_comparison(
        a.start, a.end, condition=a.condition, zone_id=z.id if z else None
    )
    r.data = d
    r.add("condition", "Condition", a.condition)
    r.add("days_with", f"Days with {a.condition}", d["days_with"], n(d["days_with"]))
    r.add("days_without", f"Days without {a.condition}", d["days_without"], n(d["days_without"]))
    if d["mean_daily_with"] is not None and d["mean_daily_without"] is not None:
        r.add(
            "with", "Mean daily pickups on such days", d["mean_daily_with"], n(d["mean_daily_with"])
        )
        r.add(
            "without",
            "Mean daily pickups on other days",
            d["mean_daily_without"],
            n(d["mean_daily_without"]),
        )
    if d["raw_ratio"] is not None:
        r.add("ratio", "Ratio of the two (raw)", d["raw_ratio"], n(d["raw_ratio"], 2))
    if d["weekday_adjusted_ratio"] is not None:
        r.add(
            "adj_ratio",
            "Ratio after adjusting for weekday mix",
            d["weekday_adjusted_ratio"],
            n(d["weekday_adjusted_ratio"], 2),
        )
    r.notes.append(d["caveat"])


def _forecast(ctx: ToolContext, r: ToolResult, a: ForecastArgs) -> None:
    sv = ctx.services
    z = ctx.zone(a.zone, r)
    if a.zone is not None and z is None:
        return
    if a.mode == "next_day":
        frame, model_id = sv.next_day()
        t = sv.tensor()
        target = (t.days[-1] + timedelta(days=1)).date()
        sel = frame if z is None else frame[frame["location_id"] == z.id]
        if sel.empty:
            r.ok, r.error = False, "no forecast rows for that zone"
            return
        total = float(sel["pred"].sum())
        peak = extreme_row(sel, "pred")
        r.data = {"target_date": str(target), "model_id": model_id, "total": total}
        r.add("scope", "Scope", z.name if z else "the whole city")
        r.add("date", "Forecast day", str(target))
        r.add("total", "Forecast pickups for the day", total, n(total))
        r.add("peak_hour", "Forecast busiest hour", f"{pd.Timestamp(peak['hour_ts']).hour:02d}:00")
        r.add(
            "peak_value",
            "Forecast pickups in that hour",
            float(peak["pred"]),
            n(float(peak["pred"])),
        )
        if z is not None:
            r.add(
                "peak_lo",
                "Lower end of the 80% interval for that hour",
                float(peak["lo"]),
                n(float(peak["lo"])),
            )
            r.add(
                "peak_hi",
                "Upper end of the 80% interval for that hour",
                float(peak["hi"]),
                n(float(peak["hi"])),
            )
        else:
            r.notes.append("No interval is given for a city total: zone intervals cannot be added.")
        try:
            cov = float(sv.evaluation()["interval"]["overall"]["coverage"])
            r.add("coverage", "Measured coverage of the intervals on held-out days", cov, pct(cov))
        except (NotReady, KeyError):
            pass
        r.add(
            "nominal",
            "Nominal coverage of the interval",
            sv.model().coverage,
            pct(sv.model().coverage, 0),
        )
        r.notes.append("A forecast is an estimate from past patterns, not a guarantee.")
        return
    # backtest: a past out-of-sample day
    if a.day is None:
        r.ok, r.error = False, "a backtest needs a date"
        return
    t = sv.tensor()
    preds = sv.predictions()
    ts = pd.Timestamp(a.day)
    if ts not in t.days:
        r.ok, r.error = False, f"{a.day} is outside the data range"
        return
    di = int((ts - t.days[0]).days)
    sel = preds[preds["day_index"] == di]
    if z is not None:
        sel = sel[sel["location_id"] == z.id]
    if sel.empty:
        lo, hi = int(preds["day_index"].min()), int(preds["day_index"].max())
        r.ok = False
        r.error = f"no out-of-sample forecast for {a.day}; evaluation days are {t.days[lo].date()} to {t.days[hi].date()}"
        return
    actual, fc = float(sel["y"].sum()), float(sel["lightgbm"].sum())
    wape = float((sel["lightgbm"] - sel["y"]).abs().sum() / sel["y"].sum()) if actual > 0 else None
    inside = float(((sel["y"] >= sel["lo"]) & (sel["y"] <= sel["hi"])).mean())
    r.data = {"date": str(a.day), "actual": actual, "forecast": fc}
    r.add("scope", "Scope", z.name if z else "the whole city")
    r.add("date", "Day", str(a.day))
    r.add("actual", "Actual pickups", actual, n(actual))
    r.add("forecast", "Forecast pickups", fc, n(fc))
    if wape is not None:
        r.add("wape", "Error of hourly forecasts that day (WAPE)", wape, pct(wape))
    r.add("inside", "Share of hours inside the interval", inside, pct(inside))
    r.add("nominal", "Nominal coverage of the interval", 0.8, "80%")
    r.notes.append("This forecast was made from midnight using only earlier days (out-of-sample).")


def _model_performance(ctx: ToolContext, r: ToolResult, a: NoArgs) -> None:
    ev = ctx.services.evaluation()
    o = ev["overall"]
    best = ev["best_baseline"]
    imp = ev["bootstrap"]["improvement"][best]
    r.data = {"overall": o, "best_baseline": best}
    r.add("label", "Data label", ev["data_label"])
    r.add("wape", "LightGBM error (WAPE)", o["lightgbm"]["wape"], pct(o["lightgbm"]["wape"]))
    r.add(
        "mae",
        "LightGBM mean absolute error per zone-hour",
        o["lightgbm"]["mae"],
        n(o["lightgbm"]["mae"], 2),
    )
    r.add("best_baseline", "Strongest baseline", best.replace("_", " "))
    r.add("baseline_wape", "Strongest baseline error (WAPE)", o[best]["wape"], pct(o[best]["wape"]))
    r.add(
        "naive_wape",
        "Yesterday-copy baseline error (WAPE)",
        o["naive"]["wape"],
        pct(o["naive"]["wape"]),
    )
    r.add(
        "gain_pp",
        "WAPE difference to the strongest baseline, percentage points",
        100 * imp["wape_point_difference"],
        n(100 * imp["wape_point_difference"], 1),
    )
    r.add("ci_level", "Confidence level of the difference interval", 0.95, "95%")
    r.add(
        "gain_lo",
        "Lower end of its 95% interval, pp",
        100 * imp["difference_ci95"][0],
        n(100 * imp["difference_ci95"][0], 1),
    )
    r.add(
        "gain_hi",
        "Upper end of its 95% interval, pp",
        100 * imp["difference_ci95"][1],
        n(100 * imp["difference_ci95"][1], 1),
    )
    r.add(
        "coverage",
        "Measured coverage of the intervals",
        ev["interval"]["overall"]["coverage"],
        pct(ev["interval"]["overall"]["coverage"]),
    )
    r.add(
        "nominal",
        "Nominal coverage of the intervals",
        ev["interval"]["nominal"],
        pct(ev["interval"]["nominal"], 0),
    )
    r.add("test_days", "Held-out test days", ev["test_days"], n(ev["test_days"]))
    r.add("test_rows", "Held-out zone-hours", ev["test_rows"], n(ev["test_rows"]))
    r.notes.append("Only about five months of history exist, so annual seasonality is not learned.")
    r.notes.append("Federal holidays are forecast much worse than ordinary days.")


def _anomalies(ctx: ToolContext, r: ToolResult, a: AnomalyArgs) -> None:
    z = ctx.zone(a.zone, r)
    if a.zone is not None and z is None:
        return
    df = ctx.services.events()
    rep = ctx.services.anomaly_report()
    if a.severity:
        df = df[df["severity"] == a.severity]
    if a.direction:
        df = df[df["direction"] == a.direction]
    if z is not None:
        df = df[df["location_id"] == z.id]
    if a.start:
        df = df[df["end"] > pd.Timestamp(a.start)]
    if a.end:
        df = df[df["start"] < pd.Timestamp(a.end)]
    r.data = {"total": len(df), "returned": int(min(len(df), a.limit))}
    r.add("total", "Matching anomaly events", len(df), n(len(df)))
    # Say which filters were applied, so an answer can never look filtered when it is not.
    applied = [f"severity {a.severity}"] if a.severity else []
    applied += [f"direction {a.direction}"] if a.direction else []
    r.add("filters", "Filters applied", ", ".join(applied) if applied else "none")
    r.add("scored_days", "Days scored", f"{rep['scored_days'][0]} to {rep['scored_days'][1]}")
    for i, e in enumerate(df.head(a.limit).to_dict("records"), start=1):
        r.add(f"e{i}.zone", f"Event {i} zone", f"{e['zone']} ({e['borough']})")
        r.add(
            f"e{i}.when",
            f"Event {i} time",
            f"{pd.Timestamp(e['start']):%a %d %b %H:%M} to {pd.Timestamp(e['end']):%a %d %b %H:%M}",
        )
        r.add(f"e{i}.dir", f"Event {i} direction", str(e["direction"]))
        r.add(f"e{i}.sev", f"Event {i} severity", str(e["severity"]))
        if e["ratio"] is not None and not np.isnan(e["ratio"]):
            r.add(
                f"e{i}.ratio",
                f"Event {i} actual / forecast",
                float(e["ratio"]),
                n(float(e["ratio"]), 1),
            )
    r.notes.append(str(rep["accuracy_status"]))
    r.notes.append("Events describe deviations from the forecast; they do not establish causes.")


def _explain(ctx: ToolContext, r: ToolResult, a: ExplainArgs) -> None:
    z = ctx.zone(a.zone, r)
    if a.zone is not None and z is None:
        return
    df = ctx.services.events()
    if z is not None:
        df = df[df["location_id"] == z.id]
    if a.day is not None:
        d0 = pd.Timestamp(a.day)
        df = df[(df["start"] < d0 + pd.Timedelta(days=1)) & (df["end"] > d0)]
    if len(df) < a.rank:
        r.ok, r.error = False, "no matching anomaly event"
        return
    e = df.iloc[a.rank - 1].to_dict()
    r.data = {"explanation": str(e["explanation"]), "context": list(e["context"])}
    r.add("zone", "Zone", f"{e['zone']} ({e['borough']})")
    r.add(
        "when",
        "When",
        f"{pd.Timestamp(e['start']):%a %d %b %H:%M} to {pd.Timestamp(e['end']):%a %d %b %H:%M}",
    )
    r.add("direction", "Direction", str(e["direction"]))
    r.add("actual", "Actual pickups", float(e["actual"]), n(float(e["actual"])))
    r.add("forecast", "Forecast pickups", float(e["forecast"]), n(float(e["forecast"])))
    r.add("score", "Event score", float(e["event_z"]), n(float(e["event_z"]), 1))
    r.add(
        "overlap",
        "Other zones with events at the same time, same direction",
        int(e["overlapping_events"]),
        n(int(e["overlapping_events"])),
    )
    for i, c in enumerate(e["context"]):
        r.add(f"ctx{i}", "Context that coincided", str(c))
    r.notes.append("Context listed coincided with the event; it is not shown to be the cause.")


def _scenario(ctx: ToolContext, r: ToolResult, a: ScenarioArgs) -> None:
    sv = ctx.services
    if a.end_hour <= a.start_hour:
        r.ok, r.error = False, "end_hour must be after start_hour"
        return
    if not sv.solver_slots.acquire(blocking=False):
        r.ok, r.error = False, "the scenario solver is busy; try again shortly"
        return
    try:
        rep = scenario_report(
            sv.settings, a.day, Window(a.start_hour, a.end_hour),
            RebalanceParams(min_service_share=a.min_service_share, time_limit_s=10.0),
            coverage=a.coverage, multipliers=a.multipliers or None,
            t=sv.tensor(), preds=sv.predictions(),
        )  # fmt: skip
    finally:
        sv.solver_slots.release()
    r.data = {k: rep[k] for k in ("status", "message", "moves", "assumptions")}
    r.data["moves"] = rep["moves"][:5]
    r.add("status", "Solver status", rep["status"])
    r.add("window", "Window", f"{rep['context']['date']} {rep['context']['window']}")
    r.add("fleet", "Assumed fleet (vehicles)", rep["fleet"], n(rep["fleet"]))
    r.add(
        "before",
        "Served share without repositioning",
        rep["service_share_before"],
        pct(rep["service_share_before"], 2),
    )
    if rep["status"] in ("optimal", "feasible_time_limit"):
        r.add(
            "after",
            "Served share with the plan",
            rep["service_share_after"],
            pct(rep["service_share_after"], 2),
        )
        r.add("moved", "Vehicles repositioned", rep["vehicles_moved"], n(rep["vehicles_moved"]))
        r.add("km", "Total kilometres driven empty", rep["km_total"], n(rep["km_total"]))
    else:
        r.add("message", "Solver message", rep["message"])
        if rep["best_attainable_service_share"] is not None:
            r.add(
                "best",
                "Best attainable served share",
                rep["best_attainable_service_share"],
                pct(rep["best_attainable_service_share"]),
            )
    for k, v in rep["assumptions"].items():
        if k in ("coverage", "trips_per_vehicle", "max_km", "max_move_share", "cost_per_km"):
            r.add(f"assume.{k}", f"Assumption {k}", v, str(v))
    r.notes.append(
        "SIMULATED SCENARIO under explicit assumptions; not a prediction of real-world outcomes."
    )


def _optimization_findings(ctx: ToolContext, r: ToolResult, a: NoArgs) -> None:
    bt = ctx.services.backtest_report()
    p = bt["planners"]
    r.data = {"planners": p}
    r.add("windows", "Day-windows scored", bt["windows_scored"], n(bt["windows_scored"]))
    r.add(
        "none",
        "Served share with no repositioning",
        p["no_repositioning"]["served_share"],
        pct(p["no_repositioning"]["served_share"], 2),
    )
    r.add(
        "lgbm",
        "Served share planning with the LightGBM forecast",
        p["plan_lightgbm"]["served_share"],
        pct(p["plan_lightgbm"]["served_share"], 2),
    )
    r.add(
        "seasonal",
        "Served share planning with the seasonal-mean forecast",
        p["plan_seasonal_mean"]["served_share"],
        pct(p["plan_seasonal_mean"]["served_share"], 2),
    )
    r.add(
        "oracle",
        "Served share planning with the actual demand (upper bound)",
        p["plan_oracle"]["served_share"],
        pct(p["plan_oracle"]["served_share"], 2),
    )
    d = bt["lightgbm_vs_none"]
    r.add(
        "gain_pp",
        "LightGBM plan minus no repositioning, percentage points",
        100 * d["point"],
        n(100 * d["point"], 2),
    )
    r.notes.append(str(bt["label"]))
    r.notes.append("Supply, vehicle capacity and costs are assumptions; no fleet data exist.")


def _glossary(ctx: ToolContext, r: ToolResult, a: GlossaryArgs) -> None:
    hit = lookup(a.term)
    if hit is None:
        r.ok, r.error = False, f"no definition for '{a.term}'"
        return
    key, text = hit
    r.data = {"term": key, "definition": text}
    r.add("term", "Term", key)
    r.add("definition", "Definition", text)


TOOLS: dict[str, ToolSpec] = {
    t.name: t
    for t in (
        ToolSpec("get_data_overview", "What data is loaded: label, date range, zones, trips.", NoArgs, _data_overview),
        ToolSpec("get_zone_metrics", "Pickups, rank, share and variability for one zone over a period.", ZoneMetricsArgs, _zone_metrics),
        ToolSpec("get_top_zones", "Busiest (or quietest) zones over a period.", TopZonesArgs, _top_zones),
        ToolSpec("compare_periods", "Compare demand between two periods, citywide or for a zone.", CompareArgs, _compare),
        ToolSpec("get_hourly_profile", "Average demand by hour of day (busiest and quietest hour).", ProfileArgs, _profile),
        ToolSpec("get_weather_comparison", "Demand on days with and without rain, snow or freezing weather.", WeatherArgs, _weather),
        ToolSpec("get_forecast", "Next-day forecast, or an out-of-sample forecast vs actual for a past day.", ForecastArgs, _forecast),
        ToolSpec("get_model_performance", "How accurate the forecasting model is versus simple baselines.", NoArgs, _model_performance),
        ToolSpec("get_anomalies", "Detected demand anomalies (surges and drops) with filters.", AnomalyArgs, _anomalies),
        ToolSpec("explain_anomaly", "Details and coinciding context for one anomaly event.", ExplainArgs, _explain),
        ToolSpec("run_rebalancing_scenario", "SIMULATED vehicle repositioning what-if for a date and window.", ScenarioArgs, _scenario),
        ToolSpec("get_optimization_findings", "Results of the repositioning backtest (simulated).", NoArgs, _optimization_findings),
        ToolSpec("get_glossary", "Definition of a term used in the analysis.", GlossaryArgs, _glossary),
    )
}  # fmt: skip


def call_tool(services: Services, call_id: str, name: str, raw_args: dict[str, Any]) -> ToolResult:
    """Validate and run one tool. Expected failures come back as ``ok=False``, never raised."""
    result = ToolResult(call_id=call_id, name=name, args=raw_args, ok=True)
    spec = TOOLS.get(name)
    if spec is None:
        result.ok, result.error = False, f"unknown tool '{name}'"
        return result
    try:
        args = spec.args(**raw_args)
        result.args = {
            k: str(v) if isinstance(v, date) else v for k, v in args.model_dump().items()
        }
        spec.run(ToolContext(services), result, args)
    except ValidationError as exc:
        result.ok = False
        result.error = "; ".join(
            f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors()[:4]
        )
    except (AnalyticsError, NotReady, ValueError) as exc:
        result.ok, result.error = False, str(exc)
    except (KeyError, TypeError, IndexError) as exc:
        # A stale or malformed artifact (for example generated by an older version): report it
        # cleanly, keep the details in the log, and never let a tool crash the request.
        log.exception("tool failed", extra={"ctx": {"tool": name, "error": type(exc).__name__}})
        result.ok = False
        result.error = (
            "a stored artifact has an unexpected format; regenerate it "
            "(forecast-eval, anomalies, optimize-backtest)"
        )
    return result
