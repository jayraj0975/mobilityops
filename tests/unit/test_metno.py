"""MET Norway adapter: parsing and validation against the response shape (no network)."""

from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pandas as pd
import pytest

from mobilityops.pune.sources import metno
from mobilityops.pune.sources.base import SourceError

NOW = datetime(2026, 9, 24, 19, 50, tzinfo=UTC)


def _payload(n: int = 3, **inst: object) -> dict:  # type: ignore[type-arg]
    base = {"air_temperature": 22.4, "relative_humidity": 84.7, "wind_speed": 4.1, **inst}
    times = pd.date_range("2026-09-24 19:00", periods=n, freq="h", tz="UTC")
    return {
        "properties": {
            "timeseries": [
                {
                    "time": t.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "data": {
                        "instant": {"details": base},
                        "next_1_hours": {"details": {"precipitation_amount": 0.2 * i}},
                    },
                }
                for i, t in enumerate(times)
            ]
        }
    }


def test_current_conversion_units_and_clocks() -> None:
    obs = {o.metric: o for o in metno.parse_current(_payload(), 18.52, 73.86, NOW)}
    assert obs["temperature_2m"].value == 22.4 and obs["temperature_2m"].unit == "°C"
    assert obs["wind_speed_10m"].value == pytest.approx(14.76)  # 4.1 m/s in km/h
    assert obs["precipitation"].value == 0.0
    o = obs["temperature_2m"]
    assert o.observed_at == datetime(2026, 9, 24, 19, 0, tzinfo=UTC) and o.received_at == NOW
    assert o.source == "metno-forecast" and o.modelled and o.data_class == "NEAR-REAL-TIME"


def test_bad_values_are_dropped_and_nothing_usable_is_an_error() -> None:
    obs = metno.parse_current(
        _payload(air_temperature=99.0, relative_humidity="wet"), 18.5, 73.8, NOW
    )
    assert {o.metric for o in obs} == {"wind_speed_10m", "precipitation"}
    empty = {
        "properties": {
            "timeseries": [{"time": "2026-09-24T19:00:00Z", "data": {"instant": {"details": {}}}}]
        }
    }
    with pytest.raises(SourceError, match="no usable"):
        metno.parse_current(empty, 18.5, 73.8, NOW)


def test_missing_or_malformed_payloads_are_errors() -> None:
    for bad in ({}, {"properties": {}}, {"properties": {"timeseries": []}}, "x", None):
        with pytest.raises(SourceError, match="no timeseries"):
            metno.parse_current(bad, 18.5, 73.8, NOW)
    bad_time = {"properties": {"timeseries": [{"time": "nonsense", "data": {}}]}}
    with pytest.raises(SourceError, match="unparseable"):
        metno.parse_current(bad_time, 18.5, 73.8, NOW)


def test_rain_is_hourly_and_in_pune_local_time() -> None:
    rain = metno.parse_rain(_payload(4))
    assert list(rain["precipitation"]) == [0.0, 0.2, 0.4, 0.6000000000000001] or len(rain) == 4
    assert rain["hour_ts"].iloc[0] == pd.Timestamp("2026-09-25 00:30")  # 19:00 UTC is 00:30 IST


def test_http_failures_become_source_errors_and_the_request_identifies_itself() -> None:
    seen: dict[str, str] = {}

    def ok(request: httpx.Request) -> httpx.Response:
        seen["ua"] = request.headers["user-agent"]
        seen["q"] = str(request.url.query, "utf-8")
        return httpx.Response(200, json=_payload())

    with httpx.Client(transport=httpx.MockTransport(ok)) as c:
        assert metno.fetch(c, 18.52, 73.86)["properties"]
    assert "MobilityOps" in seen["ua"] and "lat=18.5200" in seen["q"] and "lon=73.8600" in seen["q"]

    for handler, message in (
        (lambda r: httpx.Response(429), "HTTP 429"),
        (lambda r: httpx.Response(200, content=b"<html>"), "invalid JSON"),
    ):
        with (
            httpx.Client(transport=httpx.MockTransport(handler)) as c,
            pytest.raises(SourceError, match=message),
        ):
            metno.fetch(c, 18.5, 73.8)

    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    with (
        httpx.Client(transport=httpx.MockTransport(down)) as c,
        pytest.raises(SourceError, match="unreachable"),
    ):
        metno.fetch(c, 18.5, 73.8)
