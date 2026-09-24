"""City profiles: New York keeps its original behaviour, Pune gets its own calendar and timezone."""

from __future__ import annotations

from datetime import date

import pytest

from mobilityops.city import CITIES, NYC, PUNE, get_city
from mobilityops.config import ConfigError, Settings
from mobilityops.transform.calendar import build_dim_date, build_dim_hour


def test_nyc_holidays_match_the_original_us_federal_calendar() -> None:
    days = NYC.holidays(date(2024, 1, 1), date(2024, 12, 31))
    assert days[date(2024, 7, 4)] == "Independence Day"
    assert days[date(2024, 11, 28)] == "Thanksgiving Day"
    assert len(days) == 11


def test_pune_uses_the_maharashtra_calendar() -> None:
    days = PUNE.holidays(date(2026, 1, 1), date(2026, 12, 31))
    assert days[date(2026, 9, 14)] == "Ganesh Chaturthi"
    assert date(2026, 1, 26) in days  # Republic Day
    assert date(2026, 7, 4) not in days  # a US holiday, not an Indian one


def test_holidays_respect_the_requested_window() -> None:
    days = PUNE.holidays(date(2026, 9, 1), date(2026, 9, 30))
    assert days and all(date(2026, 9, 1) <= d <= date(2026, 9, 30) for d in days)


def test_dim_date_flags_the_city_holidays() -> None:
    dim = build_dim_date(date(2026, 9, 1), date(2026, 10, 1), PUNE).set_index("date")
    assert bool(dim.loc["2026-09-14", "is_holiday"])
    nyc = build_dim_date(date(2024, 7, 1), date(2024, 8, 1), NYC).set_index("date")
    assert bool(nyc["is_holiday"].sum() == 1)


def test_pune_has_no_daylight_saving_and_nyc_does() -> None:
    pune = build_dim_hour(date(2026, 3, 1), date(2026, 4, 1), PUNE)
    nyc = build_dim_hour(date(2024, 3, 1), date(2024, 4, 1), NYC)
    assert len(pune) == 31 * 24 and pune["is_valid"].all()
    assert int((~nyc["is_valid"]).sum()) == 1  # the hour skipped on 10 March 2024


def test_unknown_city_is_rejected() -> None:
    with pytest.raises(ValueError, match="unknown city"):
        get_city("atlantis")
    assert set(CITIES) == {"nyc", "pune"}


def test_mode_selects_the_city_and_label() -> None:
    pune = Settings.from_env({"MOBILITYOPS_MODE": "pune"})
    assert pune.city is PUNE and pune.synthetic
    assert "SIMULATED" in pune.data_label
    real = Settings.from_env({"MOBILITYOPS_MODE": "real"})
    assert real.city is NYC and not real.synthetic and real.data_label == "real data"
    sample = Settings.from_env({"MOBILITYOPS_MODE": "sample"})
    assert sample.synthetic and "SYNTHETIC" in sample.data_label
    with pytest.raises(ConfigError):
        Settings.from_env({"MOBILITYOPS_MODE": "mars"})
