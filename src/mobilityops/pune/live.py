"""Live logic for Pune: today's SIMULATED demand, the forecast for today, and live events.

Everything here is pure (no network, no clock reads): the worker passes in ``now``, the recent rain
and the models, so every behaviour can be tested with a fixed time. Demand is simulated, so the
"live" numbers are a replay of the model at the real time of day, conditioned on the real rain that
has fallen so far. They are labelled SIMULATED wherever shown.
"""

from __future__ import annotations

import math
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from mobilityops.city import PUNE, City
from mobilityops.forecasting.evaluate import forecast_next_day
from mobilityops.forecasting.features import DemandTensor
from mobilityops.forecasting.model import ForecastModel
from mobilityops.pune import simulate as sim

LOCAL = ZoneInfo(PUNE.timezone)
HOURS = 24
# Live detection rule (documented in docs/LIVE_DATA.md): a run of at least two consecutive completed
# hours whose pooled standardised deviation from the forecast is large and whose size is material.
MIN_RUN_HOURS = 2
SEED_Z = 2.5  # an hour joins a run when its own standardised deviation is at least this
EVENT_Z = 5.0  # the run's pooled deviation must reach this
MIN_RATIO_UP = 1.5
MAX_RATIO_DOWN = 0.6
MIN_TRIPS = 30  # ignore runs where the forecast total is small: noise dominates
MODEL_ERROR_SHARE = 0.15  # forecast error beyond Poisson noise, as a share of the forecast


def local_naive(now: datetime) -> datetime:
    """A UTC (or aware) time as naive Asia/Kolkata local time, as the demand tables use."""
    return now.astimezone(LOCAL).replace(tzinfo=None)


def _rain_for_day(rain: pd.DataFrame, day: date) -> np.ndarray:
    idx = pd.date_range(pd.Timestamp(day), periods=HOURS, freq="h")
    return rain.set_index("hour_ts")["precipitation"].reindex(idx).to_numpy()


def hour_fraction(hour_start: datetime | pd.Timestamp, at: datetime | pd.Timestamp) -> float:
    """How much of the hour starting at ``hour_start`` has elapsed at ``at`` (both naive local)."""
    seconds = (pd.Timestamp(at) - pd.Timestamp(hour_start)).total_seconds()
    return float(min(1.0, max(0.0, seconds / 3600.0)))


def simulate_recent(
    model: sim.ZoneModel,
    now: datetime,
    rain: pd.DataFrame,
    seed: int,
    city: City = PUNE,
    days_back: int = 1,
) -> tuple[pd.DataFrame, str]:
    """Simulated zone-hours from ``days_back`` days ago up to and including the running hour.

    Values are for the WHOLE hour, including the one still running; readers pro-rate that hour
    with :func:`hour_fraction` so any moment in the last day can be shown. Returns
    ``(frame, running_hour)`` with ``frame`` = ``location_id, hour_ts, pickups, dropoffs``.
    """
    local = local_naive(now)
    running = pd.Timestamp(local).floor("h")
    frames = []
    for back in range(days_back, -1, -1):
        day = local.date() - timedelta(days=back)
        pick = sim.simulate_day(
            model,
            day,
            _rain_for_day(rain, day),
            day in city.holidays(day, day),
            seed,
            sim.events_for_day(model, day, seed),
        )
        drop = sim.allocate_dropoffs(pick, model)
        hours = pd.date_range(pd.Timestamp(day), periods=HOURS, freq="h")
        keep = np.asarray(hours <= running)
        frames.append(
            pd.DataFrame(
                {
                    "location_id": np.repeat(model.zone_ids, int(keep.sum())),
                    "hour_ts": np.tile(hours[keep].to_numpy(), len(model.zone_ids)),
                    "pickups": pick[:, keep].ravel(),
                    "dropoffs": drop[:, keep].ravel(),
                }
            )
        )
    return pd.concat(frames, ignore_index=True), running.isoformat()


def extend_tensor(
    t: DemandTensor,
    model: sim.ZoneModel,
    upto: date,
    rain: pd.DataFrame,
    seed: int,
    city: City = PUNE,
) -> DemandTensor:
    """The tensor with simulated days appended so that its last day is the day before ``upto``.

    Days beyond the analytical database (built up to some past day) are filled with the same
    simulation the build uses, so forecasting today does not need a nightly rebuild.
    """
    last = t.days[-1].date()
    n_missing = (upto - last).days - 1
    if n_missing <= 0:
        return t
    if not np.array_equal(t.zones["location_id"].to_numpy(), model.zone_ids):
        raise ValueError("the tensor's zones do not match the simulation model")
    ext = t.extended(n_missing)
    holidays = city.holidays(last + timedelta(days=1), upto - timedelta(days=1))
    for k in range(n_missing):
        day = last + timedelta(days=k + 1)
        ext.y[:, t.n_days + k, :] = sim.simulate_day(
            model,
            day,
            _rain_for_day(rain, day),
            day in holidays,
            seed,
            sim.events_for_day(model, day, seed),
        )
    return ext


def forecast_today(
    t: DemandTensor,
    forecaster: ForecastModel,
    sim_model: sim.ZoneModel,
    today: date,
    rain: pd.DataFrame,
    seed: int,
    city: City = PUNE,
) -> pd.DataFrame:
    """Day-ahead forecast (with the model's 80% range) for every zone-hour of ``today``."""
    upto_yesterday = extend_tensor(t, sim_model, today, rain, seed, city)
    if upto_yesterday.days[-1].date() != today - timedelta(days=1):
        raise ValueError(
            f"the data ends {upto_yesterday.days[-1].date()}, expected {today - timedelta(days=1)}"
        )
    return forecast_next_day(upto_yesterday, forecaster)


def _severity(z: float) -> str:
    a = abs(z)
    return "high" if a >= 10 else "medium" if a >= 7 else "low"


def detect_live_events(
    actual: pd.DataFrame,
    forecast: pd.DataFrame,
    zone_names: dict[int, str],
    now: datetime,
) -> list[dict[str, Any]]:
    """Events among the completed hours of today: runs where demand left the forecast.

    A rule, not a trained detector, and it runs on simulated demand. For each zone an hour has
    standardised deviation ``(actual - forecast) / sqrt(forecast + (0.15 * forecast)^2)`` (Poisson
    noise plus typical model error). Consecutive hours of one sign with |z| >= 2.5 form a run; the
    run is an event when its pooled deviation reaches 5, the ratio is at least 1.5x (or at most
    0.6x) and the forecast total is at least 30 trips. The running hour is never used.

    ``actual``: location_id, hour_ts, pickups. ``forecast``: location_id, hour_ts, pred.
    """
    if actual.empty or forecast.empty:
        return []
    running = pd.Timestamp(local_naive(now)).floor("h")
    df = actual[actual["hour_ts"] < running].merge(
        forecast[["location_id", "hour_ts", "pred"]], on=["location_id", "hour_ts"]
    )
    out: list[dict[str, Any]] = []
    hour = np.timedelta64(1, "h")
    for _, g in df.sort_values("hour_ts").groupby("location_id"):
        zone = int(g["location_id"].iloc[0])
        hours = g["hour_ts"].to_numpy()
        act = g["pickups"].to_numpy(dtype=float)
        pred = g["pred"].to_numpy(dtype=float)
        var = pred + (MODEL_ERROR_SHARE * pred) ** 2
        z = (act - pred) / np.sqrt(np.maximum(var, 1.0))
        i, n = 0, len(g)
        while i < n:
            if abs(z[i]) < SEED_Z:
                i += 1
                continue
            j = i
            while (
                j + 1 < n
                and abs(z[j + 1]) >= SEED_Z
                and np.sign(z[j + 1]) == np.sign(z[i])
                and hours[j + 1] - hours[j] == hour
            ):
                j += 1
            sl = slice(i, j + 1)
            ev = _close_run(zone, hours[i], hours[j], act[sl], pred[sl], var[sl], zone_names, now)
            if ev is not None:
                out.append(ev)
            i = j + 1
    return sorted(out, key=lambda e: -abs(float(e["score"])))


def _close_run(
    zone: int,
    first_hour: np.datetime64,
    last_hour: np.datetime64,
    act: np.ndarray,
    pred: np.ndarray,
    var: np.ndarray,
    names: dict[int, str],
    now: datetime,
) -> dict[str, Any] | None:
    if len(act) < MIN_RUN_HOURS:
        return None
    actual, expected, variance = float(act.sum()), float(pred.sum()), float(var.sum())
    if expected < MIN_TRIPS or variance <= 0:
        return None
    z = (actual - expected) / math.sqrt(variance)
    ratio = actual / expected
    up = z > 0
    if abs(z) < EVENT_Z or (up and ratio < MIN_RATIO_UP) or (not up and ratio > MAX_RATIO_DOWN):
        return None
    start = pd.Timestamp(first_hour)
    end = pd.Timestamp(last_hour) + pd.Timedelta(hours=1)
    name = names.get(zone, f"zone {zone}")
    kind = "surge" if up else "drop"
    text = (
        f"{name} had {actual:.0f} simulated pickups between {start:%H:%M} and {end:%H:%M}, "
        f"{ratio:.1f}x the forecast of {expected:.0f} ({kind}; deviation {z:+.1f} sigma). "
        "This is a departure from the forecast in simulated demand; it says nothing about a cause."
    )
    return {
        "id": f"{start:%Y%m%dT%H}-{zone}-{kind}",
        "zone_id": zone,
        "kind": kind,
        "severity": _severity(z),
        "start_ts": start.isoformat(),
        "end_ts": end.isoformat(),
        "actual": actual,
        "expected": expected,
        "score": round(z, 2),
        "detected_at": now.isoformat(timespec="seconds"),
        "explanation": text,
    }
