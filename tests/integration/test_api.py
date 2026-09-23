"""HTTP API contract tests on the TEST / SYNTHETIC sample (via the in-process test client)."""

from __future__ import annotations

import dataclasses
import logging
import re

import pytest
from fastapi.testclient import TestClient

from mobilityops.anomaly.run import run_anomaly_detection
from mobilityops.api.app import MAX_BODY_BYTES, create_app
from mobilityops.config import Settings
from mobilityops.forecasting.evaluate import EvalConfig, run_evaluation, train_final
from mobilityops.optimization.run import run_backtest
from mobilityops.optimization.scenario import BacktestConfig

API = "/api/v1"
S, E = "2024-01-15", "2024-01-22"


@pytest.fixture(scope="module")
def settings(built_sample) -> Settings:  # type: ignore[no-untyped-def]
    """Sample env with every derived artifact generated (small, fast configs)."""
    st, _ = built_sample
    run_evaluation(st, oracle_experiment=False)
    train_final(
        st, EvalConfig(n_folds=1, fold_days=7, calib_days=7, params={"num_boost_round": 60})
    )
    run_anomaly_detection(st, injection=False)
    run_backtest(st, BacktestConfig(day_stride=6), sensitivity=False)
    return st


@pytest.fixture(scope="module")
def client(settings) -> TestClient:  # type: ignore[no-untyped-def]
    return TestClient(create_app(settings))


def error_code(r) -> str:  # type: ignore[no-untyped-def]
    body = r.json()
    assert set(body) == {"error"} and {"code", "message", "request_id"} <= set(body["error"])
    return str(body["error"]["code"])


# ------------------------------------------------------------------------- operations
def test_health_ready_and_meta(client: TestClient) -> None:
    assert client.get("/health").json() == {"status": "ok"}
    ready = client.get("/ready").json()
    assert ready["status"] == "ready" and all(ready["components"].values())
    meta = client.get(f"{API}/meta").json()
    assert meta["mode"] == "sample" and meta["synthetic"] is True
    assert meta["data_label"] == "TEST / SYNTHETIC DATA" and meta["n_zones"] == 12
    assert meta["llm_configured"] is False


def test_every_response_names_its_data_and_carries_security_headers(client: TestClient) -> None:
    for path in ("/health", f"{API}/meta", f"{API}/zones", f"{API}/nope"):
        r = client.get(path)
        assert r.headers["X-Data-Label"] == "TEST / SYNTHETIC DATA"
        assert r.headers["X-Data-Mode"] == "sample"
        assert r.headers["X-Content-Type-Options"] == "nosniff"
        assert r.headers["X-Frame-Options"] == "DENY"
        assert r.headers["Cache-Control"] == "no-store"


def test_request_id_is_echoed_when_safe_and_replaced_when_not(client: TestClient) -> None:
    ok = client.get("/health", headers={"X-Request-ID": "abc-123_XYZ"})
    assert ok.headers["X-Request-ID"] == "abc-123_XYZ"
    bad = client.get("/health", headers={"X-Request-ID": "x y\t<script>"})
    assert re.fullmatch(r"[0-9a-f]{32}", bad.headers["X-Request-ID"])
    assert client.get("/health").headers["X-Request-ID"]


def test_quality_reports(client: TestClient) -> None:
    stages = client.get(f"{API}/quality").json()
    assert [x["stage"] for x in stages] == ["bronze", "silver", "gold"]
    assert all(x["overall"] in ("PASS", "WARN") for x in stages)


# ------------------------------------------------------------------------------ zones
def test_zones_list_filter_search_and_unknown(client: TestClient) -> None:
    zones = client.get(f"{API}/zones").json()
    assert len(zones) == 12 and {"location_id", "zone", "borough"} <= set(zones[0])
    assert client.get(f"{API}/zones", params={"q": "zone 03"}).json()[0]["location_id"] == 3
    assert client.get(f"{API}/zones", params={"borough": "nowhere"}).json() == []
    assert client.get(f"{API}/zones/3").json()["location_id"] == 3
    r = client.get(f"{API}/zones/399")
    assert r.status_code == 404 and error_code(r) == "no_data"
    assert client.get(f"{API}/zones/0").status_code == 422


# ----------------------------------------------------------------------------- demand
def test_demand_series_daily_and_hourly(client: TestClient) -> None:
    r = client.get(f"{API}/demand/series", params={"start": S, "end": E, "grain": "day"})
    body = r.json()
    assert r.status_code == 200 and len(body["points"]) == 7 and body["zone_id"] is None
    h = client.get(
        f"{API}/demand/series",
        params={"start": S, "end": "2024-01-16", "grain": "hour", "zone_id": 3},
    ).json()
    assert len(h["points"]) == 24 and h["zone_name"] == "Sample Zone 03"


def test_demand_top_zones_profiles_and_comparisons(client: TestClient) -> None:
    top = client.get(f"{API}/demand/top-zones", params={"start": S, "end": E, "limit": 3}).json()
    assert len(top) == 3 and top[0]["value"] >= top[1]["value"] >= top[2]["value"]
    hp = client.get(f"{API}/demand/profile/hourly", params={"start": S, "end": E}).json()
    assert [p["hour_of_day"] for p in hp] == list(range(24))
    wp = client.get(f"{API}/demand/profile/weekday", params={"start": S, "end": E}).json()
    assert len(wp) == 7
    cmp = client.get(
        f"{API}/demand/compare",
        params={"a_start": S, "a_end": E, "b_start": E, "b_end": "2024-01-29"},
    ).json()
    assert cmp["equal_length"] is True and cmp["period_a"]["days"] == 7
    assert client.get(f"{API}/demand/growth", params={"end": E}).status_code == 200
    vol = client.get(f"{API}/demand/volatility", params={"start": S, "end": E, "zone_id": 3}).json()
    assert vol["zone_id"] == 3 and vol["days"] == 7
    conc = client.get(f"{API}/demand/concentration", params={"start": S, "end": E}).json()
    assert 0 < conc["top_n_share"] <= 1


def test_weather_comparison_always_carries_its_caveat(client: TestClient) -> None:
    w = client.get(
        f"{API}/demand/weather-comparison", params={"start": "2024-01-01", "end": "2024-02-20"}
    ).json()
    assert "does not show that the weather caused" in w["caveat"]
    assert (
        client.get(
            f"{API}/demand/weather-comparison", params={"start": S, "end": E, "condition": "lava"}
        ).status_code
        == 422
    )


def test_bad_demand_requests_get_the_unified_error_shape(client: TestClient) -> None:
    rev = client.get(f"{API}/demand/series", params={"start": E, "end": S})
    assert rev.status_code == 422 and error_code(rev) == "invalid_query"
    out = client.get(f"{API}/demand/series", params={"start": "1999-01-01", "end": "1999-02-01"})
    assert out.status_code in (404, 422)
    bad = client.get(f"{API}/demand/series", params={"start": S, "end": E, "grain": "minute"})
    assert bad.status_code == 422 and error_code(bad) == "validation_error"
    assert bad.json()["error"]["details"][0]["field"].endswith("grain")
    assert (
        client.get(
            f"{API}/demand/top-zones", params={"start": S, "end": E, "limit": 500}
        ).status_code
        == 422
    )
    assert (
        client.get(f"{API}/demand/series", params={"start": "notadate", "end": E}).status_code
        == 422
    )


def test_injection_style_input_is_rejected_or_harmless(client: TestClient) -> None:
    evil = "1; DROP TABLE fact_zone_hourly_demand; --"
    assert (
        client.get(
            f"{API}/demand/series", params={"start": S, "end": E, "zone_id": evil}
        ).status_code
        == 422
    )
    assert (
        client.get(
            f"{API}/demand/series", params={"start": S, "end": E, "metric": evil}
        ).status_code
        == 422
    )
    r = client.get(f"{API}/zones", params={"q": "' OR 1=1 --"})
    assert r.status_code == 200 and r.json() == []
    assert client.get(f"{API}/zones", params={"q": "x" * 200}).status_code == 422
    assert (
        client.get(f"{API}/demand/series", params={"start": S, "end": E}).status_code == 200
    )  # intact


# --------------------------------------------------------------------------- forecast
def test_forecast_documents(client: TestClient) -> None:
    perf = client.get(f"{API}/forecast/performance").json()
    assert perf["data_label"] == "TEST / SYNTHETIC DATA" and "lightgbm" in perf["overall"]
    model = client.get(f"{API}/forecast/model").json()
    assert model["data_label"] == "TEST / SYNTHETIC DATA" and "features" in model


def test_backtest_forecast_for_a_zone_day(client: TestClient) -> None:
    days = client.get(f"{API}/forecast/performance").json()["folds"][-1]["test_days"]
    r = client.get(f"{API}/forecast/backtest", params={"zone_id": 3, "date": days[1]})
    body = r.json()
    assert r.status_code == 200 and len(body["points"]) == 24
    assert all(
        p["lo"] <= p["forecast"] <= p["hi"] and p["actual"] is not None for p in body["points"]
    )
    assert "never saw this day" in body["note"]
    early = client.get(f"{API}/forecast/backtest", params={"zone_id": 3, "date": "2024-01-20"})
    assert early.status_code == 404 and "evaluation days" in early.json()["error"]["message"]
    assert (
        client.get(f"{API}/forecast/backtest", params={"zone_id": 399, "date": days[1]}).status_code
        == 404
    )


def test_next_day_forecast_city_and_zone(client: TestClient) -> None:
    city = client.get(f"{API}/forecast/next-day").json()
    assert len(city["points"]) == 24 and city["zone_id"] is None
    assert all(p["lo"] is None for p in city["points"]) and "cannot be added" in city["note"]
    assert city["nominal_coverage"] == 0.8 and city["target_date"] == "2024-02-26"
    z = client.get(f"{API}/forecast/next-day", params={"zone_id": 3}).json()
    assert len(z["points"]) == 24 and z["zone_name"] == "Sample Zone 03"
    assert all(p["lo"] <= p["forecast"] <= p["hi"] for p in z["points"])
    assert client.get(f"{API}/forecast/next-day", params={"zone_id": 399}).status_code == 404


# -------------------------------------------------------------------------- anomalies
def test_anomalies_list_filters_and_pagination(client: TestClient) -> None:
    page = client.get(f"{API}/anomalies").json()
    assert page["total"] == len(page["items"]) >= 1
    assert "planted ground truth" in page["accuracy_status"]
    first = page["items"][0]
    assert "not a cause" in first["explanation"] and first["context"] is not None
    only = client.get(f"{API}/anomalies", params={"direction": "drop"}).json()
    assert all(i["direction"] == "drop" for i in only["items"])
    one = client.get(f"{API}/anomalies", params={"limit": 1, "offset": 1}).json()
    assert len(one["items"]) <= 1 and one["total"] == page["total"]
    assert client.get(f"{API}/anomalies", params={"limit": 500}).status_code == 422
    assert client.get(f"{API}/anomalies", params={"severity": "catastrophic"}).status_code == 422
    assert client.get(f"{API}/anomalies", params={"zone_id": 5}).json()["total"] >= 1
    assert client.get(f"{API}/anomalies/summary").json()["events_total"] == page["total"]


# ----------------------------------------------------------------------- optimization
def test_optimization_backtest_document_is_labelled(client: TestClient) -> None:
    doc = client.get(f"{API}/optimization/backtest").json()
    assert "SIMULATED" in doc["label"] and "planners" in doc


def _day(client: TestClient) -> str:
    return str(client.get(f"{API}/forecast/performance").json()["folds"][-1]["test_days"][1])


def test_scenario_feasible_and_infeasible(client: TestClient) -> None:
    day = _day(client)
    ok = client.post(f"{API}/optimization/scenario", json={"date": day}).json()
    assert ok["status"] in ("optimal", "feasible_time_limit") and "SIMULATED" in ok["label"]
    assert ok["service_share_after"] >= ok["service_share_before"] - 1e-9
    assert ok["assumptions"]["max_km"] == 6.0 and len(ok["moves"]) <= 25
    bad = client.post(
        f"{API}/optimization/scenario", json={"date": day, "min_service_share": 0.999}
    ).json()
    assert bad["status"] == "infeasible" and bad["best_attainable_service_share"] < 0.999


def test_scenario_input_validation(client: TestClient) -> None:
    day = _day(client)
    for body in (
        {"date": day, "start_hour": 20, "end_hour": 15},
        {"date": day, "coverage": 9},
        {"date": day, "max_km": 1000},
        {"date": day, "demand_multipliers": {"3": 99}},
        {"date": day, "demand_multipliers": {str(i): 1.0 for i in range(1, 30)}},
        {"date": day, "surprise": True},
        {"date": "not-a-date"},
    ):
        r = client.post(f"{API}/optimization/scenario", json=body)
        assert r.status_code == 422 and error_code(r) == "validation_error", body
    out = client.post(f"{API}/optimization/scenario", json={"date": "2024-01-20"})
    assert out.status_code == 422 and error_code(out) == "invalid_query"
    unk = client.post(
        f"{API}/optimization/scenario", json={"date": day, "demand_multipliers": {"999": 2}}
    )
    assert unk.status_code == 422 and "unknown zone" in unk.json()["error"]["message"]


def test_scenario_concurrency_is_capped(settings, client: TestClient) -> None:  # type: ignore[no-untyped-def]
    slots = client.app.state.services.solver_slots  # type: ignore[attr-defined]
    held = 0
    while slots.acquire(blocking=False):
        held += 1
    try:
        r = client.post(f"{API}/optimization/scenario", json={"date": _day(client)})
        assert r.status_code == 429 and error_code(r) == "busy"
    finally:
        for _ in range(held):
            slots.release()
    assert (
        client.post(f"{API}/optimization/scenario", json={"date": _day(client)}).status_code == 200
    )


# --------------------------------------------------------------------- robustness / auth
def test_oversized_body_is_refused(client: TestClient) -> None:
    r = client.post(
        f"{API}/optimization/scenario",
        content=b"{" + b" " * (MAX_BODY_BYTES + 10) + b"}",
        headers={"content-type": "application/json"},
    )
    assert r.status_code == 413 and error_code(r) == "payload_too_large"


def test_internal_errors_do_not_leak_details(settings) -> None:  # type: ignore[no-untyped-def]
    app = create_app(settings)

    def boom() -> None:
        raise RuntimeError("SECRET-INTERNAL-PATH /home/x/db")

    app.state.services.events = boom
    r = TestClient(app).get(f"{API}/anomalies")
    assert r.status_code == 500 and error_code(r) == "internal_error"
    assert "SECRET" not in r.text and "Traceback" not in r.text
    assert r.headers["X-Request-ID"] == r.json()["error"]["request_id"]


def test_api_key_protects_api_routes_but_not_probes(settings) -> None:  # type: ignore[no-untyped-def]
    secured = TestClient(create_app(dataclasses.replace(settings, api_key="s3cret-key")))
    assert secured.get("/health").status_code == 200
    r = secured.get(f"{API}/meta")
    assert r.status_code == 401 and error_code(r) == "http_error"
    assert secured.get(f"{API}/meta", headers={"X-API-Key": "wrong"}).status_code == 401
    assert secured.get(f"{API}/meta", headers={"X-API-Key": "s3cret-key"}).status_code == 200
    assert "s3cret-key" not in repr(dataclasses.replace(settings, api_key="s3cret-key"))


def test_cors_allows_only_configured_origins(client: TestClient) -> None:
    ok = client.options(
        f"{API}/meta",
        headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "GET"},
    )
    assert ok.headers.get("access-control-allow-origin") == "http://localhost:5173"
    evil = client.options(
        f"{API}/meta",
        headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "GET"},
    )
    assert "access-control-allow-origin" not in evil.headers


def test_not_ready_states_explain_what_to_run(sample_files, tmp_path) -> None:  # type: ignore[no-untyped-def]
    from mobilityops.ingestion.pipeline import ingest_sample
    from mobilityops.pipeline import build_all
    from tests.conftest import make_env

    st = make_env(tmp_path / "bare", sample_files)
    empty = TestClient(create_app(st))  # nothing built yet
    assert empty.get("/ready").status_code == 503
    r = empty.get(f"{API}/meta")
    assert (
        r.status_code == 503
        and error_code(r) == "not_ready"
        and "build" in r.json()["error"]["message"]
    )

    ingest_sample(st)
    build_all(st)  # database exists, but no forecasts / anomalies / backtest
    part = TestClient(create_app(st))
    assert part.get("/ready").json()["status"] == "degraded"
    assert part.get(f"{API}/meta").status_code == 200
    for path, hint in (
        ("/forecast/performance", "forecast-eval"),
        ("/forecast/next-day", "forecast-train"),
        ("/anomalies", "anomalies"),
        ("/optimization/backtest", "optimize-backtest"),
    ):
        r = part.get(API + path)
        assert r.status_code == 503 and hint in r.json()["error"]["message"], path


def test_openapi_documents_the_contract(client: TestClient) -> None:
    spec = client.get("/openapi.json").json()
    assert (
        "SIMULATED" in spec["info"]["description"]
        and "TEST / SYNTHETIC" in spec["info"]["description"]
    )
    paths = spec["paths"]
    assert (
        f"{API}/optimization/scenario" in paths and "post" in paths[f"{API}/optimization/scenario"]
    )
    assert len([p for p in paths if p.startswith(API)]) >= 20
    assert "ScenarioRequest" in spec["components"]["schemas"]


def test_requests_are_logged_with_structured_context(client: TestClient, caplog) -> None:  # type: ignore[no-untyped-def]
    with caplog.at_level(logging.INFO, logger="mobilityops.api"):
        client.get(
            f"{API}/zones", headers={"X-Request-ID": "trace-1", "X-API-Key": "should-not-log"}
        )
    rec = next(r for r in caplog.records if r.getMessage() == "request")
    ctx = rec.ctx  # type: ignore[attr-defined]
    assert ctx["request_id"] == "trace-1" and ctx["path"] == f"{API}/zones" and ctx["status"] == 200
    assert "should-not-log" not in str(ctx)
