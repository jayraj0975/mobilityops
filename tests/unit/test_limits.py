"""Rate limiting and body caps: correctness, isolation, bounded memory, and proxy-header trust."""

from __future__ import annotations

import pytest

from mobilityops.api import limits
from mobilityops.api.limits import RateLimiter, client_ip
from mobilityops.config import ConfigError, Settings


class Clock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


def test_allows_up_to_the_limit_then_refuses_and_says_when_to_retry() -> None:
    clock = Clock()
    rl = RateLimiter(clock)
    assert [rl.check("a", "api", 3)[0] for _ in range(3)] == [True, True, True]
    ok, wait = rl.check("a", "api", 3)
    assert not ok and 59.0 <= wait <= 60.0


def test_window_slides_so_old_requests_stop_counting() -> None:
    clock = Clock()
    rl = RateLimiter(clock)
    for _ in range(3):
        rl.check("a", "api", 3)
    clock.t += 30
    assert not rl.check("a", "api", 3)[0]
    clock.t += 31  # the first three are now more than 60 s old
    assert rl.check("a", "api", 3)[0]


def test_clients_and_buckets_are_counted_separately() -> None:
    rl = RateLimiter(Clock())
    assert rl.check("a", "api", 1)[0] and not rl.check("a", "api", 1)[0]
    assert rl.check("b", "api", 1)[0]  # another client is unaffected
    assert rl.check("a", "heavy", 1)[0]  # another bucket is unaffected


def test_a_limit_of_zero_disables_the_bucket() -> None:
    rl = RateLimiter(Clock())
    assert all(rl.check("a", "api", 0)[0] for _ in range(1000))


def test_memory_is_bounded_even_under_a_flood_of_distinct_clients(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(limits, "MAX_TRACKED_CLIENTS", 50)
    rl = RateLimiter(Clock())
    for i in range(500):
        rl.check(f"ip{i}", "api", 5)
    assert len(rl._hits) <= 50


def test_forwarded_for_is_ignored_unless_the_proxy_is_trusted() -> None:
    assert client_ip("10.0.0.1", "1.2.3.4", 0) == "10.0.0.1"
    assert client_ip("10.0.0.1", None, 1) == "10.0.0.1"
    assert client_ip(None, None, 0) == "unknown"
    assert client_ip("10.0.0.1", "x" * 200, 1) == "10.0.0.1"  # absurd header ignored


def test_the_client_is_counted_from_the_right_so_a_forged_prefix_changes_nothing() -> None:
    # one trusted proxy appended the real client address after whatever the client sent
    assert client_ip("10.0.0.1", "6.6.6.6, 1.2.3.4", 1) == "1.2.3.4"
    assert client_ip("10.0.0.1", "7.7.7.7, 6.6.6.6, 1.2.3.4", 1) == "1.2.3.4"
    # two trusted proxies: the client is second from the right
    assert client_ip("10.0.0.1", "6.6.6.6, 1.2.3.4, 172.16.0.5", 2) == "1.2.3.4"
    # a chain shorter than the trusted depth did not come through our proxies
    assert client_ip("10.0.0.1", "1.2.3.4", 2) == "10.0.0.1"


def test_settings_validate_the_limit_variables() -> None:
    s = Settings.from_env(
        {
            "MOBILITYOPS_RATE_LIMIT": "120",
            "MOBILITYOPS_RATE_LIMIT_HEAVY": "10",
            "MOBILITYOPS_TRUST_PROXY": "true",
        }
    )
    assert (s.rate_limit, s.rate_limit_heavy, s.trust_proxy) == (120, 10, 1)
    d = Settings.from_env({})
    assert (d.rate_limit, d.rate_limit_heavy, d.trust_proxy) == (0, 0, 0)
    assert Settings.from_env({"MOBILITYOPS_TRUST_PROXY": "2"}).trust_proxy == 2
    with pytest.raises(ConfigError, match="TRUST_PROXY"):
        Settings.from_env({"MOBILITYOPS_TRUST_PROXY": "many"})
    for bad in ("-5", "lots", "9999999"):
        with pytest.raises(ConfigError, match="RATE_LIMIT"):
            Settings.from_env({"MOBILITYOPS_RATE_LIMIT": bad})
