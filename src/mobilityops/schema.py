"""Source schemas and shared constants.

The TLC publishes trip records as Parquet with a stable core of columns. We validate the columns
we actually depend on instead of assuming the rest, and we record what the file really contains
in the ingestion manifest.
"""

from __future__ import annotations

from dataclasses import dataclass

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


@dataclass(frozen=True)
class ServiceSpec:
    """Column names of one TLC trip-record family that is aggregated to zone-hour pickups."""

    name: str
    file_prefix: str
    pickup: str
    dropoff: str
    pu_zone: str
    distance: str
    amount: str  # a fare column; negative values are refunds/adjustments, as for yellow taxis
    label: str


# Yellow taxis have their own full pipeline (trip-level silver layer). These families are
# aggregated straight to pickups per zone-hour: only counts are needed and the for-hire file is
# several hundred MB a month.
SERVICE_SPECS: dict[str, ServiceSpec] = {
    "green": ServiceSpec(
        "green",
        "green_tripdata",
        "lpep_pickup_datetime",
        "lpep_dropoff_datetime",
        "PULocationID",
        "trip_distance",
        "fare_amount",
        "Green taxis (boro taxis)",
    ),
    "fhvhv": ServiceSpec(
        "fhvhv",
        "fhvhv_tripdata",
        "pickup_datetime",
        "dropoff_datetime",
        "PULocationID",
        "trip_miles",
        "base_passenger_fare",
        "High-volume for-hire vehicles (Uber, Lyft and similar)",
    ),
}

ZONE_LOOKUP_COLUMNS: tuple[str, ...] = ("LocationID", "Borough", "Zone", "service_zone")

# NOAA GHCN-Daily (NCEI daily-summaries) elements we use, in metric units.
WEATHER_COLUMNS: tuple[str, ...] = ("DATE", "PRCP", "SNOW", "TMAX", "TMIN")

# Location IDs the TLC uses for "unknown" pickups/dropoffs; they are not real zones.
TLC_UNKNOWN_ZONE_IDS: frozenset[int] = frozenset({264, 265})
