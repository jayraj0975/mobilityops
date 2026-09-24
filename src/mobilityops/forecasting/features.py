"""Demand tensor and leak-free features for day-ahead, per-zone, hourly forecasting.

The forecasting problem
-----------------------
At the start of a local day D (00:00, the *origin*) forecast pickups for every zone and each of
the 24 hours of D. Only information available before the origin may be used.

How leakage is prevented
------------------------
Demand is held as a tensor ``y[zone, day, hour]``. Every history feature is a function of days
*strictly before* D (``shift_days(y, k)`` for ``k >= 1``), so a feature can never look at D or
later. There is no random split anywhere; ``tests/unit/test_forecast_features.py`` proves the
property by scrambling every value from day D onwards and asserting the features of day D do not
change. Calendar features (hour, weekday, holiday) describe the *target* time and are known in
advance, which is legitimate. Same-period weather is NOT a feature: at the origin it would have to
be a weather *forecast*, which this project does not have (see ``ORACLE_WEATHER_FEATURES``).

Local time
----------
TLC timestamps are naive New York local time. Lags are in whole days, so "same hour yesterday" is
the same wall-clock hour, which is what demand follows (people commute at 08:00 local). The
spring-forward hour is absent from the grid and the fall-back hour is not modelable; both are NaN
here and are simply skipped, never read as zero demand.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

from mobilityops.transform.calendar import build_dim_date

HOURS = 24
MIN_HISTORY_DAYS = 14  # the longest lag; origins earlier than this lack full history
LEVEL_DAYS = 28

# Features that use history only. Order is part of the model contract (stored with the model).
HISTORY_FEATURES: tuple[str, ...] = (
    "lag_1d",  # same local hour, 1 day before the target day
    "lag_2d",
    "lag_7d",
    "lag_14d",
    "same_hour_mean_7d",  # mean of the same hour over the 7 days before the target day
    "same_dow_hour_mean_4w",  # mean of the same weekday+hour over the previous 4 weeks
    "prev_day_mean",  # mean hourly pickups on the day before
    "mean_7d",
    "mean_28d",
    "prev_day_evening_mean",  # 18:00-23:59 of the previous day: the state closest to the origin
)
CALENDAR_FEATURES: tuple[str, ...] = (
    "hour",
    "day_of_week",
    "is_weekend",
    "is_holiday",
    "is_day_after_holiday",
    "is_day_before_holiday",
)
ZONE_FEATURES: tuple[str, ...] = ("location_id", "borough_code", "centroid_lon", "centroid_lat")
BASE_FEATURES: tuple[str, ...] = HISTORY_FEATURES + CALENDAR_FEATURES + ZONE_FEATURES
CATEGORICAL_FEATURES: tuple[str, ...] = ("location_id", "borough_code")

# Experiment only, always labelled ORACLE in reports: uses the target day's ACTUAL weather, which
# in real operation would have to be forecast. Measures an upper bound on what weather could add.
ORACLE_WEATHER_FEATURES: tuple[str, ...] = ("prcp_mm", "tmax_c", "is_rain", "is_snow")


@dataclass(frozen=True)
class DemandTensor:
    y: np.ndarray  # (zones, days, 24) float64; NaN = not observable / not modelable
    zones: pd.DataFrame  # one row per zone, same order as y axis 0
    days: pd.DatetimeIndex  # local midnight of each day, same order as y axis 1
    calendar: pd.DataFrame  # one row per day (date, is_weekend, is_holiday, ...)
    weather: pd.DataFrame  # one row per day; NaN where the source has no weather

    @property
    def n_zones(self) -> int:
        return int(self.y.shape[0])

    @property
    def n_days(self) -> int:
        return int(self.y.shape[1])

    def extended(self, extra_days: int = 1) -> DemandTensor:
        """Append future days with unknown demand (NaN) so an unobserved day can be forecast."""
        if extra_days < 1:
            raise ValueError("extra_days must be >= 1")
        y = np.concatenate([self.y, np.full((self.n_zones, extra_days, HOURS), np.nan)], axis=1)
        days = pd.date_range(self.days[0], periods=self.n_days + extra_days, freq="D")
        cal = _calendar_frame(days)
        return DemandTensor(y, self.zones, days, cal, self.weather.reindex(days))


def _calendar_frame(days: pd.DatetimeIndex) -> pd.DataFrame:
    """Calendar attributes for ``days``, including the neighbours of each holiday."""
    start = days[0].date() - timedelta(days=1)
    end = days[-1].date() + timedelta(days=2)
    full = build_dim_date(start, end).set_index("date")
    hol = full["is_holiday"]
    out = pd.DataFrame(index=days)
    out["day_of_week"] = full.loc[days, "day_of_week"].to_numpy()
    out["is_weekend"] = full.loc[days, "is_weekend"].to_numpy()
    out["is_holiday"] = hol.loc[days].to_numpy()
    out["is_day_after_holiday"] = hol.shift(1).fillna(False).loc[days].to_numpy()
    out["is_day_before_holiday"] = hol.shift(-1).fillna(False).loc[days].to_numpy()
    return out


def load_demand(db_path: Path) -> DemandTensor:
    """Read the gold layer into a tensor. Non-modelable and non-existent hours become NaN."""
    if not db_path.exists():
        raise FileNotFoundError(f"database not found at {db_path}; run `ingest` and `build` first")
    con = duckdb.connect(str(db_path), read_only=True)
    try:
        zones = con.execute(
            "SELECT DISTINCT z.location_id, z.zone, z.borough, z.centroid_lon, z.centroid_lat "
            "FROM dim_zone z JOIN fact_zone_hourly_demand f USING (location_id) "
            "ORDER BY z.location_id"
        ).df()
        fact = con.execute(
            "SELECT f.location_id, f.hour_ts, f.pickups FROM fact_zone_hourly_demand f "
            "JOIN dim_hour h USING (hour_ts) WHERE h.is_modelable"
        ).df()
        weather = con.execute(
            "SELECT date, prcp_mm, tmax_c, is_rain, is_snow FROM fact_weather_daily"
        ).df()
    finally:
        con.close()
    if fact.empty:
        raise ValueError("the gold layer has no demand rows; run `ingest` and `build` first")

    first = pd.Timestamp(fact["hour_ts"].min()).normalize()
    last = pd.Timestamp(fact["hour_ts"].max()).normalize()
    days = pd.date_range(first, last, freq="D")
    zone_index = {int(z): i for i, z in enumerate(zones["location_id"])}
    y = np.full((len(zones), len(days), HOURS), np.nan)
    ts = pd.DatetimeIndex(fact["hour_ts"])
    zi = fact["location_id"].map(zone_index).to_numpy()
    di = ((ts.normalize() - first).days).to_numpy()
    y[zi, di, ts.hour.to_numpy()] = fact["pickups"].to_numpy(dtype=float)

    weather["date"] = pd.to_datetime(weather["date"])
    weather = weather.set_index("date").reindex(days)
    weather.index = days
    return DemandTensor(y, zones.reset_index(drop=True), days, _calendar_frame(days), weather)


def shift_days(a: np.ndarray, k: int) -> np.ndarray:
    """``out[:, d, :] = a[:, d - k, :]``; the first ``k`` days are NaN. ``k >= 1`` only."""
    if k < 1:
        raise ValueError("history features must look back at least one day")
    out = np.full_like(a, np.nan)
    out[:, k:, :] = a[:, :-k, :]
    return out


def _nanmean(stack: list[np.ndarray]) -> np.ndarray:
    arr = np.stack(stack)
    count = np.sum(~np.isnan(arr), axis=0)
    total = np.nansum(arr, axis=0)
    return np.divide(total, count, out=np.full(total.shape, np.nan), where=count > 0)


def history_tensors(y: np.ndarray) -> dict[str, np.ndarray]:
    """All history features as (zones, days, 24) arrays. Pure function of ``y`` shifted back."""
    lag = {k: shift_days(y, k) for k in (1, 2, 7, 14, 21, 28)}
    # Daily means are (zones, days, 1): tiny, so long look-backs stay cheap.
    daily = _nanmean([y[:, :, h : h + 1] for h in range(HOURS)])
    evening = _nanmean([y[:, :, h : h + 1] for h in range(18, HOURS)])

    def prev_days_mean(n: int) -> np.ndarray:
        return _nanmean([shift_days(daily, k) for k in range(1, n + 1)])

    def spread(a: np.ndarray) -> np.ndarray:
        return np.broadcast_to(a, y.shape)

    return {
        "lag_1d": lag[1],
        "lag_2d": lag[2],
        "lag_7d": lag[7],
        "lag_14d": lag[14],
        "same_hour_mean_7d": _nanmean([shift_days(y, k) for k in range(1, 8)]),
        "same_dow_hour_mean_4w": _nanmean([lag[7], lag[14], lag[21], lag[28]]),
        "prev_day_mean": spread(shift_days(daily, 1)),
        "mean_7d": spread(prev_days_mean(7)),
        "mean_28d": spread(prev_days_mean(LEVEL_DAYS)),
        "prev_day_evening_mean": spread(shift_days(evening, 1)),
    }


def build_features(
    t: DemandTensor,
    days: range | None = None,
    *,
    oracle_weather: bool = False,
) -> pd.DataFrame:
    """One row per (zone, target day in ``days``, hour). ``target`` is NaN where unobserved.

    ``days`` are indices into ``t.days``; by default every day with full history.
    """
    day_idx = np.arange(MIN_HISTORY_DAYS, t.n_days) if days is None else np.asarray(days)
    if len(day_idx) == 0:
        return pd.DataFrame()
    tensors = history_tensors(t.y)
    z_n, d_n = t.n_zones, len(day_idx)
    shape = (z_n, d_n, HOURS)

    def flat(a: np.ndarray) -> np.ndarray:
        return np.ascontiguousarray(a[:, day_idx, :]).reshape(-1)

    data: dict[str, np.ndarray] = {name: flat(a).astype(np.float32) for name, a in tensors.items()}
    data["hour"] = np.broadcast_to(np.arange(HOURS), shape).reshape(-1).astype(np.int8)
    for col in CALENDAR_FEATURES[1:]:  # everything except "hour"
        per_day = t.calendar[col].to_numpy()[day_idx].astype(np.int8)
        data[col] = np.broadcast_to(per_day[None, :, None], shape).reshape(-1)
    zones = t.zones
    borough = zones["borough"].astype("category")
    for col, values in (
        ("location_id", zones["location_id"].to_numpy()),
        ("borough_code", borough.cat.codes.to_numpy()),
        ("centroid_lon", zones["centroid_lon"].to_numpy(dtype=float)),
        ("centroid_lat", zones["centroid_lat"].to_numpy(dtype=float)),
    ):
        data[col] = np.broadcast_to(values[:, None, None], shape).reshape(-1)
    if oracle_weather:
        for col in ORACLE_WEATHER_FEATURES:
            per_day = pd.to_numeric(t.weather[col], errors="coerce").to_numpy(dtype=float)[day_idx]
            data[col] = np.broadcast_to(per_day[None, :, None], shape).reshape(-1)

    frame = pd.DataFrame(data)
    frame["zone_index"] = np.broadcast_to(np.arange(z_n)[:, None, None], shape).reshape(-1)
    frame["day_index"] = np.broadcast_to(day_idx[None, :, None], shape).reshape(-1)
    frame["target"] = flat(t.y)
    return frame


def feature_columns(oracle_weather: bool = False) -> list[str]:
    return list(BASE_FEATURES) + (list(ORACLE_WEATHER_FEATURES) if oracle_weather else [])


def hour_timestamps(t: DemandTensor, frame: pd.DataFrame) -> pd.DatetimeIndex:
    """Local timestamp of each row's target hour."""
    base = t.days[frame["day_index"].to_numpy()]
    return pd.DatetimeIndex(base) + pd.to_timedelta(frame["hour"].to_numpy(dtype=int), unit="h")
