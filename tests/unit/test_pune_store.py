"""The operational store: writes, reads, versioning, pruning, and read-only safety."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest

from mobilityops.pune.sources.base import Observation
from mobilityops.pune.store import StateStore

NOW = datetime(2026, 9, 24, 12, 0, tzinfo=UTC)


@pytest.fixture()
def store(tmp_path: Path) -> StateStore:
    return StateStore(tmp_path / "live" / "state.sqlite")


def _obs(
    metric: str = "temperature_2m", value: float = 24.0, at: datetime = NOW, **kw: object
) -> Observation:
    base: dict[str, object] = {
        "source": "open-meteo-forecast",
        "metric": metric,
        "value": value,
        "unit": "°C",
        "observed_at": at,
        "received_at": at + timedelta(seconds=3),
        "lat": 18.5,
        "lon": 73.8,
        "data_class": "NEAR-REAL-TIME",
        "modelled": True,
    }
    base.update(kw)
    return Observation(**base)  # type: ignore[arg-type]


def test_store_uses_wal_and_starts_at_version_zero(store: StateStore) -> None:
    with sqlite3.connect(store.path) as con:
        assert con.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert store.version() == 0


def test_every_write_bumps_the_version(store: StateStore) -> None:
    store.add_observations([_obs()])
    v1 = store.version()
    store.record_run("s", NOW, NOW, ok=True)
    store.set_kv("k", {"a": 1})
    assert store.version() == v1 + 2 and store.get_kv("k") == {"a": 1}
    assert store.get_kv("missing", "dflt") == "dflt"


def test_latest_observation_per_place_and_metric(store: StateStore) -> None:
    store.add_observations([_obs(value=20.0, at=NOW - timedelta(minutes=15)), _obs(value=21.0)])
    store.add_observations([_obs(value=30.0, lat=18.6)])
    rows = store.latest_observations("open-meteo-forecast")
    assert sorted(r["value"] for r in rows) == [21.0, 30.0]
    assert all(r["modelled"] == 1 and r["data_class"] == "NEAR-REAL-TIME" for r in rows)


def test_observation_carries_both_clocks(store: StateStore) -> None:
    store.add_observations([_obs()])
    row = store.latest_observations()[0]
    assert row["observed_at"] != row["received_at"]  # observed_at is not received_at


def test_source_status_tracks_failures_since_the_last_success(store: StateStore) -> None:
    t = NOW
    store.record_run("src", t, t + timedelta(seconds=1), ok=True, records_in=9, records_ok=9)
    for i in range(3):
        store.record_run("src", t, t + timedelta(seconds=2 + i), ok=False, error=f"boom {i}")
    st = store.source_status("src")
    assert st["consecutive_failures"] == 3 and st["last_error"] == "boom 2"
    assert st["last_success_at"] == t + timedelta(seconds=1) and st["successes"] == 1
    store.record_run("src", t, t + timedelta(seconds=9), ok=True)
    again = store.source_status("src")
    assert again["consecutive_failures"] == 0 and again["last_error"] is None


def test_computed_sources_use_their_asof_marker(store: StateStore) -> None:
    store.set_asof("simulated-demand", NOW)
    assert store.source_status("simulated-demand")["last_observed_at"] == NOW
    assert store.source_status("never-seen")["last_observed_at"] is None


def test_zone_hours_and_forecast_round_trip(store: StateStore) -> None:
    hours = pd.date_range("2026-09-24 20:00", periods=2, freq="h")
    frame = pd.DataFrame(
        {
            "location_id": [1, 1, 2, 2],
            "hour_ts": list(hours) * 2,
            "pickups": [5, 6, 7, 8],
            "dropoffs": [4, 4, 4, 4],
        }
    )
    store.put_zone_hours(frame, partial_hour=hours[1].isoformat(), now=NOW)
    got = store.zone_hours("2026-09-24T00:00:00", "2026-09-25T00:00:00")
    assert len(got) == 4 and int(got["partial"].sum()) == 2 and got["pickups"].sum() == 26
    store.put_zone_hours(frame.assign(pickups=[1, 1, 1, 1]), partial_hour=None, now=NOW)
    assert store.zone_hours("2026-09-24T00:00:00", "2026-09-25T00:00:00")["pickups"].sum() == 4
    fc = pd.DataFrame(
        {
            "location_id": [1, 1],
            "hour_ts": list(hours),
            "pred": [5.0, 6.0],
            "lo": [3.0, 4.0],
            "hi": [8.0, 9.0],
        }
    )
    store.put_forecast(fc, "m1", NOW)
    out = store.forecast("2026-09-24T00:00:00", "2026-09-25T00:00:00")
    assert out["model_id"].unique().tolist() == ["m1"] and out["hi"].tolist() == [8.0, 9.0]


def test_events_are_replaced_per_day(store: StateStore) -> None:
    def ev(i: str, start: str) -> dict:  # type: ignore[type-arg]
        return {
            "id": i, "zone_id": 1, "kind": "surge", "severity": "low", "start_ts": start,
            "end_ts": start, "actual": 10.0, "expected": 5.0, "score": 6.0, "detected_at": "x",
            "explanation": "e",
        }  # fmt: skip

    store.replace_events("2026-09-23", [ev("a", "2026-09-23T18:00:00")])
    store.replace_events(
        "2026-09-24", [ev("b", "2026-09-24T18:00:00"), ev("c", "2026-09-24T19:00:00")]
    )
    assert {e["id"] for e in store.events()} == {"a", "b", "c"}
    store.replace_events("2026-09-24", [ev("d", "2026-09-24T20:00:00")])
    assert {e["id"] for e in store.events()} == {"a", "d"}


def test_prune_drops_old_rows_but_keeps_recent_ones(store: StateStore) -> None:
    store.add_observations([_obs(at=NOW - timedelta(days=30)), _obs(at=NOW)])
    store.prune(NOW)
    assert len(store.latest_observations()) == 1
    with sqlite3.connect(store.path) as con:
        assert con.execute("SELECT count(*) FROM observation").fetchone()[0] == 1


def test_read_only_connections_cannot_write(store: StateStore) -> None:
    store.set_kv("k", 1)
    reader = StateStore(store.path, read_only=True)
    assert reader.get_kv("k") == 1
    with pytest.raises(sqlite3.OperationalError, match="readonly"):
        reader.set_kv("k", 2)
    assert store.get_kv("k") == 1


def test_a_reader_sees_writes_made_after_it_opened(store: StateStore) -> None:
    reader = StateStore(store.path, read_only=True)
    v = reader.version()
    store.record_run("s", NOW, NOW, ok=True)
    assert reader.version() == v + 1


def test_observation_series_averages_places(store: StateStore) -> None:
    store.add_observations([_obs(value=20.0), _obs(value=30.0, lat=18.6)])
    series = store.observation_series(
        "open-meteo-forecast", "temperature_2m", 3, NOW + timedelta(hours=1)
    )
    assert series and series[0]["value"] == 25.0
