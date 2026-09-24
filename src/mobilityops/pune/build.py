"""Build the Pune analytical database.

Real inputs: hourly rain from the ERA5 archive, OpenStreetMap zones, the Maharashtra holiday
calendar. Simulated: the trip counts (``simulate.py``). The result has the same tables the New York
pipeline produces, so forecasting, anomaly detection, optimisation and the API run unchanged, and
the run is stamped ``synthetic`` with a SIMULATED label.

The build follows the same discipline as the New York pipeline: a quality gate runs on the freshly
built file, a FAIL stops the run, and the previously promoted database is left untouched.
"""

from __future__ import annotations

import hashlib
import json
import math
import platform
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import duckdb
import httpx
import lightgbm
import pandas as pd

from mobilityops.config import Settings
from mobilityops.log import get_logger
from mobilityops.pipeline import _git_commit, quality_dir
from mobilityops.pune import simulate
from mobilityops.pune.sources import openmeteo
from mobilityops.pune.zones import EARTH_RADIUS_M, load_zones
from mobilityops.quality.checks import QualityGateError, QualityReport, Status
from mobilityops.transform.calendar import build_dim_date, build_dim_hour
from mobilityops.transform.gold import RAIN_THRESHOLD_MM, building_path, promote

log = get_logger("pune.build")

SEED = 20260924
ARCHIVE_LAG_DAYS = 7  # ERA5 reaches within days of today; stay clear of the incomplete tail
DEFAULT_DAYS = 365
WEATHER_FILE = "weather_hourly.parquet"
PROVENANCE_FILE = "weather_provenance.json"
WEATHER_COVERAGE_WARN = 0.95
WEATHER_COVERAGE_FAIL = 0.50


@dataclass(frozen=True)
class PuneBuild:
    run_id: str
    db_path: Path
    window: tuple[date, date]
    zones: int
    hours: int
    trips: int
    report: QualityReport
    events: list[simulate.Event]


def default_window(today: date | None = None) -> tuple[date, date]:
    """The last ``DEFAULT_DAYS`` days that ERA5 covers: [start, end)."""
    end = (today or datetime.now(UTC).date()) - timedelta(days=ARCHIVE_LAG_DAYS)
    return end - timedelta(days=DEFAULT_DAYS), end


def zone_frame() -> pd.DataFrame:
    """``dim_zone`` for Pune from the committed OpenStreetMap-derived file."""
    doc = load_zones()
    rows = []
    for z in doc["zones"]:
        cos = math.cos(math.radians(z["lat"]))
        km2_per_deg2 = (math.pi / 180.0 * EARTH_RADIUS_M / 1000.0) ** 2 * cos
        rows.append(
            {
                "location_id": int(z["id"]),
                "borough": simulate.sector(z["lat"], z["lon"]),
                "zone": z["name"],
                "service_zone": z["place"],
                "centroid_lon": float(z["lon"]),
                "centroid_lat": float(z["lat"]),
                "area_deg2": float(z["area_km2"]) / km2_per_deg2,
                "is_real_zone": True,
            }
        )
    return pd.DataFrame(rows).sort_values("location_id").reset_index(drop=True)


def load_or_fetch_weather(
    settings: Settings,
    window: tuple[date, date],
    client: httpx.Client | None = None,
    refresh: bool = False,
) -> pd.DataFrame:
    """Hourly rain history for the window, cached with its provenance.

    Raises :class:`~mobilityops.pune.sources.base.SourceError` if the archive cannot be reached and
    no cached copy covers the window: there is no substitute, because the rain is what makes the
    simulated demand respond to real conditions.
    """
    settings.raw_dir.mkdir(parents=True, exist_ok=True)
    cache = settings.raw_dir / WEATHER_FILE
    if cache.exists() and not refresh:
        cached = pd.read_parquet(cache)
        need = pd.date_range(
            pd.Timestamp(window[0]), pd.Timestamp(window[1]), freq="h", inclusive="left"
        )
        if len(need) and need[0] >= cached["hour_ts"].min() and need[-1] <= cached["hour_ts"].max():
            return cached
    own = client is None
    http = client or httpx.Client()
    try:
        lat, lon = (
            settings.city.bbox[0] / 2 + settings.city.bbox[2] / 2,
            settings.city.bbox[1] / 2 + settings.city.bbox[3] / 2,
        )
        frame = openmeteo.fetch_archive(http, lat, lon, window[0], window[1] - timedelta(days=1))
    finally:
        if own:
            http.close()
    frame.to_parquet(cache, index=False)
    prov = {
        "source": "Open-Meteo archive (ERA5 reanalysis)",
        "url": openmeteo.ARCHIVE_URL,
        "attribution": openmeteo.ATTRIBUTION,
        "fetched_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "window_start": window[0].isoformat(),
        "window_end_exclusive": window[1].isoformat(),
        "rows": len(frame),
        "sha256": hashlib.sha256(cache.read_bytes()).hexdigest(),
        "data_class": "HISTORICAL",
    }
    (settings.raw_dir / PROVENANCE_FILE).write_text(json.dumps(prov, indent=2))
    return frame


def daily_weather(hourly: pd.DataFrame) -> pd.DataFrame:
    """Daily rain and temperature from hourly values; a day missing any hour has unknown rain."""
    d = hourly.assign(date=hourly["hour_ts"].dt.normalize())
    g = d.groupby("date")
    out = pd.DataFrame(
        {
            "prcp_mm": g["precipitation"].sum(min_count=24),
            "snow_mm": 0.0,
            "tmax_c": g["temperature_2m"].max(),
            "tmin_c": g["temperature_2m"].min(),
        }
    ).reset_index()
    out["is_rain"] = (out["prcp_mm"] >= RAIN_THRESHOLD_MM).fillna(False)
    out["is_snow"] = False
    out["is_freezing"] = (out["tmax_c"] <= 0).fillna(False)
    return out


def check_pune_gold(
    db_path: Path, window: tuple[date, date], n_zones: int, trips: int, holidays: int
) -> QualityReport:
    r = QualityReport("gold")
    con = duckdb.connect(str(db_path), read_only=True)
    try:

        def scalar(sql: str) -> Any:
            row = con.execute(sql).fetchone()
            assert row is not None
            return row[0]

        n_hours = int(scalar("SELECT count(*) FROM dim_hour WHERE is_valid"))
        rows = int(scalar("SELECT count(*) FROM fact_zone_hourly_demand"))
        r.add(
            "grid_complete",
            Status.PASS if rows == n_zones * n_hours else Status.FAIL,
            f"{rows:,} rows, expected zones x valid hours = {n_zones * n_hours:,}",
            rows=rows,
            expected=n_zones * n_hours,
        )
        orphans = int(
            scalar(
                "SELECT count(*) FROM fact_zone_hourly_demand f "
                "LEFT JOIN dim_zone z USING (location_id) WHERE z.location_id IS NULL"
            )
        )
        r.add(
            "referential_integrity_zone",
            Status.FAIL if orphans else Status.PASS,
            f"{orphans} fact rows reference an unknown zone"
            if orphans
            else "every fact zone exists",
        )
        bad = int(
            scalar(
                "SELECT count(*) FROM fact_zone_hourly_demand "
                "WHERE pickups < 0 OR dropoffs < 0 OR revenue < 0 OR pickups IS NULL"
            )
        )
        r.add(
            "counts_non_negative",
            Status.FAIL if bad else Status.PASS,
            "ok" if not bad else f"{bad} bad rows",
        )
        picks = int(scalar("SELECT coalesce(sum(pickups), 0) FROM fact_zone_hourly_demand"))
        drops = int(scalar("SELECT coalesce(sum(dropoffs), 0) FROM fact_zone_hourly_demand"))
        r.add(
            "pickups_reconcile_with_generator",
            Status.PASS if picks == trips else Status.FAIL,
            f"fact pickups {picks:,} vs generated trips {trips:,}",
        )
        r.add(
            "dropoffs_reconcile_with_pickups",
            Status.PASS if drops == picks else Status.FAIL,
            f"dropoffs {drops:,} vs pickups {picks:,}: every trip ends in the grid",
        )
        n_days = (window[1] - window[0]).days
        wdays = int(scalar("SELECT count(*) FROM fact_weather_daily WHERE prcp_mm IS NOT NULL"))
        cov = wdays / n_days if n_days else 0.0
        status = (
            Status.FAIL
            if cov < WEATHER_COVERAGE_FAIL
            else Status.PASS
            if cov >= WEATHER_COVERAGE_WARN
            else Status.WARN
        )
        r.add(
            "weather_coverage",
            status,
            f"rain history for {wdays} of {n_days} days ({cov:.1%}); missing days: no rain effect",
            coverage=cov,
        )
        r.add(
            "holiday_calendar_present",
            Status.PASS if holidays else Status.WARN,
            f"{holidays} Maharashtra/India public holidays in the window",
            holidays=holidays,
        )
        r.add(
            "demand_is_simulated",
            Status.PASS,
            "all trip counts are SIMULATED; only rain, calendar and geography are real inputs",
        )
    finally:
        con.close()
    return r


def _write_run(
    db_path: Path,
    settings: Settings,
    run_id: str,
    window: tuple[date, date],
    trips: int,
    report: QualityReport,
) -> None:
    run = pd.DataFrame(
        [
            {
                "run_id": run_id,
                "mode": settings.mode,
                "built_at_utc": datetime.now(UTC).isoformat(timespec="seconds"),
                "git_commit": _git_commit(),
                "window_start": window[0].isoformat(),
                "window_end": window[1].isoformat(),
                "rows_in": trips,
                "rows_valid": trips,
                "rows_rejected": 0,
                "python": platform.python_version(),
                "duckdb": duckdb.__version__,
                "pandas": pd.__version__,
                "lightgbm": lightgbm.__version__,
                "synthetic": True,
            }
        ]
    )
    quality = pd.DataFrame(
        [
            {
                "run_id": run_id,
                "stage": report.stage,
                "check": res.name,
                "status": res.status.value,
                "message": res.message,
            }
            for res in report.results
        ]
    )
    con = duckdb.connect(str(db_path))
    try:
        con.register("run_df", run)
        con.execute("CREATE TABLE pipeline_run AS SELECT * FROM run_df")
        con.register("q_df", quality)
        con.execute("CREATE TABLE quality_result AS SELECT * FROM q_df")
    finally:
        con.close()


def build_pune(
    settings: Settings,
    window: tuple[date, date] | None = None,
    *,
    seed: int = SEED,
    weather: pd.DataFrame | None = None,
    client: httpx.Client | None = None,
    refresh_weather: bool = False,
) -> PuneBuild:
    """Build and promote the Pune database. ``weather``: hourly frame to use instead of fetching."""
    if settings.mode != "pune":
        raise ValueError("Pune data can only be built with MOBILITYOPS_MODE=pune")
    window = window or default_window()
    if (window[1] - window[0]).days < 28:
        raise ValueError("the window must cover at least 28 days")
    city = settings.city
    settings.ensure_dirs()
    hourly = (
        weather
        if weather is not None
        else load_or_fetch_weather(settings, window, client, refresh_weather)
    )
    zones = zone_frame()
    model = simulate.build_model(zones)
    days = simulate.date_range(*window)
    events = simulate.plan_events(model, days, seed)
    fact = simulate.simulate_range(model, days, hourly, city, seed, events)
    trips = int(fact["pickups"].sum())
    dim_date = build_dim_date(*window, city)
    dim_hour = build_dim_hour(*window, city)
    weather_daily = daily_weather(
        hourly[
            (hourly["hour_ts"] >= pd.Timestamp(window[0]))
            & (hourly["hour_ts"] < pd.Timestamp(window[1]))
        ]
    )

    path = building_path(settings)
    path.unlink(missing_ok=True)
    con = duckdb.connect(str(path))
    try:
        for name, frame in (
            ("dim_zone", zones),
            ("dim_date", dim_date),
            ("dim_hour", dim_hour),
            ("fact_weather_daily", weather_daily),
            ("fact_zone_hourly_demand", fact),
            (
                "sim_events",
                pd.DataFrame(
                    [e.__dict__ for e in events], columns=list(simulate.Event.__dataclass_fields__)
                ),
            ),
        ):
            con.register("src_df", frame)
            con.execute(f"CREATE TABLE {name} AS SELECT * FROM src_df")  # noqa: S608  (fixed names)
            con.unregister("src_df")
        con.execute(
            "CREATE TABLE dq_unallocated_dropoffs(reason VARCHAR, do_zone INTEGER, trips BIGINT)"
        )
    finally:
        con.close()
    report = check_pune_gold(path, window, len(zones), trips, int(dim_date["is_holiday"].sum()))
    qdir = quality_dir(settings)
    report.write(qdir / "gold.json")
    try:
        report.raise_if_failed()
        run_id = f"{datetime.now(UTC):%Y%m%dT%H%M%SZ}-{uuid.uuid4().hex[:8]}"
        _write_run(path, settings, run_id, window, trips, report)
        db_path = promote(settings)
    except QualityGateError:
        path.unlink(missing_ok=True)  # never leave a half-built database
        raise
    (settings.raw_dir / "ground_truth.json").write_text(
        json.dumps(
            {
                "label": simulate.SIMULATED_LABEL,
                "seed": seed,
                "window": [window[0].isoformat(), window[1].isoformat()],
                "events": [e.__dict__ for e in events],
                "model": simulate.model_card(),
            },
            indent=2,
        )
    )
    log.info("pune database built", extra={"ctx": {"run_id": run_id, "trips": trips}})
    return PuneBuild(run_id, db_path, window, len(zones), len(dim_hour), trips, report, events)
