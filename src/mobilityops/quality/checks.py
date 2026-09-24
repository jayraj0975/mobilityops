"""Data-quality checks with PASS / WARN / FAIL states and a hard gate.

* PASS: as expected.
* WARN: worth a human look but does not make downstream results invalid.
* FAIL: downstream results would be wrong or misleading. ``QualityReport.raise_if_failed`` turns
  this into a :class:`QualityGateError`, which stops the pipeline, so invalid data never flows
  onward. The previous good database is left untouched.

Every result carries the numbers behind the verdict, and reports are written to disk as JSON so
they can be inspected later (and are served by the API).
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import date
from enum import StrEnum
from pathlib import Path
from typing import Any

import duckdb

from mobilityops.ingestion.download import sha256_file
from mobilityops.ingestion.manifest import Manifest
from mobilityops.sqlutil import quote_literal
from mobilityops.transform.gold import GoldResult
from mobilityops.transform.services import ServiceSilver
from mobilityops.transform.silver import SilverResult

# Thresholds, stated once so they are easy to find, discuss and change.
REJECT_RATE_WARN = 0.02  # more than 2% of raw rows rejected: look at the quarantine file
REJECT_RATE_FAIL = 0.20  # more than 20%: the source is probably broken
DUPLICATE_RATE_WARN = 0.01
DAY_COVERAGE_WARN = 0.95  # share of window days that contain at least one trip
DAY_COVERAGE_FAIL = 0.50
WEATHER_COVERAGE_WARN = 0.95
DROPOFF_UNALLOCATED_WARN = 0.02  # more than 2% of dropoffs cannot be placed in the zone-hour grid


class Status(StrEnum):
    PASS = "PASS"  # noqa: S105  (a status label, not a credential)
    WARN = "WARN"
    FAIL = "FAIL"


_ORDER = {Status.PASS: 0, Status.WARN: 1, Status.FAIL: 2}


@dataclass(frozen=True)
class CheckResult:
    name: str
    status: Status
    message: str
    metrics: dict[str, Any] = field(default_factory=dict)


class QualityGateError(RuntimeError):
    def __init__(self, report: QualityReport) -> None:
        failed = [r for r in report.results if r.status is Status.FAIL]
        detail = "; ".join(f"{r.name}: {r.message}" for r in failed)
        super().__init__(f"quality gate failed at stage '{report.stage}': {detail}")
        self.report = report


@dataclass
class QualityReport:
    stage: str
    results: list[CheckResult] = field(default_factory=list)

    def add(self, name: str, status: Status, message: str, **metrics: Any) -> None:
        self.results.append(CheckResult(name, status, message, metrics))

    @property
    def overall(self) -> Status:
        return max((r.status for r in self.results), key=lambda s: _ORDER[s], default=Status.PASS)

    def to_dict(self) -> dict[str, Any]:
        return {
            "stage": self.stage,
            "overall": self.overall.value,
            "results": [{**asdict(r), "status": r.status.value} for r in self.results],
        }

    def write(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2, default=str))

    def raise_if_failed(self) -> None:
        if self.overall is Status.FAIL:
            raise QualityGateError(self)


def _rate_status(rate: float, warn: float, fail: float | None = None) -> Status:
    if fail is not None and rate > fail:
        return Status.FAIL
    return Status.WARN if rate > warn else Status.PASS


# ------------------------------------------------------------------------------- bronze
def check_bronze(manifest: Manifest, data_dir: Path) -> QualityReport:
    """Raw files still match what the manifest recorded, and are schema-consistent."""
    r = QualityReport("bronze")
    trips = [e for e in manifest.entries.values() if e.source == "tlc_trips"]
    r.add(
        "trip_files_present",
        Status.PASS if trips else Status.FAIL,
        f"{len(trips)} trip file(s) in the manifest" if trips else "no trip files ingested",
        files=len(trips),
    )
    for e in manifest.entries.values():
        p = data_dir / e.path
        if not p.exists():
            r.add(f"file_exists:{e.path}", Status.FAIL, "file listed in the manifest is missing")
        elif sha256_file(p) != e.sha256:
            r.add(
                f"file_unchanged:{e.path}",
                Status.FAIL,
                "file content differs from the manifest (corrupted or edited after ingestion)",
            )
    empty = [e.path for e in trips if not e.rows]
    r.add(
        "trip_files_nonempty",
        Status.FAIL if empty else Status.PASS,
        f"empty files: {empty}" if empty else "all trip files contain rows",
    )
    col_sets = {frozenset(e.columns or {}) for e in trips}
    r.add(
        "schema_consistent_across_files",
        Status.WARN if len(col_sets) > 1 else Status.PASS,
        "trip files have different column sets (publisher schema change?)"
        if len(col_sets) > 1
        else "all trip files share one column set",
        distinct_schemas=len(col_sets),
    )
    if manifest.window is None:
        r.add("window_recorded", Status.FAIL, "manifest has no date window")
    return r


# ------------------------------------------------------------------------------- silver
def check_silver(
    silver: SilverResult, window: tuple[date, date], zone_ids: set[int]
) -> QualityReport:
    r = QualityReport("silver")
    r.add(
        "rows_present",
        Status.PASS if silver.rows_valid > 0 else Status.FAIL,
        f"{silver.rows_valid:,} valid rows",
        rows_valid=silver.rows_valid,
    )
    rate = silver.rows_rejected / silver.rows_in if silver.rows_in else 1.0
    r.add(
        "rejection_rate",
        _rate_status(rate, REJECT_RATE_WARN, REJECT_RATE_FAIL),
        f"{rate:.2%} of raw rows rejected (see quarantine file for every rejected row and reason)",
        rate=rate,
        rejected=silver.rejected,
    )
    dup_rate = silver.duplicates / silver.rows_in if silver.rows_in else 0.0
    r.add(
        "duplicate_rate",
        _rate_status(dup_rate, DUPLICATE_RATE_WARN),
        f"{dup_rate:.3%} exact duplicates removed",
        duplicates=silver.duplicates,
    )

    con = duckdb.connect(":memory:")
    try:
        src = f"read_parquet({quote_literal(silver.trips_path.as_posix())})"
        start, end = window
        row = con.execute(
            f"""
            SELECT
              count(*) FILTER (WHERE pickup_ts IS NULL OR dropoff_ts IS NULL OR pu_zone IS NULL
                               OR fare_amount IS NULL OR total_amount IS NULL),
              count(*) FILTER (WHERE dropoff_ts < pickup_ts),
              count(*) FILTER (WHERE pickup_ts < TIMESTAMP {quote_literal(start)}
                               OR pickup_ts >= TIMESTAMP {quote_literal(end)}),
              count(*) FILTER (WHERE fare_amount < 0 OR total_amount < 0 OR trip_distance < 0),
              count(DISTINCT date_trunc('day', pickup_ts))
            FROM {src}
            """
        ).fetchone()
        assert row is not None
        nulls, misordered, outside, negatives, days_with_trips = (int(x) for x in row)
        zones = {int(z) for (z,) in con.execute(f"SELECT DISTINCT pu_zone FROM {src}").fetchall()}
    finally:
        con.close()

    for name, count, what in (
        ("no_nulls_in_required_columns", nulls, "required column(s) contain nulls"),
        ("timestamps_ordered", misordered, "trips end before they start"),
        ("pickups_within_window", outside, "pickups fall outside the expected window"),
        ("amounts_and_distance_non_negative", negatives, "negative fares or distances"),
    ):
        r.add(
            name,
            Status.FAIL if count else Status.PASS,
            f"{count:,} rows: {what}" if count else "ok",
            count=count,
        )
    unknown = sorted(zones - zone_ids)
    r.add(
        "pickup_zones_valid",
        Status.FAIL if unknown else Status.PASS,
        f"pickup zones not in the zone table: {unknown[:10]}"
        if unknown
        else "all pickup zones valid",
        unknown_zones=unknown[:50],
    )
    n_days = (end - start).days
    coverage = days_with_trips / n_days if n_days else 0.0
    status = (
        Status.FAIL
        if coverage < DAY_COVERAGE_FAIL
        else Status.WARN
        if coverage < DAY_COVERAGE_WARN
        else Status.PASS
    )
    r.add(
        "day_coverage",
        status,
        f"{days_with_trips} of {n_days} window days contain trips ({coverage:.1%})",
        days_with_trips=days_with_trips,
        window_days=n_days,
    )
    return r


# --------------------------------------------------------------------------------- gold
def check_services(services: list[ServiceSilver], window: tuple[date, date]) -> QualityReport:
    """Cleaning and coverage of the aggregated services (green taxis, for-hire vehicles)."""
    r = QualityReport("services")
    n_days = (window[1] - window[0]).days
    for s in services:
        r.add(
            f"{s.service}:rows_present",
            Status.PASS if s.rows_valid else Status.FAIL,
            f"{s.rows_valid:,} valid rows from {len(s.files)} file(s)",
            rows_valid=s.rows_valid,
        )
        rate = s.rows_rejected / s.rows_in if s.rows_in else 1.0
        r.add(
            f"{s.service}:rejection_rate",
            _rate_status(rate, REJECT_RATE_WARN, REJECT_RATE_FAIL),
            f"{rate:.2%} of raw rows rejected; counts per reason and file are in "
            f"silver/service_{s.service}_hourly.summary.json",
            rate=rate,
            rejected=s.rejected,
        )
        days = (
            duckdb.connect(":memory:")
            .execute(
                "SELECT count(DISTINCT date_trunc('day', hour_ts)) "
                f"FROM read_parquet({quote_literal(s.hourly_path.as_posix())})"
            )
            .fetchone()
        )
        covered = int(days[0]) if days else 0
        cov = covered / n_days if n_days else 0.0
        r.add(
            f"{s.service}:day_coverage",
            _rate_status(1 - cov, 1 - DAY_COVERAGE_WARN, 1 - DAY_COVERAGE_FAIL),
            f"{covered} of {n_days} window days contain trips ({cov:.1%})",
            coverage=cov,
        )
    return r


def check_gold(
    db_path: Path,
    gold: GoldResult,
    silver: SilverResult,
    window: tuple[date, date],
    services: list[ServiceSilver] | None = None,
) -> QualityReport:
    r = QualityReport("gold")
    con = duckdb.connect(str(db_path), read_only=True)
    try:

        def scalar(sql: str) -> Any:
            row = con.execute(sql).fetchone()
            assert row is not None
            return row[0]

        expected_rows = gold.n_zones * gold.n_hours
        r.add(
            "grid_complete",
            Status.PASS if gold.fact_rows == expected_rows else Status.FAIL,
            f"{gold.fact_rows:,} rows, expected zones x valid hours = {expected_rows:,}",
            rows=gold.fact_rows,
            expected=expected_rows,
        )
        orphans = scalar(
            "SELECT count(*) FROM fact_zone_hourly_demand f "
            "LEFT JOIN dim_zone z USING (location_id) WHERE z.location_id IS NULL"
        )
        r.add(
            "referential_integrity_zone",
            Status.FAIL if orphans else Status.PASS,
            f"{orphans} fact rows reference an unknown zone"
            if orphans
            else "every fact zone exists in dim_zone",
            orphans=orphans,
        )
        bad = scalar(
            "SELECT count(*) FROM fact_zone_hourly_demand "
            "WHERE pickups < 0 OR dropoffs < 0 OR revenue < 0 OR pickups IS NULL"
        )
        r.add(
            "counts_non_negative",
            Status.FAIL if bad else Status.PASS,
            "ok" if not bad else f"{bad} bad rows",
            bad=bad,
        )

        trips = f"read_parquet({quote_literal(silver.trips_path.as_posix())})"
        expected_pickups = scalar(
            f"""
            SELECT count(*) FROM {trips} s
            JOIN dim_zone z ON z.location_id = s.pu_zone AND z.is_real_zone
            JOIN dim_hour h ON h.hour_ts = date_trunc('hour', s.pickup_ts) AND h.is_valid
            """
        )
        got = scalar("SELECT coalesce(sum(pickups), 0) FROM fact_zone_hourly_demand")
        r.add(
            "pickups_reconcile_with_silver",
            Status.PASS if got == expected_pickups else Status.FAIL,
            f"fact pickups {got:,} vs trips in valid hours {expected_pickups:,}",
            fact=got,
            silver=expected_pickups,
        )
        if services:
            expected_service_rows = (1 + len(services)) * expected_rows
            r.add(
                "service_grid_complete",
                Status.PASS if gold.service_rows == expected_service_rows else Status.FAIL,
                f"{gold.service_rows:,} rows, expected (1 + {len(services)}) services x zones x "
                f"valid hours = {expected_service_rows:,}",
                rows=gold.service_rows,
                expected=expected_service_rows,
            )
            yellow = scalar(
                "SELECT coalesce(sum(pickups), 0) FROM fact_service_zone_hourly "
                "WHERE service = 'yellow'"
            )
            r.add(
                "service_yellow_matches_zone_fact",
                Status.PASS if yellow == got else Status.FAIL,
                f"yellow pickups in the service table {yellow:,} vs zone fact {got:,}",
            )
            for s in services:
                src = f"read_parquet({quote_literal(s.hourly_path.as_posix())})"
                want = scalar(
                    f"""
                    SELECT coalesce(sum(a.pickups), 0) FROM {src} a
                    JOIN dim_zone z ON z.location_id = a.location_id AND z.is_real_zone
                    JOIN dim_hour h ON h.hour_ts = a.hour_ts AND h.is_valid
                    """
                )
                have = scalar(
                    "SELECT coalesce(sum(pickups), 0) FROM fact_service_zone_hourly "
                    f"WHERE service = {quote_literal(s.service)}"
                )
                r.add(
                    f"service_reconcile:{s.service}",
                    Status.PASS if want == have else Status.FAIL,
                    f"fact pickups {have:,} vs cleaned trips in valid hours {want:,}",
                    fact=have,
                    silver=want,
                )
        # Dropoffs: every trip's dropoff is either in the fact table or accounted for as
        # unallocated (unknown zone, or an hour outside the grid). Nothing may vanish silently.
        placed = int(scalar("SELECT coalesce(sum(dropoffs), 0) FROM fact_zone_hourly_demand"))
        unplaced = int(scalar("SELECT coalesce(sum(trips), 0) FROM dq_unallocated_dropoffs"))
        r.add(
            "dropoffs_reconcile_with_silver",
            Status.PASS if placed + unplaced == silver.rows_valid else Status.FAIL,
            f"dropoffs placed {placed:,} + unallocated {unplaced:,} vs silver trips "
            f"{silver.rows_valid:,}",
            placed=placed,
            unallocated=unplaced,
            silver=silver.rows_valid,
        )
        share = unplaced / silver.rows_valid if silver.rows_valid else 0.0
        by_reason = {
            str(k): int(v)
            for k, v in con.execute(
                "SELECT reason, sum(trips) FROM dq_unallocated_dropoffs GROUP BY 1"
            ).fetchall()
        }
        r.add(
            "dropoffs_unallocated_share",
            _rate_status(share, DROPOFF_UNALLOCATED_WARN),
            f"{share:.2%} of dropoffs cannot be placed in the zone-hour grid "
            f"({by_reason or 'none'}); the trips' pickups are unaffected",
            share=share,
            by_reason=by_reason,
        )
        n_dates = (window[1] - window[0]).days
        weather_days = scalar("SELECT count(*) FROM fact_weather_daily WHERE prcp_mm IS NOT NULL")
        cov = weather_days / n_dates if n_dates else 0.0
        r.add(
            "weather_coverage",
            Status.PASS if cov >= WEATHER_COVERAGE_WARN else Status.WARN,
            f"weather for {weather_days} of {n_dates} days ({cov:.1%}); "
            "missing days simply have no weather context",
            coverage=cov,
        )
        dst_gaps = scalar("SELECT count(*) FROM dim_hour WHERE is_dst_gap")
        r.add(
            "dst_gap_hours_excluded",
            Status.PASS,
            f"{dst_gaps} nonexistent local hour(s) excluded from the grid",
            dst_gap_hours=dst_gaps,
        )
    finally:
        con.close()
    return r
