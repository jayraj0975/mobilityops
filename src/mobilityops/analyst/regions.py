"""Lets the analyst answer about any of the three regions in one running server, without a
restart: New York (mode ``real``), Pune and Mumbai each get their own ``Services``/``Analyst``,
built lazily from the same base ``Settings`` with only ``mode`` swapped (every path - the
database, artifacts, live state - is already a function of ``mode``, see ``config.py``).

A region with no generated data yet (for example Mumbai, until someone runs its forecast
pipeline on this machine) is not pre-filtered out: asking it a question goes through the normal
``Analyst.ask`` path, which already turns a missing-data ``NotReady`` into an honest "the data is
not ready" answer. There is deliberately no separate "is this region available" check to keep in
sync with that.
"""

from __future__ import annotations

import dataclasses
import threading

from mobilityops.analyst.agent import Analyst
from mobilityops.analyst.planner import Planner
from mobilityops.api.services import Services
from mobilityops.config import Settings

# The regions the AI copilot exposes a selector for. "real" is internally NYC's mode name;
# "sample" (synthetic test data) is deliberately not offered here, it is not a region.
REGION_LABELS: dict[str, str] = {"real": "New York", "pune": "Pune", "mumbai": "Mumbai"}


class UnknownRegion(ValueError):
    pass


class RegionRegistry:
    def __init__(self, base_settings: Settings, planner: Planner) -> None:
        self._base = base_settings
        self._planner = planner
        self._lock = threading.Lock()
        self._analysts: dict[str, Analyst] = {}

    def settings_for(self, region: str) -> Settings:
        if region not in REGION_LABELS:
            raise UnknownRegion(f"unknown region {region!r}; choose one of {list(REGION_LABELS)}")
        return dataclasses.replace(self._base, mode=region)  # type: ignore[arg-type]

    def seed(self, region: str, analyst: Analyst) -> None:
        """Register an already-built Analyst (e.g. this server's own native-mode one) so
        ``analyst_for`` reuses it instead of constructing a second Services for the same data."""
        with self._lock:
            self._analysts[region] = analyst

    def analyst_for(self, region: str) -> Analyst:
        if region not in REGION_LABELS:
            raise UnknownRegion(f"unknown region {region!r}; choose one of {list(REGION_LABELS)}")
        with self._lock:
            a = self._analysts.get(region)
            if a is None:
                a = Analyst(Services(self.settings_for(region)), self._planner, registry=self)
                self._analysts[region] = a
            return a
