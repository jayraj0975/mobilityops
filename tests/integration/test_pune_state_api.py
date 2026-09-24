"""The Pune state API and its event stream, over a store filled by a real worker tick."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from mobilityops.api.app import create_app
from mobilityops.config import Settings
from mobilityops.forecasting.evaluate import train_final
from mobilityops.live.hub import LiveBusy
from mobilityops.pune import build as pb
from mobilityops.pune.hub import StateHub
from mobilityops.pune.state import StateService
from mobilityops.pune.store import StateStore
from mobilityops.pune.worker import Worker
from tests.integration.test_pune_worker import NOW, WINDOW, FakeOpenMeteo, _weather_frame

HEADERS: dict[str, str] = {}


@pytest.fixture(scope="module")
def settings(tmp_path_factory: pytest.TempPathFactory) -> Settings:
    root = tmp_path_factory.mktemp("pune_api")
    s = Settings.from_env({"MOBILITYOPS_DATA_DIR": str(root / "data"), "MOBILITYOPS_MODE": "pune"})
    pb.build_pune(s, WINDOW, weather=_weather_frame())
    train_final(s)
    store = StateStore(s.state_path)
    client = httpx.Client(transport=httpx.MockTransport(FakeOpenMeteo()))
    Worker(s, store, client, clock=lambda: NOW).tick(mono=0.0)
    return s


@pytest.fixture()
def client(settings: Settings) -> TestClient:
    app = create_app(settings)
    app.state.state_provider.clock = lambda: NOW
    return TestClient(app)


def test_geometry_is_static_attributed_and_complete(client: TestClient) -> None:
    body = client.get("/api/v1/state/geometry").json()
    assert body["city"] == "Pune" and len(body["zones"]) == 91
    assert "OpenStreetMap" in body["attribution"] and "ODbL" in body["licence"]
    assert "not an administrative boundary" in body["method"]
    assert all(len(z["ring"]) >= 3 for z in body["zones"])


def test_snapshot_now_is_labelled_and_complete(client: TestClient) -> None:
    r = client.get("/api/v1/state/snapshot")
    assert r.status_code == 200
    assert "SIMULATED" in r.headers["x-data-label"] and r.headers["x-data-mode"] == "pune"
    d = r.json()
    assert d["demand_class"] == "SIMULATED" and "SIMULATED" in d["data_label"]
    assert d["city"] == "Pune" and d["timezone"] == "Asia/Kolkata" and d["selector"] == "now"
    assert len(d["zones"]) == 91 and d["totals"]["forecast"] > 0 and d["totals"]["actual"] > 0
    assert d["window_start"].startswith("2026-09-24T21:00") and d["window_end"].startswith(
        "2026-09-24T21:17"
    )
    assert d["freshness"] == "LIVE" and d["worker"]["freshness"] == "LIVE"
    env = d["environment"]
    assert env["temperature"]["value"] == 23.8 and env["temperature"]["modelled"] is True
    assert env["us_aqi"]["freshness"] == "LIVE" and "Open-Meteo" in env["attribution"]
    assert d["forecast_model"] and d["forecast_made_at"]
    z0 = d["zones"][0]
    assert z0["lo"] <= z0["forecast"] <= z0["hi"] and z0["status"] == "normal"


@pytest.mark.parametrize(
    ("at", "starts", "has_actual"),
    [
        ("now", "2026-09-24T21:00", True),
        ("-15m", "2026-09-24T21:00", True),  # 21:02: still the 21:00 hour
        ("-1h", "2026-09-24T20:00", True),
        ("-6h", "2026-09-24T15:00", True),
        ("today", "2026-09-24T00:00", True),
        ("forecast", "2026-09-24T22:00", False),
    ],
)
def test_every_time_selector_answers(
    client: TestClient, at: str, starts: str, has_actual: bool
) -> None:
    d = client.get(f"/api/v1/state/snapshot?at={at}").json()
    assert d["selector"] == at and d["window_start"].startswith(starts)
    assert (d["totals"]["actual"] is not None) == has_actual
    assert d["totals"]["forecast"] > 0 and d["window_note"]
    if not has_actual:
        assert all(z["actual"] is None and z["ratio"] is None for z in d["zones"])


def test_today_accumulates_and_forecast_looks_ahead(client: TestClient) -> None:
    now = client.get("/api/v1/state/snapshot?at=now").json()["totals"]
    today = client.get("/api/v1/state/snapshot?at=today").json()["totals"]
    assert today["actual"] > 20 * now["actual"] and today["forecast"] > 20 * now["forecast"]
    assert 0.5 < today["ratio"] < 1.6  # the day so far tracks its own forecast


def test_invalid_selector_is_a_validation_error(client: TestClient) -> None:
    r = client.get("/api/v1/state/snapshot?at=yesterday")
    assert r.status_code == 422 and r.json()["error"]["code"] == "validation_error"


def test_zone_detail_has_actual_against_a_forecast_range(client: TestClient) -> None:
    body = client.get("/api/v1/state/zones/5").json()
    assert body["id"] == 5 and body["name"] and body["sector"]
    series = body["series"]
    assert len(series) >= 30
    running = [p for p in series if p["partial"]]
    assert len(running) == 1 and running[0]["hour"].startswith("2026-09-24T21:00")
    future = [p for p in series if p["hour"] >= "2026-09-24T22:00"]
    assert future and all(p["actual"] is None and p["forecast"] is not None for p in future)
    past = [p for p in series if p["hour"] < "2026-09-24T21:00" and p["forecast"] is not None]
    assert past and all(
        p["actual"] is not None and p["lo"] <= p["forecast"] <= p["hi"] for p in past
    )
    assert body["today_actual"] > 0 and body["today_forecast"] > 0


def test_city_series_covers_the_past_and_the_forecast_hours(client: TestClient) -> None:
    body = client.get("/api/v1/state/series?back=30&ahead=6").json()
    series = body["series"]
    assert "wider than a true 80% range" in body["envelope_note"]
    assert len(series) >= 30 and sum(1 for p in series if p["partial"]) == 1
    past = [
        p
        for p in series
        if p["actual"] is not None and not p["partial"] and p["forecast"] is not None
    ]
    assert past and all(p["lo"] <= p["forecast"] <= p["hi"] for p in past)
    ahead = [p for p in series if p["hour"] >= "2026-09-24T22:00"]
    assert ahead and all(p["actual"] is None for p in ahead) and len(ahead) <= 6
    assert body["today_actual"] > 0 and abs(body["today_actual"] / body["today_forecast"] - 1) < 0.6
    assert client.get("/api/v1/state/series?back=0").status_code == 422


def test_unknown_zone_is_a_404(client: TestClient) -> None:
    r = client.get("/api/v1/state/zones/9999")
    assert r.status_code == 404 and r.json()["error"]["code"] == "no_data"
    assert client.get("/api/v1/state/zones/abc").status_code == 422


def test_an_event_marks_its_zone_in_the_snapshot(settings: Settings, client: TestClient) -> None:
    store = StateStore(settings.state_path)
    store.replace_events(
        "2026-09-24",
        [
            {
                "id": "e1", "zone_id": 5, "kind": "surge", "severity": "high",
                "start_ts": "2026-09-24T19:00:00", "end_ts": "2026-09-24T21:00:00",
                "actual": 300.0, "expected": 120.0, "score": 11.5,
                "detected_at": "2026-09-24T15:40:00+00:00", "explanation": "simulated surge",
            }
        ],
    )  # fmt: skip
    try:
        d = client.get("/api/v1/state/snapshot?at=today").json()
        z = next(z for z in d["zones"] if z["id"] == 5)
        assert z["status"] == "surge" and z["event_id"] == "e1"
        ev = client.get("/api/v1/state/events").json()
        assert ev[0]["zone"] and ev[0]["data_class"] == "SIMULATED" and ev[0]["severity"] == "high"
        # at NOW (21:17) the 19:00-21:00 event is over, so the zone is not flagged
        now = client.get("/api/v1/state/snapshot?at=now").json()
        assert next(z for z in now["zones"] if z["id"] == 5)["status"] == "normal"
    finally:
        store.replace_events("2026-09-24", [])


def test_sources_are_honest_about_what_is_connected(client: TestClient) -> None:
    src = {s["key"]: s for s in client.get("/api/v1/state/sources").json()}
    assert (
        src["open-meteo-forecast"]["freshness"] == "LIVE" and src["open-meteo-forecast"]["modelled"]
    )
    assert src["simulated-demand"]["data_class"] == "SIMULATED"
    for key in ("tomtom-traffic", "openaq", "pmpml-gtfs"):
        assert src[key]["freshness"] == "DISABLED" and src[key]["enabled"] is False
        assert src[key]["disabled_reason"]
    assert src["era5-archive"]["freshness"] == "NOT_PERIODIC"
    assert all(s["data_class"] != "LIVE" for s in src.values())
    assert all(s["licence"] for s in src.values())


def test_quality_centre_reports_the_database_and_source_health(client: TestClient) -> None:
    q = client.get("/api/v1/state/quality").json()
    db = q["database"]
    assert db["available"] and db["synthetic"] is True and db["days_behind"] == 0
    assert {c["status"] for c in db["checks"]} == {"PASS"} and len(db["checks"]) >= 6
    health = {h["key"]: h for h in q["health"]}
    assert (
        health["simulated-demand"]["runs_24h"] >= 1
        and health["simulated-demand"]["success_rate_24h"] == 1.0
    )
    assert q["runs"] and any("SIMULATED" in n for n in q["notes"])


def test_runs_can_be_filtered_by_source(client: TestClient) -> None:
    runs = client.get("/api/v1/state/runs?source=open-meteo-forecast&limit=5").json()
    assert runs and {r["source"] for r in runs} == {"open-meteo-forecast"}
    assert runs[0]["ok"] and runs[0]["records_ok"] == 36 and runs[0]["duration_ms"] >= 0
    assert client.get("/api/v1/state/runs?limit=0").status_code == 422


def test_when_the_worker_stops_everything_degrades_visibly(settings: Settings) -> None:
    app = create_app(settings)
    app.state.state_provider.clock = lambda: NOW + timedelta(hours=14)
    d = TestClient(app).get("/api/v1/state/snapshot").json()
    assert d["worker"]["freshness"] == "OFFLINE" and d["freshness"] == "OFFLINE"
    src = {s["key"]: s for s in d["sources"]}
    assert (
        src["open-meteo-forecast"]["freshness"] == "OFFLINE"
        and src["simulated-demand"]["freshness"] == "OFFLINE"
    )
    assert (
        d["environment"]["temperature"]["freshness"] == "OFFLINE"
    )  # values kept, marked not current
    assert d["environment"]["temperature"]["value"] == 23.8


def test_state_needs_the_worker_and_the_pune_mode(tmp_path: Path, settings: Settings) -> None:
    empty = Settings.from_env(
        {"MOBILITYOPS_DATA_DIR": str(tmp_path / "d"), "MOBILITYOPS_MODE": "pune"}
    )
    r = TestClient(create_app(empty)).get("/api/v1/state/snapshot")
    assert r.status_code == 503 and "worker" in r.json()["error"]["message"]
    sample = Settings.from_env(
        {"MOBILITYOPS_DATA_DIR": str(tmp_path / "s"), "MOBILITYOPS_MODE": "sample"}
    )
    r = TestClient(create_app(sample)).get("/api/v1/state/snapshot")
    assert r.status_code == 404 and "pune mode" in r.json()["error"]["message"]


def test_state_endpoints_require_the_api_key_when_one_is_set(settings: Settings) -> None:
    keyed = Settings.from_env(
        {
            "MOBILITYOPS_DATA_DIR": str(settings.data_dir),
            "MOBILITYOPS_MODE": "pune",
            "MOBILITYOPS_API_KEY": "k" * 20,
        }
    )
    app = create_app(keyed)
    app.state.state_provider.clock = lambda: NOW
    c = TestClient(app)
    assert c.get("/api/v1/state/snapshot").status_code == 401
    assert c.get("/api/v1/state/stream?limit=1").status_code == 401
    assert c.get("/api/v1/state/snapshot", headers={"X-API-Key": "k" * 20}).status_code == 200


def _events(text: str) -> list[tuple[str, dict, str]]:  # type: ignore[type-arg]
    out = []
    for block in text.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.splitlines() if ": " in line)
        if "event" in lines:
            out.append((lines["event"], json.loads(lines["data"]), lines["id"]))
    return out


def test_the_stream_starts_with_a_full_snapshot_then_updates(client: TestClient) -> None:
    with client.stream("GET", "/api/v1/state/stream?limit=3") as r:
        assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
        assert r.headers["cache-control"] == "no-cache" and r.headers["x-accel-buffering"] == "no"
        text = "".join(r.iter_text())
    events = _events(text)
    kinds = [k for k, _, _ in events]
    assert kinds[0] == "hello" and "snapshot" in kinds
    hello = events[0][1]
    assert (
        hello["available"]
        and len(hello["snapshot"]["zones"]) == 91
        and hello["heartbeat_seconds"] == 10.0
    )
    ids = [int(i) for _, _, i in events]
    assert ids == sorted(ids) and len(set(ids)) == len(ids)


def test_stream_status_reports_viewers(client: TestClient) -> None:
    s = client.get("/api/v1/state/stream/status").json()
    assert s["streams"] == 0 and s["max_streams"] == 32


# ---------------------------------------------------------------------------------- the hub
def _service(settings: Settings) -> StateService:
    return StateService(settings, StateStore(settings.state_path, read_only=True))


def test_hub_pushes_only_when_the_store_changes_and_heartbeats_otherwise(
    settings: Settings,
) -> None:
    async def scenario() -> tuple[list[str], list[str]]:
        svc = _service(settings)
        hub = StateHub(
            lambda: svc,
            poll_seconds=0.02,
            heartbeat_seconds=0.1,
            snapshot_every=60.0,
            clock=lambda: NOW,
        )
        viewer = hub.subscribe()
        first: list[str] = []
        await asyncio.sleep(0.35)
        while not viewer.queue.empty():
            first.append(viewer.queue.get_nowait()[0])
        StateStore(settings.state_path).set_kv("touch", 1)  # a write by the worker
        await asyncio.sleep(0.15)
        second: list[str] = []
        while not viewer.queue.empty():
            second.append(viewer.queue.get_nowait()[0])
        hub.unsubscribe(viewer)
        return first, second

    first, second = asyncio.run(scenario())
    assert first.count("snapshot") == 1 and first.count("heartbeat") >= 2  # quiet store: beats only
    assert "snapshot" in second  # a write triggers a new snapshot


def test_hub_caps_viewers_and_stops_its_poller_when_the_last_leaves(settings: Settings) -> None:
    async def scenario() -> None:
        hub = StateHub(lambda: _service(settings), max_streams=2, poll_seconds=0.05)
        a, b = hub.subscribe(), hub.subscribe()
        with pytest.raises(LiveBusy, match="2 live streams"):
            hub.subscribe()
        assert hub.streams == 2 and hub._task is not None
        hub.unsubscribe(a)
        assert hub._task is not None
        hub.unsubscribe(b)
        assert hub._task is None and hub.streams == 0

    asyncio.run(scenario())


def test_a_slow_viewer_loses_old_events_without_blocking_others(settings: Settings) -> None:
    async def scenario() -> tuple[int, int, int]:
        hub = StateHub(lambda: None, poll_seconds=10.0)
        slow, fast = hub.subscribe(), hub.subscribe()
        for i in range(60):
            hub.publish("snapshot", {"i": i})
            while not fast.queue.empty():
                fast.queue.get_nowait()
        depth, newest = slow.queue.qsize(), 0
        while not slow.queue.empty():
            newest = slow.queue.get_nowait()[1]["i"]
        hub.unsubscribe(slow)
        hub.unsubscribe(fast)
        return depth, newest, hub.dropped

    depth, newest, dropped = asyncio.run(scenario())
    assert depth == 20 and newest == 59 and dropped > 0


def test_hub_without_a_worker_says_so_instead_of_inventing_data() -> None:
    async def scenario() -> str:
        hub = StateHub(
            lambda: None, poll_seconds=0.05, clock=lambda: datetime(2026, 9, 24, tzinfo=UTC)
        )
        gen = hub.stream(limit=1)
        chunk = await gen.__anext__()
        await gen.aclose()
        return chunk

    ((kind, payload, _),) = _events(asyncio.run(scenario()))
    assert kind == "hello" and payload["available"] is False and payload["snapshot"] is None


def test_readiness_reports_the_worker_and_ignores_what_pune_does_not_run(
    settings: Settings,
) -> None:
    from datetime import UTC, datetime

    from mobilityops.pune.store import worker_alive

    c = TestClient(create_app(settings))
    body = c.get("/ready").json()
    assert set(body["components"]) >= {"database", "forecast_model", "live_worker"}
    assert body["components"]["optimization_backtest"] is False  # never run for Pune
    # the fixture's worker ticked at a fixed 2026 time, so against the real clock it is not alive
    assert body["components"]["live_worker"] is False and body["status"] == "degraded"
    assert worker_alive(settings.state_path, NOW) is True
    assert worker_alive(settings.state_path, NOW + timedelta(seconds=89)) is True
    assert worker_alive(settings.state_path, NOW + timedelta(seconds=91)) is False
    assert worker_alive(settings.state_path.with_name("missing.sqlite")) is False
    assert datetime.now(UTC).year >= 2026


def test_ready_is_ready_when_the_worker_is_alive(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("mobilityops.pune.store.worker_alive", lambda path, now=None: True)
    body = TestClient(create_app(settings)).get("/ready").json()
    assert body["status"] == "ready"


def test_state_endpoints_are_rate_limited(settings: Settings) -> None:
    limited = Settings.from_env(
        {
            "MOBILITYOPS_DATA_DIR": str(settings.data_dir),
            "MOBILITYOPS_MODE": "pune",
            "MOBILITYOPS_RATE_LIMIT": "5",
        }
    )
    app = create_app(limited)
    app.state.state_provider.clock = lambda: NOW
    c = TestClient(app)
    codes = [c.get("/api/v1/state/sources").status_code for _ in range(8)]
    assert codes[:5] == [200] * 5 and set(codes[5:]) == {429}
    r = c.get("/api/v1/state/snapshot")
    assert r.status_code == 429 and r.headers["retry-after"]
    assert c.get("/health").status_code == 200  # probes are never limited


def test_state_responses_carry_the_security_headers_and_no_cors_wildcard(
    client: TestClient,
) -> None:
    r = client.get("/api/v1/state/snapshot", headers={"Origin": "https://evil.example"})
    assert (
        r.headers["x-content-type-options"] == "nosniff" and r.headers["x-frame-options"] == "DENY"
    )
    assert r.headers["cache-control"] == "no-store" and r.headers["x-request-id"]
    assert "access-control-allow-origin" not in r.headers  # an unlisted origin gets no CORS grant
    with client.stream(
        "GET", "/api/v1/state/stream?limit=1", headers={"Origin": "https://evil.example"}
    ) as s:
        assert s.headers["x-content-type-options"] == "nosniff"
        assert "access-control-allow-origin" not in s.headers


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/state/zones/1%20OR%201=1",
        "/api/v1/state/zones/-1",
        "/api/v1/state/zones/99999999999999999999",
        "/api/v1/state/snapshot?at=now;DROP%20TABLE%20kv",
        "/api/v1/state/runs?source='%20OR%20'1'='1",
        "/api/v1/state/events?limit=1000000",
        "/api/v1/state/series?back=-5",
    ],
)
def test_hostile_input_is_rejected_or_harmless(
    client: TestClient, path: str, settings: Settings
) -> None:
    r = client.get(path)
    assert r.status_code in (200, 404, 422)
    assert r.status_code != 500 and "Traceback" not in r.text
    if r.status_code == 200:  # a filter that matches nothing returns nothing, it does not widen
        assert r.json() == []
    # and the store is intact
    assert StateStore(settings.state_path).version() > 0
