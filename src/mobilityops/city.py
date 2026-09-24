"""City profiles: everything about a place that the pipeline must not assume.

The pipeline was first built on New York data. A city profile carries what differs between places:
the timezone (and so daylight-saving behaviour), the public-holiday calendar, and the study area.
The New York profile reproduces the original behaviour exactly; Pune uses Asia/Kolkata (no daylight
saving) and the Maharashtra holiday calendar.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date

import pandas as pd
from pandas.tseries.holiday import USFederalHolidayCalendar

HolidayLookup = Callable[[date, date], dict[date, str]]


def _us_federal(start: date, end: date) -> dict[date, str]:
    """US federal holidays in [start, end], with the dates the original pipeline used."""
    found = USFederalHolidayCalendar().holidays(
        start=pd.Timestamp(start).to_pydatetime(),
        end=pd.Timestamp(end).to_pydatetime(),
        return_name=True,
    )
    idx = pd.DatetimeIndex(found.index)
    return {ts.date(): str(n) for ts, n in zip(idx, found.to_numpy(), strict=True)}


def _india_maharashtra(start: date, end: date) -> dict[date, str]:
    """Public holidays of India and Maharashtra in [start, end] (the ``holidays`` package).

    Many Indian holidays follow lunar calendars, so their dates cannot be computed with a simple
    rule or safely hard-coded; that is why a maintained package is used.
    """
    import holidays

    calendar = holidays.India(subdiv="MH", years=range(start.year, end.year + 1))
    return {d: str(n) for d, n in calendar.items() if start <= d <= end}


@dataclass(frozen=True)
class City:
    key: str
    name: str
    timezone: str
    bbox: tuple[float, float, float, float]  # (min_lat, min_lon, max_lat, max_lon)
    holiday_lookup: HolidayLookup
    holiday_label: str  # what the holidays are, for documents ("US federal holidays")

    def holidays(self, start: date, end: date) -> dict[date, str]:
        """Holiday name by date, for every holiday in [start, end] inclusive."""
        return self.holiday_lookup(start, end)

    @property
    def timezone_note(self) -> str:
        return f"{self.timezone} (timestamps are naive local time)"


NYC = City(
    key="nyc",
    name="New York City",
    timezone="America/New_York",
    bbox=(40.49, -74.27, 40.92, -73.68),
    holiday_lookup=_us_federal,
    holiday_label="US federal holidays",
)

PUNE = City(
    key="pune",
    name="Pune",
    timezone="Asia/Kolkata",
    bbox=(18.40, 73.70, 18.68, 74.02),
    holiday_lookup=_india_maharashtra,
    holiday_label="public holidays of India and Maharashtra",
)

CITIES: dict[str, City] = {c.key: c for c in (NYC, PUNE)}
DEFAULT_CITY = NYC


def get_city(key: str) -> City:
    try:
        return CITIES[key]
    except KeyError:
        raise ValueError(f"unknown city {key!r}; choose from {sorted(CITIES)}") from None
