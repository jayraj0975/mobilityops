"""Run and summarise the repositioning backtest and one-off scenarios; write artifacts."""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import UTC, date, datetime
from typing import Any

import numpy as np
import pandas as pd

from mobilityops.anomaly.run import load_predictions
from mobilityops.config import Settings
from mobilityops.forecasting.evaluate import data_run_id
from mobilityops.forecasting.features import DemandTensor, load_demand
from mobilityops.optimization.model import SIMULATION_LABEL, RebalanceParams
from mobilityops.optimization.scenario import (
    BacktestConfig,
    Window,
    backtest,
    run_scenario,
)

BOOTSTRAP_RESAMPLES = 2000
PLANNERS = ("no_repositioning", "plan_lightgbm", "plan_seasonal_mean", "plan_oracle")


def optimization_dir(settings: Settings):  # type: ignore[no-untyped-def]
    return settings.artifacts_dir / "optimization"


def _share(df: pd.DataFrame, planner: str) -> float:
    part = df[df["planner"] == planner]
    return float(part["served"].sum() / part["actual_demand"].sum())


def summarize(df: pd.DataFrame, t: DemandTensor, seed: int = 7) -> dict[str, Any]:
    """Served share per planner, paired differences with day-level bootstrap CIs."""
    per = {
        p: {
            "served_share": _share(df, p),
            "vehicles_moved_per_window": float(df[df["planner"] == p]["vehicles_moved"].mean()),
            "km_per_window": float(df[df["planner"] == p]["km"].mean()),
        }
        for p in PLANNERS
    }
    # day-level paired bootstrap on served shares
    days = np.sort(df["day_index"].unique())
    sums = {
        p: df[df["planner"] == p].groupby("day_index")[["served", "actual_demand"]].sum().loc[days]
        for p in PLANNERS
    }
    rng = np.random.default_rng(seed)
    draws = rng.integers(0, len(days), size=(BOOTSTRAP_RESAMPLES, len(days)))

    def boot_share(p: str) -> np.ndarray:
        s, a = sums[p]["served"].to_numpy(), sums[p]["actual_demand"].to_numpy()
        return s[draws].sum(axis=1) / a[draws].sum(axis=1)

    shares = {p: boot_share(p) for p in PLANNERS}

    def ci(a: np.ndarray) -> list[float]:
        return [float(np.percentile(a, 2.5)), float(np.percentile(a, 97.5))]

    def diff(a: str, b: str) -> dict[str, Any]:
        d = shares[a] - shares[b]
        return {
            "point": per[a]["served_share"] - per[b]["served_share"],
            "ci95": ci(d),
            "share_of_resamples_positive": float(np.mean(d > 0)),
        }

    gap = shares["plan_oracle"] - shares["no_repositioning"]
    closed = (shares["plan_lightgbm"] - shares["no_repositioning"]) / np.where(gap > 0, gap, np.nan)
    point_gap = per["plan_oracle"]["served_share"] - per["no_repositioning"]["served_share"]
    cal = t.calendar
    by_type = {}
    day_kind = pd.Series(
        np.where(
            cal["is_holiday"].to_numpy()[df["day_index"].to_numpy()],
            t.city.holiday_kind,
            np.where(
                cal["is_weekend"].to_numpy()[df["day_index"].to_numpy()], "weekend", "weekday"
            ),
        ),
        index=df.index,
    )
    for kind, sub in df.groupby(day_kind):
        by_type[str(kind)] = {
            "windows": int(sub[sub["planner"] == "no_repositioning"].shape[0]),
            **{p: _share(sub, p) for p in PLANNERS},
        }
    by_window = {str(w): {p: _share(sub, p) for p in PLANNERS} for w, sub in df.groupby("window")}
    statuses = df[df["planner"] != "no_repositioning"]["status"].value_counts().to_dict()
    return {
        "windows_scored": int(df[df["planner"] == "no_repositioning"].shape[0]),
        "days": len(days),
        "planners": per,
        "lightgbm_vs_none": diff("plan_lightgbm", "no_repositioning"),
        "lightgbm_vs_seasonal_mean_planning": diff("plan_lightgbm", "plan_seasonal_mean"),
        "oracle_vs_none": diff("plan_oracle", "no_repositioning"),
        "share_of_oracle_gap_closed_by_lightgbm": {
            "point": (
                per["plan_lightgbm"]["served_share"] - per["no_repositioning"]["served_share"]
            )
            / point_gap
            if point_gap > 0
            else None,
            "ci95": ci(closed[~np.isnan(closed)]) if np.isfinite(closed).any() else None,
        },
        "by_day_type": by_type,
        "by_window": by_window,
        "solver_status_counts": {str(k): int(v) for k, v in statuses.items()},
    }


SENSITIVITY: tuple[tuple[str, dict[str, Any]], ...] = (
    ("coverage 0.70 (scarcer fleet)", {"coverage": 0.70}),
    ("coverage 1.00 (fleet matches demand)", {"coverage": 1.00}),
    ("only 10% of fleet may move", {"max_move_share": 0.10}),
    ("up to 50% of fleet may move", {"max_move_share": 0.50}),
    ("moves limited to 3 km", {"max_km": 3.0}),
    ("moves up to 10 km", {"max_km": 10.0}),
)


def run_backtest(
    settings: Settings, cfg: BacktestConfig | None = None, *, sensitivity: bool = True
) -> dict[str, Any]:
    t = load_demand(settings.db_path, settings.city)
    preds = load_predictions(settings)
    cfg = cfg or BacktestConfig()
    df, skipped = backtest(t, preds, cfg)
    report: dict[str, Any] = {
        "label": SIMULATION_LABEL,
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "mode": settings.mode,
        "data_label": settings.data_label,
        "data_run_id": data_run_id(settings.db_path),
        "design": (
            "For each out-of-sample day and window: vehicles start distributed by the previous "
            f"{7} days' demand; a plan is computed from a demand source (LightGBM forecast, "
            "seasonal-mean forecast, or the actual demand as an unattainable oracle); the plan is "
            "then scored against the ACTUAL demand. The fleet is sized from the LightGBM forecast "
            "so no planner has hindsight about fleet size."
        ),
        "assumptions": {
            "windows": [w.label for w in cfg.windows],
            "coverage": cfg.coverage,
            **{k: v for k, v in asdict(cfg.params).items() if k != "min_service_share"},
            "supply": "no fleet data exist; supply is assumed (see design)",
            "service model": "a vehicle serves demand only in the zone where it stands",
        },
        "days_scored": [
            t.days[int(preds["day_index"].min())].date().isoformat(),
            t.days[int(preds["day_index"].max())].date().isoformat(),
        ],
        "skipped": skipped,
        **summarize(df, t),
    }
    if sensitivity:
        sens = []
        for name, change in SENSITIVITY:
            cov = change.get("coverage", cfg.coverage)
            kw = {k: v for k, v in change.items() if k != "coverage"}
            c2 = BacktestConfig(
                windows=cfg.windows, coverage=cov, day_stride=4, params=cfg.params
            ).with_params(**kw)
            d2, _ = backtest(t, preds, c2)
            s2 = summarize(d2, t)
            sens.append(
                {
                    "scenario": name,
                    "windows": s2["windows_scored"],
                    **{p: s2["planners"][p]["served_share"] for p in PLANNERS},
                    "lightgbm_vs_none_pp": 100 * s2["lightgbm_vs_none"]["point"],
                }
            )
        report["sensitivity"] = {
            "note": "every 4th test day only, to keep run time small",
            "rows": sens,
        }
    out = optimization_dir(settings)
    out.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out / "backtest_rows.parquet", index=False)
    (out / "backtest.json").write_text(json.dumps(report, indent=2, default=str))
    return report


def scenario_report(
    settings: Settings,
    when: date,
    window: Window,
    params: RebalanceParams,
    *,
    coverage: float = 0.85,
    multipliers: dict[int, float] | None = None,
    t: DemandTensor | None = None,
    preds: pd.DataFrame | None = None,
) -> dict[str, Any]:
    """One what-if. ``t``/``preds`` may be passed in by a caller that already holds them cached."""
    t = t if t is not None else load_demand(settings.db_path, settings.city)
    preds = preds if preds is not None else load_predictions(settings)
    ts = pd.Timestamp(when)
    if ts not in t.days:
        raise ValueError(
            f"{when} is outside the data range {t.days[0].date()}..{t.days[-1].date()}"
        )
    day = int((ts - t.days[0]).days)
    if day not in set(preds["day_index"].unique()):
        first, last = preds["day_index"].min(), preds["day_index"].max()
        raise ValueError(
            f"no out-of-sample forecast for {when}; scenarios use the evaluation days "
            f"{t.days[int(first)].date()}..{t.days[int(last)].date()}"
        )
    res, ctx = run_scenario(
        t, preds, day, window, params, coverage=coverage, multipliers=multipliers
    )
    zones = t.zones.set_index("location_id")["zone"]
    out = res.to_dict()
    out["moves"] = [
        {
            **m,
            "from_name": str(zones.get(m["from_zone"], "?")),
            "to_name": str(zones.get(m["to_zone"], "?")),
        }
        for m in out["moves"][:25]
    ]
    out.pop("final_supply", None)
    out["context"] = ctx
    out["mode"] = settings.mode
    out["data_label"] = settings.data_label
    return out
