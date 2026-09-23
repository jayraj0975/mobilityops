"""Anomaly detector behaviour on residuals with known structure."""

from __future__ import annotations

import re

import numpy as np
import pandas as pd
import pytest

from mobilityops.anomaly.detect import (
    AnomalyConfig,
    Series,
    _long_weekend,
    detect_events,
    fit_null,
    fit_scale,
    run_detection,
    score,
    severity,
)
from mobilityops.anomaly.run import accuracy_status
from mobilityops.anomaly.validate import InjectionSpec, injection_experiment
from tests.unit.test_forecast_features import make_tensor

CFG = AnomalyConfig()
LEVELS = (3.0, 15.0, 60.0, 200.0)


def make_preds(
    n_days: int = 30, seed: int = 0, noise: float = 0.25, levels: tuple[float, ...] = LEVELS
) -> pd.DataFrame:
    """Forecast = level * smooth daily profile; actual = forecast + noise proportional to sqrt."""
    rng = np.random.default_rng(seed)
    hours = np.arange(24)
    profile = 0.6 + 0.4 * np.sin((hours - 6) / 24 * 2 * np.pi)
    rows = []
    for z, level in enumerate(levels):
        pred = np.tile(level * profile, n_days)
        sd = noise * np.sqrt(pred * 5 + 1)  # error grows with demand, as in real data
        y = np.maximum(np.rint(pred + rng.normal(0, sd)), 0)
        day = np.repeat(np.arange(n_days), 24)
        hour = np.tile(hours, n_days)
        rows.append(
            pd.DataFrame(
                {
                    "fold": 0,
                    "zone_index": z,
                    "location_id": z + 1,
                    "day_index": day + 14,
                    "hour": hour,
                    "y": y,
                    "lightgbm": pred,
                }
            )
        )
    df = pd.concat(rows, ignore_index=True)
    base = pd.Timestamp("2024-01-01") + pd.to_timedelta(df["day_index"], unit="D")
    df["hour_ts"] = base + pd.to_timedelta(df["hour"], unit="h")
    return df


def plant(df: pd.DataFrame, zone: int, day: int, start: int, hours: int, factor: float) -> None:
    m = (df["zone_index"] == zone) & (df["day_index"] == day + 14)
    m &= df["hour"].between(start, start + hours - 1)
    df.loc[m, "y"] = np.rint(df.loc[m, "y"] * factor)


def pipeline(df: pd.DataFrame, cfg: AnomalyConfig = CFG):  # type: ignore[no-untyped-def]
    resid = (df["y"] - df["lightgbm"]).to_numpy()
    scale = fit_scale(df["lightgbm"].to_numpy(), resid, cfg)
    scored = score(df, scale)
    series = Series(scored)
    null = fit_null(series, cfg)
    return detect_events(scored, cfg, series, null), scored, scale, null, series


# ------------------------------------------------------------------------------- scale
def test_scale_recovers_the_known_spread_at_each_demand_level() -> None:
    rng = np.random.default_rng(1)
    pred = np.repeat([5.0, 30.0, 150.0], 5000)
    resid = rng.normal(0, 0.3 * pred)
    scale = fit_scale(pred, resid, AnomalyConfig())
    got = scale(np.array([5.0, 30.0, 150.0]))
    # the lowest level is lifted by the 1-pickup floor; the others track 0.3 * forecast
    assert got[0] == pytest.approx(max(1.5, 1.0), rel=0.1)
    assert got[1] == pytest.approx(9.0, rel=0.12)
    assert got[2] == pytest.approx(45.0, rel=0.12)


def test_scale_never_falls_below_the_floor() -> None:
    rng = np.random.default_rng(2)
    pred = np.full(4000, 0.2)
    scale = fit_scale(pred, rng.normal(0, 0.01, 4000), AnomalyConfig(min_scale=1.0))
    assert scale(np.array([0.0, 0.2, 0.4])).min() >= 1.0


def test_scale_uses_tail_not_only_the_median() -> None:
    """Heavy tails must widen the scale (a MAD-only scale would ignore them and over-flag)."""
    rng = np.random.default_rng(3)
    pred = np.full(20000, 50.0)
    normal = rng.normal(0, 8, 20000)
    heavy = rng.standard_t(2.5, 20000) * 8 * 0.6
    s_norm = fit_scale(pred, normal, AnomalyConfig())(np.array([50.0]))[0]
    s_heavy = fit_scale(pred, heavy, AnomalyConfig())(np.array([50.0]))[0]
    mad_heavy = 1.4826 * np.median(np.abs(heavy - np.median(heavy)))
    assert s_norm == pytest.approx(8.0, rel=0.1)
    assert s_heavy > 1.3 * mad_heavy


# --------------------------------------------------------------------- series and null
def test_series_span_sums_match_direct_computation() -> None:
    df = make_preds()
    _, scored, _, _, series = pipeline(df)
    z, start, end = 2, 14 * 24 + 100, 14 * 24 + 108
    sub = scored[(scored["zone_index"] == z)].sort_values(["day_index", "hour"])
    abs_hour = sub["day_index"] * 24 + sub["hour"]
    inside = sub[(abs_hour >= start) & (abs_hour < end)]
    r, v = series.span(z, start, end)
    assert r == pytest.approx(inside["residual"].sum())
    assert v == pytest.approx((inside["scale"] ** 2).sum())


def test_null_spread_is_about_one_for_independent_errors_and_grows_when_correlated() -> None:
    n_zones, n_days = 40, 60
    rng = np.random.default_rng(5)
    rows = []
    for rho, name in ((0.0, "iid"), (0.7, "ar1")):
        parts = []
        for z in range(n_zones):
            e = np.zeros(n_days * 24)
            eps = rng.normal(0, 1, n_days * 24)
            for i in range(1, len(e)):
                e[i] = rho * e[i - 1] + np.sqrt(1 - rho**2) * eps[i]
            pred = np.full(n_days * 24, 50.0)
            parts.append(
                pd.DataFrame(
                    {
                        "zone_index": z,
                        "location_id": z + 1,
                        "day_index": np.repeat(np.arange(n_days), 24),
                        "hour": np.tile(np.arange(24), n_days),
                        "y": pred + 8 * e,
                        "lightgbm": pred,
                    }
                )
            )
        rows.append((name, pd.concat(parts, ignore_index=True)))
    out = {}
    for name, df in rows:
        scored = score(
            df, fit_scale(df["lightgbm"].to_numpy(), (df["y"] - df["lightgbm"]).to_numpy(), CFG)
        )
        null = fit_null(Series(scored), CFG)
        out[name] = (null(1), null(6), null(24))
    assert out["iid"][0] == pytest.approx(1.0, abs=0.1)
    assert out["iid"][2] == pytest.approx(1.0, abs=0.2)
    assert out["ar1"][2] > 2.0 * out["iid"][2]  # correlated errors => wider null for long runs
    assert out["ar1"][0] <= out["ar1"][1] <= out["ar1"][2]  # never shrinks as runs lengthen


# -------------------------------------------------------------------------- detection
def test_planted_surge_and_drop_are_found_and_nothing_else() -> None:
    df = make_preds(n_days=30)
    plant(df, zone=3, day=20, start=17, hours=5, factor=3.0)  # busy zone surge
    plant(df, zone=2, day=22, start=8, hours=8, factor=0.15)  # sustained drop
    events, *_ = pipeline(df)
    assert len(events) == 2, events[["location_id", "direction", "start", "event_z"]]
    surge = events[events["direction"] == "surge"].iloc[0]
    drop = events[events["direction"] == "drop"].iloc[0]
    assert surge["location_id"] == 4 and drop["location_id"] == 3
    assert surge["event_z"] > 5 and drop["event_z"] < -5
    assert pd.Timestamp(surge["start"]).hour == 17 and pd.Timestamp(drop["start"]).hour in (8, 9)


def test_pure_noise_produces_no_events() -> None:
    events, *_ = pipeline(make_preds(n_days=40, seed=11))
    assert len(events) == 0


def test_a_sustained_drop_is_found_although_no_single_hour_is_extreme() -> None:
    """The reason evidence is pooled: a drop cannot exceed -forecast/scale in any one hour."""
    df = make_preds(n_days=30, noise=0.6)
    plant(df, zone=2, day=22, start=8, hours=8, factor=0.55)
    events, scored, *_ = pipeline(df)
    window = scored[(scored["zone_index"] == 2) & (scored["day_index"] == 22 + 14)]
    window = window[window["hour"].between(8, 15)]
    assert window["z"].abs().max() < 4.5  # no single hour is anywhere near a per-hour alarm
    drops = events[(events["direction"] == "drop") & (events["location_id"] == 3)]
    assert len(drops) == 1 and drops["event_z"].iloc[0] < -5


def test_small_absolute_deviations_are_dropped_by_min_excess() -> None:
    df = make_preds(n_days=30, levels=(0.4, 15.0))
    m = (df["zone_index"] == 0) & (df["day_index"] == 30) & (df["hour"] == 12)
    df.loc[m, "y"] = (
        9.0  # 9 pickups in a zone forecast at ~0.3: statistically extreme, tiny in size
    )
    lenient = AnomalyConfig(min_excess=1.0)
    strict = AnomalyConfig(min_excess=10.0)
    assert len(pipeline(df, lenient)[0]) >= 1
    assert len(pipeline(df, strict)[0]) == 0


def test_events_merge_across_midnight_and_do_not_merge_opposite_signs() -> None:
    df = make_preds(n_days=30)
    plant(df, zone=3, day=20, start=22, hours=2, factor=3.0)
    plant(df, zone=3, day=21, start=0, hours=3, factor=3.0)
    events, *_ = pipeline(df)
    surge = events[(events["direction"] == "surge") & (events["location_id"] == 4)]
    assert len(surge) == 1
    assert pd.Timestamp(surge["start"].iloc[0]).hour == 22
    assert pd.Timestamp(surge["end"].iloc[0]) > pd.Timestamp(surge["start"].iloc[0]) + pd.Timedelta(
        hours=4
    )

    df2 = make_preds(n_days=30)
    plant(df2, zone=3, day=20, start=10, hours=2, factor=3.0)
    plant(df2, zone=3, day=20, start=12, hours=2, factor=0.05)
    ev2, *_ = pipeline(df2)
    assert set(ev2[ev2["location_id"] == 4]["direction"]) <= {"surge", "drop"}
    assert not ((ev2["hours_span"] > 4) & (ev2["location_id"] == 4)).any()


def test_severity_bands() -> None:
    assert [severity(x) for x in (5.5, -9.0, 20.0)] == ["low", "medium", "high"]


# ------------------------------------------------------------------- language & context
def test_explanations_describe_coincidence_never_cause() -> None:
    df = make_preds(n_days=30)
    plant(df, zone=3, day=20, start=17, hours=5, factor=3.0)
    t = make_tensor(n_days=50, n_zones=4)
    events, *_ = run_detection(df, t, CFG)
    assert len(events) >= 1
    for text in events["explanation"]:
        assert "not a cause" in text
        assert not re.search(r"\b(caused|because|due to|led to|resulted|triggered)\b", text, re.I)
    ctx = " ".join(events["explanation"])
    assert "pickups" in ctx and "forecast" in ctx


def test_long_weekend_context_detected_only_next_to_a_holiday() -> None:
    t = make_tensor(n_days=45)  # 2024-01-01 ... MLK Day is Mon 2024-01-15
    idx = lambda d: int((pd.Timestamp(d) - t.days[0]).days)  # noqa: E731
    assert _long_weekend(t, idx("2024-01-13")) is True  # Saturday before
    assert _long_weekend(t, idx("2024-01-14")) is True  # Sunday before
    assert _long_weekend(t, idx("2024-01-20")) is False  # an ordinary weekend
    assert _long_weekend(t, idx("2024-01-17")) is False  # a weekday


def test_annotate_counts_overlapping_events_in_other_zones() -> None:
    df = make_preds(n_days=30)
    for z in (2, 3):
        plant(df, zone=z, day=20, start=17, hours=5, factor=3.0)
    t = make_tensor(n_days=50, n_zones=4)
    events, *_ = run_detection(df, t, CFG)
    both = events[events["location_id"].isin([3, 4])]
    assert len(both) == 2 and (both["overlapping_events"] == 1).all()
    assert all("other zone" in c for c in [" ".join(x) for x in both["context"]])


def test_accuracy_is_labelled_unverified_for_real_data() -> None:
    assert accuracy_status("real").startswith("UNVERIFIED")
    assert "planted ground truth" in accuracy_status("sample")


# ------------------------------------------------------------------------- injection
def test_injection_sensitivity_grows_with_size_and_is_not_trivially_one() -> None:
    df = make_preds(n_days=40, seed=4, levels=(60.0, 90.0, 200.0, 120.0))
    _, _, scale, null, _ = pipeline(df)
    spec = InjectionSpec(factors=(1.2, 3.0), durations=(3,), trials=60, seed=2)
    rows = pd.DataFrame(injection_experiment(df, scale, null, 4, 54, CFG, spec))
    by = rows.groupby("factor")["recall"].mean()
    assert by[3.0] > by[1.2]
    assert by[3.0] > 0.9 and by[1.2] < 0.5
