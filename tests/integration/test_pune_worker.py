"""The ingestion worker end to end, with recorded Open-Meteo responses instead of the network."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import numpy as np
import pandas as pd
import pytest

from mobilityops.config import Settings
from mobilityops.forecasting.evaluate import train_final
from mobilityops.pune import build as pb
from mobilityops.pune.freshness import Freshness, classify
from mobilityops.pune.store import StateStore
from mobilityops.pune.worker import Worker, weather_grid

NOW = datetime(2026, 9, 24, 15, 47, tzinfo=UTC)  # 21:17 Asia/Kolkata
WINDOW = (date(2026, 7, 1), date(2026, 9, 24))  # through yesterday


def _weather_frame() -> pd.DataFrame:
    hours = pd.date_range(
        pd.Timestamp(WINDOW[0]), pd.Timestamp(WINDOW[1]), freq="h", inclusive="left"
    )
    rng = np.random.default_rng(0)
    return pd.DataFrame(
        {
            "hour_ts": hours,
            "temperature_2m": 26.0,
            "precipitation": np.where(rng.random(len(hours)) < 0.05, 1.0, 0.0),
            "relative_humidity_2m": 80.0,
        }
    )


@pytest.fixture(scope="module")
def env(tmp_path_factory: pytest.TempPathFactory) -> Settings:
    """A small Pune database and a trained model, built once for the module."""
    root = tmp_path_factory.mktemp("pune")
    settings = Settings.from_env(
        {"MOBILITYOPS_DATA_DIR": str(root / "data"), "MOBILITYOPS_MODE": "pune"}
    )
    pb.build_pune(settings, WINDOW, weather=_weather_frame())
    train_final(settings)
    return settings


class FakeOpenMeteo:
    """Canned responses shaped like the real service; records calls and can be made to fail."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.fail: dict[str, int | str] = {}  # host -> HTTP status, or "junk" for invalid JSON

    def __call__(self, request: httpx.Request) -> httpx.Response:
        host = request.url.host
        self.calls.append(host)
        mode = self.fail.get(host)
        if isinstance(mode, int):
            return httpx.Response(mode)
        if mode == "junk":
            return httpx.Response(200, content=b"<html>not json</html>")
        params = request.url.params
        n = len(params["latitude"].split(","))
        if "current" in params:
            if host.startswith("air-quality"):
                cur = {
                    "time": "2026-09-24T21:00",
                    "interval": 3600,
                    "pm2_5": 21.2,
                    "pm10": 24.7,
                    "us_aqi": 117,
                }
            else:
                cur = {
                    "time": "2026-09-24T21:15",
                    "interval": 900,
                    "temperature_2m": 23.8,
                    "relative_humidity_2m": 87,
                    "precipitation": 0.0,
                    "wind_speed_10m": 11.6,
                }
            blocks = [{"current": cur} for _ in range(n)]
            return httpx.Response(200, json=blocks if n > 1 else blocks[0])
        hours = pd.date_range("2026-09-15", "2026-09-26 23:00", freq="h")
        return httpx.Response(
            200,
            json={
                "hourly": {
                    "time": [h.strftime("%Y-%m-%dT%H:%M") for h in hours],
                    "temperature_2m": [25.0] * len(hours),
                    "precipitation": [0.0] * len(hours),
                    "relative_humidity_2m": [80] * len(hours),
                }
            },
        )


def _worker(env: Settings, tmp_path: Path, fake: FakeOpenMeteo, clock: list[datetime]) -> Worker:
    settings = Settings.from_env(
        {"MOBILITYOPS_DATA_DIR": str(env.data_dir), "MOBILITYOPS_MODE": "pune"}
    )
    store = StateStore(tmp_path / "state.sqlite")
    client = httpx.Client(transport=httpx.MockTransport(fake))
    return Worker(settings, store, client, clock=lambda: clock[0])


def test_weather_grid_is_a_lattice_inside_the_study_area() -> None:
    grid = weather_grid((18.4, 73.7, 18.68, 74.02))
    assert len(grid) == 9 and len(set(grid)) == 9
    assert all(18.4 < lat < 18.68 and 73.7 < lon < 74.02 for lat, lon in grid)


def test_one_tick_fills_the_store_from_every_source(env: Settings, tmp_path: Path) -> None:
    fake, clock = FakeOpenMeteo(), [NOW]
    w = _worker(env, tmp_path, fake, clock)
    w.tick(mono=0.0)
    s = w.store
    runs = {r["source"]: r for r in s.runs(20)}
    assert {"open-meteo-forecast", "open-meteo-air-quality", "open-meteo-rain-hourly",
            "simulated-demand", "model-forecast"} <= set(runs)  # fmt: skip
    assert all(r["ok"] for r in runs.values())
    weather = s.latest_observations("open-meteo-forecast")
    assert len(weather) == 9 * 4 and all(o["modelled"] for o in weather)
    zh = s.zone_hours("2026-09-23T00:00:00", "2026-09-25T00:00:00")
    assert zh["hour_ts"].nunique() == 24 + 22 and int(zh["partial"].sum()) == 91
    fc = s.forecast("2026-09-24T00:00:00", "2026-09-25T00:00:00")
    assert len(fc) == 91 * 24 and (fc["lo"] <= fc["pred"]).all() and (fc["pred"] <= fc["hi"]).all()
    assert s.get_kv("forecast_meta")["model_id"]
    assert s.get_kv("worker")["last_tick_at"].startswith("2026-09-24T15:47")


def test_observed_at_and_received_at_are_kept_apart(env: Settings, tmp_path: Path) -> None:
    fake, clock = FakeOpenMeteo(), [NOW]
    w = _worker(env, tmp_path, fake, clock)
    w.tick(mono=0.0)
    row = w.store.latest_observations("open-meteo-forecast")[0]
    assert row["observed_at"].startswith("2026-09-24T15:45")  # 21:15 IST, from the source
    assert row["received_at"].startswith("2026-09-24T15:47")  # when we got it


def test_freshness_comes_from_the_source_time_not_from_us(env: Settings, tmp_path: Path) -> None:
    fake, clock = FakeOpenMeteo(), [NOW]
    w = _worker(env, tmp_path, fake, clock)
    w.tick(mono=0.0)
    st = w.store.source_status("open-meteo-forecast")
    assert classify(900, st["last_observed_at"], st["last_success_at"], NOW).state is Freshness.LIVE
    later = NOW + timedelta(hours=2)  # the worker keeps polling but the source repeats an old step
    assert classify(900, st["last_observed_at"], later, later).state is Freshness.STALE


def test_a_failing_source_is_recorded_and_does_not_stop_the_others(
    env: Settings, tmp_path: Path
) -> None:
    fake, clock = FakeOpenMeteo(), [NOW]
    fake.fail["air-quality-api.open-meteo.com"] = 503
    w = _worker(env, tmp_path, fake, clock)
    w.tick(mono=0.0)
    air = w.store.source_status("open-meteo-air-quality")
    assert air["consecutive_failures"] == 1 and "HTTP 503" in air["last_error"]
    assert w.store.latest_observations("open-meteo-air-quality") == []  # nothing was invented
    assert w.store.source_status("open-meteo-forecast")["consecutive_failures"] == 0
    assert w.store.zone_hours("2026-09-24T00:00:00", "2026-09-25T00:00:00").shape[0] > 0


def test_failures_back_off_and_recovery_resets(env: Settings, tmp_path: Path) -> None:
    fake, clock = FakeOpenMeteo(), [NOW]
    fake.fail["air-quality-api.open-meteo.com"] = 500
    w = _worker(env, tmp_path, fake, clock)
    air = next(j for j in w.jobs if j.source == "open-meteo-air-quality")
    w.tick(mono=0.0)
    assert air.next_at == 30.0  # first retry after 30 s, not a full hour
    n = len(fake.calls)
    w.tick(mono=10.0)  # not due yet: no new call to the air-quality host
    assert fake.calls.count("air-quality-api.open-meteo.com") == 1 and len(fake.calls) == n
    w.tick(mono=31.0)
    assert air.failures == 2 and air.next_at == 31.0 + 60.0
    for m in (100.0, 200.0, 400.0, 900.0):
        w.tick(mono=m)
    assert air.next_at - 900.0 <= 3600.0  # never longer than the source's own interval
    del fake.fail["air-quality-api.open-meteo.com"]
    w.tick(mono=5000.0)
    assert (
        air.failures == 0
        and w.store.source_status("open-meteo-air-quality")["consecutive_failures"] == 0
    )
    assert len(w.store.latest_observations("open-meteo-air-quality")) == 27


def test_invalid_json_is_an_error_not_a_crash(env: Settings, tmp_path: Path) -> None:
    fake, clock = FakeOpenMeteo(), [NOW]
    fake.fail["api.open-meteo.com"] = "junk"
    w = _worker(env, tmp_path, fake, clock)
    w.tick(mono=0.0)
    st = w.store.source_status("open-meteo-forecast")
    assert "invalid JSON" in st["last_error"]
    assert w.store.source_status("open-meteo-rain-hourly")["consecutive_failures"] == 1
    # demand still runs, using whatever rain history the worker already had (none: no rain effect)
    assert w.store.source_status("simulated-demand")["successes"] == 1


def test_a_bug_in_one_job_is_contained(
    env: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake, clock = FakeOpenMeteo(), [NOW]
    w = _worker(env, tmp_path, fake, clock)

    def boom(now: datetime) -> tuple[int, int]:
        raise RuntimeError("bug")

    w.jobs[1].fn = boom  # air quality
    w.tick(mono=0.0)
    st = w.store.source_status("open-meteo-air-quality")
    assert "internal error" in st["last_error"]
    assert w.store.source_status("simulated-demand")["successes"] == 1


def test_missing_model_is_reported_and_demand_still_flows(env: Settings, tmp_path: Path) -> None:
    fake, clock = FakeOpenMeteo(), [NOW]
    settings = Settings.from_env(
        {"MOBILITYOPS_DATA_DIR": str(tmp_path / "empty"), "MOBILITYOPS_MODE": "pune"}
    )
    settings.ensure_dirs()
    (settings.processed_dir).mkdir(parents=True, exist_ok=True)
    (settings.db_path).write_bytes((env.db_path).read_bytes())  # a database but no model
    store = StateStore(tmp_path / "s.sqlite")
    w = Worker(
        settings, store, httpx.Client(transport=httpx.MockTransport(fake)), clock=lambda: clock[0]
    )
    w.tick(mono=0.0)
    fc = store.source_status("model-forecast")
    assert fc["successes"] == 0 and fc["last_error"]
    assert store.source_status("simulated-demand")["successes"] == 1
    assert store.forecast("2026-09-24T00:00:00", "2026-09-25T00:00:00").empty


def test_future_rain_hours_are_forecasts_not_observations(env: Settings, tmp_path: Path) -> None:
    fake, clock = FakeOpenMeteo(), [NOW]
    w = _worker(env, tmp_path, fake, clock)
    w.tick(mono=0.0)
    rows = w.store.latest_observations("open-meteo-rain-hourly")
    series = w.store.observation_series(
        "open-meteo-rain-hourly", "precipitation", 24 * 30, NOW + timedelta(days=1)
    )
    assert (
        max(r["observed_at"] for r in series) <= "2026-09-24T15:30:00+00:00"
    )  # 21:00 IST at latest
    assert rows and all(r["data_class"] == "RECENT" for r in rows)
    assert w.rain["hour_ts"].max() >= pd.Timestamp("2026-09-26")  # kept for the demand model


def test_the_forecast_is_remade_when_the_day_changes(env: Settings, tmp_path: Path) -> None:
    fake, clock = FakeOpenMeteo(), [NOW]
    w = _worker(env, tmp_path, fake, clock)
    w.tick(mono=0.0)
    first = w.store.get_kv("forecast_meta")["made_at"]
    clock[0] = NOW + timedelta(minutes=5)
    w.tick(mono=70.0)
    assert w.store.get_kv("forecast_meta")["made_at"] == first  # same day: not recomputed
    clock[0] = datetime(2026, 9, 25, 3, 0, tzinfo=UTC)  # 08:30 next day
    w.tick(mono=200.0)
    assert w.store.get_kv("forecast_meta")["made_at"] != first
    fc = w.store.forecast("2026-09-25T00:00:00", "2026-09-26T00:00:00")
    assert len(fc) == 91 * 24  # tomorrow's tensor was extended with yesterday's simulated day


def test_live_days_extend_the_tensor_exactly_like_the_batch_build(env: Settings) -> None:
    from mobilityops.forecasting.features import load_demand
    from mobilityops.pune import live
    from mobilityops.pune import simulate as sim

    t = load_demand(env.db_path, env.city)
    model = sim.build_model(pb.zone_frame())
    rain = pd.DataFrame(
        {"hour_ts": pd.date_range("2026-09-20", periods=8 * 24, freq="h"), "precipitation": 0.0}
    )
    ext = live.extend_tensor(t, model, date(2026, 9, 27), rain, pb.SEED)
    assert ext.n_days == t.n_days + 3 and ext.days[-1] == pd.Timestamp("2026-09-26")
    assert np.array_equal(ext.y[:, : t.n_days, :], t.y)  # history untouched
    batch = sim.simulate_range(
        model,
        [date(2026, 9, 24)],
        rain,
        seed=pb.SEED,
        events=sim.events_for_day(model, date(2026, 9, 24), pb.SEED),
    )
    got = ext.y[:, t.n_days, :].ravel()
    assert np.array_equal(got, batch["pickups"].to_numpy())
    assert live.extend_tensor(t, model, date(2026, 9, 24), rain, pb.SEED) is t  # nothing missing


def _unused(_: Any) -> None:  # keeps the typing import honest for future tests
    return None


def test_the_loop_stops_at_once_when_asked(env: Settings, tmp_path: Path) -> None:
    """`docker stop` sends SIGTERM to a PID 1 that must exit on its own within seconds."""
    import threading
    import time

    fake, clock = FakeOpenMeteo(), [NOW]
    w = _worker(env, tmp_path, fake, clock)
    stop = threading.Event()
    ticks: list[int] = []
    real_tick = w.tick

    def counting_tick(mono: float | None = None) -> None:
        real_tick(mono)
        ticks.append(1)
        stop.set()  # a signal arrives during the first cycle

    w.tick = counting_tick  # type: ignore[method-assign]
    t = threading.Thread(target=w.run_forever, args=(stop,))
    started = time.monotonic()
    t.start()
    t.join(timeout=20)
    assert not t.is_alive() and ticks == [1]
    assert time.monotonic() - started < 15  # it did not sit out the 15 s wait
    assert w.store.get_kv("worker_started_at")
