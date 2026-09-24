"""Definitions the analyst may quote. Kept in code so answers cannot drift from the system."""

from __future__ import annotations

GLOSSARY: dict[str, str] = {
    "pickups": "Completed yellow-taxi trips that started in a zone during an hour, after cleaning.",
    "dropoffs": "Completed yellow-taxi trips that ended in a zone during an hour.",
    "revenue": "Sum of total_amount (fare, surcharges, tips) of trips that started in the zone.",
    "zone": "One of the 263 NYC TLC taxi zones (a neighbourhood-sized area); identified by a "
    "location id.",
    "wape": "Weighted absolute percentage error: sum of absolute forecast errors divided by the "
    "sum of actual demand. Lower is better; unlike MAPE it is defined when demand is zero.",
    "mae": "Mean absolute error, in pickups per zone-hour.",
    "rmse": "Root mean squared error, in pickups per zone-hour; penalises large misses more "
    "than MAE.",
    "baseline": "A simple forecast the model must beat: copy yesterday, copy last week, or "
    "average the same weekday and hour over four weeks.",
    "walk-forward": "Evaluation that only ever tests on days after the days used for fitting, "
    "refitting as time moves on. No random splits.",
    "prediction interval": "A range meant to contain the actual value about 80% of the time. "
    "Its real coverage is measured on held-out days and reported.",
    "coverage": "The share of held-out zone-hours whose actual value fell inside the interval.",
    "anomaly": "A run of hours where a zone's pickups differed from the out-of-sample forecast by "
    "far more than the forecaster's usual error at that demand level.",
    "event score": "The pooled deviation of an anomaly event, divided by the typical spread of "
    "such scores for events of that length. Larger magnitude means stronger evidence.",
    "severity": "A heuristic label (low, medium, high) based on the size of the event score; not "
    "a probability.",
    "surge": "An anomaly where actual demand was above the forecast.",
    "drop": "An anomaly where actual demand was below the forecast.",
    "simulated scenario": "A what-if computed under explicit assumptions (fleet size, vehicle "
    "capacity, movement limits). It is not a prediction of real outcomes.",
    "oracle": "A plan made with the actual demand: an unattainable upper bound used to show how "
    "much a decision could improve at most.",
    "served share": "In a repositioning simulation, trips served divided by trips demanded.",
    "dst": "Daylight-saving time. The spring-forward hour does not exist and the fall-back hour "
    "occurs twice; both are excluded from modelling rather than treated as zero demand.",
    "sample data": "Deterministic synthetic data for tests and demos, always labelled TEST / "
    "SYNTHETIC DATA. Never mixed with real data.",
}


# Definitions that differ where the data is not New York taxi trips.
PUNE_OVERRIDES: dict[str, str] = {
    "pickups": "SIMULATED trips that started in a zone during an hour. No real Pune trip data "
    "exists openly; the counts come from a documented model.",
    "dropoffs": "SIMULATED trips that ended in a zone during an hour.",
    "revenue": "Simulated fare in rupees of the trips that started in the zone.",
    "zone": "An analysis area: the part of Pune closer to one OpenStreetMap suburb than to any "
    "other. Not an administrative ward; identified by a location id.",
}


def lookup(term: str, mode: str = "real") -> tuple[str, str] | None:
    """Find a glossary entry by exact or contained term."""
    entries = {**GLOSSARY, **PUNE_OVERRIDES} if mode == "pune" else GLOSSARY
    t = term.strip().lower()
    if t in entries:
        return t, entries[t]
    for key in sorted(entries, key=len, reverse=True):
        if key in t or t in key:
            return key, entries[key]
    return None
