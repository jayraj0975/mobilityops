"""Shared types for source adapters."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

DataClass = Literal[
    "LIVE", "NEAR-REAL-TIME", "RECENT", "HISTORICAL", "PREDICTED", "SIMULATED", "STATIC"
]

USER_AGENT = "MobilityOps/0.2 (student portfolio project; github.com/jayraj0975/mobilityops)"


class SourceError(RuntimeError):
    """A source did not answer, answered with an error, or returned data that failed validation."""


@dataclass(frozen=True)
class Observation:
    """One measured or modelled value at a place, with the source's own clock.

    ``observed_at`` is when the source says the value applies (UTC); ``received_at`` is when this
    system got it. Freshness is computed from ``observed_at`` and the age of ``received_at`` and
    is never assumed to be the same thing.
    """

    source: str
    metric: str
    value: float
    unit: str
    observed_at: datetime
    received_at: datetime
    lat: float
    lon: float
    data_class: DataClass
    modelled: bool = False  # True when the value is a model output, not an instrument reading
