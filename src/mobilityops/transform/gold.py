"""Silver -> gold: the analytical star schema in DuckDB.

Tables (grain in brackets; see docs/DATA_DICTIONARY.md for columns):

* ``dim_zone``                    [one row per taxi zone]
* ``dim_date``                    [one row per local calendar date]
* ``dim_hour``                    [one row per local hour, with DST flags]
* ``fact_zone_hourly_demand``     [zone x valid local hour, zero-filled]
* ``fact_weather_daily``          [one row per date]
* ``dq_unallocated_dropoffs``     [reason x zone: trips whose dropoff is not in the fact table]
* ``dim_service`` and ``fact_service_zone_hourly``  [service x zone x valid local hour, zero-filled;
  yellow taxis plus any green / for-hire files that were ingested. Present only when at least
  one other service exists.]

The trip-level table is not copied into DuckDB: it stays in Parquet (``silver/trips.parquet``)
and is queried in place, which avoids duplicating hundreds of MB.

The database is built in a side file and promoted only after quality checks pass, so a failed
build never replaces a good one.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import duckdb
import pandas as pd

from mobilityops.config import Settings
from mobilityops.ingestion import adapters
from mobilityops.ingestion.pipeline import WEATHER_NAME, ZONE_LOOKUP_NAME, ZONES_GEOJSON_NAME
from mobilityops.log import get_logger
from mobilityops.schema import TLC_UNKNOWN_ZONE_IDS
from mobilityops.sqlutil import quote_literal
from mobilityops.transform.calendar import build_dim_date, build_dim_hour
from mobilityops.transform.services import ServiceSilver
from mobilityops.transform.silver import SilverResult

log = get_logger("transform.gold")

RAIN_THRESHOLD_MM = 1.0  # a day counts as "rainy" from 1 mm of precipitation


@dataclass(frozen=True)
class GoldResult:
    building_path: Path
    n_zones: int
    n_hours: int
    fact_rows: int
    service_rows: int = 0


def building_path(settings: Settings) -> Path:
    return settings.db_path.with_suffix(".building")


def build_dim_zone(settings: Settings) -> pd.DataFrame:
    lookup = adapters.read_zone_lookup(settings.raw_dir / ZONE_LOOKUP_NAME).rename(
        columns={"LocationID": "location_id", "Borough": "borough", "Zone": "zone"}
    )
    geo = adapters.read_zones_geojson(settings.raw_dir / ZONES_GEOJSON_NAME)[
        ["location_id", "centroid_lon", "centroid_lat", "area_deg2"]
    ]
    dim = lookup.merge(geo, on="location_id", how="left")
    dim["is_real_zone"] = ~dim["location_id"].isin(TLC_UNKNOWN_ZONE_IDS)
    return dim.sort_values("location_id").reset_index(drop=True)


def build_gold(
    settings: Settings,
    silver: SilverResult,
    window: tuple[date, date],
    services: list[ServiceSilver] | None = None,
) -> GoldResult:
    start, end = window
    path = building_path(settings)
    path.unlink(missing_ok=True)

    dim_zone = build_dim_zone(settings)
    dim_date = build_dim_date(start, end, settings.city)
    dim_hour = build_dim_hour(start, end, settings.city)
    weather = adapters.read_weather(settings.raw_dir / WEATHER_NAME)
    weather = weather[
        (weather["date"] >= pd.Timestamp(start)) & (weather["date"] < pd.Timestamp(end))
    ]

    con = duckdb.connect(str(path))
    try:
        for name, frame in (
            ("dim_zone", dim_zone),
            ("dim_date", dim_date),
            ("dim_hour", dim_hour),
            ("weather_src", weather),
        ):
            con.register(f"{name}_df", frame)
            con.execute(f"CREATE TABLE {name} AS SELECT * FROM {name}_df")
            con.unregister(f"{name}_df")
        con.execute(
            f"""
            CREATE TABLE fact_weather_daily AS
            SELECT date, prcp_mm, snow_mm, tmax_c, tmin_c,
                   coalesce(prcp_mm >= {RAIN_THRESHOLD_MM}, false) AS is_rain,
                   coalesce(snow_mm > 0, false) AS is_snow,
                   coalesce(tmax_c <= 0, false) AS is_freezing
            FROM weather_src ORDER BY date
            """
        )
        con.execute("DROP TABLE weather_src")
        trips = quote_literal(silver.trips_path.as_posix())
        con.execute(
            f"""
            CREATE TABLE fact_zone_hourly_demand AS
            WITH grid AS (
                SELECT z.location_id, h.hour_ts
                FROM dim_zone z CROSS JOIN dim_hour h
                WHERE z.is_real_zone AND h.is_valid
            ),
            pickup_agg AS (
                SELECT pu_zone AS location_id, date_trunc('hour', pickup_ts) AS hour_ts,
                       count(*) AS pickups, sum(total_amount) AS revenue,
                       sum(passenger_count) AS passengers
                FROM read_parquet({trips}) GROUP BY 1, 2
            ),
            dropoff_agg AS (
                SELECT do_zone AS location_id, date_trunc('hour', dropoff_ts) AS hour_ts,
                       count(*) AS dropoffs
                FROM read_parquet({trips}) GROUP BY 1, 2
            )
            SELECT g.location_id, g.hour_ts,
                   coalesce(pickup_agg.pickups, 0)::INTEGER AS pickups,
                   coalesce(dropoff_agg.dropoffs, 0)::INTEGER AS dropoffs,
                   coalesce(pickup_agg.revenue, 0)::DOUBLE AS revenue,
                   coalesce(pickup_agg.passengers, 0)::DOUBLE AS passengers
            FROM grid g
            LEFT JOIN pickup_agg ON pickup_agg.location_id = g.location_id
                 AND pickup_agg.hour_ts = g.hour_ts
            LEFT JOIN dropoff_agg ON dropoff_agg.location_id = g.location_id
                 AND dropoff_agg.hour_ts = g.hour_ts
            ORDER BY g.location_id, g.hour_ts
            """
        )
        # Pickups are validated (an unknown pickup zone rejects the trip). Dropoffs get the same
        # scrutiny without deleting the trip, whose pickup is real demand: a dropoff that cannot be
        # placed in the zone-hour grid is *accounted for* here instead of silently disappearing, and
        # a quality check requires placed + unplaced dropoffs to equal the trips exactly.
        con.execute(
            f"""
            CREATE TABLE dq_unallocated_dropoffs AS
            SELECT CASE WHEN z.location_id IS NULL THEN 'unknown_dropoff_zone'
                        ELSE 'dropoff_outside_grid' END AS reason,
                   CASE WHEN z.location_id IS NULL THEN t.do_zone END AS do_zone,
                   count(*)::BIGINT AS trips
            FROM read_parquet({trips}) t
            LEFT JOIN dim_zone z ON z.location_id = t.do_zone AND z.is_real_zone
            LEFT JOIN dim_hour h ON h.hour_ts = date_trunc('hour', t.dropoff_ts) AND h.is_valid
            WHERE z.location_id IS NULL OR h.hour_ts IS NULL
            GROUP BY 1, 2
            """
        )
        n_zones = int(con.execute("SELECT count(*) FROM dim_zone WHERE is_real_zone").fetchone()[0])  # type: ignore[index]
        n_hours = int(con.execute("SELECT count(*) FROM dim_hour WHERE is_valid").fetchone()[0])  # type: ignore[index]
        fact_rows = int(con.execute("SELECT count(*) FROM fact_zone_hourly_demand").fetchone()[0])  # type: ignore[index]
        service_rows = _build_service_fact(con, services or [])
    finally:
        con.close()
    log.info("gold built", extra={"ctx": {"zones": n_zones, "hours": n_hours, "rows": fact_rows}})
    return GoldResult(path, n_zones, n_hours, fact_rows, service_rows)


def _build_service_fact(con: duckdb.DuckDBPyConnection, services: list[ServiceSilver]) -> int:
    """Yellow plus the aggregated services on one zone-hour grid. Returns the row count."""
    if not services:
        return 0
    con.execute("CREATE TABLE dim_service(service VARCHAR, label VARCHAR)")
    con.execute("INSERT INTO dim_service VALUES ('yellow', 'Yellow taxis')")
    con.executemany(
        "INSERT INTO dim_service VALUES (?, ?)", [(s.service, s.label) for s in services]
    )
    parts = [
        "SELECT 'yellow' AS service, location_id, hour_ts, pickups::BIGINT AS pickups "
        "FROM fact_zone_hourly_demand"
    ]
    for s in services:
        parts.append(
            f"""
            SELECT {quote_literal(s.service)} AS service, g.location_id, g.hour_ts,
                   coalesce(a.pickups, 0)::BIGINT AS pickups
            FROM (SELECT z.location_id, h.hour_ts
                  FROM dim_zone z CROSS JOIN dim_hour h
                  WHERE z.is_real_zone AND h.is_valid) g
            LEFT JOIN read_parquet({quote_literal(s.hourly_path.as_posix())}) a
                 ON a.location_id = g.location_id AND a.hour_ts = g.hour_ts
            """
        )
    con.execute(
        "CREATE TABLE fact_service_zone_hourly AS "
        + " UNION ALL ".join(parts)
        + " ORDER BY 1, 2, 3"
    )
    return int(con.execute("SELECT count(*) FROM fact_service_zone_hourly").fetchone()[0])  # type: ignore[index]


def promote(settings: Settings) -> Path:
    """Atomically replace the live database with the freshly built (and checked) one."""
    os.replace(building_path(settings), settings.db_path)
    return settings.db_path
