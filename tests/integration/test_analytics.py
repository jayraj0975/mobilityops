"""Every analytic is checked against an independent pandas computation on the same raw data."""

from datetime import date, datetime

import pandas as pd
import pytest

from mobilityops.analytics.queries import Analytics, InvalidQuery, NoData

D0, D1 = date(2024, 1, 1), date(2024, 2, 26)  # the 56-day sample window


@pytest.fixture(scope="module")
def an(built_sample) -> Analytics:  # type: ignore[no-untyped-def]
    return Analytics(built_sample[0].db_path)


@pytest.fixture(scope="module")
def raw(built_sample) -> pd.DataFrame:  # type: ignore[no-untyped-def]
    """Independent ground: the cleaned trips, aggregated in pandas rather than SQL."""
    t = pd.read_parquet(built_sample[1].silver.trips_path)
    t["hour"] = t["pickup_ts"].dt.floor("h")
    return t


def test_data_range_and_metadata(an: Analytics) -> None:
    r = an.data_range()
    assert r.start == datetime(2024, 1, 1) and r.end == datetime(2024, 2, 26)
    assert r.n_zones == 12 and r.synthetic and r.mode == "sample"


def test_zone_list(an: Analytics) -> None:
    z = an.zones()
    assert list(z["location_id"]) == list(range(1, 13))
    assert an.zone_name(1) == "Sample Zone 01"


def test_hourly_series_matches_pandas(an: Analytics, raw: pd.DataFrame) -> None:
    got = an.demand_series(D0, date(2024, 1, 8), zone_id=2)
    z = raw[raw["pu_zone"] == 2]
    hours = pd.date_range("2024-01-01", periods=7 * 24, freq="h")
    want = z.groupby("hour").size().reindex(hours, fill_value=0)
    assert list(got["ts"]) == list(hours)  # every hour present, in order
    assert list(got["value"].astype("int64")) == list(want.astype("int64"))


def test_daily_citywide_series_sums_all_zones(an: Analytics, raw: pd.DataFrame) -> None:
    got = an.demand_series(D0, D1, grain="day").set_index("ts")["value"]
    want = raw.groupby(raw["pickup_ts"].dt.floor("D")).size()
    assert got.sum() == len(raw)
    pd.testing.assert_series_equal(
        got.astype("int64"), want.astype("int64"), check_names=False, check_freq=False
    )


def test_other_metrics(an: Analytics, raw: pd.DataFrame) -> None:
    rev = an.demand_series(D0, D1, grain="day", metric="revenue")["value"].sum()
    assert rev == pytest.approx(raw["total_amount"].sum())
    assert an.demand_series(D0, D1, grain="day", metric="dropoffs")["value"].sum() > 0


def test_top_zones_ranking_and_shares(an: Analytics, raw: pd.DataFrame) -> None:
    top = an.top_zones(D0, D1, limit=12)
    counts = raw.groupby("pu_zone").size().sort_values(ascending=False)
    assert list(top["location_id"]) == list(counts.index)  # zone 1 is busiest by construction
    assert top["share"].sum() == pytest.approx(1.0)
    assert list(an.top_zones(D0, D1, limit=3, ascending=True)["location_id"]) == [12, 11, 10]


def test_hourly_profile_shows_the_planted_shapes(an: Analytics) -> None:
    residential = an.hourly_profile(D0, D1, zone_id=1).set_index("hour_of_day")["avg_pickups"]
    business = an.hourly_profile(D0, D1, zone_id=2).set_index("hour_of_day")["avg_pickups"]
    assert residential.idxmax() in (7, 8)  # morning peak
    assert business.idxmax() in (17, 18)  # evening peak
    assert len(residential) == 24


def test_weekday_profile_reflects_day_of_week_factors(an: Analytics) -> None:
    p = an.weekday_profile(D0, D1).set_index("day_of_week")["avg_daily_pickups"]
    assert p.idxmax() == 4 and p.idxmin() == 6  # Friday busiest, Sunday quietest (planted)


def test_compare_periods_matches_manual_arithmetic(an: Analytics, raw: pd.DataFrame) -> None:
    c = an.compare_periods(date(2024, 1, 1), date(2024, 1, 8), date(2024, 1, 8), date(2024, 1, 15))
    a = ((raw["pickup_ts"] >= "2024-01-01") & (raw["pickup_ts"] < "2024-01-08")).sum()
    b = ((raw["pickup_ts"] >= "2024-01-08") & (raw["pickup_ts"] < "2024-01-15")).sum()
    assert c["period_a"]["total"] == a and c["period_b"]["total"] == b
    assert c["per_day_change_pct"] == pytest.approx((b - a) / a)
    assert c["equal_length"]


def test_compare_periods_flags_unequal_lengths_and_uses_per_day(an: Analytics) -> None:
    c = an.compare_periods(date(2024, 1, 1), date(2024, 1, 8), date(2024, 1, 8), date(2024, 1, 11))
    assert not c["equal_length"]
    assert c["period_b"]["per_day"] == pytest.approx(c["period_b"]["total"] / 3)


def test_growth_uses_two_adjacent_windows(an: Analytics) -> None:
    g = an.growth(date(2024, 2, 5), window_days=7)
    direct = an.compare_periods(
        date(2024, 1, 22), date(2024, 1, 29), date(2024, 1, 29), date(2024, 2, 5)
    )
    assert g["per_day_change"] == pytest.approx(direct["per_day_change"])


def test_volatility_is_positive_and_consistent(an: Analytics) -> None:
    v = an.volatility(D0, D1, zone_id=1)
    daily = an.demand_series(D0, D1, 1, grain="day")["value"].astype(float)
    assert v["days"] == 56 and v["mean_daily"] == pytest.approx(daily.mean())
    assert v["coefficient_of_variation"] == pytest.approx(daily.std(ddof=1) / daily.mean())


def test_concentration(an: Analytics) -> None:
    c = an.concentration(D0, D1, top_n=3)
    top3 = an.top_zones(D0, D1, limit=3)["share"].sum()
    assert c["top_n_share"] == pytest.approx(top3)
    assert (
        1 / 12 < c["herfindahl_index"] < 1
    )  # more concentrated than uniform, less than a monopoly
    assert c["share_covered_by_top_100"] == pytest.approx(1.0)
    assert c["zones_counted"] == 12


def test_rain_is_associated_with_lower_demand_near_the_planted_effect(an: Analytics) -> None:
    w = an.weather_comparison(D0, D1, "rain")
    assert w["days_with"] > 5 and w["days_without"] > 5
    assert w["weekday_adjusted_ratio"] < 1.0  # rain lowers demand (planted: -12%)
    assert 0.78 < w["weekday_adjusted_ratio"] < 0.98  # near 0.88, allowing sampling noise
    assert "does not show that the weather caused" in w["caveat"]  # never claims causation


def test_snow_has_no_days_in_the_sample_and_says_so(an: Analytics) -> None:
    w = an.weather_comparison(D0, D1, "snow")
    assert w["days_with"] == 0 and w["raw_ratio"] is None


# ------------------------------------------------------------------------- validation
@pytest.mark.parametrize(
    ("kwargs", "fragment"),
    [
        ({"start": D1, "end": D0}, "must be after"),
        ({"start": date(2030, 1, 1), "end": date(2030, 1, 5)}, "outside the data"),
        ({"start": D0, "end": D1, "zone_id": 999}, "unknown zone"),
        ({"start": D0, "end": D1, "zone_id": "3"}, "must be an integer"),
        ({"start": D0, "end": D1, "grain": "week"}, "grain"),
        ({"start": D0, "end": D1, "metric": "profit"}, "metric"),
    ],
)
def test_bad_requests_raise_actionable_errors(an: Analytics, kwargs: dict, fragment: str) -> None:  # type: ignore[type-arg]
    with pytest.raises(InvalidQuery, match=fragment):
        an.demand_series(**kwargs)


def test_sql_injection_attempts_are_inert(an: Analytics) -> None:
    for evil in ("1; DROP TABLE dim_zone", "1 OR 1=1", "3'--"):
        with pytest.raises(InvalidQuery):
            an.demand_series(D0, D1, zone_id=evil)  # type: ignore[arg-type]
    with pytest.raises(InvalidQuery):
        an.demand_series(D0, D1, metric="pickups; DROP TABLE dim_zone")  # type: ignore[arg-type]
    assert len(an.zones()) == 12  # nothing was touched


def test_result_size_is_bounded(an: Analytics) -> None:
    with pytest.raises(InvalidQuery, match="limit"):
        an.demand_series(datetime(2024, 1, 1), datetime(2027, 1, 1), grain="hour")
    with pytest.raises(InvalidQuery, match="limit"):
        an.top_zones(D0, D1, limit=10_000)


def test_partial_overlap_with_the_data_is_allowed(an: Analytics) -> None:
    s = an.demand_series(date(2023, 12, 25), date(2024, 1, 3), grain="day")
    assert s["ts"].min() == pd.Timestamp("2024-01-01")  # the part inside the data is returned


def test_analytics_cannot_write(built_sample) -> None:  # type: ignore[no-untyped-def]
    import duckdb

    with pytest.raises(duckdb.Error):
        Analytics(built_sample[0].db_path)._df("DELETE FROM dim_zone")


def test_missing_database_says_what_to_do(tmp_path) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(FileNotFoundError, match="build"):
        Analytics(tmp_path / "nope.duckdb")


def test_dst_spring_forward_end_to_end(sample_files, tmp_path) -> None:  # type: ignore[no-untyped-def]
    """Across the clock change the grid has no 02:00 hour on Mar 10, and queries say so."""
    from mobilityops.ingestion.pipeline import ingest_sample
    from mobilityops.pipeline import build_all
    from mobilityops.sample import SampleSpec, generate_sample
    from tests.conftest import make_env

    files = generate_sample(tmp_path / "dst", SampleSpec(start="2024-03-09", n_days=3))
    s = make_env(tmp_path / "env", files)
    ingest_sample(s)
    res = build_all(s)
    an = Analytics(res.db_path)

    day = an.demand_series(date(2024, 3, 10), date(2024, 3, 11), zone_id=1, grain="hour")
    assert len(day) == 23  # a 23-hour day
    assert pd.Timestamp("2024-03-10 02:00") not in set(day["ts"])
    with pytest.raises(NoData):
        an.demand_series(datetime(2024, 3, 10, 2), datetime(2024, 3, 10, 3), zone_id=1)
    gap_check = next(r for r in res.reports["gold"].results if r.name == "dst_gap_hours_excluded")
    assert gap_check.metrics["dst_gap_hours"] == 1
    # the missing hour is absent, not zero: the grid is complete for the hours that exist
    assert res.gold.fact_rows == 12 * (3 * 24 - 1)


# ------------------------------------------------------------------ regression: concentration
def _many_zone_db(path, n_zones: int) -> None:  # type: ignore[no-untyped-def]
    """A minimal gold database with ``n_zones`` zones of exactly equal demand."""
    import duckdb

    con = duckdb.connect(str(path))
    con.execute(
        "CREATE TABLE dim_zone AS SELECT i AS location_id, 'Zone ' || i AS zone, 'B' AS borough, "
        "'x' AS service_zone, 0.0 AS centroid_lon, 0.0 AS centroid_lat, true AS is_real_zone "
        f"FROM range(1, {n_zones + 1}) t(i)"
    )
    con.execute(
        "CREATE TABLE fact_zone_hourly_demand AS SELECT z.location_id, "
        "TIMESTAMP '2024-01-01' + INTERVAL (h) HOUR AS hour_ts, 10::INTEGER AS pickups, "
        "10::INTEGER AS dropoffs, 1.0 AS revenue, 1.0 AS passengers "
        "FROM dim_zone z CROSS JOIN range(0, 48) t(h)"
    )
    con.execute(
        "CREATE TABLE pipeline_run AS SELECT 'r' AS run_id, 'sample' AS mode, "
        "'2024-01-01T00:00:00+00:00' AS built_at_utc, 100 AS rows_valid, true AS synthetic"
    )
    con.close()


def test_concentration_covers_every_zone_not_just_the_top_hundred(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """The index used to be computed from the top 100 zones only, so with more zones it was
    understated: 150 equal zones must give exactly 1/150, not 100 * (1/150)**2."""
    db = tmp_path / "many.duckdb"
    _many_zone_db(db, 150)
    c = Analytics(db).concentration(date(2024, 1, 1), date(2024, 1, 3), top_n=10)
    assert c["zones_counted"] == 150
    assert c["herfindahl_index"] == pytest.approx(1 / 150)
    assert c["top_n_share"] == pytest.approx(10 / 150)
    assert c["share_covered_by_top_100"] == pytest.approx(100 / 150)  # honest: not the whole city


def test_concentration_rejects_an_impossible_top_n(an: Analytics) -> None:
    from mobilityops.analytics.queries import InvalidQuery

    for bad in (0, 101):
        with pytest.raises(InvalidQuery):
            an.concentration(D0, D1, top_n=bad)
