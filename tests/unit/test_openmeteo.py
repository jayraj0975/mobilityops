"""Open-Meteo adapter: parsing and validation against recorded response shapes (no network)."""

from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest

from mobilityops.pune.sources import openmeteo as om
from mobilityops.pune.sources.base import SourceError

NOW = datetime(2026, 9, 24, 15, 20, tzinfo=UTC)
PTS = [(18.52, 73.86), (18.45, 73.75)]


def _block(time: str = "2026-09-24T20:45", **values: object) -> dict:  # type: ignore[type-arg]
    return {"current": {"time": time, "interval": 900, **values}}


def test_current_converts_local_time_to_utc_and_keeps_units() -> None:
    payload = [_block(temperature_2m=23.8, precipitation=0.0), _block(temperature_2m=22.8)]
    obs = om.parse_current(
        payload,
        PTS,
        ("temperature_2m", "precipitation"),
        source="t",
        received_at=NOW,
        modelled=True,
    )
    first = obs[0]
    assert first.observed_at == datetime(2026, 9, 24, 15, 15, tzinfo=UTC)  # 20:45 IST
    assert first.unit == "°C" and first.data_class == "NEAR-REAL-TIME" and first.modelled
    assert first.received_at == NOW
    assert len(obs) == 3  # the second point has no precipitation


def test_out_of_range_and_wrong_type_values_are_dropped() -> None:
    payload = [_block(temperature_2m=99.0, relative_humidity_2m="wet", precipitation=1.5)]
    obs = om.parse_current(
        payload[:1],
        PTS[:1],
        ("temperature_2m", "relative_humidity_2m", "precipitation"),
        source="t",
        received_at=NOW,
        modelled=True,
    )
    assert [o.metric for o in obs] == ["precipitation"]


def test_nothing_usable_is_an_error_not_an_empty_success() -> None:
    with pytest.raises(SourceError, match="no usable"):
        om.parse_current(
            [_block(temperature_2m=None)],
            PTS[:1],
            ("temperature_2m",),
            source="t",
            received_at=NOW,
            modelled=True,
        )


def test_wrong_number_of_points_and_missing_block_are_errors() -> None:
    with pytest.raises(SourceError, match="asked for 2"):
        om.parse_current(
            [_block()], PTS, ("temperature_2m",), source="t", received_at=NOW, modelled=True
        )
    with pytest.raises(SourceError, match="no current block"):
        om.parse_current(
            {"oops": 1}, PTS[:1], ("temperature_2m",), source="t", received_at=NOW, modelled=True
        )


def test_single_object_response_is_accepted_for_one_point() -> None:
    obs = om.parse_current(
        _block(pm2_5=21.2), PTS[:1], ("pm2_5",), source="t", received_at=NOW, modelled=True
    )
    assert obs[0].value == 21.2


def test_archive_keeps_missing_hours_as_nan() -> None:
    payload = {
        "hourly": {
            "time": ["2026-09-01T00:00", "2026-09-01T01:00"],
            "temperature_2m": [22.6, None],
            "precipitation": [0.0, 0.4],
            "relative_humidity_2m": [88, 90],
        }
    }
    df = om.parse_archive(payload)
    assert df["temperature_2m"].isna().tolist() == [False, True]
    assert df["precipitation"].tolist() == [0.0, 0.4]


def test_archive_rejects_duplicates_and_bad_times() -> None:
    dup = {"hourly": {"time": ["2026-09-01T00:00", "2026-09-01T00:00"]}}
    with pytest.raises(SourceError, match="duplicate"):
        om.parse_archive(dup)
    with pytest.raises(SourceError, match="unparseable"):
        om.parse_archive({"hourly": {"time": ["not a time"]}})
    with pytest.raises(SourceError, match="no hourly"):
        om.parse_archive({})


def test_http_errors_become_source_errors() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    with (
        httpx.Client(transport=httpx.MockTransport(handler)) as client,
        pytest.raises(SourceError, match="HTTP 503"),
    ):
        om.fetch_current_weather(client, PTS)


def test_unreachable_source_becomes_a_source_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    with (
        httpx.Client(transport=httpx.MockTransport(handler)) as client,
        pytest.raises(SourceError, match="unreachable"),
    ):
        om.fetch_current_air(client, PTS)


def test_request_carries_an_identifying_user_agent_and_bounded_window() -> None:
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["ua"] = request.headers["user-agent"]
        return httpx.Response(200, json={"hourly": {"time": []}})

    from datetime import date

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        om.fetch_archive(client, 18.5, 73.8, date(2026, 9, 1), date(2026, 9, 2))
        with pytest.raises(ValueError, match="at most"):
            om.fetch_archive(client, 18.5, 73.8, date(2020, 1, 1), date(2026, 1, 1))
    assert "MobilityOps" in seen["ua"]
