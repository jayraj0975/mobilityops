"""Leakage and correctness tests for the forecasting features, baselines, metrics and intervals."""

from __future__ import annotations

import itertools

import numpy as np
import pandas as pd
import pytest

from mobilityops.forecasting.baselines import BASELINES, baseline_forecasts
from mobilityops.forecasting.evaluate import EvalConfig, fold_windows, metrics
from mobilityops.forecasting.features import (
    HOURS,
    MIN_HISTORY_DAYS,
    DemandTensor,
    build_features,
    history_tensors,
    shift_days,
)
from mobilityops.forecasting.model import (
    MIN_BIN_ROWS,
    PRED_BIN_EDGES,
    conformal_quantiles,
    pred_bin,
)


def make_tensor(n_days: int = 45, n_zones: int = 3, seed: int = 0) -> DemandTensor:
    from mobilityops.forecasting.features import _calendar_frame

    rng = np.random.default_rng(seed)
    y = rng.poisson(8.0, size=(n_zones, n_days, HOURS)).astype(float)
    days = pd.date_range("2024-01-01", periods=n_days, freq="D")
    zones = pd.DataFrame(
        {
            "location_id": np.arange(1, n_zones + 1),
            "zone": [f"z{i}" for i in range(n_zones)],
            "borough": ["Manhattan", "Queens", "Bronx", "Brooklyn", "Staten Island"][:n_zones],
            "centroid_lon": np.linspace(-74.0, -73.8, n_zones),
            "centroid_lat": np.linspace(40.6, 40.8, n_zones),
        }
    )
    weather = pd.DataFrame(
        {"prcp_mm": 0.0, "tmax_c": 5.0, "is_rain": False, "is_snow": False}, index=days
    )
    return DemandTensor(y, zones, days, _calendar_frame(days), weather)


FEATURE_COLS = [
    "lag_1d",
    "lag_2d",
    "lag_7d",
    "lag_14d",
    "same_hour_mean_7d",
    "same_dow_hour_mean_4w",
    "prev_day_mean",
    "mean_7d",
    "mean_28d",
    "prev_day_evening_mean",
]


@pytest.mark.parametrize("origin", [MIN_HISTORY_DAYS, 20, 33, 44])
def test_features_of_a_day_never_depend_on_that_day_or_later(origin: int) -> None:
    """The core leakage guarantee: destroy everything from the origin onwards; nothing changes."""
    t = make_tensor()
    honest = build_features(t, days=range(origin, origin + 1))
    scrambled = make_tensor()
    rng = np.random.default_rng(99)
    scrambled.y[:, origin:, :] = rng.integers(500, 900, size=scrambled.y[:, origin:, :].shape)
    after = build_features(scrambled, days=range(origin, origin + 1))
    pd.testing.assert_frame_equal(
        honest[FEATURE_COLS].reset_index(drop=True), after[FEATURE_COLS].reset_index(drop=True)
    )
    # ...while the target itself (which is what we are forecasting) is of course different
    assert not np.allclose(honest["target"], after["target"])


def test_scrambling_only_the_future_beyond_the_target_day_changes_nothing_for_baselines() -> None:
    t = make_tensor()
    origin = 30
    frame = build_features(t, days=range(origin, origin + 1))
    t.y[:, origin + 1 :, :] = 12345.0
    later = build_features(t, days=range(origin, origin + 1))
    a, _ = baseline_forecasts(frame)
    b, _ = baseline_forecasts(later)
    for name in BASELINES:
        np.testing.assert_array_equal(a[name], b[name])


def test_shift_days_is_strictly_backward() -> None:
    a = np.arange(2 * 5 * 24, dtype=float).reshape(2, 5, 24)
    s = shift_days(a, 2)
    assert np.isnan(s[:, :2, :]).all()
    np.testing.assert_array_equal(s[:, 2:, :], a[:, :-2, :])
    for bad in (0, -1):
        with pytest.raises(ValueError, match="at least one day"):
            shift_days(a, bad)


def test_history_values_are_what_they_claim_to_be() -> None:
    t = make_tensor(n_days=40, n_zones=1)
    y = t.y
    h = history_tensors(y)
    d, hr = 35, 9
    assert h["lag_1d"][0, d, hr] == y[0, d - 1, hr]
    assert h["lag_7d"][0, d, hr] == y[0, d - 7, hr]
    assert h["same_hour_mean_7d"][0, d, hr] == pytest.approx(y[0, d - 7 : d, hr].mean())
    weekly = np.mean([y[0, d - 7 * k, hr] for k in (1, 2, 3, 4)])
    assert h["same_dow_hour_mean_4w"][0, d, hr] == pytest.approx(weekly)
    assert h["mean_7d"][0, d, hr] == pytest.approx(y[0, d - 7 : d, :].mean())
    assert h["prev_day_evening_mean"][0, d, hr] == pytest.approx(y[0, d - 1, 18:].mean())


def test_missing_hours_are_skipped_not_treated_as_zero() -> None:
    t = make_tensor(n_days=40, n_zones=1)
    t.y[0, 34, 5] = np.nan  # e.g. the skipped spring-forward hour
    h = history_tensors(t.y)
    assert np.isnan(h["lag_1d"][0, 35, 5])
    expected = np.nanmean(t.y[0, 28:35, 5])
    assert h["same_hour_mean_7d"][0, 35, 5] == pytest.approx(expected)


def test_frame_shape_and_target_alignment() -> None:
    t = make_tensor(n_days=30, n_zones=3)
    f = build_features(t)
    assert len(f) == 3 * (30 - MIN_HISTORY_DAYS) * HOURS
    row = f.iloc[777]
    z, d, h = int(row["zone_index"]), int(row["day_index"]), int(row["hour"])
    assert row["target"] == t.y[z, d, h]
    assert row["lag_1d"] == pytest.approx(t.y[z, d - 1, h])
    assert f["day_index"].min() == MIN_HISTORY_DAYS


def test_calendar_features_flag_holiday_neighbours() -> None:
    t = make_tensor(n_days=45)  # 2024-01-01 (holiday) .. 2024-02-14; MLK day is 2024-01-15
    f = build_features(t, days=range(MIN_HISTORY_DAYS, 17))  # Jan 15, 16
    by_day = f.groupby("day_index")[
        ["is_holiday", "is_day_after_holiday", "is_day_before_holiday"]
    ].first()
    assert by_day.loc[14].tolist() == [1, 0, 0]  # 2024-01-15 Martin Luther King Jr. Day
    assert by_day.loc[15].tolist() == [0, 1, 0]


def test_oracle_weather_columns_exist_only_on_request() -> None:
    t = make_tensor(n_days=30)
    assert "prcp_mm" not in build_features(t).columns
    assert "prcp_mm" in build_features(t, oracle_weather=True).columns


# ------------------------------------------------------------------------- fold windows
def test_fold_windows_are_strictly_chronological_and_never_overlap() -> None:
    cfg = EvalConfig(n_folds=4, fold_days=14, calib_days=14)
    folds = fold_windows(152, cfg)
    assert [f.test.start for f in folds] == [96, 110, 124, 138]
    assert folds[-1].test.stop == 152  # tests end exactly at the last day
    for f in folds:
        assert f.train.stop == f.calibration.start  # nothing between training and calibration
        assert f.calibration.stop == f.test.start  # calibration immediately precedes test
        assert f.train.start >= MIN_HISTORY_DAYS
    for a, b in itertools.pairwise(folds):
        assert a.test.stop == b.test.start  # test blocks tile the tail with no gap or overlap
        assert b.train.stop > a.train.stop  # later folds see strictly more history


def test_too_little_history_is_a_clear_error() -> None:
    with pytest.raises(ValueError, match=r"only \d+ days"):
        fold_windows(40, EvalConfig(n_folds=4, fold_days=14, calib_days=14))


# -------------------------------------------------------------------------------- metrics
def test_metrics_match_hand_computation() -> None:
    y = np.array([10.0, 0.0, 5.0, 5.0])
    p = np.array([8.0, 1.0, 5.0, 9.0])
    m = metrics(y, p)
    assert m["mae"] == pytest.approx((2 + 1 + 0 + 4) / 4)
    assert m["rmse"] == pytest.approx(np.sqrt((4 + 1 + 0 + 16) / 4))
    assert m["wape"] == pytest.approx(7 / 20)
    assert m["bias"] == pytest.approx((8 + 1 + 5 + 9 - 20) / 20)


def test_wape_is_undefined_not_infinite_when_there_was_no_demand() -> None:
    m = metrics(np.zeros(5), np.ones(5))
    assert m["wape"] is None and m["bias"] is None and m["mae"] == 1.0
    assert metrics(np.array([]), np.array([]))["n"] == 0


# ---------------------------------------------------------------------- baselines
def test_baselines_are_the_documented_lags_and_fallbacks_are_counted() -> None:
    t = make_tensor(n_days=40, n_zones=2)
    t.y[0, 30, 4] = np.nan  # the value naive would copy for (zone 0, day 31, hour 4)
    f = build_features(t, days=range(31, 32))
    preds, fallbacks = baseline_forecasts(f)
    row = f[(f["zone_index"] == 0) & (f["hour"] == 4)].index[0]
    pos = f.index.get_loc(row)
    assert np.isnan(f["lag_1d"].iloc[pos])
    assert preds["naive"][pos] == pytest.approx(f["same_dow_hour_mean_4w"].iloc[pos])
    assert fallbacks["naive"] == 1
    other = f.index.get_loc(f[(f["zone_index"] == 1) & (f["hour"] == 4)].index[0])
    assert preds["naive"][other] == f["lag_1d"].iloc[other]
    assert preds["seasonal_naive"][other] == f["lag_7d"].iloc[other]


# -------------------------------------------------------------------- conformal bands
def test_conformal_bands_fix_the_busy_zone_undercoverage_a_pooled_quantile_has() -> None:
    """Over-dispersed demand across very different volumes: the failure seen in real data."""
    rng = np.random.default_rng(3)
    scale = np.repeat([0.3, 3.0, 15.0, 80.0], 5000)
    y_cal = rng.negative_binomial(4, 4 / (4 + scale)).astype(float)  # var = mean + mean^2/4
    y_new = rng.negative_binomial(4, 4 / (4 + scale)).astype(float)
    q = conformal_quantiles(y_cal, scale, 0.8)
    covered = np.abs(y_new - scale) <= np.asarray(q)[pred_bin(scale)]
    busy = scale == 80.0
    # continuous-ish, high-volume bands land close to nominal
    assert covered[busy].mean() == pytest.approx(0.8, abs=0.05)
    assert covered[scale == 15.0].mean() == pytest.approx(0.8, abs=0.05)
    # counts near zero are discrete, so the guarantee is "at least nominal" (conservative)
    assert covered[scale == 0.3].mean() >= 0.78
    assert covered.mean() >= 0.78
    # a single pooled quantile is dominated by the busy bands' spread and fails the quiet ones,
    # and its coverage is uneven across bands: that is what banding removes
    pooled = float(np.quantile(np.abs(y_cal - scale), 0.8, method="higher"))
    pooled_cov = {v: (np.abs(y_new - scale) <= pooled)[scale == v].mean() for v in (0.3, 80.0)}
    assert pooled_cov[0.3] > 0.97 and pooled_cov[80.0] < 0.7


def test_sparse_band_falls_back_to_pooled_quantile() -> None:
    rng = np.random.default_rng(4)
    pred = np.concatenate([np.full(MIN_BIN_ROWS * 5, 3.0), np.full(10, 200.0)])
    y = pred + rng.normal(0, 2, size=len(pred))
    q = conformal_quantiles(y, pred, 0.8)
    assert len(q) == len(PRED_BIN_EDGES) + 1
    assert q[pred_bin(np.array([200.0]))[0]] == pytest.approx(
        np.quantile(np.abs(y - pred), 0.8, method="higher"), rel=0.02
    )


def test_conformal_rejects_bad_input() -> None:
    with pytest.raises(ValueError):
        conformal_quantiles(np.array([1.0]), np.array([1.0]), 1.5)
    with pytest.raises(ValueError):
        conformal_quantiles(np.array([]), np.array([]), 0.8)
