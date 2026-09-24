"""Green-taxi and for-hire aggregation, on tiny hand-made files (TEST / SYNTHETIC DATA)."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import duckdb
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from mobilityops.analytics.queries import Analytics, InvalidQuery, NoData
from mobilityops.api.app import create_app
from mobilityops.config import Settings
from mobilityops.ingestion.adapters import SchemaError
from mobilityops.ingestion.pipeline import ingest_sample
from mobilityops.pipeline import BuildResult, build_all
from mobilityops.quality.checks import Status
from mobilityops.sample import SampleFiles
from mobilityops.transform.services import (
    available_services,
    build_service_silver,
    hourly_path,
)
from tests.conftest import make_env

WINDOW = (date(2024, 1, 1), date(2024, 2, 26))
ZONES = set(range(1, 13))
T = pd.Timestamp


def fhvhv_frame() -> pd.DataFrame:
    """Ten rows: four valid (three in one zone-hour) and one row per rejection rule."""
    rows = [
        # valid: zone 3, 2024-01-10 08:xx (x3) and zone 4 09:xx
        ("2024-01-10 08:05", "2024-01-10 08:30", 3, 2.0, 12.0),
        ("2024-01-10 08:40", "2024-01-10 09:00", 3, 3.0, 15.0),
        ("2024-01-10 08:59", "2024-01-10 09:20", 3, 0.0, 9.0),  # zero miles is legal
        ("2024-01-10 09:10", "2024-01-10 09:30", 4, 1.0, 8.0),
        # one row per rule
        (None, "2024-01-10 09:30", 3, 1.0, 8.0),  # missing_required_value
        ("2002-01-01 00:00", "2002-01-01 00:20", 3, 1.0, 8.0),  # pickup_out_of_window
        ("2024-01-10 10:30", "2024-01-10 10:00", 3, 1.0, 8.0),  # dropoff_before_pickup
        ("2024-01-10 10:00", "2024-01-10 17:00", 3, 1.0, 8.0),  # excessive_duration (7 h)
        ("2024-01-10 11:00", "2024-01-10 11:20", 3, 1.0, -4.0),  # negative_amount
        ("2024-01-10 12:00", "2024-01-10 12:20", 3, 999.0, 8.0),  # invalid_distance
        ("2024-01-10 13:00", "2024-01-10 13:20", 265, 1.0, 8.0),  # unknown_pickup_zone
    ]
    return pd.DataFrame(
        {
            "hvfhs_license_num": "HV0003",
            "pickup_datetime": [None if r[0] is None else T(r[0]) for r in rows],
            "dropoff_datetime": [T(r[1]) for r in rows],
            "PULocationID": [r[2] for r in rows],
            "trip_miles": [r[3] for r in rows],
            "base_passenger_fare": [r[4] for r in rows],
        }
    )


def green_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "lpep_pickup_datetime": [T("2024-02-03 22:15"), T("2024-02-03 22:45")],
            "lpep_dropoff_datetime": [T("2024-02-03 22:30"), T("2024-02-03 23:10")],
            "PULocationID": [5, 5],
            "trip_distance": [1.5, 4.0],
            "fare_amount": [9.0, 20.0],
        }
    )


def daily_files(s: Settings) -> None:
    """One valid trip on every day of the window plus one planted defect: passes the gate."""
    days = pd.date_range(WINDOW[0], WINDOW[1], freq="D", inclusive="left")
    pickups = [d + pd.Timedelta(hours=8, minutes=15) for d in days]
    ends = [p + pd.Timedelta(minutes=20) for p in pickups]
    fhv = pd.DataFrame(
        {
            "pickup_datetime": [*pickups, pickups[0]],
            "dropoff_datetime": [*ends, ends[0]],
            "PULocationID": [3] * (len(pickups) + 1),
            "trip_miles": [2.0] * (len(pickups) + 1),
            "base_passenger_fare": [*([10.0] * len(pickups)), -5.0],  # one refund
        }
    )
    fhv.to_parquet(s.raw_dir / "fhvhv_tripdata_2024-01.parquet")
    green = pd.DataFrame(
        {
            "lpep_pickup_datetime": pickups,
            "lpep_dropoff_datetime": [p + pd.Timedelta(minutes=20) for p in pickups],
            "PULocationID": 5,
            "trip_distance": 1.5,
            "fare_amount": 9.0,
        }
    )
    green.to_parquet(s.raw_dir / "green_tripdata_2024-02.parquet")


@pytest.fixture()
def service_settings(tmp_path: Path) -> Settings:
    s = Settings.from_env({"MOBILITYOPS_DATA_DIR": str(tmp_path / "data")})
    s.ensure_dirs()
    fhvhv_frame().to_parquet(s.raw_dir / "fhvhv_tripdata_2024-01.parquet")
    green_frame().to_parquet(s.raw_dir / "green_tripdata_2024-02.parquet")
    return s


def test_every_rule_rejects_exactly_its_planted_row(service_settings: Settings) -> None:
    res = build_service_silver(service_settings, WINDOW, ZONES, "fhvhv")
    assert res.rows_in == 11 and res.rows_valid == 4
    assert res.rejected == {
        "missing_required_value": 1,
        "pickup_out_of_window": 1,
        "dropoff_before_pickup": 1,
        "excessive_duration": 1,
        "negative_amount": 1,
        "invalid_distance": 1,
        "unknown_pickup_zone": 1,
    }
    assert res.rows_valid + res.rows_rejected == res.rows_in
    assert res.rejected_by_file["fhvhv_tripdata_2024-01.parquet"] == res.rejected


def test_hourly_counts_group_by_zone_and_hour(service_settings: Settings) -> None:
    build_service_silver(service_settings, WINDOW, ZONES, "fhvhv")
    got = pd.read_parquet(hourly_path(service_settings, "fhvhv"))
    counts = {(r.location_id, r.hour_ts): r.pickups for r in got.itertuples()}
    assert counts == {(3, T("2024-01-10 08:00")): 3, (4, T("2024-01-10 09:00")): 1}
    assert set(got["service"]) == {"fhvhv"}


def test_green_uses_its_own_column_names(service_settings: Settings) -> None:
    res = build_service_silver(service_settings, WINDOW, ZONES, "green")
    assert res.rows_valid == 2 and res.rejected == {}
    got = pd.read_parquet(res.hourly_path)
    assert [(r.location_id, r.hour_ts, r.pickups) for r in got.itertuples()] == [
        (5, T("2024-02-03 22:00"), 2)
    ]


def test_available_services_lists_only_those_with_files(service_settings: Settings) -> None:
    assert available_services(service_settings) == ["green", "fhvhv"]
    (service_settings.raw_dir / "green_tripdata_2024-02.parquet").unlink()
    assert available_services(service_settings) == ["fhvhv"]


def test_a_renamed_column_fails_with_an_actionable_message(service_settings: Settings) -> None:
    bad = fhvhv_frame().rename(columns={"trip_miles": "miles"})
    bad.to_parquet(service_settings.raw_dir / "fhvhv_tripdata_2024-01.parquet")
    with pytest.raises(SchemaError, match="trip_miles"):
        build_service_silver(service_settings, WINDOW, ZONES, "fhvhv")


@pytest.fixture(scope="module")
def with_services(
    sample_files: SampleFiles, tmp_path_factory: pytest.TempPathFactory
) -> tuple[Settings, BuildResult]:
    s = make_env(tmp_path_factory.mktemp("services"), sample_files)
    daily_files(s)
    ingest_sample(s)
    return s, build_all(s)


def test_pipeline_adds_service_tables_and_leaves_yellow_unchanged(
    built_sample: tuple[Settings, object], with_services: tuple[Settings, BuildResult]
) -> None:
    plain_settings, _ = built_sample
    s, result = with_services

    assert result.reports["services"].overall in (Status.PASS, Status.WARN)
    assert result.reports["gold"].overall is Status.PASS
    names = {r.name for r in result.reports["gold"].results}
    assert {"service_reconcile:green", "service_reconcile:fhvhv"} <= names

    con = duckdb.connect(str(s.db_path), read_only=True)
    try:
        rows = con.execute("SELECT count(*) FROM fact_service_zone_hourly").fetchone()[0]
        per_service = dict(
            con.execute(
                "SELECT service, sum(pickups) FROM fact_service_zone_hourly GROUP BY 1"
            ).fetchall()
        )
        yellow = con.execute(
            "SELECT location_id, hour_ts, pickups FROM fact_zone_hourly_demand ORDER BY 1, 2"
        ).df()
    finally:
        con.close()
    assert rows == 3 * result.gold.n_zones * result.gold.n_hours
    days = (WINDOW[1] - WINDOW[0]).days
    assert per_service["fhvhv"] == days and per_service["green"] == days
    assert result.services[0].rejected == {}
    assert result.services[1].rejected == {"negative_amount": 1}

    base = duckdb.connect(str(plain_settings.db_path), read_only=True)
    try:
        before = base.execute(
            "SELECT location_id, hour_ts, pickups FROM fact_zone_hourly_demand ORDER BY 1, 2"
        ).df()
        no_service_table = base.execute(
            "SELECT count(*) FROM information_schema.tables "
            "WHERE table_name = 'fact_service_zone_hourly'"
        ).fetchone()[0]
    finally:
        base.close()
    pd.testing.assert_frame_equal(yellow, before)  # yellow results are byte-for-byte the same
    assert no_service_table == 0  # and a build without other services has no service table


def test_service_mix_shares_sum_to_one_and_match_the_counts(
    with_services: tuple[Settings, BuildResult],
) -> None:
    s, _ = with_services
    a = Analytics(s.db_path)
    assert a.has_services()
    monthly = a.service_mix(WINDOW[0], WINDOW[1], grain="month")
    assert set(monthly["service"]) == {"yellow", "green", "fhvhv"}
    assert monthly.groupby("period")["share"].sum().round(9).eq(1.0).all()
    total = a.service_mix(WINDOW[0], WINDOW[1], grain="total")
    assert len(total["period"].unique()) == 1
    days = (WINDOW[1] - WINDOW[0]).days
    got = dict(zip(total["service"], total["pickups"], strict=True))
    assert got["fhvhv"] == days and got["green"] == days
    assert total["share"].sum() == pytest.approx(1.0)
    zone3 = a.service_mix(WINDOW[0], WINDOW[1], zone_id=3, grain="total")
    assert dict(zip(zone3["service"], zone3["pickups"], strict=True))["fhvhv"] == days
    assert a.service_mix(WINDOW[0], WINDOW[1], zone_id=5)["service"].nunique() == 3


def test_service_hourly_profile_puts_the_planted_trips_at_eight(
    with_services: tuple[Settings, BuildResult],
) -> None:
    s, _ = with_services
    prof = Analytics(s.db_path).service_hourly_profile(WINDOW[0], WINDOW[1])
    fh = prof[(prof["service"] == "fhvhv") & (prof["avg_pickups"] > 0)]
    assert list(fh["hour_of_day"]) == [8]


def test_service_queries_refuse_politely_without_service_data(
    built_sample: tuple[Settings, object],
) -> None:
    plain, _ = built_sample
    a = Analytics(plain.db_path)
    assert not a.has_services()
    with pytest.raises(NoData, match="yellow-taxi data only"):
        a.service_mix(WINDOW[0], WINDOW[1])
    with pytest.raises(InvalidQuery):
        a.service_mix(WINDOW[0], WINDOW[1], grain="week")  # type: ignore[arg-type]


# --------------------------------------------------------------------------------------- API
def test_api_serves_the_service_mix_and_lists_the_services(
    with_services: tuple[Settings, BuildResult],
) -> None:
    s, _ = with_services
    client = TestClient(create_app(s))
    meta = client.get("/api/v1/meta").json()
    assert {x["service"] for x in meta["services"]} == {"yellow", "green", "fhvhv"}
    r = client.get(
        "/api/v1/demand/services",
        params={"start": "2024-01-01", "end": "2024-02-26", "grain": "total"},
    )
    assert r.status_code == 200
    rows = r.json()
    assert {x["service"] for x in rows} == {"yellow", "green", "fhvhv"}
    assert sum(x["share"] for x in rows) == pytest.approx(1.0)
    prof = client.get(
        "/api/v1/demand/services/profile", params={"start": "2024-01-01", "end": "2024-02-26"}
    )
    assert prof.status_code == 200 and {x["service"] for x in prof.json()} == {
        "yellow",
        "green",
        "fhvhv",
    }
    bad = client.get(
        "/api/v1/demand/services",
        params={"start": "2024-01-01", "end": "2024-02-26", "grain": "week"},
    )
    assert bad.status_code == 422
    stages = {x["stage"] for x in client.get("/api/v1/quality").json()}
    assert "services" in stages


def test_api_without_service_data_answers_no_data_not_an_error_page(
    built_sample: tuple[Settings, object],
) -> None:
    plain, _ = built_sample
    client = TestClient(create_app(plain))
    assert client.get("/api/v1/meta").json()["services"] == []
    r = client.get("/api/v1/demand/services", params={"start": "2024-01-01", "end": "2024-02-26"})
    assert r.status_code == 404
    body = r.json()["error"]
    assert body["code"] == "no_data" and "yellow-taxi data only" in body["message"]
