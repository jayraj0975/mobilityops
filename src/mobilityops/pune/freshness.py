"""Freshness: how old data is, computed from the source's own timestamps.

A state is never a flag someone sets. It is derived from two clocks: ``observed_at`` (when the
source says the value applies) and the time of the last successful poll, compared with how often
that source is expected to update. The four states:

* LIVE     arriving on schedule (age within 2.5x the expected interval)
* DELAYED  late, but recent enough to trust (within 5x)
* STALE    old (within 12x); shown, but marked as not current
* OFFLINE  older than that, or never received

The LIVE bound is 2.5x, not 1x, because a value stamped at the start of an interval and polled once
per interval is up to two intervals old while everything is healthy.

DISABLED is separate: the source is not configured, which is not a failure.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

LIVE_FACTOR = 2.5
DELAYED_FACTOR = 5.0
STALE_FACTOR = 12.0


class Freshness(StrEnum):
    LIVE = "LIVE"
    DELAYED = "DELAYED"
    STALE = "STALE"
    OFFLINE = "OFFLINE"
    DISABLED = "DISABLED"
    NOT_PERIODIC = "NOT_PERIODIC"  # static or historical: freshness does not apply


@dataclass(frozen=True)
class FreshnessReading:
    state: Freshness
    age_s: float | None  # since the source's own observation time
    since_poll_s: float | None  # since we last heard from it successfully

    def to_dict(self) -> dict[str, float | str | None]:
        return {"state": self.state.value, "age_s": self.age_s, "since_poll_s": self.since_poll_s}


def _aware(ts: datetime) -> datetime:
    return ts if ts.tzinfo else ts.replace(tzinfo=UTC)


def classify(
    interval_s: int | None,
    observed_at: datetime | None,
    last_success_at: datetime | None,
    now: datetime,
    *,
    enabled: bool = True,
) -> FreshnessReading:
    """Freshness of one source at ``now``.

    Age is measured from ``observed_at`` when the source provides one, otherwise from the last
    successful poll. A source polled successfully but whose own timestamp is old (a stuck upstream)
    therefore goes stale even though our poller is healthy.
    """
    if not enabled:
        return FreshnessReading(Freshness.DISABLED, None, None)
    if interval_s is None:
        return FreshnessReading(Freshness.NOT_PERIODIC, None, None)
    now = _aware(now)
    since_poll = (
        max(0.0, (now - _aware(last_success_at)).total_seconds()) if last_success_at else None
    )
    ref = observed_at or last_success_at
    if ref is None:
        return FreshnessReading(Freshness.OFFLINE, None, since_poll)
    age = max(0.0, (now - _aware(ref)).total_seconds())
    # our own poll can also be the late party: use the worse of the two clocks
    effective = max(age, since_poll) if since_poll is not None and observed_at is None else age
    if effective <= LIVE_FACTOR * interval_s:
        state = Freshness.LIVE
    elif effective <= DELAYED_FACTOR * interval_s:
        state = Freshness.DELAYED
    elif effective <= STALE_FACTOR * interval_s:
        state = Freshness.STALE
    else:
        state = Freshness.OFFLINE
    return FreshnessReading(state, age, since_poll)


def worst(states: list[Freshness]) -> Freshness:
    """The least healthy of the states that apply (disabled and non-periodic ones are ignored)."""
    order = [Freshness.LIVE, Freshness.DELAYED, Freshness.STALE, Freshness.OFFLINE]
    applicable = [s for s in states if s in order]
    return max(applicable, key=order.index) if applicable else Freshness.NOT_PERIODIC
