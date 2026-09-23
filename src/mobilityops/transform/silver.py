"""Bronze -> silver: canonical, cleaned trips, with every rejected row quarantined.

Cleaning is a fixed, ordered list of rules. A row that fails is *not* deleted: it goes to the
quarantine file together with the first rule it failed, so nothing disappears silently and the
counts per reason are always available. Rules are deliberately conservative and each one is
justified below.

Timestamps: the TLC records pickup/dropoff in New York local time with no timezone. They are kept
as naive local timestamps (see ``gold.dim_hour`` for how DST gaps and overlaps are flagged).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

import duckdb

from mobilityops.config import Settings
from mobilityops.ingestion.adapters import inspect_trips
from mobilityops.log import get_logger
from mobilityops.sqlutil import quote_literal

log = get_logger("transform.silver")

# Ordered: a row is labelled with the FIRST rule it fails.
REJECT_REASONS: tuple[str, ...] = (
    "missing_required_value",  # cannot attribute or time the trip
    "pickup_out_of_window",  # TLC files contain rows dated years outside their month
    "dropoff_before_pickup",  # impossible ordering
    "excessive_duration",  # > MAX_TRIP_HOURS: almost always a meter left running
    "negative_amount",  # refunds/disputes; not a real completed trip for demand purposes
    "invalid_distance",  # negative, or absurdly long for a taxi in NYC
    "unknown_pickup_zone",  # TLC's 'unknown' ids (264/265) or ids not in the zone table
    "duplicate_row",  # exact duplicate of an already-kept row
)

MAX_TRIP_HOURS = 6
MAX_DISTANCE_MILES = 200

SILVER_COLUMNS = (
    "pickup_ts",
    "dropoff_ts",
    "pu_zone",
    "do_zone",
    "passenger_count",
    "trip_distance",
    "fare_amount",
    "total_amount",
    "payment_type",
    "source_file",
)


@dataclass(frozen=True)
class SilverResult:
    rows_in: int
    rows_valid: int
    rejected: dict[str, int]  # reason -> count (only reasons that occurred)
    trips_path: Path
    quarantine_path: Path

    @property
    def rows_rejected(self) -> int:
        return sum(self.rejected.values())

    @property
    def duplicates(self) -> int:
        return self.rejected.get("duplicate_row", 0)


def silver_dir(settings: Settings) -> Path:
    return settings.processed_dir / "silver"


def _select_for_file(path: Path) -> str:
    """A SELECT that renames one file's columns to the canonical schema."""
    info = inspect_trips(path)
    inv = {canon: actual for actual, canon in info.canonical.items()}

    def col(canon: str) -> str:
        return f'"{inv[canon]}"'

    return f"""
        SELECT
            CAST({col("tpep_pickup_datetime")} AS TIMESTAMP) AS pickup_ts,
            CAST({col("tpep_dropoff_datetime")} AS TIMESTAMP) AS dropoff_ts,
            CAST({col("PULocationID")} AS INTEGER) AS pu_zone,
            CAST({col("DOLocationID")} AS INTEGER) AS do_zone,
            CAST({col("passenger_count")} AS DOUBLE) AS passenger_count,
            CAST({col("trip_distance")} AS DOUBLE) AS trip_distance,
            CAST({col("fare_amount")} AS DOUBLE) AS fare_amount,
            CAST({col("total_amount")} AS DOUBLE) AS total_amount,
            CAST({col("payment_type")} AS INTEGER) AS payment_type,
            {quote_literal(path.name)} AS source_file
        FROM read_parquet({quote_literal(path.as_posix())})
    """


def build_silver(
    settings: Settings,
    window: tuple[date, date],
    valid_zone_ids: set[int],
    trip_files: list[Path] | None = None,
) -> SilverResult:
    """Clean the raw trip files. ``window`` is the half-open [start, end) date range expected."""
    files = trip_files or sorted(settings.raw_dir.glob("yellow_tripdata_*.parquet"))
    if not files:
        raise FileNotFoundError(f"no yellow_tripdata_*.parquet files in {settings.raw_dir}")
    out = silver_dir(settings)
    out.mkdir(parents=True, exist_ok=True)
    trips_path = out / "trips.parquet"
    quarantine_path = out / "trips_rejected.parquet"

    con = duckdb.connect(":memory:")
    try:
        con.execute("CREATE TABLE raw AS " + " UNION ALL ".join(_select_for_file(f) for f in files))
        con.execute("CREATE TABLE zones(id INTEGER)")
        con.executemany("INSERT INTO zones VALUES (?)", [(z,) for z in sorted(valid_zone_ids)])
        start, end = window
        con.execute(
            f"""
            CREATE TABLE flagged AS
            SELECT *,
              CASE
                WHEN pickup_ts IS NULL OR dropoff_ts IS NULL OR pu_zone IS NULL
                     OR fare_amount IS NULL OR total_amount IS NULL OR trip_distance IS NULL
                  THEN 'missing_required_value'
                WHEN pickup_ts < TIMESTAMP {quote_literal(start)}
                     OR pickup_ts >= TIMESTAMP {quote_literal(end)}
                  THEN 'pickup_out_of_window'
                WHEN dropoff_ts < pickup_ts THEN 'dropoff_before_pickup'
                WHEN dropoff_ts - pickup_ts > INTERVAL {MAX_TRIP_HOURS} HOUR
                  THEN 'excessive_duration'
                WHEN fare_amount < 0 OR total_amount < 0 THEN 'negative_amount'
                WHEN trip_distance < 0 OR trip_distance > {MAX_DISTANCE_MILES}
                  THEN 'invalid_distance'
                WHEN pu_zone NOT IN (SELECT id FROM zones) THEN 'unknown_pickup_zone'
              END AS reject_reason
            FROM raw
            """
        )
        # Among rows that passed every other rule, keep one copy of exact duplicates.
        con.execute(
            """
            CREATE TABLE final AS
            SELECT * EXCLUDE (rn) REPLACE (
                CASE WHEN reject_reason IS NULL AND rn > 1 THEN 'duplicate_row'
                     ELSE reject_reason END AS reject_reason
            )
            FROM (
                SELECT *,
                  row_number() OVER (
                    PARTITION BY pickup_ts, dropoff_ts, pu_zone, do_zone, passenger_count,
                                 trip_distance, fare_amount, total_amount, payment_type
                    ORDER BY source_file
                  ) AS rn
                FROM flagged
                WHERE reject_reason IS NULL
                UNION ALL
                SELECT *, 1 AS rn FROM flagged WHERE reject_reason IS NOT NULL
            )
            """
        )
        cols = ", ".join(SILVER_COLUMNS)
        order = "pickup_ts, pu_zone, dropoff_ts, do_zone, fare_amount, total_amount"
        con.execute(
            f"COPY (SELECT {cols} FROM final WHERE reject_reason IS NULL ORDER BY {order}) "
            f"TO {quote_literal(trips_path.as_posix())} (FORMAT PARQUET)"
        )
        con.execute(
            f"COPY (SELECT {cols}, reject_reason FROM final WHERE reject_reason IS NOT NULL "
            f"ORDER BY reject_reason, {order}) "
            f"TO {quote_literal(quarantine_path.as_posix())} (FORMAT PARQUET)"
        )
        rows_in = int(con.execute("SELECT count(*) FROM raw").fetchone()[0])  # type: ignore[index]
        rows_valid = int(
            con.execute("SELECT count(*) FROM final WHERE reject_reason IS NULL").fetchone()[0]  # type: ignore[index]
        )
        rejected = {
            str(r): int(n)
            for r, n in con.execute(
                "SELECT reject_reason, count(*) FROM final WHERE reject_reason IS NOT NULL "
                "GROUP BY 1 ORDER BY 1"
            ).fetchall()
        }
    finally:
        con.close()

    result = SilverResult(rows_in, rows_valid, rejected, trips_path, quarantine_path)
    log.info(
        "silver built",
        extra={"ctx": {"rows_in": rows_in, "rows_valid": rows_valid, "rejected": rejected}},
    )
    return result
