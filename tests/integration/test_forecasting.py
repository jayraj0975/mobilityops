"""End-to-end forecasting on the TEST / SYNTHETIC sample, including a daylight-saving week."""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from mobilityops.forecasting.evaluate import (
    EvalConfig,
    default_config,
    forecast_next_day,
    run_evaluation,
    summarize,
    train_final,
    walk_forward,
)
from mobilityops.forecasting.features import HOURS, load_demand
from mobilityops.forecasting.model import load_model


@pytest.fixture(scope="module")
def tensor(built_sample):  # type: ignore[no-untyped-def]
    settings, _ = built_sample
    return load_demand(settings.db_path)


@pytest.fixture(scope="module")
def wf(tensor):  # type: ignore[no-untyped-def]
    cfg = default_config(tensor.n_days)
    return cfg, walk_forward(tensor, cfg)


def test_tensor_matches_gold_totals(built_sample, tensor) -> None:  # type: ignore[no-untyped-def]
    settings, _ = built_sample
    assert tensor.n_zones == 12 and tensor.n_days == 56
    import duckdb

    con = duckdb.connect(str(settings.db_path), read_only=True)
    total = con.execute(
        "SELECT sum(pickups) FROM fact_zone_hourly_demand f JOIN dim_hour h USING (hour_ts) "
        "WHERE h.is_modelable"
    ).fetchone()[0]
    con.close()
    assert np.nansum(tensor.y) == total


def test_predictions_cover_exactly_the_test_days_once(wf, tensor) -> None:  # type: ignore[no-untyped-def]
    cfg, res = wf
    p = res.predictions
    first_test = tensor.n_days - cfg.n_folds * cfg.fold_days
    assert p["day_index"].min() == first_test and p["day_index"].max() == tensor.n_days - 1
    assert not p.duplicated(["zone_index", "day_index", "hour"]).any()
    assert len(p) == tensor.n_zones * cfg.n_folds * cfg.fold_days * HOURS  # no DST in this window
    assert (p["lo"] <= p["lightgbm"]).all() and (p["lightgbm"] <= p["hi"]).all()
    assert (p["lo"] >= 0).all() and (p["lightgbm"] >= 0).all()
    # each fold's model was calibrated on data strictly before that fold's test days
    for f in res.folds:
        assert f["calibration_days"][1] < f["test_days"][0]
        assert f["train_days"][1] < f["calibration_days"][0]


def test_model_beats_persistence_and_intervals_are_roughly_calibrated(wf, tensor) -> None:  # type: ignore[no-untyped-def]
    cfg, res = wf
    rep = summarize(tensor, res, cfg)
    overall = rep["overall"]
    assert overall["lightgbm"]["wape"] < overall["naive"]["wape"]
    assert overall["lightgbm"]["wape"] < overall["seasonal_naive"]["wape"]
    assert 0.65 < rep["interval"]["overall"]["coverage"] < 0.92
    b = rep["bootstrap"]["improvement"]["naive"]
    assert b["difference_ci95"][0] > 0  # improvement over persistence is not a bootstrap fluke


def test_walk_forward_is_deterministic(tensor) -> None:  # type: ignore[no-untyped-def]
    cfg = EvalConfig(n_folds=1, fold_days=7, calib_days=7, params={"num_boost_round": 40})
    a = walk_forward(tensor, cfg).predictions["lightgbm"].to_numpy()
    b = walk_forward(tensor, cfg).predictions["lightgbm"].to_numpy()
    np.testing.assert_array_equal(a, b)


def test_run_evaluation_writes_a_labelled_report(built_sample) -> None:  # type: ignore[no-untyped-def]
    settings, _ = built_sample
    cfg = EvalConfig(n_folds=1, fold_days=7, calib_days=7, params={"num_boost_round": 40})
    rep = run_evaluation(settings, cfg)
    assert rep["data_label"] == "TEST / SYNTHETIC DATA"
    assert "ORACLE" in rep["oracle_weather_experiment"]["label"]
    saved = json.loads((settings.artifacts_dir / "forecast" / "evaluation.json").read_text())
    assert saved["overall"]["lightgbm"]["n"] == rep["test_rows"]
    assert (settings.artifacts_dir / "forecast" / "predictions.parquet").exists()


def test_final_model_round_trips_and_forecasts_the_next_day(built_sample, tensor) -> None:  # type: ignore[no-untyped-def]
    settings, _ = built_sample
    cfg = EvalConfig(n_folds=1, fold_days=7, calib_days=7, params={"num_boost_round": 40})
    path = train_final(settings, cfg)
    meta = json.loads((path / "meta.json").read_text())
    assert meta["data_label"] == "TEST / SYNTHETIC DATA" and meta["mode"] == "sample"
    assert meta["calibration_days"][1] == str(tensor.days[-1].date())
    model = load_model(settings)
    out = forecast_next_day(tensor, model)
    assert len(out) == tensor.n_zones * HOURS
    day_after = tensor.days[-1] + pd.Timedelta(days=1)
    assert out["hour_ts"].min() == day_after and out["hour_ts"].max() == day_after + pd.Timedelta(
        hours=23
    )
    assert (out["lo"] <= out["pred"]).all() and (out["pred"] <= out["hi"]).all()
    # save -> load must not change a single prediction
    again = load_model(settings, meta["model_id"])
    pd.testing.assert_frame_equal(out[["pred"]], forecast_next_day(tensor, again)[["pred"]])


def test_load_model_without_training_is_a_clear_error(sample_settings) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(FileNotFoundError, match="forecast-train"):
        load_model(sample_settings)


def test_spring_forward_week_is_handled(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """The nonexistent 02:00 on 2024-03-10 is neither a target nor read as zero demand."""
    from mobilityops.ingestion.pipeline import ingest_sample
    from mobilityops.pipeline import build_all
    from mobilityops.sample import SampleSpec, generate_sample
    from tests.conftest import make_env

    files = generate_sample(
        tmp_path / "dst", SampleSpec(start="2024-02-01", n_days=52, n_zones=6, dirty_fraction=0.0)
    )
    s = make_env(tmp_path / "env", files)
    ingest_sample(s)
    res = build_all(s)
    t = load_demand(res.db_path)
    gap_day = int((pd.Timestamp("2024-03-10") - t.days[0]).days)
    assert np.isnan(t.y[:, gap_day, 2]).all()  # the skipped hour is missing...
    assert not np.isnan(t.y[:, gap_day, 3]).any()  # ...and its neighbours are not

    # the test block starts on the clock-change day itself (day 38 of 52)
    cfg = EvalConfig(n_folds=1, fold_days=14, calib_days=7, params={"num_boost_round": 30})
    out = walk_forward(t, cfg).predictions
    on_gap_day = out[out["day_index"] == gap_day]
    assert 2 not in set(on_gap_day["hour"])  # no forecast row for an hour that did not exist
    assert len(on_gap_day) == t.n_zones * (HOURS - 1)
    assert out["lightgbm"].notna().all()


def test_next_day_forecast_from_a_tail_equals_the_full_history_forecast(
    tensor, built_sample
) -> None:  # type: ignore[no-untyped-def]
    """The memory optimisation must not change a single prediction."""
    from mobilityops.forecasting.features import build_features, feature_columns

    settings, _ = built_sample
    train_final(
        settings, EvalConfig(n_folds=1, fold_days=7, calib_days=7, params={"num_boost_round": 40})
    )
    model = load_model(settings)
    fast = forecast_next_day(tensor, model)
    ext = tensor.extended(1)  # the old way: features over the whole history
    frame = build_features(ext, days=range(ext.n_days - 1, ext.n_days))
    slow = model.predict(frame[feature_columns()])
    np.testing.assert_allclose(fast["pred"].to_numpy(), slow["pred"].to_numpy(), rtol=0, atol=1e-9)
    np.testing.assert_allclose(fast["hi"].to_numpy(), slow["hi"].to_numpy(), rtol=0, atol=1e-9)
    assert tensor.tail(10).n_days == 10 and tensor.tail(10_000).n_days == tensor.n_days
    with pytest.raises(ValueError):
        tensor.tail(0)
