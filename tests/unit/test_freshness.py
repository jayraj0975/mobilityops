"""Freshness is derived from the source's own timestamps, never set by hand."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from mobilityops.pune.freshness import Freshness, classify, worst
from mobilityops.pune.sources.registry import BY_KEY, SOURCES

NOW = datetime(2026, 9, 24, 12, 0, tzinfo=UTC)


def _ago(seconds: float) -> datetime:
    return NOW - timedelta(seconds=seconds)


@pytest.mark.parametrize(
    ("age", "expected"),
    [
        (0, Freshness.LIVE),
        (2.5 * 900, Freshness.LIVE),  # boundary is inclusive
        (2.5 * 900 + 1, Freshness.DELAYED),
        (5 * 900, Freshness.DELAYED),
        (5 * 900 + 1, Freshness.STALE),
        (12 * 900, Freshness.STALE),
        (12 * 900 + 1, Freshness.OFFLINE),
    ],
)
def test_state_thresholds_for_a_fifteen_minute_source(age: float, expected: Freshness) -> None:
    assert classify(900, _ago(age), _ago(10), NOW).state is expected


def test_a_healthy_poller_with_a_stuck_upstream_goes_stale() -> None:
    """We polled 5 seconds ago, but the source's own timestamp is three hours old."""
    reading = classify(900, _ago(3 * 3600), _ago(5), NOW)
    assert reading.state is Freshness.STALE
    assert reading.age_s == pytest.approx(3 * 3600) and reading.since_poll_s == pytest.approx(5)


def test_without_a_source_timestamp_the_poll_time_is_used() -> None:
    assert classify(60, None, _ago(30), NOW).state is Freshness.LIVE
    assert classify(60, None, _ago(400), NOW).state is Freshness.STALE


def test_never_received_is_offline_not_live() -> None:
    reading = classify(900, None, None, NOW)
    assert reading.state is Freshness.OFFLINE and reading.age_s is None


def test_disabled_and_non_periodic_sources_are_not_failures() -> None:
    assert classify(300, None, None, NOW, enabled=False).state is Freshness.DISABLED
    assert classify(None, _ago(10**7), _ago(10**7), NOW).state is Freshness.NOT_PERIODIC


def test_future_timestamps_do_not_produce_negative_ages() -> None:
    reading = classify(900, NOW + timedelta(minutes=3), NOW, NOW)
    assert reading.age_s == 0.0 and reading.state is Freshness.LIVE


def test_naive_timestamps_are_treated_as_utc() -> None:
    naive = (NOW - timedelta(seconds=30)).replace(tzinfo=None)
    assert classify(900, naive, naive, NOW).state is Freshness.LIVE


def test_worst_ignores_states_that_do_not_apply() -> None:
    assert worst([Freshness.LIVE, Freshness.STALE, Freshness.DISABLED]) is Freshness.STALE
    assert worst([Freshness.DISABLED, Freshness.NOT_PERIODIC]) is Freshness.NOT_PERIODIC
    assert worst([Freshness.LIVE, Freshness.OFFLINE, Freshness.DELAYED]) is Freshness.OFFLINE


def test_reading_serialises() -> None:
    d = classify(900, _ago(10), _ago(5), NOW).to_dict()
    assert d["state"] == "LIVE" and d["age_s"] == 10.0


def test_registry_is_consistent_and_honest_about_what_is_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert len({s.key for s in SOURCES}) == len(SOURCES)
    for key in ("tomtom-traffic", "openaq"):
        spec = BY_KEY[key]
        assert not spec.enabled({}) and "no adapter" in (spec.disabled_reason() or "")
        # a key cannot switch on code that does not exist
        assert not spec.enabled({spec.requires_key or "": "secret"})
    assert not BY_KEY["pmpml-gtfs"].enabled({})
    assert all(s.implemented for s in SOURCES if s.enabled({}))
    assert BY_KEY["simulated-demand"].data_class == "SIMULATED"
    assert BY_KEY["open-meteo-air-quality"].modelled
    assert all(s.data_class != "LIVE" for s in SOURCES)  # nothing in Pune is claimed LIVE
    monkeypatch.setenv("OPENAQ_API_KEY", "real-looking-key")
    assert not BY_KEY["openaq"].enabled()  # still not enabled: there is nothing to enable
