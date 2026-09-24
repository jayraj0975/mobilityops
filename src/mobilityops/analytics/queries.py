"""Read-only analytical queries over the gold database.

This is the single data-access layer for everything user-facing: the API and the AI analyst both go
through it. That is deliberate. It means:

* **Bound parameters only.** Values from callers are always passed as SQL parameters. The few
  identifiers that vary (a metric column) are chosen from a fixed whitelist, never interpolated
  from input.
* **Read-only.** Connections are opened ``read_only=True``; nothing here can modify data.
* **Bounded.** Every query has a maximum output size, so a careless caller cannot ask for
  millions of rows.
* **Validated.** Unknown zones and impossible date ranges raise :class:`InvalidQuery` with a
  message a person can act on.

Time arguments are naive New York local times, half-open ``[start, end)``.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

import duckdb
import numpy as np
import pandas as pd

MAX_SERIES_POINTS = 20_000  # rows a single time-series query may return
MAX_TOP_N = 100

Metric = Literal["pickups", "dropoffs", "revenue"]
_METRIC_COLUMN: dict[str, str] = {
    "pickups": "pickups",
    "dropoffs": "dropoffs",
    "revenue": "revenue",
}
Grain = Literal["hour", "day"]

WEATHER_CAVEAT = (
    "This compares observed demand on days with and without the condition. It is an association: "
    "other things differ between such days, and one weather station stands in for the whole city, "
    "so it does not show that the weather caused the difference."
)


class AnalyticsError(ValueError):
    """Base class for errors caused by the request rather than by a bug."""


class InvalidQuery(AnalyticsError):
    """The request is malformed or out of range; the message says how to fix it."""


class NoData(AnalyticsError):
    """The request is valid but the data holds nothing for it."""


def _as_dt(value: date | datetime) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime(value.year, value.month, value.day)


@dataclass(frozen=True)
class DataRange:
    start: datetime  # first hour in the data
    end: datetime  # exclusive end
    n_zones: int
    mode: str
    synthetic: bool
    built_at_utc: str
    run_id: str
    rows_valid: int


class Analytics:
    def __init__(self, db_path: Path) -> None:
        if not db_path.exists():
            raise FileNotFoundError(f"no database at {db_path}. Run `ingest` and `build` first.")
        self.db_path = db_path
        self._range: DataRange | None = None
        self._zones: pd.DataFrame | None = None

    # ------------------------------------------------------------------ plumbing
    @contextmanager
    def _con(self) -> Iterator[duckdb.DuckDBPyConnection]:
        con = duckdb.connect(str(self.db_path), read_only=True)
        try:
            yield con
        finally:
            con.close()

    def _df(self, sql: str, params: Sequence[Any] = ()) -> pd.DataFrame:
        with self._con() as con:
            return con.execute(sql, list(params)).fetchdf()

    def _row(self, sql: str) -> tuple[Any, ...]:
        with self._con() as con:
            row = con.execute(sql).fetchone()
        if row is None:
            raise NoData("query returned no rows")
        return tuple(row)

    def _check_range(
        self, start: date | datetime, end: date | datetime
    ) -> tuple[datetime, datetime]:
        s, e = _as_dt(start), _as_dt(end)
        if e <= s:
            raise InvalidQuery(f"end ({e}) must be after start ({s})")
        r = self.data_range()
        if e <= r.start or s >= r.end:
            raise InvalidQuery(
                f"requested period {s:%Y-%m-%d %H:%M} to {e:%Y-%m-%d %H:%M} is outside the data "
                f"({r.start:%Y-%m-%d %H:%M} to {r.end:%Y-%m-%d %H:%M})"
            )
        return s, e

    def _check_zone(self, zone_id: int | None) -> None:
        if zone_id is None:
            return
        if not isinstance(zone_id, int | np.integer) or isinstance(zone_id, bool):
            raise InvalidQuery(f"zone id must be an integer, got {zone_id!r}")
        if int(zone_id) not in set(self.zones()["location_id"]):
            raise InvalidQuery(f"unknown zone id {zone_id}; use zones() to list valid ids")

    # -------------------------------------------------------------------- metadata
    def data_range(self) -> DataRange:
        if self._range is None:
            lo, hi = self._row("SELECT min(hour_ts), max(hour_ts) FROM fact_zone_hourly_demand")
            run = self._df("SELECT * FROM pipeline_run ORDER BY built_at_utc DESC LIMIT 1").iloc[0]
            (n_zones,) = self._row("SELECT count(*) FROM dim_zone WHERE is_real_zone")
            self._range = DataRange(
                start=lo,
                end=hi + timedelta(hours=1),
                n_zones=int(n_zones),
                mode=str(run["mode"]),
                synthetic=bool(run["synthetic"]),
                built_at_utc=str(run["built_at_utc"]),
                run_id=str(run["run_id"]),
                rows_valid=int(run["rows_valid"]),
            )
        return self._range

    def zones(self) -> pd.DataFrame:
        if self._zones is None:
            self._zones = self._df(
                "SELECT location_id, zone, borough, service_zone, centroid_lon, centroid_lat "
                "FROM dim_zone WHERE is_real_zone ORDER BY location_id"
            )
        return self._zones

    def zone_name(self, zone_id: int) -> str:
        self._check_zone(zone_id)
        z = self.zones()
        return str(z.loc[z["location_id"] == zone_id, "zone"].iloc[0])

    # ---------------------------------------------------------------------- series
    def demand_series(
        self,
        start: date | datetime,
        end: date | datetime,
        zone_id: int | None = None,
        grain: Grain = "hour",
        metric: Metric = "pickups",
    ) -> pd.DataFrame:
        """Demand over time for one zone, or summed over all zones when ``zone_id`` is None."""
        if grain not in ("hour", "day"):
            raise InvalidQuery("grain must be 'hour' or 'day'")
        col = self._metric(metric)
        s, e = self._check_range(start, end)
        self._check_zone(zone_id)
        bucket = (
            "f.hour_ts" if grain == "hour" else "CAST(date_trunc('day', f.hour_ts) AS TIMESTAMP)"
        )
        n_buckets = (e - s) / (timedelta(hours=1) if grain == "hour" else timedelta(days=1))
        if n_buckets > MAX_SERIES_POINTS:
            raise InvalidQuery(
                f"requested {int(n_buckets):,} {grain} points; the limit is {MAX_SERIES_POINTS:,}. "
                "Use a shorter period or grain='day'."
            )
        where = "f.hour_ts >= ? AND f.hour_ts < ?"
        params: list[Any] = [s, e]
        if zone_id is not None:
            where += " AND f.location_id = ?"
            params.append(int(zone_id))
        df = self._df(
            f"SELECT {bucket} AS ts, sum(f.{col}) AS value FROM fact_zone_hourly_demand f "  # noqa: S608 (bucket/col whitelisted; values bound)
            f"WHERE {where} GROUP BY 1 ORDER BY 1",
            params,
        )
        if df.empty:
            raise NoData("no demand data for that zone and period")
        return df

    def top_zones(
        self,
        start: date | datetime,
        end: date | datetime,
        metric: Metric = "pickups",
        limit: int = 10,
        ascending: bool = False,
    ) -> pd.DataFrame:
        """Zones ranked by a metric over a period, with each zone's share of the citywide total."""
        if not 1 <= limit <= MAX_TOP_N:
            raise InvalidQuery(f"limit must be between 1 and {MAX_TOP_N}")
        col = self._metric(metric)
        s, e = self._check_range(start, end)
        order = "ASC" if ascending else "DESC"
        df = self._df(
            f"""
            WITH t AS (
              SELECT location_id, sum({col}) AS value FROM fact_zone_hourly_demand
              WHERE hour_ts >= ? AND hour_ts < ? GROUP BY 1
            )
            SELECT z.location_id, z.zone, z.borough, t.value,
                   t.value / nullif(sum(t.value) OVER (), 0) AS share
            FROM t JOIN dim_zone z USING (location_id)
            ORDER BY t.value {order}, z.location_id LIMIT ?
            """,  # noqa: S608 (col whitelisted; order is a literal; values bound)
            [s, e, limit],
        )
        if df.empty:
            raise NoData("no demand data for that period")
        return df

    def hourly_profile(
        self, start: date | datetime, end: date | datetime, zone_id: int | None = None
    ) -> pd.DataFrame:
        """Average demand by hour of day (0-23), counting only whole days' worth of hours."""
        s, e = self._check_range(start, end)
        self._check_zone(zone_id)
        where = "f.hour_ts >= ? AND f.hour_ts < ?"
        params: list[Any] = [s, e]
        if zone_id is not None:
            where += " AND f.location_id = ?"
            params.append(int(zone_id))
        df = self._df(
            f"""
            WITH hourly AS (
              SELECT f.hour_ts, sum(f.pickups) AS p FROM fact_zone_hourly_demand f
              WHERE {where} GROUP BY 1
            )
            SELECT h.hour_of_day, avg(p) AS avg_pickups, count(*) AS n_hours
            FROM hourly JOIN dim_hour h USING (hour_ts) GROUP BY 1 ORDER BY 1
            """,  # noqa: S608 (where from fixed fragments; values bound)
            params,
        )
        if df.empty:
            raise NoData("no demand data for that zone and period")
        return df

    # -------------------------------------------------------------------- services
    def has_services(self) -> bool:
        """True when green-taxi or for-hire data were ingested for this database."""
        (n,) = self._row(
            "SELECT count(*) FROM information_schema.tables "
            "WHERE table_name = 'fact_service_zone_hourly'"
        )
        return bool(n)

    def service_list(self) -> pd.DataFrame:
        """The services present (``service``, ``label``); empty for a yellow-taxi-only database."""
        if not self.has_services():
            return pd.DataFrame({"service": [], "label": []})
        return self._df("SELECT service, label FROM dim_service ORDER BY service")

    def _require_services(self) -> None:
        if not self.has_services():
            raise NoData(
                "this database holds yellow-taxi data only; ingest with "
                "`--services green,fhvhv` and rebuild to compare services"
            )

    def service_mix(
        self,
        start: date | datetime,
        end: date | datetime,
        zone_id: int | None = None,
        grain: Literal["month", "total"] = "month",
    ) -> pd.DataFrame:
        """Pickups per service and each service's share of all services' pickups.

        The share is of *cleaned pickups counted in these files*: it is not the share of all
        mobility in the city (subways, buses, private cars and the older for-hire files are not
        here). Columns: ``period`` (start of the month, or of the requested period), ``service``,
        ``label``, ``pickups``, ``share``.
        """
        if grain not in ("month", "total"):
            raise InvalidQuery("grain must be 'month' or 'total'")
        self._require_services()
        s, e = self._check_range(start, end)
        self._check_zone(zone_id)
        bucket = "CAST(date_trunc('month', f.hour_ts) AS TIMESTAMP)" if grain == "month" else "?"
        params: list[Any] = ([s] if grain == "total" else []) + [s, e]
        where = "f.hour_ts >= ? AND f.hour_ts < ?"
        if zone_id is not None:
            where += " AND f.location_id = ?"
            params.append(int(zone_id))
        df = self._df(
            f"""
            WITH agg AS (
              SELECT {bucket} AS period, f.service, sum(f.pickups) AS pickups
              FROM fact_service_zone_hourly f WHERE {where} GROUP BY 1, 2
            )
            SELECT a.period, a.service, d.label, a.pickups::DOUBLE AS pickups,
                   a.pickups::DOUBLE / nullif(sum(a.pickups) OVER (PARTITION BY a.period), 0)
                     AS share
            FROM agg a JOIN dim_service d USING (service)
            ORDER BY a.period, a.service
            """,  # noqa: S608 (bucket/where from fixed fragments; values bound)
            params,
        )
        if df.empty:
            raise NoData("no service data for that period")
        return df

    def service_hourly_profile(
        self, start: date | datetime, end: date | datetime, zone_id: int | None = None
    ) -> pd.DataFrame:
        """Average pickups by hour of day (0-23) for each service."""
        self._require_services()
        s, e = self._check_range(start, end)
        self._check_zone(zone_id)
        where = "f.hour_ts >= ? AND f.hour_ts < ?"
        params: list[Any] = [s, e]
        if zone_id is not None:
            where += " AND f.location_id = ?"
            params.append(int(zone_id))
        df = self._df(
            f"""
            WITH hourly AS (
              SELECT f.service, f.hour_ts, sum(f.pickups) AS p FROM fact_service_zone_hourly f
              WHERE {where} GROUP BY 1, 2
            )
            SELECT hourly.service, h.hour_of_day, avg(p)::DOUBLE AS avg_pickups, count(*) AS n_hours
            FROM hourly JOIN dim_hour h USING (hour_ts) GROUP BY 1, 2 ORDER BY 1, 2
            """,  # noqa: S608 (where from fixed fragments; values bound)
            params,
        )
        if df.empty:
            raise NoData("no service data for that zone and period")
        return df

    def weekday_profile(
        self, start: date | datetime, end: date | datetime, zone_id: int | None = None
    ) -> pd.DataFrame:
        """Average daily demand by day of week (Monday = 0)."""
        daily = self.demand_series(start, end, zone_id, grain="day").copy()
        daily["day_of_week"] = pd.to_datetime(daily["ts"]).dt.dayofweek
        out = daily.groupby("day_of_week")["value"].agg(avg_daily_pickups="mean", n_days="count")
        return out.reset_index()

    # ------------------------------------------------------------------- comparisons
    def compare_periods(
        self,
        a_start: date | datetime,
        a_end: date | datetime,
        b_start: date | datetime,
        b_end: date | datetime,
        zone_id: int | None = None,
        metric: Metric = "pickups",
    ) -> dict[str, Any]:
        """Totals and per-day averages for two periods, and the change from A to B."""
        totals = []
        for s, e in ((a_start, a_end), (b_start, b_end)):
            ds = self.demand_series(s, e, zone_id, grain="day", metric=metric)
            span_days = (_as_dt(e) - _as_dt(s)).total_seconds() / 86400
            totals.append({"total": float(ds["value"].sum()), "days": span_days})
        a, b = totals
        a["per_day"] = a["total"] / a["days"]
        b["per_day"] = b["total"] / b["days"]
        change = b["per_day"] - a["per_day"]
        return {
            "metric": metric,
            "zone_id": zone_id,
            "period_a": a,
            "period_b": b,
            "per_day_change": change,
            "per_day_change_pct": (change / a["per_day"]) if a["per_day"] else None,
            "equal_length": abs(a["days"] - b["days"]) < 1e-9,
        }

    def growth(
        self, end: date | datetime, window_days: int = 7, zone_id: int | None = None
    ) -> dict[str, Any]:
        """Demand in the ``window_days`` before ``end`` versus the window before that."""
        if not 1 <= window_days <= 90:
            raise InvalidQuery("window_days must be between 1 and 90")
        e = _as_dt(end)
        mid = e - timedelta(days=window_days)
        return self.compare_periods(mid - timedelta(days=window_days), mid, mid, e, zone_id)

    def volatility(
        self, start: date | datetime, end: date | datetime, zone_id: int
    ) -> dict[str, Any]:
        """Variability of a zone's daily demand: mean, std and coefficient of variation."""
        v = self.demand_series(start, end, zone_id, grain="day")["value"].astype(float)
        mean = float(v.mean())
        std = float(v.std(ddof=1)) if len(v) > 1 else 0.0
        return {
            "zone_id": zone_id,
            "days": len(v),
            "mean_daily": mean,
            "std_daily": std,
            "coefficient_of_variation": (std / mean) if mean else None,
        }

    def concentration(
        self, start: date | datetime, end: date | datetime, top_n: int = 10
    ) -> dict[str, Any]:
        """How concentrated demand is: the top zones' share, and the Herfindahl index.

        The index is computed over **every** zone with demand in the period (a top-N list would drop
        the tail and understate it); ``zones_counted`` says how many that was.
        """
        if not 1 <= top_n <= MAX_TOP_N:
            raise InvalidQuery(f"top_n must be between 1 and {MAX_TOP_N}")
        s, e = self._check_range(start, end)
        df = self._df(
            """
            WITH t AS (
              SELECT location_id, sum(pickups) AS value FROM fact_zone_hourly_demand
              WHERE hour_ts >= ? AND hour_ts < ? GROUP BY 1
            )
            SELECT value / nullif(sum(value) OVER (), 0) AS share FROM t WHERE value > 0
            ORDER BY share DESC
            """,
            [s, e],
        )
        if df.empty:
            raise NoData("no demand data for that period")
        shares = df["share"].to_numpy(dtype=float)  # sorted, largest first, covers all zones
        return {
            "top_n": top_n,
            "top_n_share": float(shares[:top_n].sum()),
            "herfindahl_index": float((shares**2).sum()),
            "zones_counted": len(shares),
            "share_covered_by_top_100": float(shares[:MAX_TOP_N].sum()),
        }

    # ---------------------------------------------------------------------- weather
    def weather_comparison(
        self,
        start: date | datetime,
        end: date | datetime,
        condition: Literal["rain", "snow", "freezing"] = "rain",
        zone_id: int | None = None,
    ) -> dict[str, Any]:
        """Average daily demand on days with vs without a weather condition.

        Besides the raw ratio, a weekday-adjusted ratio is reported (the ratio within each day of
        week, averaged with weights by the number of condition days), because weekends and
        weekdays differ by more than most weather effects.
        """
        flag = {"rain": "is_rain", "snow": "is_snow", "freezing": "is_freezing"}.get(condition)
        if flag is None:
            raise InvalidQuery("condition must be 'rain', 'snow' or 'freezing'")
        daily = self.demand_series(start, end, zone_id, grain="day")
        w = self._df(
            f"SELECT CAST(date AS TIMESTAMP) AS ts, {flag} AS flag FROM fact_weather_daily"  # noqa: S608 (flag from a fixed mapping)
        )
        df = daily.merge(w, on="ts", how="inner")
        if df.empty:
            raise NoData("no weather data overlaps that period")
        df["dow"] = pd.to_datetime(df["ts"]).dt.dayofweek
        with_c, without_c = df[df["flag"]], df[~df["flag"]]
        out: dict[str, Any] = {
            "condition": condition,
            "zone_id": zone_id,
            "days_with": len(with_c),
            "days_without": len(without_c),
            "mean_daily_with": float(with_c["value"].mean()) if len(with_c) else None,
            "mean_daily_without": float(without_c["value"].mean()) if len(without_c) else None,
            "raw_ratio": None,
            "weekday_adjusted_ratio": None,
            "caveat": WEATHER_CAVEAT,
        }
        if len(with_c) and len(without_c):
            out["raw_ratio"] = out["mean_daily_with"] / out["mean_daily_without"]
            ratios, weights = [], []
            for _, g in df.groupby("dow"):
                a, b = g[g["flag"]], g[~g["flag"]]
                if len(a) and len(b) and b["value"].mean() > 0:
                    ratios.append(a["value"].mean() / b["value"].mean())
                    weights.append(len(a))
            if ratios:
                out["weekday_adjusted_ratio"] = float(np.average(ratios, weights=weights))
        return out

    # ------------------------------------------------------------------------ helpers
    @staticmethod
    def _metric(metric: str) -> str:
        col = _METRIC_COLUMN.get(metric)
        if col is None:
            raise InvalidQuery(f"metric must be one of {sorted(_METRIC_COLUMN)}, got {metric!r}")
        return col
