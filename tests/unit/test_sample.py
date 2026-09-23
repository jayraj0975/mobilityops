"""The synthetic generator is the foundation of every later test, so it is tested carefully."""

import json

import pandas as pd

from mobilityops.sample import SampleSpec, generate_sample
from mobilityops.schema import TLC_REQUIRED_COLUMNS, WEATHER_COLUMNS, ZONE_LOOKUP_COLUMNS


def test_files_match_the_real_source_schemas(sample_files) -> None:  # type: ignore[no-untyped-def]
    trips = pd.read_parquet(sample_files.trips)
    assert set(TLC_REQUIRED_COLUMNS) <= set(trips.columns)
    assert set(ZONE_LOOKUP_COLUMNS) <= set(pd.read_csv(sample_files.zone_lookup).columns)
    assert set(WEATHER_COLUMNS) <= set(pd.read_csv(sample_files.weather).columns)


def test_generation_is_deterministic(tmp_path) -> None:  # type: ignore[no-untyped-def]
    a = generate_sample(tmp_path / "a", SampleSpec(n_days=14))
    b = generate_sample(tmp_path / "b", SampleSpec(n_days=14))
    pd.testing.assert_frame_equal(pd.read_parquet(a.trips), pd.read_parquet(b.trips))
    assert a.weather.read_text() == b.weather.read_text()


def test_different_seeds_differ(tmp_path) -> None:  # type: ignore[no-untyped-def]
    a = generate_sample(tmp_path / "a", SampleSpec(seed=1, n_days=7))
    b = generate_sample(tmp_path / "b", SampleSpec(seed=2, n_days=7))
    assert len(pd.read_parquet(a.trips)) != len(pd.read_parquet(b.trips))


def test_ground_truth_is_labelled_synthetic_and_counts_defects(sample_files) -> None:  # type: ignore[no-untyped-def]
    truth = json.loads(sample_files.ground_truth.read_text())
    assert truth["label"] == "TEST / SYNTHETIC DATA"
    trips = pd.read_parquet(sample_files.trips)
    assert truth["rows_total"] == len(trips)
    assert truth["rows_expected_removed_by_cleaning"] == sum(truth["defect_counts"].values()) > 0


def test_planted_defects_are_really_in_the_data(sample_files) -> None:  # type: ignore[no-untyped-def]
    truth = json.loads(sample_files.ground_truth.read_text())["defect_counts"]
    t = pd.read_parquet(sample_files.trips)
    assert (t["tpep_pickup_datetime"].dt.year == 2002).sum() == truth["timestamp_out_of_range"]
    assert (t["fare_amount"] < 0).sum() == truth["negative_fare"]
    assert (t["PULocationID"] == 265).sum() == truth["unknown_pickup_zone"]


def test_planted_anomalies_show_in_the_underlying_counts(sample_files) -> None:  # type: ignore[no-untyped-def]
    """A 3x surge in zone 3 must be visible in raw hourly counts, or detection tests are moot."""
    t = pd.read_parquet(sample_files.trips)
    t = t[t["tpep_pickup_datetime"].dt.year == 2024]
    hourly = t[t["PULocationID"] == 3].groupby(t["tpep_pickup_datetime"].dt.floor("h")).size()
    start = pd.Timestamp("2024-01-01") + pd.Timedelta(days=40, hours=17)
    surge = hourly.reindex(pd.date_range(start, periods=4, freq="h"), fill_value=0).mean()
    same_hours_prev_weeks = [
        hourly.reindex(
            pd.date_range(start - pd.Timedelta(weeks=w), periods=4, freq="h"), fill_value=0
        ).mean()
        for w in (1, 2, 3)
    ]
    assert surge > 2 * max(same_hours_prev_weeks)


def test_rain_lowers_demand_as_specified(sample_files) -> None:  # type: ignore[no-untyped-def]
    t = pd.read_parquet(sample_files.trips)
    t = t[t["tpep_pickup_datetime"].dt.year == 2024]
    daily = t.groupby(t["tpep_pickup_datetime"].dt.strftime("%Y-%m-%d")).size()
    rainy = set(json.loads(sample_files.ground_truth.read_text())["rainy_dates"])
    is_rain = daily.index.isin(rainy)
    # the weekday mix is only approximately equal, so require just a clear, correct-sign gap
    assert daily[is_rain].mean() < daily[~is_rain].mean()


def test_sample_is_small_enough_for_ci(sample_files) -> None:  # type: ignore[no-untyped-def]
    assert sample_files.trips.stat().st_size < 15 * 1024 * 1024
