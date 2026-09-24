"""What each data source is, how often it should update, and whether it is on.

The registry is the single place the interface, the API and the freshness logic read from, so a
source cannot be described differently in two places. Disabled sources are listed honestly as
disabled; nothing pretends to be connected.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass

from mobilityops.pune.sources.base import DataClass


@dataclass(frozen=True)
class SourceSpec:
    key: str
    label: str
    provider: str
    data_class: DataClass
    interval_s: int | None  # how often new data is expected; None = not periodic
    licence: str
    note: str
    modelled: bool = False
    requires_key: str | None = None  # environment variable that enables it
    always_on: bool = True

    def enabled(self, env: Mapping[str, str] | None = None) -> bool:
        e = os.environ if env is None else env
        if self.requires_key is not None:
            return bool((e.get(self.requires_key) or "").strip())
        return self.always_on

    def disabled_reason(self) -> str | None:
        if self.requires_key is not None:
            return f"no {self.requires_key} configured"
        if not self.always_on:
            return "no feed configured"
        return None


SOURCES: tuple[SourceSpec, ...] = (
    SourceSpec(
        "open-meteo-forecast",
        "Weather now",
        "Open-Meteo",
        "NEAR-REAL-TIME",
        900,
        "CC BY 4.0; free tier non-commercial",
        "Latest 15-minute step of Open-Meteo's model blend at 9 grid points; not a station "
        "reading.",
        modelled=True,
    ),
    SourceSpec(
        "open-meteo-air-quality",
        "Air quality now",
        "Open-Meteo (CAMS model)",
        "NEAR-REAL-TIME",
        3600,
        "CC BY 4.0; free tier non-commercial",
        "Atmospheric-composition model on a coarse grid. MODELLED, not a monitoring-station value.",
        modelled=True,
    ),
    SourceSpec(
        "open-meteo-rain-hourly",
        "Rain, recent hours",
        "Open-Meteo",
        "RECENT",
        3600,
        "CC BY 4.0; free tier non-commercial",
        "Hourly precipitation for the last days (each value is stamped at the start of its hour, so "
        "it is up to an hour old by design); drives the simulated demand's rain response.",
        modelled=True,
    ),
    SourceSpec(
        "simulated-demand",
        "Mobility demand",
        "MobilityOps simulator",
        "SIMULATED",
        60,
        "MIT (this project)",
        "No open Pune trip source exists. Counts come from a documented model conditioned on "
        "real rain and the real holiday calendar.",
    ),
    SourceSpec(
        "model-forecast",
        "Demand forecast",
        "MobilityOps LightGBM",
        "PREDICTED",
        None,
        "MIT (this project)",
        "Day-ahead forecast with a conformal 80% range, made from data up to yesterday.",
    ),
    SourceSpec(
        "era5-archive",
        "Weather history",
        "Open-Meteo (ERA5)",
        "HISTORICAL",
        None,
        "CC BY 4.0",
        "Reanalysis used for the historical period; lags real time by days.",
    ),
    SourceSpec(
        "openstreetmap-zones",
        "Zones and map",
        "OpenStreetMap contributors",
        "STATIC",
        None,
        "ODbL 1.0",
        "Zones are the service areas of OpenStreetMap suburbs, not administrative wards.",
    ),
    SourceSpec(
        "tomtom-traffic",
        "Road traffic flow",
        "TomTom",
        "NEAR-REAL-TIME",
        300,
        "TomTom terms (not verified here)",
        "Adapter not enabled: needs an API key and a reading of TomTom's caching terms.",
        requires_key="TOMTOM_API_KEY",
    ),
    SourceSpec(
        "openaq",
        "Air quality stations",
        "OpenAQ",
        "NEAR-REAL-TIME",
        3600,
        "CC BY 4.0 (not verified here)",
        "Adapter not enabled: needs an API key. Would give real station readings.",
        requires_key="OPENAQ_API_KEY",
    ),
    SourceSpec(
        "pmpml-gtfs",
        "Bus timetable (PMPML)",
        "unofficial community feed",
        "STATIC",
        None,
        "data terms unknown",
        "Not bundled. No official PMPML feed found; an operator-supplied GTFS zip can be read.",
        always_on=False,
    ),
)
BY_KEY: dict[str, SourceSpec] = {s.key: s for s in SOURCES}
