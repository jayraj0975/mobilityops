"""Real-time features: the replay, the live feeds (fake publisher), the hub and the API."""

from __future__ import annotations

import asyncio
import dataclasses
import itertools
import json
from typing import Any

import httpx
import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from mobilityops.anomaly.run import run_anomaly_detection
from mobilityops.api.app import create_app
from mobilityops.api.services import Services
from mobilityops.config import Settings
from mobilityops.forecasting.evaluate import run_evaluation
from mobilityops.live import feeds as feeds_mod
from mobilityops.live.feeds import LiveFeeds, summarize_citibike, summarize_weather
from mobilityops.live.hub import LiveBusy, LiveHub, Subscription, encode
from mobilityops.live.replay import Replay, ReplayUnavailable, build_replay


@pytest.fixture(scope="module")
def live_settings(built_sample) -> Settings:  # type: ignore[no-untyped-def]
    """Sample env with the held-out forecasts and anomaly events generated; fast replay clock."""
    st, _ = built_sample
    run_evaluation(st, oracle_experiment=False)
    run_anomaly_detection(st, injection=False)
    return dataclasses.replace(st, live_seconds_per_hour=0.05, live_feeds=False)


@pytest.fixture(scope="module")
def replay(live_settings: Settings) -> Replay:
    services = Services(live_settings)
    art = services.artifacts
    return build_replay(
        art / "forecast" / "predictions.parquet",
        services.analytics().zones(),
        art / "anomaly" / "events.parquet",
        seconds_per_hour=2.0,
        data_label=services.data_label,
    )


# ------------------------------------------------------------------------------- replay
def test_replay_ticks_carry_actual_forecast_and_a_running_accuracy(replay: Replay) -> None:
    t = replay.tick(10)
    assert t["kind"] == "replay" and t["index"] == 10 and t["of"] == replay.n
    assert t["actual"] == pytest.approx(float(replay.actual[10]))
    assert t["abs_error"] == pytest.approx(abs(t["forecast"] - t["actual"]))
    expected = float(
        np.abs(replay.forecast[:11] - replay.actual[:11]).sum() / replay.actual[:11].sum()
    )
    assert t["running_wape"] == pytest.approx(expected)
    assert "REPLAY" in t["label"] and "Not live taxi data" in t["label"]
    assert "SYNTHETIC" in t["label"]  # sample mode is labelled as such


def test_label_names_the_last_replayed_day_not_the_exclusive_end(replay: Replay) -> None:
    first, last = replay.hours[0], replay.hours[-1]
    assert f"{first:%Y-%m-%d} to {last:%Y-%m-%d}" in replay.label
    assert replay.meta()["end"] > last.isoformat()  # the machine-readable end stays exclusive


def test_replay_clock_is_shared_and_loops(replay: Replay) -> None:
    replay.t0 = 100.0
    sph = replay.seconds_per_hour
    assert replay.index_at(100.0) == 0
    assert replay.index_at(100.0 + 3.5 * sph) == 3
    assert replay.index_at(100.0 + replay.n * sph + 0.1) == 0  # wraps to the start
    assert replay.index_at(50.0) == 0  # before the origin never goes negative


def test_history_is_capped_and_ends_at_the_current_tick(replay: Replay) -> None:
    hist = replay.history(200, 48)
    assert len(hist) == 48 and hist[-1]["index"] == 200 and hist[0]["index"] == 153
    assert [h["index"] for h in replay.history(3, 48)] == [0, 1, 2, 3]


def test_top_zones_are_the_five_busiest_hours_zones(replay: Replay) -> None:
    for i in (0, replay.n // 2, replay.n - 1):
        top = replay.tick(i)["top_zones"]
        assert 1 <= len(top) <= 5
        assert [z["actual"] for z in top] == sorted((z["actual"] for z in top), reverse=True)


def test_anomalies_appear_on_exactly_the_hours_their_events_cover(
    live_settings: Settings, replay: Replay
) -> None:
    ev = pd.read_parquet(Services(live_settings).artifacts / "anomaly" / "events.parquet")
    if ev.empty:
        pytest.skip("no anomaly events in the sample")
    e = ev.iloc[0]
    hour = pd.Timestamp(e["start"])
    i = int(replay.hours.searchsorted(hour))
    assert any(a["zone"] == str(e["zone"]) for a in replay.tick(i)["anomalies"])
    total = sum(len(replay.tick(j)["anomalies"]) for j in range(replay.n))
    assert total >= 1


def test_replay_without_predictions_says_what_to_generate(tmp_path) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(ReplayUnavailable, match="forecast-eval"):
        build_replay(
            tmp_path / "nope.parquet",
            pd.DataFrame({"location_id": [], "zone": []}),
            None,
            seconds_per_hour=1.0,
            data_label="real data",
        )


# -------------------------------------------------------------------------------- feeds
def gbfs_status(stations: list[dict[str, Any]], updated: int = 1_780_000_000) -> dict[str, Any]:
    return {"last_updated": updated, "ttl": 60, "data": {"stations": stations}}


def st(i: str, bikes: int, docks: int, *, ebikes: int = 0, renting: int = 1) -> dict[str, Any]:
    return {
        "station_id": i,
        "num_bikes_available": bikes,
        "num_ebikes_available": ebikes,
        "num_docks_available": docks,
        "is_installed": 1,
        "is_renting": renting,
    }


INFO = {
    "data": {
        "stations": [
            {"station_id": "a", "name": "Alpha St", "capacity": 30},
            {"station_id": "b", "name": "Beta St", "capacity": 20},
            {"station_id": "c", "name": "Gamma St", "capacity": 40},
            {"station_id": "d", "name": "Delta St", "capacity": 10},
        ]
    }
}


def test_citibike_summary_counts_only_active_stations_and_ranks_by_capacity() -> None:
    status = gbfs_status(
        [
            st("a", 0, 30),  # empty, big
            st("b", 0, 20),  # empty, smaller
            st("c", 40, 0, ebikes=5),  # full
            st("d", 3, 7, ebikes=1, renting=0),  # offline: excluded from every count
        ]
    )
    s = summarize_citibike(status, INFO)
    assert (s["stations"], s["active"], s["offline"]) == (4, 3, 1)
    assert (s["bikes"], s["ebikes"], s["docks"]) == (40, 5, 50)
    assert (s["empty"], s["full"]) == (2, 1)
    assert [x["name"] for x in s["largest_empty"]] == ["Alpha St", "Beta St"]
    assert [x["name"] for x in s["largest_full"]] == ["Gamma St"]


def test_weather_summary_keeps_missing_values_as_none() -> None:
    obs = {
        "properties": {
            "timestamp": "2026-09-24T12:51:00+00:00",
            "textDescription": "Mostly Cloudy",
            "temperature": {"value": 21.7},
            "windSpeed": {"value": None},
            "relativeHumidity": {"value": 63.2},
            "precipitationLastHour": {"value": None},
        }
    }
    w = summarize_weather(obs)
    assert w["temperature_c"] == 21.7 and w["wind_kmh"] is None
    assert w["precipitation_last_hour_mm"] is None and w["description"] == "Mostly Cloudy"


class FakePublisher:
    def __init__(self) -> None:
        self.fail: set[str] = set()
        self.requests: list[str] = []
        self.status_bikes = 10

    def __call__(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        self.requests.append(url)
        assert "mobilityops" in request.headers["user-agent"]  # NWS requires an identifying agent
        assert "@" not in request.headers["user-agent"]  # and we never send a personal address
        for name in self.fail:
            if name in url:
                return httpx.Response(503)
        if url == feeds_mod.CITIBIKE_INFO_URL:
            return httpx.Response(200, json=INFO)
        if url == feeds_mod.CITIBIKE_STATUS_URL:
            return httpx.Response(200, json=gbfs_status([st("a", self.status_bikes, 5)]))
        if url == feeds_mod.NWS_URL:
            return httpx.Response(
                200,
                json={
                    "properties": {
                        "timestamp": "2026-09-24T12:51:00+00:00",
                        "temperature": {"value": 20.0},
                    }
                },
            )
        return httpx.Response(404)


def test_feeds_report_freshness_and_keep_history() -> None:
    pub = FakePublisher()

    async def go() -> LiveFeeds:
        async with httpx.AsyncClient(transport=httpx.MockTransport(pub)) as client:
            f = LiveFeeds(client)
            await f.poll_citibike(1_780_000_100.0)
            pub.status_bikes = 12
            await f.poll_citibike(1_780_000_160.0)
            await f.poll_weather(1_780_000_160.0)
            return f

    f = asyncio.run(go())
    assert f.citibike.status == "ok" and f.citibike.data is not None
    assert f.citibike.data["bikes"] == 12
    assert f.citibike.as_of is not None and f.citibike.as_of.startswith(
        "2026-"
    )  # the publisher's time
    assert [h["bikes"] for h in f.history] == [10, 12]
    assert f.weather.data is not None and f.weather.data["temperature_c"] == 20.0
    assert sum(1 for u in pub.requests if u == feeds_mod.CITIBIKE_INFO_URL) == 1  # cached


def test_a_failing_feed_keeps_its_last_good_data_and_says_so() -> None:
    pub = FakePublisher()

    async def go() -> LiveFeeds:
        async with httpx.AsyncClient(transport=httpx.MockTransport(pub)) as client:
            f = LiveFeeds(client)
            await f.poll_citibike(1_780_000_100.0)
            pub.fail.add("station_status")
            await f.poll_citibike(1_780_000_160.0)
            return f

    f = asyncio.run(go())
    assert f.citibike.status == "unavailable" and "503" in (f.citibike.error or "")
    assert f.citibike.data is not None and f.citibike.data["bikes"] == 10  # last good, not blanked
    assert len(f.history) == 1  # a failed poll adds no point


# --------------------------------------------------------------------------------- hub
def test_hub_streams_ticks_in_order_and_stops_its_tasks(live_settings: Settings) -> None:
    hub = LiveHub(live_settings, Services(live_settings))

    async def go() -> list[int]:
        events = []
        async for chunk in hub.stream(limit=6):
            events.append(chunk)
        assert hub._tasks == [] and hub.streams == 0  # the last viewer left: everything stopped
        return [
            json.loads(c.split("data: ", 1)[1])["index"]
            for c in events
            if c.startswith("event: replay")
        ]

    idx = asyncio.run(go())
    assert len(idx) == 5 and idx == sorted(idx)
    assert all(b - a in (1, 2) for a, b in itertools.pairwise(idx))  # consecutive hours


def test_hello_comes_first_with_recent_history_and_the_replay_label(
    live_settings: Settings,
) -> None:
    hub = LiveHub(live_settings, Services(live_settings))

    async def go() -> dict[str, Any]:
        async for chunk in hub.stream(limit=1):
            assert chunk.startswith("event: hello\n")
            return json.loads(chunk.split("data: ", 1)[1])  # type: ignore[no-any-return]
        raise AssertionError("no event")

    hello = asyncio.run(go())
    assert hello["replay"]["available"] is True and "REPLAY" in hello["replay"]["label"]
    assert hello["feeds"] == {"enabled": False}
    assert hello["data_label"] == "TEST / SYNTHETIC DATA"


def test_stream_cap_and_slow_viewer_handling(live_settings: Settings) -> None:
    capped = dataclasses.replace(live_settings, live_max_streams=1)
    hub = LiveHub(capped, Services(capped))

    async def go() -> None:
        first = hub.subscribe()
        with pytest.raises(LiveBusy):
            hub.subscribe()
        for i in range(250):  # a viewer that never reads only ever holds the newest events
            hub.publish("replay", {"i": i})
        assert first.queue.qsize() == 100
        assert first.queue.get_nowait()[1]["i"] == 150
        hub.unsubscribe(first)
        assert hub.streams == 0

    asyncio.run(go())


def test_encode_is_valid_server_sent_event_framing() -> None:
    text = encode("replay", {"a": 1})
    assert text == 'event: replay\ndata: {"a":1}\n\n'
    assert isinstance(Subscription().queue, asyncio.Queue)


# ---------------------------------------------------------------------------------- api
def sse_events(text: str) -> list[tuple[str, dict[str, Any]]]:
    out = []
    for block in text.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.splitlines() if ": " in line)
        if "event" in lines:
            out.append((lines["event"], json.loads(lines["data"])))
    return out


def test_api_status_snapshot_and_stream(live_settings: Settings) -> None:
    with TestClient(create_app(live_settings)) as client:
        status = client.get("/api/v1/live/status").json()
        assert status["replay_available"] is True and status["max_streams"] == 32
        snap = client.get("/api/v1/live/snapshot").json()
        assert snap["kind"] == "hello" and snap["replay"]["ticks"] > 24
        r = client.get("/api/v1/live/stream", params={"limit": 4})
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/event-stream")
        assert r.headers["cache-control"] == "no-cache"
        assert r.headers["x-data-label"] == "TEST / SYNTHETIC DATA"
        events = sse_events(r.text)
        assert events[0][0] == "hello" and [e[0] for e in events[1:]] == ["replay"] * 3
        assert all("REPLAY" in e[1]["label"] for e in events[1:])
        assert client.get("/api/v1/live/stream", params={"limit": 0}).status_code == 422


def test_api_reports_busy_with_retry_after(live_settings: Settings) -> None:
    capped = dataclasses.replace(live_settings, live_max_streams=1)
    app = create_app(capped)
    app.state.hub._subs.add(Subscription())  # one viewer already connected
    with TestClient(app) as client:
        r = client.get("/api/v1/live/stream", params={"limit": 1})
    assert r.status_code == 429 and r.json()["error"]["code"] == "busy"
    assert r.headers["retry-after"] == "5"


def test_without_forecast_artifacts_the_api_explains_instead_of_failing(tmp_path) -> None:  # type: ignore[no-untyped-def]
    s = Settings.from_env(
        {"MOBILITYOPS_DATA_DIR": str(tmp_path / "data"), "MOBILITYOPS_LIVE_FEEDS": "false"}
    )
    hub = LiveHub(s, Services(s))
    assert hub.replay() is None
    hello = hub.hello()
    assert hello["replay"]["available"] is False
    assert "ingest" in hello["replay"]["reason"]  # no database yet: say what to run first
    assert hub.status()["replay_available"] is False
