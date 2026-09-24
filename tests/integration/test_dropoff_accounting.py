"""Dropoffs must never vanish silently: placed + unallocated dropoffs always equal the trips."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import duckdb
import pandas as pd
import pytest

from mobilityops.config import Settings
from mobilityops.quality.checks import Status, check_gold
from mobilityops.sample import SampleFiles
from mobilityops.transform.gold import build_gold
from mobilityops.transform.silver import SilverResult
from tests.conftest import make_env

WINDOW = (date(2024, 1, 1), date(2024, 1, 4))  # three days; the sample's zones are 1..12
T = pd.Timestamp


def trips_frame() -> pd.DataFrame:
    """Ten valid trips: 6 dropoffs fine, 2 to unknown zones, 1 missing, 1 after the window ends."""
    rows = [
        # (pickup, dropoff, pu_zone, do_zone)
        ("2024-01-01 08:10", "2024-01-01 08:30", 3, 4),
        ("2024-01-01 08:20", "2024-01-01 08:50", 3, 4),
        ("2024-01-01 09:05", "2024-01-01 09:20", 4, 3),
        ("2024-01-01 10:05", "2024-01-01 10:20", 5, 6),
        ("2024-01-02 11:05", "2024-01-02 11:40", 6, 5),
        ("2024-01-02 12:05", "2024-01-02 12:15", 7, 7),
        ("2024-01-02 13:05", "2024-01-02 13:25", 3, 265),  # TLC's "unknown" zone
        ("2024-01-02 14:05", "2024-01-02 14:25", 3, 264),  # the other unknown id
        ("2024-01-02 15:05", "2024-01-02 15:25", 3, None),  # missing dropoff zone
        ("2024-01-03 23:50", "2024-01-04 00:20", 3, 4),  # dropped off after the window ends
    ]
    return pd.DataFrame(
        {
            "pickup_ts": [T(r[0]) for r in rows],
            "dropoff_ts": [T(r[1]) for r in rows],
            "pu_zone": [r[2] for r in rows],
            "do_zone": pd.array([r[3] for r in rows], dtype="Int64"),
            "passenger_count": 1.0,
            "trip_distance": 1.0,
            "fare_amount": 8.0,
            "total_amount": 10.0,
            "payment_type": 1,
            "source_file": "hand-made",
        }
    )


@pytest.fixture()
def built(sample_files: SampleFiles, tmp_path: Path) -> tuple[Settings, SilverResult, object]:
    s: Settings = make_env(tmp_path, sample_files)
    trips = trips_frame()
    silver_dir = s.processed_dir / "silver"
    silver_dir.mkdir(parents=True, exist_ok=True)
    path = silver_dir / "trips.parquet"
    trips.to_parquet(path, index=False)
    silver = SilverResult(len(trips), len(trips), {}, path, silver_dir / "rejected.parquet")
    gold = build_gold(s, silver, WINDOW)
    return s, silver, gold


def test_every_dropoff_is_placed_or_accounted_for_by_reason(built) -> None:  # type: ignore[no-untyped-def]
    _, silver, gold = built
    con = duckdb.connect(str(gold.building_path), read_only=True)
    try:
        placed = con.execute("SELECT sum(dropoffs) FROM fact_zone_hourly_demand").fetchone()[0]
        rows = con.execute(
            "SELECT reason, do_zone, trips FROM dq_unallocated_dropoffs ORDER BY reason, do_zone"
        ).fetchall()
    finally:
        con.close()
    assert placed == 6
    assert rows == [
        ("dropoff_outside_grid", None, 1),
        ("unknown_dropoff_zone", 264, 1),
        ("unknown_dropoff_zone", 265, 1),
        ("unknown_dropoff_zone", None, 1),
    ]
    assert placed + sum(r[2] for r in rows) == silver.rows_valid  # nothing vanishes


def test_the_quality_gate_reconciles_dropoffs_and_reports_the_share(built) -> None:  # type: ignore[no-untyped-def]
    _, silver, gold = built
    report = check_gold(gold.building_path, gold, silver, WINDOW)
    by_name = {r.name: r for r in report.results}
    rec = by_name["dropoffs_reconcile_with_silver"]
    assert rec.status is Status.PASS and rec.metrics["unallocated"] == 4
    share = by_name["dropoffs_unallocated_share"]
    assert share.status is Status.WARN  # 4 of 10 trips is far above the 2% threshold
    assert share.metrics["by_reason"] == {"unknown_dropoff_zone": 3, "dropoff_outside_grid": 1}


def test_the_gate_fails_if_dropoffs_go_missing(built) -> None:  # type: ignore[no-untyped-def]
    """Simulate the original defect: an unallocated row is dropped from the accounting table."""
    _, silver, gold = built
    con = duckdb.connect(str(gold.building_path))
    con.execute("DELETE FROM dq_unallocated_dropoffs WHERE do_zone = 265")
    con.close()
    report = check_gold(gold.building_path, gold, silver, WINDOW)
    rec = next(r for r in report.results if r.name == "dropoffs_reconcile_with_silver")
    assert rec.status is Status.FAIL and "vs silver trips" in rec.message
