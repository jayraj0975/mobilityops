"""Source schemas and shared constants.

The TLC publishes trip records as Parquet with a stable core of columns. We validate the columns
we actually depend on instead of assuming the rest, and we record what the file really contains
in the ingestion manifest.
"""

from __future__ import annotations

TIMEZONE = "America/New_York"

# Columns the pipeline cannot work without (TLC yellow-taxi trip records).
TLC_REQUIRED_COLUMNS: tuple[str, ...] = (
    "tpep_pickup_datetime",
    "tpep_dropoff_datetime",
    "PULocationID",
    "DOLocationID",
    "passenger_count",
    "trip_distance",
    "fare_amount",
    "total_amount",
    "payment_type",
)

ZONE_LOOKUP_COLUMNS: tuple[str, ...] = ("LocationID", "Borough", "Zone", "service_zone")

# NOAA GHCN-Daily (NCEI daily-summaries) elements we use, in metric units.
WEATHER_COLUMNS: tuple[str, ...] = ("DATE", "PRCP", "SNOW", "TMAX", "TMIN")

# Location IDs the TLC uses for "unknown" pickups/dropoffs; they are not real zones.
TLC_UNKNOWN_ZONE_IDS: frozenset[int] = frozenset({264, 265})
