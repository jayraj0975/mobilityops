import json
from datetime import date
from pathlib import Path

import duckdb
import pandas as pd
import pytest

from mobilityops.config import Settings
from mobilityops.transform.silver import REJECT_REASONS, build_silver

WINDOW = (date(2024, 1, 1), date(2024, 2, 26))
ZONES = set(range(1, 13))
# generator defect kind -> the cleaning rule that must catch it
KIND_TO_REASON = {
    "dropoff_before_pickup": "dropoff_before_pickup",
    "negative_fare": "negative_amount",
    "unknown_pickup_zone": "unknown_pickup_zone",
    "timestamp_out_of_range": "pickup_out_of_window",
}


def test_cleaning_rejects_exactly_the_planted_defects(sample_settings: Settings) -> None:
    res = build_silver(sample_settings, WINDOW, ZONES)
    truth = json.loads((sample_settings.raw_dir / "ground_truth.json").read_text())
    expected = {KIND_TO_REASON[k]: n for k, n in truth["defect_counts"].items()}
    assert res.rejected == expected  # same reasons, same counts: nothing extra, nothing missed
    assert res.rows_in == truth["rows_total"]
    # corruption happens in place, so total rows never change: valid = total - planted defects
    assert res.rows_valid == truth["rows_total"] - truth["rows_expected_removed_by_cleaning"]


def test_row_counts_reconcile(sample_settings: Settings) -> None:
    res = build_silver(sample_settings, WINDOW, ZONES)
    assert res.rows_valid + res.rows_rejected == res.rows_in
    assert len(pd.read_parquet(res.trips_path)) == res.rows_valid
    assert len(pd.read_parquet(res.quarantine_path)) == res.rows_rejected


def test_quarantine_keeps_the_bad_rows_with_their_reason(sample_settings: Settings) -> None:
    res = build_silver(sample_settings, WINDOW, ZONES)
    q = pd.read_parquet(res.quarantine_path)
    assert set(q["reject_reason"]) <= set(REJECT_REASONS)
    neg = q[q["reject_reason"] == "negative_amount"]
    assert (neg["fare_amount"] < 0).all() and len(neg) > 0
    early = q[q["reject_reason"] == "pickup_out_of_window"]
    assert (early["pickup_ts"].dt.year == 2002).all()


def test_silver_is_clean(sample_settings: Settings) -> None:
    res = build_silver(sample_settings, WINDOW, ZONES)
    t = pd.read_parquet(res.trips_path)
    assert t["pickup_ts"].between("2024-01-01", "2024-02-26", inclusive="left").all()
    assert (t["dropoff_ts"] >= t["pickup_ts"]).all()
    assert (t["fare_amount"] >= 0).all() and t["pu_zone"].isin(ZONES).all()
    assert t.isna().sum().sum() == 0
    assert list(t.columns[:3]) == ["pickup_ts", "dropoff_ts", "pu_zone"]


def _one_file_settings(tmp_path: Path, frame: pd.DataFrame) -> Settings:
    s = Settings.from_env(
        {"MOBILITYOPS_DATA_DIR": str(tmp_path / "d"), "MOBILITYOPS_MODE": "sample"}
    )
    s.ensure_dirs()
    frame.to_parquet(s.raw_dir / "yellow_tripdata_x.parquet", index=False)
    return s


def _trip(**over: object) -> dict[str, object]:
    base: dict[str, object] = {
        "tpep_pickup_datetime": pd.Timestamp("2024-01-05 10:00:00"),
        "tpep_dropoff_datetime": pd.Timestamp("2024-01-05 10:20:00"),
        "PULocationID": 3,
        "DOLocationID": 4,
        "passenger_count": 1.0,
        "trip_distance": 2.5,
        "fare_amount": 12.0,
        "total_amount": 15.0,
        "payment_type": 1,
    }
    base.update(over)
    return base


def test_each_rule_fires_on_a_minimal_example(tmp_path: Path) -> None:
    rows = [
        _trip(),  # good
        _trip(tpep_pickup_datetime=pd.NaT),
        _trip(tpep_pickup_datetime=pd.Timestamp("2023-12-31 23:59:59")),
        _trip(tpep_dropoff_datetime=pd.Timestamp("2024-01-05 09:00:00")),
        _trip(tpep_dropoff_datetime=pd.Timestamp("2024-01-05 17:00:01")),  # > 6 h
        _trip(total_amount=-1.0),
        _trip(trip_distance=250.0),
        _trip(PULocationID=265),
        _trip(PULocationID=999),  # not in the zone table
        _trip(fare_amount=None),
    ]
    s = _one_file_settings(tmp_path, pd.DataFrame(rows))
    res = build_silver(s, WINDOW, ZONES)
    assert res.rows_valid == 1
    assert res.rejected == {
        "missing_required_value": 2,
        "pickup_out_of_window": 1,
        "dropoff_before_pickup": 1,
        "excessive_duration": 1,
        "negative_amount": 1,
        "invalid_distance": 1,
        "unknown_pickup_zone": 2,
    }


def test_exact_duplicates_keep_one_copy(tmp_path: Path) -> None:
    s = _one_file_settings(
        tmp_path, pd.DataFrame([_trip(), _trip(), _trip(), _trip(fare_amount=13.0)])
    )
    res = build_silver(s, WINDOW, ZONES)
    assert res.rows_valid == 2 and res.rejected == {"duplicate_row": 2}


def test_boundary_values_are_accepted(tmp_path: Path) -> None:
    rows = [
        _trip(
            tpep_pickup_datetime=pd.Timestamp("2024-01-01 00:00:00"),  # window start is inclusive
            tpep_dropoff_datetime=pd.Timestamp("2024-01-01 00:10:00"),
        ),
        _trip(
            tpep_pickup_datetime=pd.Timestamp("2024-02-25 23:59:59"),
            tpep_dropoff_datetime=pd.Timestamp("2024-02-26 00:10:00"),
        ),
        _trip(tpep_dropoff_datetime=pd.Timestamp("2024-01-05 10:00:00")),  # zero-length trip
        _trip(fare_amount=0.0, total_amount=0.0),
    ]
    res = build_silver(_one_file_settings(tmp_path, pd.DataFrame(rows)), WINDOW, ZONES)
    assert res.rows_valid == 4 and res.rejected == {}


def test_pickup_at_window_end_is_rejected(tmp_path: Path) -> None:
    rows = [
        _trip(
            tpep_pickup_datetime=pd.Timestamp("2024-02-26 00:00:00"),
            tpep_dropoff_datetime=pd.Timestamp("2024-02-26 00:10:00"),
        )
    ]
    res = build_silver(_one_file_settings(tmp_path, pd.DataFrame(rows)), WINDOW, ZONES)
    assert res.rejected == {"pickup_out_of_window": 1}


def test_column_name_variants_and_types_are_handled(tmp_path: Path) -> None:
    df = pd.DataFrame([_trip()]).rename(
        columns={
            "tpep_pickup_datetime": "lpep_pickup_datetime",
            "tpep_dropoff_datetime": "lpep_dropoff_datetime",
            "PULocationID": "pulocationid",
        }
    )
    df["passenger_count"] = df["passenger_count"].astype("int64")
    res = build_silver(_one_file_settings(tmp_path, df), WINDOW, ZONES)
    assert res.rows_valid == 1


def test_no_files_is_a_clear_error(tmp_path: Path) -> None:
    s = Settings.from_env({"MOBILITYOPS_DATA_DIR": str(tmp_path), "MOBILITYOPS_MODE": "sample"})
    s.ensure_dirs()
    with pytest.raises(FileNotFoundError, match="yellow_tripdata"):
        build_silver(s, WINDOW, ZONES)


def test_rebuilding_gives_identical_data(sample_settings: Settings) -> None:
    a = build_silver(sample_settings, WINDOW, ZONES)
    first = pd.read_parquet(a.trips_path)
    b = build_silver(sample_settings, WINDOW, ZONES)
    pd.testing.assert_frame_equal(first, pd.read_parquet(b.trips_path))
    assert a.rejected == b.rejected


def test_duckdb_can_read_the_outputs_directly(sample_settings: Settings) -> None:
    res = build_silver(sample_settings, WINDOW, ZONES)
    n = duckdb.sql(f"SELECT count(*) FROM read_parquet('{res.trips_path.as_posix()}')").fetchone()
    assert n is not None and n[0] == res.rows_valid
