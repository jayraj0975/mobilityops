"""Calendar dimensions, including daylight-saving handling.

TLC timestamps are New York local time with no timezone. Two hours a year are therefore unsafe to
treat as ordinary hours:

* spring forward: the local hour 02:00-02:59 does not exist, so a zero count there is *not* a
  demand collapse. Such hours are ``is_dst_gap`` and excluded from the hourly grid.
* fall back: the local hour 01:00-01:59 happens twice, so a naive local-hour count merges two
  real hours. Such hours are ``is_dst_overlap``; they stay in the grid but are flagged and are
  not used for modelling (``is_modelable`` is false).
"""

from __future__ import annotations

from datetime import UTC, date
from zoneinfo import ZoneInfo

import pandas as pd

from mobilityops.city import DEFAULT_CITY, City


def build_dim_date(start: date, end: date, city: City = DEFAULT_CITY) -> pd.DataFrame:
    """One row per calendar date in [start, end), with the city's public holidays."""
    dates = pd.date_range(start, end, freq="D", inclusive="left")
    names = city.holidays(start, end)
    return pd.DataFrame(
        {
            "date": dates,
            "day_of_week": dates.dayofweek,  # Monday = 0
            "day_name": dates.day_name(),
            "is_weekend": dates.dayofweek >= 5,
            "is_holiday": [d.date() in names for d in dates],
            "holiday_name": [names.get(d.date()) for d in dates],
        }
    )


def build_dim_hour(start: date, end: date, city: City = DEFAULT_CITY) -> pd.DataFrame:
    """One row per local hour in [start, end), with daylight-saving flags (none without DST)."""
    tz = ZoneInfo(city.timezone)
    hours = pd.date_range(start, end, freq="h", inclusive="left")
    gap: list[bool] = []
    overlap: list[bool] = []
    for ts in hours.to_pydatetime():
        local = ts.replace(tzinfo=tz)
        round_trip = local.astimezone(UTC).astimezone(tz).replace(tzinfo=None)
        exists = round_trip == ts
        gap.append(not exists)
        overlap.append(
            exists
            and ts.replace(tzinfo=tz, fold=0).utcoffset()
            != ts.replace(tzinfo=tz, fold=1).utcoffset()
        )
    dates = build_dim_date(start, end, city).set_index("date")
    day = hours.normalize()
    df = pd.DataFrame(
        {
            "hour_ts": hours,
            "date": day,
            "hour_of_day": hours.hour,
            "day_of_week": hours.dayofweek,
            "is_weekend": hours.dayofweek >= 5,
            "is_holiday": dates.loc[day, "is_holiday"].to_numpy(),
            "is_dst_gap": gap,
            "is_dst_overlap": overlap,
        }
    )
    df["is_valid"] = ~df["is_dst_gap"]
    df["is_modelable"] = df["is_valid"] & ~df["is_dst_overlap"]
    return df
