"""The Pune demand simulator: determinism, structure, reconciliation, honesty."""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest

from mobilityops.pune import simulate as sim
from mobilityops.pune.build import zone_frame

DAYS = sim.date_range(date(2026, 9, 7), date(2026, 9, 21))  # Mon 7 Sep .. Sun 20 Sep


@pytest.fixture(scope="module")
def model() -> sim.ZoneModel:
    return sim.build_model(zone_frame())


def _dry(days: list[date]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "hour_ts": pd.date_range(pd.Timestamp(days[0]), periods=len(days) * 24, freq="h"),
            "precipitation": 0.0,
        }
    )


def test_model_weights_and_destinations_are_proper_distributions(model: sim.ZoneModel) -> None:
    assert model.weight.sum() == pytest.approx(1.0)
    assert np.allclose(model.dropoff.sum(axis=1), 1.0)
    assert np.allclose(model.mix.sum(axis=1), 1.0)
    assert np.allclose(model.shape.mean(axis=1), 1.0)
    assert (model.fare_inr > 90).all()


def test_business_hubs_are_the_busiest_and_weights_are_not_flat(model: sim.ZoneModel) -> None:
    assert model.weight.max() / np.median(model.weight) > 3


def test_simulation_is_a_pure_function_of_seed_date_and_weather(model: sim.ZoneModel) -> None:
    a = sim.simulate_range(model, DAYS, _dry(DAYS), seed=1)
    b = sim.simulate_range(model, DAYS, _dry(DAYS), seed=1)
    c = sim.simulate_range(model, DAYS, _dry(DAYS), seed=2)
    assert a.equals(b) and not a.equals(c)


def test_a_day_is_the_same_alone_or_inside_a_longer_window(model: sim.ZoneModel) -> None:
    """The live worker builds today on its own; it must agree with the batch build."""
    long = sim.simulate_range(model, DAYS, _dry(DAYS), seed=5)
    one = sim.simulate_range(model, DAYS[3:4], _dry(DAYS[3:4]), seed=5)
    same_day = long[long["hour_ts"].dt.date == DAYS[3]].reset_index(drop=True)
    assert one.reset_index(drop=True).equals(same_day)


def test_dropoffs_reconcile_with_pickups_every_hour(model: sim.ZoneModel) -> None:
    df = sim.simulate_range(model, DAYS, _dry(DAYS), seed=3)
    by_hour = df.groupby("hour_ts")[["pickups", "dropoffs"]].sum()
    assert (by_hour["pickups"] == by_hour["dropoffs"]).all()
    assert (df[["pickups", "dropoffs", "revenue", "passengers"]] >= 0).all().all()


def test_weekend_demand_falls_in_business_zones(model: sim.ZoneModel) -> None:
    df = sim.simulate_range(model, DAYS, _dry(DAYS), seed=4)
    biz = model.zone_ids[np.argsort(-model.mix[:, 0])[:5]]
    d = df[df["location_id"].isin(biz)].assign(dow=lambda x: x["hour_ts"].dt.dayofweek)
    weekday = d[d["dow"] < 5].groupby(d["hour_ts"].dt.date)["pickups"].sum().mean()
    sunday = d[d["dow"] == 6].groupby(d["hour_ts"].dt.date)["pickups"].sum().mean()
    assert sunday < 0.6 * weekday


def test_rain_raises_demand_and_missing_rain_means_no_effect(model: sim.ZoneModel) -> None:
    day = DAYS[:1]
    dry = _dry(day)
    wet = dry.assign(precipitation=5.0)
    unknown = dry.assign(precipitation=np.nan)
    base = sim.simulate_range(model, day, dry, seed=6)["pickups"].sum()
    rain = sim.simulate_range(model, day, wet, seed=6)["pickups"].sum()
    nan = sim.simulate_range(model, day, unknown, seed=6)["pickups"].sum()
    assert rain > 1.2 * base and nan == base
    assert sim.rain_multiplier(np.array([100.0]))[0] == pytest.approx(1 + sim.RAIN_CAP)


def test_a_holiday_cuts_business_demand(model: sim.ZoneModel) -> None:
    ganesh = date(2026, 9, 14)  # Monday, public holiday in Maharashtra
    days = [date(2026, 9, 7), ganesh]
    df = sim.simulate_range(model, days, _dry(days), seed=8)
    biz = model.zone_ids[np.argsort(-model.mix[:, 0])[:5]]
    by_day = df[df["location_id"].isin(biz)].groupby(df["hour_ts"].dt.date)["pickups"].sum()
    assert by_day[ganesh] < 0.7 * by_day[date(2026, 9, 7)]


def test_planted_events_are_deterministic_late_and_recorded(model: sim.ZoneModel) -> None:
    days = sim.date_range(date(2026, 1, 1), date(2026, 4, 11))
    a = sim.plan_events(model, days, seed=1)
    assert a == sim.plan_events(model, days, seed=1)
    assert len(a) == 8 and {e.kind for e in a} == {"surge", "drop"}
    first_late = days[len(days) * 2 // 3].isoformat()
    assert all(e.date >= first_late for e in a)
    assert sim.plan_events(model, days[:10], seed=1) == []


def test_an_event_changes_only_its_zone_and_hours(model: sim.ZoneModel) -> None:
    day = DAYS[:1]
    z = int(model.zone_ids[0])
    ev = sim.Event(z, day[0].isoformat(), 18, 3, 3.0, "surge", "test")
    plain = sim.simulate_range(model, day, _dry(day), seed=9)
    hit = sim.simulate_range(model, day, _dry(day), seed=9, events=[ev])
    diff = plain.merge(hit, on=["location_id", "hour_ts"], suffixes=("_a", "_b"))
    changed = diff[diff["pickups_a"] != diff["pickups_b"]]
    assert set(changed["location_id"]) == {z}
    assert set(changed["hour_ts"].dt.hour) <= {18, 19, 20}


def test_model_card_states_the_caveat() -> None:
    card = sim.model_card()
    assert card["label"] == "SIMULATED DEMAND" and "assumptions" in card["caveat"]
    assert sim.sector(18.5204, 73.8567) == "Central"
