"""The pre-registered holiday features (docs/PREREGISTRATION_HOLIDAY.md) on known real dates."""

from __future__ import annotations

import pandas as pd

from mobilityops.forecasting.features import (
    BASE_FEATURES,
    HOLIDAY_FEATURES,
    _calendar_frame,
    feature_columns,
)


def frame(start: str, end: str) -> pd.DataFrame:
    return _calendar_frame(pd.date_range(start, end, freq="D"))


def col(f: pd.DataFrame, name: str) -> list[int]:
    return [int(v) for v in f[name]]


def test_memorial_day_2024_is_a_three_day_block_not_the_friday_before() -> None:
    f = frame("2024-05-24", "2024-05-28")  # Fri Sat Sun Mon(holiday) Tue
    assert col(f, "is_long_weekend") == [0, 1, 1, 1, 0]
    assert col(f, "days_to_holiday") == [-3, -2, -1, 0, 1]


def test_labor_day_2024_block_and_ordinary_weekend() -> None:
    f = frame("2024-08-30", "2024-09-03")  # Fri Sat Sun Mon(holiday) Tue
    assert col(f, "is_long_weekend") == [0, 1, 1, 1, 0]
    ordinary = frame("2024-06-07", "2024-06-10")  # Fri Sat Sun Mon, no holiday nearby
    assert col(ordinary, "is_long_weekend") == [0, 0, 0, 0]
    assert col(ordinary, "days_to_holiday") == [4, 4, 4, 4]


def test_thanksgiving_2024_only_the_thursday_is_off_so_no_long_weekend() -> None:
    f = frame("2024-11-27", "2024-12-02")
    assert col(f, "days_to_holiday") == [-1, 0, 1, 2, 3, 4]
    assert col(f, "is_long_weekend") == [0, 0, 0, 0, 0, 0]  # Fri is a working day; Sat-Sun is 2


def test_distance_uses_the_nearest_holiday_across_the_year_end() -> None:
    f = frame("2024-12-22", "2025-01-03")
    d = dict(zip(f.index.strftime("%m-%d"), col(f, "days_to_holiday"), strict=True))
    assert d["12-25"] == 0 and d["01-01"] == 0
    assert d["12-24"] == -1 and d["12-26"] == 1
    assert d["12-28"] == 3  # Christmas is 3 days back, New Year 4 ahead
    assert d["12-29"] == -3  # Christmas 4 days back, New Year 3 ahead
    assert d["12-22"] == -3


def test_values_do_not_depend_on_how_much_calendar_is_requested() -> None:
    """A run that crosses the start or end of the requested range must not change its flags."""
    whole = frame("2024-05-01", "2024-06-30")
    for start, end in (
        ("2024-05-25", "2024-05-27"),
        ("2024-05-27", "2024-05-27"),
        ("2024-05-24", "2024-05-24"),
    ):
        part = frame(start, end)
        pd.testing.assert_frame_equal(part, whole.loc[start:end], check_freq=False)


def test_existing_calendar_columns_are_unchanged_by_the_wider_window() -> None:
    f = frame("2024-05-27", "2024-05-27")
    assert bool(f["is_holiday"].iloc[0]) and not bool(f["is_day_after_holiday"].iloc[0])
    g = frame("2024-05-28", "2024-05-28")
    assert bool(g["is_day_after_holiday"].iloc[0]) and not bool(g["is_holiday"].iloc[0])


def test_holiday_features_are_opt_in() -> None:
    assert not set(HOLIDAY_FEATURES) & set(feature_columns())
    assert list(feature_columns()) == list(BASE_FEATURES)
    assert set(HOLIDAY_FEATURES) <= set(feature_columns(holiday_features=True))
