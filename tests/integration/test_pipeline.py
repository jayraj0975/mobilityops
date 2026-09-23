import hashlib
import json
from datetime import date
from pathlib import Path

import duckdb
import pandas as pd
import pytest

from mobilityops.ingestion.pipeline import ingest_sample
from mobilityops.pipeline import build_all
from mobilityops.quality.checks import QualityGateError, Status
from mobilityops.sample import SampleSpec, generate_sample
from tests.conftest import make_env


def q(db: Path, sql: str) -> list[tuple]:  # type: ignore[type-arg]
    con = duckdb.connect(str(db), read_only=True)
    try:
        return con.execute(sql).fetchall()
    finally:
        con.close()


def test_full_pipeline_on_sample_succeeds(built_sample) -> None:  # type: ignore[no-untyped-def]
    settings, res = built_sample
    assert res.db_path == settings.db_path and res.db_path.exists()
    assert {r.overall for r in res.reports.values()} <= {Status.PASS, Status.WARN}
    assert set(res.reports) == {"bronze", "silver", "gold"}


def test_tables_have_the_expected_shape(built_sample) -> None:  # type: ignore[no-untyped-def]
    settings, _ = built_sample
    db = settings.db_path
    assert q(db, "SELECT count(*) FROM dim_zone")[0][0] == 12
    assert q(db, "SELECT count(*) FROM dim_date")[0][0] == 56
    assert q(db, "SELECT count(*) FROM dim_hour")[0][0] == 56 * 24
    assert q(db, "SELECT count(*) FROM fact_zone_hourly_demand")[0][0] == 12 * 56 * 24
    assert q(db, "SELECT count(*) FROM fact_weather_daily")[0][0] == 56
    assert q(db, "SELECT count(*) FROM dim_zone WHERE centroid_lon IS NULL")[0][0] == 0


def test_demand_grid_is_zero_filled_and_unique(built_sample) -> None:  # type: ignore[no-untyped-def]
    db = built_sample[0].db_path
    assert (
        q(
            db,
            "SELECT count(*) FROM (SELECT location_id, hour_ts FROM fact_zone_hourly_demand "
            "GROUP BY 1, 2 HAVING count(*) > 1)",
        )[0][0]
        == 0
    )
    assert (
        q(db, "SELECT count(*) FROM fact_zone_hourly_demand WHERE pickups = 0")[0][0] > 0
    )  # sparse zones/nights


def test_pickups_reconcile_with_the_generators_ground_truth(built_sample) -> None:  # type: ignore[no-untyped-def]
    settings, res = built_sample
    truth = json.loads((settings.raw_dir / "ground_truth.json").read_text())
    total = q(settings.db_path, "SELECT sum(pickups) FROM fact_zone_hourly_demand")[0][0]
    assert (
        total
        == truth["rows_total"] - truth["rows_expected_removed_by_cleaning"]
        == res.silver.rows_valid
    )


def test_planted_surge_is_visible_in_gold(built_sample) -> None:  # type: ignore[no-untyped-def]
    db = built_sample[0].db_path
    rows = q(
        db,
        "SELECT hour_ts, pickups FROM fact_zone_hourly_demand "
        "WHERE location_id = 3 ORDER BY hour_ts",
    )
    s = pd.Series({pd.Timestamp(h): p for h, p in rows})
    start = pd.Timestamp("2024-01-01") + pd.Timedelta(days=40, hours=17)
    surge = s[start : start + pd.Timedelta(hours=3)].mean()
    normal = [
        s[
            start - pd.Timedelta(weeks=w) : start - pd.Timedelta(weeks=w) + pd.Timedelta(hours=3)
        ].mean()
        for w in (1, 2, 3)
    ]
    assert surge > 2 * max(normal)


def test_weather_flags_match_ground_truth(built_sample) -> None:  # type: ignore[no-untyped-def]
    settings = built_sample[0]
    truth = json.loads((settings.raw_dir / "ground_truth.json").read_text())
    n_rain = q(settings.db_path, "SELECT count(*) FROM fact_weather_daily WHERE is_rain")[0][0]
    assert n_rain == len(truth["rainy_dates"])


def test_run_metadata_is_stored_and_marked_synthetic(built_sample) -> None:  # type: ignore[no-untyped-def]
    settings, res = built_sample
    rows = q(
        settings.db_path,
        "SELECT run_id, mode, synthetic, rows_valid, python, duckdb FROM pipeline_run",
    )
    assert (
        len(rows) == 1
        and rows[0][0] == res.run_id
        and rows[0][1] == "sample"
        and rows[0][2] is True
    )
    assert (
        q(settings.db_path, "SELECT count(*) FROM quality_result WHERE status = 'FAIL'")[0][0] == 0
    )


def test_quality_reports_are_written_as_json(built_sample) -> None:  # type: ignore[no-untyped-def]
    settings = built_sample[0]
    for stage in ("bronze", "silver", "gold"):
        rep = json.loads((settings.processed_dir / "quality" / f"{stage}.json").read_text())
        assert rep["stage"] == stage and rep["overall"] in {"PASS", "WARN"} and rep["results"]


def test_no_building_file_left_behind(built_sample) -> None:  # type: ignore[no-untyped-def]
    assert not list(built_sample[0].processed_dir.glob("*.building"))


# -------------------------------------------------------------------- the gate at work
def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def test_file_changed_after_ingestion_is_caught_at_bronze(sample_files, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    s = make_env(tmp_path, sample_files)
    ingest_sample(s)
    with (s.raw_dir / "weather_daily.csv").open("a") as f:
        f.write("X,2030-01-01,0,0,1,1\n")  # tampered after the manifest was written
    with pytest.raises(QualityGateError, match="bronze") as e:
        build_all(s)
    assert "differs from the manifest" in str(e.value)
    assert not s.db_path.exists()


def test_a_failing_build_never_damages_the_existing_good_database(
    sample_files, tmp_path: Path
) -> None:  # type: ignore[no-untyped-def]
    s = make_env(tmp_path, sample_files)
    ingest_sample(s)
    build_all(s)
    before = _sha(s.db_path)
    # replace the raw data with a source where half the rows are corrupt, and re-ingest it
    bad = generate_sample(tmp_path / "bad", SampleSpec(dirty_fraction=0.5))
    for f in bad.directory.iterdir():
        (s.raw_dir / f.name).write_bytes(f.read_bytes())
    ingest_sample(s)
    with pytest.raises(QualityGateError, match="rejection_rate"):
        build_all(s)
    assert _sha(s.db_path) == before  # the old database is byte-for-byte untouched
    assert not list(s.processed_dir.glob("*.building"))


def test_warn_does_not_stop_the_pipeline(sample_files, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    s = make_env(tmp_path, sample_files)
    warned = generate_sample(
        tmp_path / "w", SampleSpec(dirty_fraction=0.05)
    )  # 5%: above WARN, below FAIL
    for f in warned.directory.iterdir():
        (s.raw_dir / f.name).write_bytes(f.read_bytes())
    ingest_sample(s)
    res = build_all(s)
    rej = next(r for r in res.reports["silver"].results if r.name == "rejection_rate")
    assert rej.status is Status.WARN and res.db_path.exists()


def test_missing_weather_is_a_warning_not_a_failure(sample_files, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    s = make_env(tmp_path, sample_files)
    w = pd.read_csv(s.raw_dir / "weather_daily.csv")
    w.iloc[:20].to_csv(s.raw_dir / "weather_daily.csv", index=False)  # only 20 of 56 days
    ingest_sample(s)
    res = build_all(s)
    cov = next(r for r in res.reports["gold"].results if r.name == "weather_coverage")
    assert cov.status is Status.WARN and res.db_path.exists()


def test_rebuild_is_idempotent(sample_files, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    s = make_env(tmp_path, sample_files)
    ingest_sample(s)
    a = build_all(s)
    first = q(a.db_path, "SELECT * FROM fact_zone_hourly_demand ORDER BY 1, 2")
    b = build_all(s)
    assert first == q(b.db_path, "SELECT * FROM fact_zone_hourly_demand ORDER BY 1, 2")
    assert a.run_id != b.run_id  # runs are distinguishable even when results are identical


def test_missing_manifest_says_what_to_do(sample_files, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    s = make_env(tmp_path, sample_files)
    with pytest.raises(FileNotFoundError, match="ingest"):
        build_all(s)


def test_window_dates_round_trip() -> None:
    assert date.fromisoformat("2024-01-01") < date.fromisoformat("2024-02-26")
