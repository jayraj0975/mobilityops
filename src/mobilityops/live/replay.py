"""Replay of the held-out days: per-hour actual vs forecast, on a clock shared by all viewers.

The rows come from ``forecast/predictions.parquet``: forecasts the model made *before* seeing those
days (walk-forward, out of sample), so the replay shows genuine forecast error, not a fit to the
past. City totals are sums over zones; zone-level prediction intervals cannot be added into an
interval for a total (documented in docs/LIMITATIONS.md), so none is shown for the total.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

TOP_ZONES = 5
HISTORY_TICKS = 48


class ReplayUnavailable(RuntimeError):
    """The forecast evaluation (or its predictions) has not been generated yet."""


@dataclass
class Replay:
    hours: pd.DatetimeIndex
    actual: np.ndarray
    forecast: np.ndarray
    baseline: np.ndarray
    cum_abs_err: np.ndarray
    cum_actual: np.ndarray
    top: list[list[dict[str, Any]]]
    anomalies: list[list[dict[str, Any]]]
    label: str
    seconds_per_hour: float
    t0: float = field(default=0.0)

    @property
    def n(self) -> int:
        return len(self.hours)

    def index_at(self, now: float) -> int:
        """Tick shown ``now`` seconds on the clock (loops when the last hour is reached)."""
        return int(max(0.0, now - self.t0) / self.seconds_per_hour) % self.n

    def tick(self, i: int, *, loop: int = 0) -> dict[str, Any]:
        wape = float(self.cum_abs_err[i] / self.cum_actual[i]) if self.cum_actual[i] > 0 else None
        return {
            "kind": "replay",
            "label": self.label,
            "index": i,
            "of": self.n,
            "loop": loop,
            "hour_ts": self.hours[i].isoformat(),
            "actual": float(self.actual[i]),
            "forecast": float(self.forecast[i]),
            "baseline": float(self.baseline[i]),
            "abs_error": float(abs(self.forecast[i] - self.actual[i])),
            "running_wape": wape,
            "top_zones": self.top[i],
            "anomalies": self.anomalies[i],
        }

    def history(self, i: int, n: int = HISTORY_TICKS) -> list[dict[str, Any]]:
        return [self.tick(j) for j in range(max(0, i - n + 1), i + 1)]

    def meta(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "start": self.hours[0].isoformat(),
            "end": (self.hours[-1] + pd.Timedelta(hours=1)).isoformat(),
            "ticks": self.n,
            "seconds_per_hour": self.seconds_per_hour,
            "loop_seconds": self.n * self.seconds_per_hour,
        }


def build_replay(
    predictions_path: Path,
    zones: pd.DataFrame,
    events_path: Path | None,
    *,
    seconds_per_hour: float,
    data_label: str,
    model_col: str = "lightgbm",
    baseline_col: str = "seasonal_mean_4w",
) -> Replay:
    """Aggregate the held-out predictions to one row per hour."""
    if not predictions_path.exists():
        raise ReplayUnavailable(
            "no forecast predictions yet; run `forecast-eval` to generate the held-out days"
        )
    p = pd.read_parquet(predictions_path)
    if p.empty:
        raise ReplayUnavailable("the forecast evaluation holds no held-out days")
    p["hour_ts"] = pd.to_datetime(p["hour_ts"])
    city = p.groupby("hour_ts")[["y", model_col, baseline_col]].sum().sort_index()
    hours = pd.DatetimeIndex(city.index)
    actual = city["y"].to_numpy(dtype=float)
    forecast = city[model_col].to_numpy(dtype=float)
    err = np.abs(forecast - actual)
    names = dict(zip(zones["location_id"], zones["zone"], strict=True))

    top: list[list[dict[str, Any]]] = []
    for _, g in p.groupby("hour_ts", sort=True):
        best = g.nlargest(TOP_ZONES, "y").to_dict("records")
        top.append(
            [
                {
                    "location_id": int(r["location_id"]),
                    "zone": str(names.get(r["location_id"], r["location_id"])),
                    "actual": float(r["y"]),
                    "forecast": float(r[model_col]),
                }
                for r in best
            ]
        )

    anomalies: list[list[dict[str, Any]]] = [[] for _ in hours]
    if events_path is not None and events_path.exists():
        ev = pd.read_parquet(events_path)
        for r in ev.to_dict("records"):
            start, end = pd.Timestamp(r["start"]), pd.Timestamp(r["end"])
            lo = int(hours.searchsorted(start, side="left"))
            hi = int(hours.searchsorted(end, side="left"))
            for i in range(lo, min(hi, len(hours))):
                anomalies[i].append(
                    {
                        "zone": str(r["zone"]),
                        "direction": str(r["direction"]),
                        "severity": str(r["severity"]),
                        "scope": str(r["scope"]),
                    }
                )

    first, last = hours[0], hours[-1]  # both inclusive: the last hour's own day
    label = (
        f"REPLAY of held-out days {first:%Y-%m-%d} to {last:%Y-%m-%d}: forecasts made before "
        "those days, shown against what happened. Not live taxi data"
        + (" (TEST / SYNTHETIC DATA)" if "SYNTHETIC" in data_label else "")
        + "."
    )
    return Replay(
        hours=hours,
        actual=actual,
        forecast=forecast,
        baseline=city[baseline_col].to_numpy(dtype=float),
        cum_abs_err=np.cumsum(err),
        cum_actual=np.cumsum(actual),
        top=top,
        anomalies=anomalies,
        label=label,
        seconds_per_hour=seconds_per_hour,
    )


def parse_ts(value: str) -> datetime:
    return datetime.fromisoformat(value)
