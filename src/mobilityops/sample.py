"""Deterministic synthetic data in the same shapes as the real TLC / NOAA sources.

TEST / SYNTHETIC DATA. Nothing produced here describes real-world behaviour, and results computed
from it must never be reported as real-world results. It exists so that the whole pipeline
(ingestion, cleaning, forecasting, anomaly detection, optimisation, API, AI tools) can run in
seconds on a laptop or in CI without downloading gigabytes.

The generator plants known structure and records it in ``ground_truth.json``:

* hour-of-day and day-of-week seasonality, different per zone type
* a rain effect on demand (so weather-conditioned comparisons have a real signal to find)
* a small number of injected anomalies (surges and a drop) late in the series, so a forecaster
  trained on the earlier period can be checked against events it has never seen
* a known number of deliberately corrupt rows of each kind, so the cleaning stage can be
  verified against an exact expected count

Everything is a pure function of ``SampleSpec`` (including the seed).
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

SYNTHETIC_LABEL = "TEST / SYNTHETIC DATA"

# Hour-of-day shapes (mean 1.0). "residential" peaks in the morning, "business" in the evening.
# fmt: off
_HOUR_RESIDENTIAL = np.array(
    [0.35, 0.25, 0.2, 0.2, 0.3, 0.6, 1.2, 1.8, 1.9, 1.4, 1.1, 1.0,
     1.0, 1.0, 1.0, 1.1, 1.2, 1.3, 1.2, 1.0, 0.9, 0.8, 0.6, 0.45]
)
_HOUR_BUSINESS = np.array(
    [0.5, 0.35, 0.25, 0.2, 0.2, 0.3, 0.6, 1.0, 1.3, 1.2, 1.1, 1.2,
     1.3, 1.2, 1.1, 1.2, 1.5, 1.9, 1.9, 1.5, 1.2, 1.0, 0.8, 0.6]
)
# fmt: on
_DOW_FACTOR = np.array([0.95, 1.0, 1.05, 1.1, 1.2, 1.15, 0.85])  # Monday=0

# Peak-scale trips/hour for zone 1..12. Busy zones have strong signal; quiet ones are sparse.
_ZONE_BASE = np.array([40, 30, 25, 20, 15, 12, 10, 8, 6, 5, 4, 3], dtype=float)


@dataclass(frozen=True)
class Anomaly:
    zone: int
    day: int  # 0-based day index from the series start
    start_hour: int
    hours: int
    factor: float  # demand multiplier during the event
    kind: str  # "surge" or "drop"


@dataclass(frozen=True)
class SampleSpec:
    seed: int = 7
    start: str = "2024-01-01"
    n_days: int = 56
    n_zones: int = 12
    dirty_fraction: float = 0.004
    rain_effect: float = -0.12  # multiplicative effect on demand on rainy days
    anomalies: tuple[Anomaly, ...] = field(
        default=(
            Anomaly(zone=3, day=40, start_hour=17, hours=4, factor=3.0, kind="surge"),
            Anomaly(zone=7, day=44, start_hour=8, hours=6, factor=0.15, kind="drop"),
            Anomaly(zone=5, day=50, start_hour=12, hours=3, factor=2.5, kind="surge"),
        )
    )


@dataclass(frozen=True)
class SampleFiles:
    directory: Path
    trips: Path
    zone_lookup: Path
    weather: Path
    zones_geojson: Path
    ground_truth: Path


def _zone_profiles(n_zones: int) -> np.ndarray:
    """(24, n_zones) hour-of-day multipliers: odd zones residential, even zones business."""
    cols = [(_HOUR_RESIDENTIAL if (z % 2 == 1) else _HOUR_BUSINESS) for z in range(1, n_zones + 1)]
    return np.stack(cols, axis=1)


def _weather(spec: SampleSpec, rng: np.random.Generator) -> pd.DataFrame:
    dates = pd.date_range(spec.start, periods=spec.n_days, freq="D")
    doy = dates.dayofyear.to_numpy()
    tmax = 6 + 12 * np.sin((doy - 100) / 365 * 2 * np.pi) + rng.normal(0, 3, len(dates))
    rainy = rng.random(len(dates)) < 0.28
    prcp = np.where(rainy, rng.exponential(6.0, len(dates)) + 1.0, 0.0)
    return pd.DataFrame(
        {
            "STATION": "SYNTHETIC",
            "DATE": dates.strftime("%Y-%m-%d"),
            "PRCP": np.round(prcp, 1),
            "SNOW": 0.0,
            "TMAX": np.round(tmax, 1),
            "TMIN": np.round(tmax - 6 - rng.random(len(dates)) * 2, 1),
        }
    )


def _demand_rates(spec: SampleSpec, weather: pd.DataFrame) -> tuple[pd.DatetimeIndex, np.ndarray]:
    hours = pd.date_range(spec.start, periods=spec.n_days * 24, freq="h")
    profile = _zone_profiles(spec.n_zones)[hours.hour.to_numpy()]  # (n_hours, n_zones)
    dow = _DOW_FACTOR[hours.dayofweek.to_numpy()][:, None]
    base = _ZONE_BASE[: spec.n_zones][None, :]
    rain_day = (weather["PRCP"].to_numpy() >= 1.0)[np.arange(len(hours)) // 24][:, None]
    rain = np.where(rain_day, 1.0 + spec.rain_effect, 1.0)
    lam = base * profile * dow * rain
    for a in spec.anomalies:
        if a.zone > spec.n_zones:
            continue
        s = a.day * 24 + a.start_hour
        lam[s : s + a.hours, a.zone - 1] *= a.factor
    return hours, lam


def _trips_from_counts(
    hours: pd.DatetimeIndex, counts: np.ndarray, spec: SampleSpec, rng: np.random.Generator
) -> pd.DataFrame:
    h_idx, z_idx = np.nonzero(counts)
    reps = counts[h_idx, z_idx]
    hour_start = np.repeat(hours.to_numpy()[h_idx], reps)
    zone = np.repeat(z_idx + 1, reps)
    n = int(reps.sum())
    pickup = hour_start + (rng.random(n) * 3600).astype("timedelta64[s]").astype("timedelta64[us]")
    minutes = np.clip(rng.lognormal(2.5, 0.5, n), 3, 90)
    dropoff = pickup + (minutes * 60).astype("timedelta64[s]").astype("timedelta64[us]")
    miles = np.clip(minutes * rng.uniform(0.12, 0.3, n), 0.2, 30)
    fare = np.round(np.clip(3 + 2.5 * miles + 0.4 * minutes + rng.normal(0, 1.5, n), 3, None), 2)
    tip = np.round(np.where(rng.random(n) < 0.6, fare * rng.uniform(0.1, 0.25, n), 0.0), 2)
    return pd.DataFrame(
        {
            "VendorID": rng.choice([1, 2], n).astype("int64"),
            "tpep_pickup_datetime": pickup,
            "tpep_dropoff_datetime": dropoff,
            "passenger_count": rng.choice([1, 1, 1, 2, 2, 3, 4], n).astype("float64"),
            "trip_distance": np.round(miles, 2),
            "RatecodeID": np.ones(n, dtype="float64"),
            "PULocationID": zone.astype("int64"),
            "DOLocationID": rng.integers(1, spec.n_zones + 1, n).astype("int64"),
            "payment_type": rng.choice([1, 1, 1, 2], n).astype("int64"),
            "fare_amount": fare,
            "tip_amount": tip,
            "total_amount": np.round(fare + tip + 1.3, 2),
        }
    )


def _corrupt(trips: pd.DataFrame, spec: SampleSpec, rng: np.random.Generator) -> dict[str, int]:
    """Corrupt a known number of rows, in place, and return exact counts per defect kind.

    The trips frame has a default RangeIndex, so integer positions double as index labels.
    """
    kinds = (
        "dropoff_before_pickup",
        "negative_fare",
        "unknown_pickup_zone",
        "timestamp_out_of_range",
    )
    n_bad = int(len(trips) * spec.dirty_fraction)
    chosen = rng.choice(len(trips), size=n_bad, replace=False)
    groups = {kind: chosen[i :: len(kinds)] for i, kind in enumerate(kinds)}

    idx = groups["dropoff_before_pickup"]
    trips.loc[idx, "tpep_dropoff_datetime"] = trips.loc[idx, "tpep_pickup_datetime"] - pd.Timedelta(
        minutes=10
    )

    idx = groups["negative_fare"]
    trips.loc[idx, "fare_amount"] = -trips.loc[idx, "fare_amount"].abs()

    idx = groups["unknown_pickup_zone"]
    trips.loc[idx, "PULocationID"] = 265

    idx = groups["timestamp_out_of_range"]  # the real TLC files contain rows dated years off
    trips.loc[idx, "tpep_pickup_datetime"] = pd.Timestamp("2002-12-31 23:00:00")
    trips.loc[idx, "tpep_dropoff_datetime"] = pd.Timestamp("2002-12-31 23:20:00")

    return {kind: len(rows) for kind, rows in groups.items()}


def _zones(n_zones: int) -> tuple[pd.DataFrame, dict[str, Any]]:
    """A 4-column grid of unit squares near lower Manhattan, plus a matching lookup table."""
    rows, feats = [], []
    for z in range(1, n_zones + 1):
        col, row = (z - 1) % 4, (z - 1) // 4
        x0, y0 = -74.02 + col * 0.02, 40.70 + row * 0.02
        ring = [[x0, y0], [x0 + 0.02, y0], [x0 + 0.02, y0 + 0.02], [x0, y0 + 0.02], [x0, y0]]
        rows.append(
            {
                "LocationID": z,
                "Borough": "Sample",
                "Zone": f"Sample Zone {z:02d}",
                "service_zone": "Sample",
            }
        )
        feats.append(
            {
                "type": "Feature",
                "properties": {
                    "LocationID": z,
                    "zone": f"Sample Zone {z:02d}",
                    "borough": "Sample",
                },
                "geometry": {"type": "Polygon", "coordinates": [ring]},
            }
        )
    return pd.DataFrame(rows), {"type": "FeatureCollection", "features": feats}


def generate_sample(out_dir: Path, spec: SampleSpec | None = None) -> SampleFiles:
    """Write the synthetic source files into ``out_dir`` and return their paths."""
    spec = spec or SampleSpec()
    out_dir.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(spec.seed)

    weather = _weather(spec, rng)
    hours, lam = _demand_rates(spec, weather)
    counts = rng.poisson(lam)
    trips = _trips_from_counts(hours, counts, spec, rng)
    n_clean = len(trips)
    defect_counts = _corrupt(trips, spec, rng)
    trips = trips.sample(frac=1.0, random_state=spec.seed).reset_index(
        drop=True
    )  # unordered, like real files

    lookup, geojson = _zones(spec.n_zones)
    files = SampleFiles(
        directory=out_dir,
        trips=out_dir / "yellow_tripdata_sample.parquet",
        zone_lookup=out_dir / "taxi_zone_lookup.csv",
        weather=out_dir / "weather_daily.csv",
        zones_geojson=out_dir / "zones.geojson",
        ground_truth=out_dir / "ground_truth.json",
    )
    trips.to_parquet(files.trips, index=False)
    lookup.to_csv(files.zone_lookup, index=False)
    weather.to_csv(files.weather, index=False)
    files.zones_geojson.write_text(json.dumps(geojson))

    truth = {
        "label": SYNTHETIC_LABEL,
        "spec": asdict(spec),
        "rows_total": len(trips),
        "rows_generated_before_corruption": n_clean,
        "defect_counts": defect_counts,
        "rows_expected_removed_by_cleaning": sum(defect_counts.values()),
        "rainy_dates": weather.loc[weather["PRCP"] >= 1.0, "DATE"].tolist(),
        "rate_model": "lambda[hour, zone] = base * hour_profile * dow * rain * event",
    }
    files.ground_truth.write_text(json.dumps(truth, indent=2))
    return files
