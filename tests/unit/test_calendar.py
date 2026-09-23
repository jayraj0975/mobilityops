"""Daylight saving and holidays: a clock change must not look like a demand collapse."""

from datetime import date

import pandas as pd

from mobilityops.transform.calendar import build_dim_date, build_dim_hour


def test_spring_forward_removes_the_nonexistent_hour() -> None:
    h = build_dim_hour(date(2024, 3, 9), date(2024, 3, 12)).set_index("hour_ts")
    gap = h[h["is_dst_gap"]]
    assert list(gap.index) == [pd.Timestamp("2024-03-10 02:00")]  # 02:00-02:59 does not exist
    assert not h.loc["2024-03-10 02:00", "is_valid"]
    assert h["is_valid"].sum() == 3 * 24 - 1  # a 23-hour day


def test_fall_back_flags_the_duplicated_hour_and_keeps_it_out_of_modelling() -> None:
    h = build_dim_hour(date(2024, 11, 2), date(2024, 11, 5)).set_index("hour_ts")
    overlap = h[h["is_dst_overlap"]]
    assert list(overlap.index) == [pd.Timestamp("2024-11-03 01:00")]
    assert h.loc["2024-11-03 01:00", "is_valid"]  # it exists (twice), so it stays in the grid...
    assert not h.loc["2024-11-03 01:00", "is_modelable"]  # ...but is not trusted for modelling


def test_ordinary_days_have_no_dst_flags() -> None:
    h = build_dim_hour(date(2024, 1, 1), date(2024, 2, 1))
    assert len(h) == 31 * 24 and not h["is_dst_gap"].any() and not h["is_dst_overlap"].any()
    assert h["is_modelable"].all()


def test_us_federal_holidays_are_flagged_with_names() -> None:
    d = build_dim_date(date(2024, 1, 1), date(2024, 2, 1)).set_index("date")
    assert (
        d.loc["2024-01-01", "is_holiday"]
        and d.loc["2024-01-01", "holiday_name"] == "New Year's Day"
    )
    assert d.loc["2024-01-15", "is_holiday"]  # Martin Luther King Jr. Day
    assert d["is_holiday"].sum() == 2
    assert not d.loc["2024-01-02", "is_holiday"] and pd.isna(d.loc["2024-01-02", "holiday_name"])


def test_weekend_and_weekday_flags() -> None:
    d = build_dim_date(date(2024, 1, 1), date(2024, 1, 8)).set_index("date")
    assert d.loc["2024-01-01", "day_name"] == "Monday" and d.loc["2024-01-01", "day_of_week"] == 0
    assert list(d.index[d["is_weekend"]]) == [
        pd.Timestamp("2024-01-06"),
        pd.Timestamp("2024-01-07"),
    ]


def test_hour_table_inherits_holiday_flag_from_its_date() -> None:
    h = build_dim_hour(date(2024, 1, 1), date(2024, 1, 3))
    assert h.loc[h["date"] == "2024-01-01", "is_holiday"].all()
    assert not h.loc[h["date"] == "2024-01-02", "is_holiday"].any()
