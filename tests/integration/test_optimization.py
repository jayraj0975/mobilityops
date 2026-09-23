"""Backtest and scenarios end to end on the TEST / SYNTHETIC sample."""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from mobilityops.forecasting.evaluate import run_evaluation
from mobilityops.forecasting.features import load_demand
from mobilityops.optimization.model import RebalanceParams
from mobilityops.optimization.run import optimization_dir, run_backtest, scenario_report
from mobilityops.optimization.scenario import BacktestConfig, Window, window_demand
from tests.unit.test_forecast_features import make_tensor


@pytest.fixture(scope="module")
def env(built_sample):  # type: ignore[no-untyped-def]
    settings, _ = built_sample
    run_evaluation(settings, oracle_experiment=False)  # writes out-of-sample predictions
    cfg = BacktestConfig(day_stride=3)
    return settings, cfg, run_backtest(settings, cfg, sensitivity=False)


def test_report_is_labelled_a_simulation_with_assumptions_stated(env) -> None:  # type: ignore[no-untyped-def]
    _, cfg, rep = env
    assert "SIMULATED" in rep["label"] and rep["data_label"] == "TEST / SYNTHETIC DATA"
    a = rep["assumptions"]
    assert a["coverage"] == cfg.coverage and a["max_km"] == cfg.params.max_km
    assert "no fleet data" in a["supply"] and "zone where it stands" in a["service model"]
    assert "ACTUAL demand" in rep["design"]


def test_planners_are_scored_on_the_same_days_fleet_and_demand(env) -> None:  # type: ignore[no-untyped-def]
    settings, _, _ = env
    rows = pd.read_parquet(optimization_dir(settings) / "backtest_rows.parquet")
    per_key = rows.groupby(["day_index", "window"])
    assert (per_key["fleet"].nunique() == 1).all()
    assert (per_key["actual_demand"].nunique() == 1).all()
    assert (per_key["planner"].nunique() == 4).all()
    none = rows[rows["planner"] == "no_repositioning"]
    assert (none["vehicles_moved"] == 0).all() and (none["km"] == 0).all()
    assert (rows["served"] <= rows["actual_demand"] + 1e-9).all()


def test_oracle_plan_is_never_worse_than_any_other_plan_on_its_own_objective(env) -> None:  # type: ignore[no-untyped-def]
    """The oracle optimises against the actuals: no other feasible plan beats its objective."""
    settings, cfg, _ = env
    rows = pd.read_parquet(optimization_dir(settings) / "backtest_rows.parquet")
    rows = rows.assign(objective=rows["served"] - cfg.params.cost_per_km * rows["km"])
    wide = rows.pivot_table(index=["day_index", "window"], columns="planner", values="objective")
    for other in ("no_repositioning", "plan_lightgbm", "plan_seasonal_mean"):
        assert (wide["plan_oracle"] >= wide[other] - 0.1).all(), other


def test_summary_shapes_and_bootstrap_intervals(env) -> None:  # type: ignore[no-untyped-def]
    _, _, rep = env
    for name, v in rep["planners"].items():
        assert 0 <= v["served_share"] <= 1, name
    d = rep["lightgbm_vs_none"]
    assert d["ci95"][0] <= d["point"] <= d["ci95"][1] or abs(d["point"]) < 1e-3
    assert rep["oracle_vs_none"]["point"] >= -1e-9
    assert set(rep["solver_status_counts"]) <= {"optimal", "feasible_time_limit"}


# ----------------------------------------------------------------------------- scenarios
def _test_day(settings) -> date:  # type: ignore[no-untyped-def]
    t = load_demand(settings.db_path)
    return (t.days[-3]).date()


def test_scenario_returns_moves_with_names_and_context(env) -> None:  # type: ignore[no-untyped-def]
    settings, _, _ = env
    rep = scenario_report(settings, _test_day(settings), Window(17, 20), RebalanceParams())
    assert rep["status"] in ("optimal", "feasible_time_limit")
    assert "SIMULATED" in rep["label"] and rep["context"]["window"] == "17:00-20:00"
    assert rep["service_share_after"] >= rep["service_share_before"] - 1e-9
    for m in rep["moves"]:
        assert m["from_name"] and m["to_name"] and m["km"] <= 6.0 + 1e-9


def test_infeasible_service_request_is_explained_not_hidden(env) -> None:  # type: ignore[no-untyped-def]
    settings, _, _ = env
    rep = scenario_report(
        settings,
        _test_day(settings),
        Window(17, 20),
        RebalanceParams(min_service_share=0.999),
    )
    assert rep["status"] == "infeasible"
    assert rep["best_attainable_service_share"] < 0.999
    assert "cannot be reached" in rep["message"]


def test_demand_shock_increases_planned_demand(env) -> None:  # type: ignore[no-untyped-def]
    settings, _, _ = env
    day = _test_day(settings)
    base = scenario_report(settings, day, Window(17, 20), RebalanceParams())
    shock = scenario_report(settings, day, Window(17, 20), RebalanceParams(), multipliers={3: 3.0})
    assert shock["demand_total"] > base["demand_total"]
    assert "multipliers" in shock["context"]["demand_source"]


def test_scenario_input_errors_are_clear(env) -> None:  # type: ignore[no-untyped-def]
    settings, _, _ = env
    day = _test_day(settings)
    with pytest.raises(ValueError, match="outside the data range"):
        scenario_report(settings, date(2030, 1, 1), Window(7, 10), RebalanceParams())
    with pytest.raises(ValueError, match="no out-of-sample forecast"):
        scenario_report(settings, date(2024, 1, 20), Window(7, 10), RebalanceParams())
    with pytest.raises(ValueError, match="unknown zone"):
        scenario_report(settings, day, Window(7, 10), RebalanceParams(), multipliers={9999: 2.0})
    with pytest.raises(ValueError, match="must not be negative"):
        scenario_report(settings, day, Window(7, 10), RebalanceParams(), multipliers={3: -1.0})
    assert day - timedelta(days=1) < day  # sanity for the date helper


def test_windows_touching_unobserved_hours_are_skipped_not_zero_filled() -> None:
    t = make_tensor(n_days=20, n_zones=3)
    t.y[:, 5, 2] = np.nan  # the skipped spring-forward hour
    assert window_demand(t.y, 5, Window(1, 4)) is None
    assert window_demand(t.y, 5, Window(5, 8)) is not None
