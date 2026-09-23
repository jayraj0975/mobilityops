"""Build optimisation instances from the demand tensor, and run what-if scenarios.

Supply is an ASSUMPTION (no fleet data exist): the fleet is sized so its total capacity is
``coverage`` times the expected demand in the window, and vehicles start distributed in proportion
to *recent* demand for that window (the mean of the previous 7 days, all known before the window).
That mimics an operator who positions vehicles by habit. Rebalancing then matters when the
expected demand differs from habit (holidays, events, unusual days).
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any

import numpy as np
import pandas as pd

from mobilityops.forecasting.features import DemandTensor
from mobilityops.optimization.model import (
    Instance,
    RebalanceParams,
    ScenarioResult,
    served_trips,
    solve_rebalancing,
)

RECENT_DAYS = 7


@dataclass(frozen=True)
class Window:
    start_hour: int
    end_hour: int  # exclusive

    def __post_init__(self) -> None:
        if not 0 <= self.start_hour < self.end_hour <= 24:
            raise ValueError("window must satisfy 0 <= start_hour < end_hour <= 24")

    @property
    def hours(self) -> int:
        return self.end_hour - self.start_hour

    @property
    def label(self) -> str:
        return f"{self.start_hour:02d}:00-{self.end_hour:02d}:00"


def apportion(weights: np.ndarray, total: int) -> np.ndarray:
    """Split ``total`` whole vehicles in proportion to ``weights`` (largest remainder)."""
    w = np.clip(np.nan_to_num(weights, nan=0.0), 0.0, None)
    if total <= 0 or w.sum() <= 0:
        return np.zeros(len(w), dtype=int)
    quota = total * w / w.sum()
    base = np.floor(quota).astype(int)
    short = int(total - base.sum())
    if short > 0:
        order = np.argsort(-(quota - base), kind="stable")
        base[order[:short]] += 1
    return base


def window_demand(y: np.ndarray, day: int, w: Window) -> np.ndarray | None:
    """Total pickups per zone in the window, or ``None`` if any hour is unobserved (DST gap)."""
    block = y[:, day, w.start_hour : w.end_hour]
    return None if np.isnan(block).any() else block.sum(axis=1)


def recent_habit(t: DemandTensor, day: int, w: Window) -> np.ndarray:
    """Mean window demand over the previous days (strictly before ``day``)."""
    lo = max(0, day - RECENT_DAYS)
    totals = np.nansum(t.y[:, lo:day, w.start_hour : w.end_hour], axis=2)
    return np.asarray(totals.mean(axis=1))


def fleet_size(expected_total: float, coverage: float, trips_per_vehicle: float) -> int:
    return int(np.floor(coverage * expected_total / trips_per_vehicle))


def build_instance(
    t: DemandTensor,
    day: int,
    w: Window,
    planned_demand: np.ndarray,
    *,
    fleet: int,
) -> Instance:
    supply = apportion(recent_habit(t, day, w), fleet)
    return Instance(
        zone_ids=t.zones["location_id"].to_numpy(dtype=int),
        demand=np.asarray(planned_demand, dtype=float),
        supply=supply.astype(float),
        lon=t.zones["centroid_lon"].to_numpy(dtype=float),
        lat=t.zones["centroid_lat"].to_numpy(dtype=float),
    )


def forecast_window(pred: pd.DataFrame, n_zones: int, day: int, w: Window, col: str) -> np.ndarray:
    """Sum a forecast column over the window, per zone."""
    sel = pred[(pred["day_index"] == day) & pred["hour"].between(w.start_hour, w.end_hour - 1)]
    out = np.zeros(n_zones)
    np.add.at(out, sel["zone_index"].to_numpy(), sel[col].to_numpy(dtype=float))
    return out


def run_scenario(
    t: DemandTensor,
    predictions: pd.DataFrame,
    day: int,
    w: Window,
    params: RebalanceParams,
    *,
    coverage: float = 0.85,
    multipliers: dict[int, float] | None = None,
    model_col: str = "lightgbm",
) -> tuple[ScenarioResult, dict[str, Any]]:
    """Prospective what-if: plan against the *forecast* (optionally shocked in chosen zones)."""
    demand = forecast_window(predictions, t.n_zones, day, w, model_col)
    ids = t.zones["location_id"].to_numpy(dtype=int)
    for zone, factor in (multipliers or {}).items():
        if factor < 0:
            raise ValueError("demand multipliers must not be negative")
        idx = np.nonzero(ids == zone)[0]
        if len(idx) == 0:
            raise ValueError(f"unknown zone id {zone}")
        demand[idx] *= factor
    fleet = fleet_size(float(demand.sum()), coverage, params.trips_per_vehicle)
    inst = build_instance(t, day, w, demand, fleet=fleet)
    res = solve_rebalancing(inst, params)
    ctx = {
        "date": t.days[day].date().isoformat(),
        "window": w.label,
        "coverage_assumption": coverage,
        "demand_source": f"{model_col} forecast"
        + (f" with multipliers {multipliers}" if multipliers else ""),
        "supply_assumption": f"fleet distributed in proportion to the mean of the previous "
        f"{RECENT_DAYS} days' demand in the same window",
    }
    return res, ctx


# ------------------------------------------------------------------------------- backtest
PLANNERS: dict[str, str | None] = {
    "no_repositioning": None,
    "plan_lightgbm": "lightgbm",
    "plan_seasonal_mean": "seasonal_mean_4w",
    "plan_oracle": "y",  # plans with the actual demand: an upper bound, not achievable
}


@dataclass(frozen=True)
class BacktestConfig:
    windows: tuple[Window, ...] = (Window(7, 10), Window(17, 20))
    coverage: float = 0.85
    day_stride: int = 1  # use every n-th test day (sensitivity runs subsample)
    params: RebalanceParams = field(default_factory=RebalanceParams)

    def with_params(self, **kw: Any) -> BacktestConfig:
        return replace(self, params=replace(self.params, **kw))


def backtest(
    t: DemandTensor, predictions: pd.DataFrame, cfg: BacktestConfig
) -> tuple[pd.DataFrame, dict[str, int]]:
    """Plan with each demand source, score every plan against actual demand.

    Returns one row per (day, window, planner) and counts of skipped windows.
    """
    days = sorted(int(d) for d in predictions["day_index"].unique())[:: cfg.day_stride]
    rows: list[dict[str, Any]] = []
    skipped = {"dst_or_missing_actuals": 0}
    c = cfg.params.trips_per_vehicle
    for day in days:
        for w in cfg.windows:
            actual = window_demand(t.y, day, w)
            if actual is None:
                skipped["dst_or_missing_actuals"] += 1
                continue
            f_model = forecast_window(predictions, t.n_zones, day, w, "lightgbm")
            fleet = fleet_size(float(f_model.sum()), cfg.coverage, c)  # sized without hindsight
            base = build_instance(t, day, w, actual, fleet=fleet)
            plans = {
                "no_repositioning": None,
                "plan_lightgbm": f_model,
                "plan_seasonal_mean": forecast_window(
                    predictions, t.n_zones, day, w, "seasonal_mean_4w"
                ),
                "plan_oracle": actual,
            }
            for name, planned in plans.items():
                if planned is None:
                    final, moved, km, status = base.supply, 0, 0.0, "n/a"
                else:
                    res = solve_rebalancing(replace(base, demand=planned), cfg.params)
                    final = res.final_supply if res.final_supply is not None else base.supply
                    moved, km, status = res.vehicles_moved, res.km_total, res.status.value
                rows.append(
                    {
                        "day_index": day,
                        "window": w.label,
                        "planner": name,
                        "fleet": fleet,
                        "actual_demand": float(actual.sum()),
                        "served": served_trips(actual, np.asarray(final, dtype=float), c),
                        "vehicles_moved": moved,
                        "km": km,
                        "status": status,
                    }
                )
    return pd.DataFrame(rows), skipped
