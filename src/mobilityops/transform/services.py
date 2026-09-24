"""Green-taxi and high-volume for-hire files -> cleaned pickups per zone-hour.

Yellow taxis keep their full trip-level pipeline (``silver``). The other services are aggregated
straight to counts: a demand model only needs pickups, and the for-hire file alone is about
470 MB and 20 million trips a month, so a trip-level copy would add gigabytes for no benefit.

The cleaning rules are the ones used for yellow taxis, in the same order, applied to each family's
own columns (``schema.SERVICE_SPECS``). Every rejected row is *counted* by its first failing rule
and file, so nothing disappears silently, but the rows themselves are not written out (unlike the
yellow quarantine file). One rule is not applied: exact-duplicate removal, which needs the whole
trip table in memory; the yellow data has 4 duplicates in 41 million rows.

Timestamps are New York local time, as for yellow taxis.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import duckdb

from mobilityops.config import Settings
from mobilityops.ingestion.adapters import inspect_service_trips
from mobilityops.log import get_logger
from mobilityops.schema import SERVICE_SPECS, ServiceSpec
from mobilityops.sqlutil import quote_literal
from mobilityops.transform.silver import MAX_DISTANCE_MILES, MAX_TRIP_HOURS

log = get_logger("transform.services")


@dataclass(frozen=True)
class ServiceSilver:
    service: str
    label: str
    files: list[str]
    rows_in: int
    rows_valid: int
    rejected: dict[str, int]  # reason -> count
    rejected_by_file: dict[str, dict[str, int]] = field(default_factory=dict)
    hourly_path: Path = Path()

    @property
    def rows_rejected(self) -> int:
        return sum(self.rejected.values())


def service_dir(settings: Settings) -> Path:
    return settings.processed_dir / "silver"


def hourly_path(settings: Settings, service: str) -> Path:
    return service_dir(settings) / f"service_{service}_hourly.parquet"


def available_services(settings: Settings) -> list[str]:
    """Services that have at least one raw file in the current mode's raw directory."""
    return [
        name
        for name, spec in SERVICE_SPECS.items()
        if any(settings.raw_dir.glob(f"{spec.file_prefix}_*.parquet"))
    ]


def _flagged_sql(spec: ServiceSpec, path: Path, window: tuple[date, date]) -> str:
    start, end = window
    return f"""
        SELECT pickup_ts, pu_zone,
          CASE
            WHEN pickup_ts IS NULL OR dropoff_ts IS NULL OR pu_zone IS NULL
                 OR amount IS NULL OR distance IS NULL THEN 'missing_required_value'
            WHEN pickup_ts < TIMESTAMP {quote_literal(start)}
                 OR pickup_ts >= TIMESTAMP {quote_literal(end)} THEN 'pickup_out_of_window'
            WHEN dropoff_ts < pickup_ts THEN 'dropoff_before_pickup'
            WHEN dropoff_ts - pickup_ts > INTERVAL {MAX_TRIP_HOURS} HOUR THEN 'excessive_duration'
            WHEN amount < 0 THEN 'negative_amount'
            WHEN distance < 0 OR distance > {MAX_DISTANCE_MILES} THEN 'invalid_distance'
            WHEN pu_zone NOT IN (SELECT id FROM zones) THEN 'unknown_pickup_zone'
          END AS reject_reason
        FROM (
          SELECT CAST("{spec.pickup}" AS TIMESTAMP) AS pickup_ts,
                 CAST("{spec.dropoff}" AS TIMESTAMP) AS dropoff_ts,
                 CAST("{spec.pu_zone}" AS INTEGER) AS pu_zone,
                 CAST("{spec.distance}" AS DOUBLE) AS distance,
                 CAST("{spec.amount}" AS DOUBLE) AS amount
          FROM read_parquet({quote_literal(path.as_posix())})
        )
    """


def build_service_silver(
    settings: Settings, window: tuple[date, date], valid_zone_ids: set[int], service: str
) -> ServiceSilver:
    """Clean one service's files and write its hourly pickup counts (Parquet)."""
    spec = SERVICE_SPECS[service]
    files = sorted(settings.raw_dir.glob(f"{spec.file_prefix}_*.parquet"))
    if not files:
        raise FileNotFoundError(f"no {spec.file_prefix}_*.parquet files in {settings.raw_dir}")
    out = hourly_path(settings, service)
    out.parent.mkdir(parents=True, exist_ok=True)

    con = duckdb.connect(":memory:")
    try:
        con.execute("CREATE TABLE zones(id INTEGER)")
        con.executemany("INSERT INTO zones VALUES (?)", [(z,) for z in sorted(valid_zone_ids)])
        con.execute("CREATE TABLE hourly(location_id INTEGER, hour_ts TIMESTAMP, pickups BIGINT)")
        rows_in = 0
        rejected: dict[str, int] = {}
        by_file: dict[str, dict[str, int]] = {}
        for f in files:
            inspect_service_trips(f, service)  # actionable error if the schema changed
            rows = con.execute(
                f"""
                SELECT reject_reason,
                       CASE WHEN reject_reason IS NULL THEN pu_zone END,
                       CASE WHEN reject_reason IS NULL THEN date_trunc('hour', pickup_ts) END,
                       count(*)
                FROM ({_flagged_sql(spec, f, window)}) GROUP BY 1, 2, 3
                """
            ).fetchall()
            counts: dict[str, int] = {}
            for reason, zone, hour, n in rows:
                rows_in += n
                if reason is None:
                    con.execute("INSERT INTO hourly VALUES (?, ?, ?)", [zone, hour, n])
                else:
                    counts[reason] = counts.get(reason, 0) + n
            by_file[f.name] = counts
            for reason, n in counts.items():
                rejected[reason] = rejected.get(reason, 0) + n
            log.info(
                "service file cleaned",
                extra={
                    "ctx": {"service": service, "file": f.name, "rejected": sum(counts.values())}
                },
            )
        con.execute(
            f"""
            COPY (
              SELECT {quote_literal(service)} AS service, location_id, hour_ts,
                     sum(pickups)::BIGINT AS pickups
              FROM hourly GROUP BY 2, 3 ORDER BY 2, 3
            ) TO {quote_literal(out.as_posix())} (FORMAT PARQUET)
            """
        )
        valid = int(con.execute("SELECT coalesce(sum(pickups), 0) FROM hourly").fetchone()[0])  # type: ignore[index]
    finally:
        con.close()
    result = ServiceSilver(
        service, spec.label, [f.name for f in files], rows_in, valid, rejected, by_file, out
    )
    (out.with_suffix(".summary.json")).write_text(
        json.dumps(
            {
                "service": service,
                "files": result.files,
                "rows_in": rows_in,
                "rows_valid": valid,
                "rejected": rejected,
                "rejected_by_file": by_file,
            },
            indent=2,
        )
    )
    return result
