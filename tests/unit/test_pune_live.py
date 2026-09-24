"""Live logic: pro-rating, batch/live agreement, and the event rule."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import numpy as np
import pandas as pd
import pytest

from mobilityops.pune import live
from mobilityops.pune import simulate as sim
from mobilityops.pune.build import zone_frame

NOW = datetime(2026, 9, 24, 15, 47, tzinfo=UTC)  # 21:17 in Pune


@pytest.fixture(scope="module")
def model() -> sim.ZoneModel:
    return sim.build_model(zone_frame())


def _rain(days: int = 8) -> pd.DataFrame:
    hours = pd.date_range("2026-09-18", periods=days * 24, freq="h")
    return pd.DataFrame({"hour_ts": hours, "precipitation": np.where(hours.hour == 17, 2.0, 0.0)})


def test_local_time_is_naive_kolkata() -> None:
    assert live.local_naive(NOW) == datetime(2026, 9, 24, 21, 17)
    assert live.local_naive(datetime(2026, 9, 24, 19, 0, tzinfo=UTC)) == datetime(
        2026, 9, 25, 0, 30
    )


def test_hour_fraction_is_clamped() -> None:
    h = pd.Timestamp("2026-09-24 21:00")
    assert live.hour_fraction(h, pd.Timestamp("2026-09-24 21:15")) == 0.25
    assert live.hour_fraction(h, pd.Timestamp("2026-09-24 20:00")) == 0.0
    assert live.hour_fraction(h, pd.Timestamp("2026-09-24 23:00")) == 1.0


def test_recent_covers_yesterday_and_today_up_to_the_running_hour(model: sim.ZoneModel) -> None:
    frame, running = live.simulate_recent(model, NOW, _rain(), seed=1)
    assert running == "2026-09-24T21:00:00"
    hours = pd.DatetimeIndex(sorted(frame["hour_ts"].unique()))
    assert hours[0] == pd.Timestamp("2026-09-23 00:00") and hours[-1] == pd.Timestamp(
        "2026-09-24 21:00"
    )
    assert len(hours) == 24 + 22
    assert len(frame) == len(hours) * len(model.zone_ids)
    assert (frame[["pickups", "dropoffs"]] >= 0).all().all()


def test_the_live_worker_and_the_batch_build_agree_on_every_hour(model: sim.ZoneModel) -> None:
    """Same seed, date and rain give the same numbers whichever code path produced them."""
    rain = _rain()
    frame, _ = live.simulate_recent(model, NOW, rain, seed=7)
    days = [date(2026, 9, 23), date(2026, 9, 24)]
    batch = sim.simulate_range(model, days, rain, seed=7, events=sim.plan_events(model, days, 7))
    merged = frame.merge(batch, on=["location_id", "hour_ts"], suffixes=("_live", "_batch"))
    assert len(merged) == len(frame)
    assert (merged["pickups_live"] == merged["pickups_batch"]).all()
    assert (merged["dropoffs_live"] == merged["dropoffs_batch"]).all()


def test_rain_now_changes_the_hours_it_falls_in_and_nothing_else(model: sim.ZoneModel) -> None:
    dry = _rain().assign(precipitation=0.0)
    wet = dry.copy()
    wet.loc[wet["hour_ts"] == pd.Timestamp("2026-09-24 18:00"), "precipitation"] = 6.0
    a, _ = live.simulate_recent(model, NOW, dry, seed=3)
    b, _ = live.simulate_recent(model, NOW, wet, seed=3)
    by_hour = pd.DataFrame(
        {"a": a.groupby("hour_ts")["pickups"].sum(), "b": b.groupby("hour_ts")["pickups"].sum()}
    )
    changed = by_hour[by_hour["a"] != by_hour["b"]]
    assert (
        list(changed.index) == [pd.Timestamp("2026-09-24 18:00")]
        and changed["b"].iloc[0] > changed["a"].iloc[0]
    )


# ------------------------------------------------------------------------------- event rule
def _series(
    zone: int, base: float, factors: dict[int, float], day: str = "2026-09-24"
) -> tuple[pd.DataFrame, pd.DataFrame]:
    hours = pd.date_range(day, periods=20, freq="h")
    pred = np.full(20, base)
    act = np.array([round(base * factors.get(h, 1.0)) for h in range(20)], dtype=float)
    fc = pd.DataFrame(
        {"location_id": zone, "hour_ts": hours, "pred": pred, "lo": pred * 0.8, "hi": pred * 1.2}
    )
    ac = pd.DataFrame({"location_id": zone, "hour_ts": hours, "pickups": act})
    return ac, fc


NAMES = {1: "Shivajinagar", 2: "Kothrud"}


def test_a_sustained_surge_becomes_one_event() -> None:
    ac, fc = _series(1, 60.0, {16: 2.2, 17: 2.4, 18: 2.1})
    events = live.detect_live_events(ac, fc, NAMES, NOW)
    assert len(events) == 1
    e = events[0]
    assert e["zone_id"] == 1 and e["kind"] == "surge" and e["start_ts"].endswith("16:00:00")
    assert e["end_ts"].endswith("19:00:00") and e["actual"] > 2 * e["expected"] * 0.99
    assert "Shivajinagar" in e["explanation"] and "says nothing about a cause" in e["explanation"]
    assert e["severity"] in {"medium", "high"}


def test_a_sustained_drop_is_a_drop_event() -> None:
    ac, fc = _series(2, 80.0, {9: 0.3, 10: 0.25, 11: 0.3})
    (e,) = live.detect_live_events(ac, fc, NAMES, NOW)
    assert e["kind"] == "drop" and e["zone_id"] == 2


def test_ordinary_noise_produces_no_events() -> None:
    rng = np.random.default_rng(0)
    hours = pd.date_range("2026-09-24", periods=20, freq="h")
    pred = np.full(20, 60.0)
    ac = pd.DataFrame(
        {"location_id": 1, "hour_ts": hours, "pickups": rng.poisson(pred).astype(float)}
    )
    fc = pd.DataFrame({"location_id": 1, "hour_ts": hours, "pred": pred, "lo": 0, "hi": 0})
    assert live.detect_live_events(ac, fc, NAMES, NOW) == []


def test_a_single_hour_spike_is_not_an_event() -> None:
    ac, fc = _series(1, 60.0, {17: 3.0})
    assert live.detect_live_events(ac, fc, NAMES, NOW) == []


def test_a_run_broken_by_a_normal_hour_is_not_joined() -> None:
    ac, fc = _series(1, 60.0, {14: 2.5, 16: 2.5})
    assert live.detect_live_events(ac, fc, NAMES, NOW) == []


def test_low_volume_zones_are_ignored() -> None:
    ac, fc = _series(1, 3.0, {16: 5.0, 17: 5.0, 18: 5.0})
    assert live.detect_live_events(ac, fc, NAMES, NOW) == []


def test_the_running_hour_never_counts() -> None:
    """At 21:17 the 21:00 hour is unfinished; only 19:00 and 20:00 are complete."""
    ac, fc = _series(1, 60.0, {})
    ac.loc[ac["hour_ts"] == pd.Timestamp("2026-09-24 21:00"), "pickups"] = 500.0
    hours = pd.date_range("2026-09-24 19:00", periods=3, freq="h")
    ac = pd.concat(
        [ac, pd.DataFrame({"location_id": 1, "hour_ts": hours[1:], "pickups": [500.0, 500.0]})]
    )
    fc = pd.concat(
        [
            fc,
            pd.DataFrame(
                {"location_id": 1, "hour_ts": hours[1:], "pred": 60.0, "lo": 0.0, "hi": 0.0}
            ),
        ]
    )
    events = live.detect_live_events(
        ac.drop_duplicates(["location_id", "hour_ts"], keep="last"),
        fc.drop_duplicates(["location_id", "hour_ts"]),
        NAMES,
        NOW,
    )
    assert all(pd.Timestamp(e["end_ts"]) <= pd.Timestamp("2026-09-24 21:00") for e in events)


def test_empty_inputs_are_fine() -> None:
    empty = pd.DataFrame(columns=["location_id", "hour_ts", "pickups"])
    assert live.detect_live_events(empty, empty.assign(pred=1.0), NAMES, NOW) == []


def test_severity_bands() -> None:
    assert (
        live._severity(4.9) == "low"
        and live._severity(-7.0) == "medium"
        and live._severity(11) == "high"
    )


def test_planted_events_are_found_by_the_rule_on_simulated_demand(model: sim.ZoneModel) -> None:
    """End to end on the simulator: a planted surge is detected against the true expected value."""
    day = date(2026, 9, 24)
    z = int(model.zone_ids[int(np.argmax(model.weight))])
    ev = sim.Event(z, day.isoformat(), 14, 4, 2.5, "surge", "test")
    rain = _rain()
    pick = sim.simulate_day(model, day, np.zeros(24), False, 11, [ev])
    base = sim.simulate_day(model, day, np.zeros(24), False, 11, [])
    hours = pd.date_range(pd.Timestamp(day), periods=24, freq="h")
    act = pd.DataFrame(
        {
            "location_id": np.repeat(model.zone_ids, 24),
            "hour_ts": np.tile(hours, len(model.zone_ids)),
            "pickups": pick.ravel(),
        }
    )
    expected = pd.DataFrame(
        {
            "location_id": np.repeat(model.zone_ids, 24),
            "hour_ts": np.tile(hours, len(model.zone_ids)),
            "pred": base.ravel().astype(float),
            "lo": 0.0,
            "hi": 0.0,
        }
    )
    # forecast = the no-event mean; smooth the Poisson noise out by using the model's lambda proxy
    expected["pred"] = expected.groupby("location_id")["pred"].transform(
        lambda s: s.rolling(3, center=True, min_periods=1).mean()
    )
    late = datetime(2026, 9, 24, 19, 0, tzinfo=UTC) + timedelta(
        hours=0
    )  # 00:30 next day: day complete
    events = live.detect_live_events(act, expected, {int(i): str(i) for i in model.zone_ids}, late)
    assert any(e["zone_id"] == z and e["kind"] == "surge" for e in events)
    assert rain is not None
