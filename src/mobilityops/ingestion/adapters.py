"""Source adapters: read each raw source, validate its schema, return clean canonical frames.

Adapters do not assume a schema. They look at what the file actually contains, accept the known
name variations the publisher has used over the years, and raise a :class:`SchemaError` that says
which columns are missing and which were found, instead of failing later with an obscure
KeyError deep inside a query.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from mobilityops.geo import polygon_centroid
from mobilityops.schema import (
    SERVICE_SPECS,
    TLC_REQUIRED_COLUMNS,
    WEATHER_COLUMNS,
    ZONE_LOOKUP_COLUMNS,
)


class SchemaError(ValueError):
    """A source file does not have the structure the pipeline needs."""


# Known publisher name variants (compared case-insensitively) -> the canonical name we use.
_TRIP_ALIASES: dict[str, tuple[str, ...]] = {
    "tpep_pickup_datetime": ("tpep_pickup_datetime", "lpep_pickup_datetime", "pickup_datetime"),
    "tpep_dropoff_datetime": ("tpep_dropoff_datetime", "lpep_dropoff_datetime", "dropoff_datetime"),
    "PULocationID": ("pulocationid", "pu_location_id", "pickup_location_id"),
    "DOLocationID": ("dolocationid", "do_location_id", "dropoff_location_id"),
    "passenger_count": ("passenger_count",),
    "trip_distance": ("trip_distance",),
    "fare_amount": ("fare_amount",),
    "total_amount": ("total_amount",),
    "payment_type": ("payment_type",),
}


def canonical_trip_columns(columns: list[str]) -> dict[str, str]:
    """Map actual column names to canonical names for the columns we recognise."""
    lookup = {alias.lower(): canon for canon, aliases in _TRIP_ALIASES.items() for alias in aliases}
    return {c: lookup[c.lower()] for c in columns if c.lower() in lookup}


@dataclass(frozen=True)
class TripsFileInfo:
    path: Path
    rows: int
    columns: dict[str, str]  # actual column name -> arrow type, as found in the file
    canonical: dict[str, str]  # actual name -> canonical name (recognised columns only)


def inspect_trips(path: Path) -> TripsFileInfo:
    """Read only the Parquet footer: cheap even for multi-hundred-MB files."""
    try:
        pf = pq.ParquetFile(path)
    except Exception as exc:  # corrupt/truncated file
        raise SchemaError(f"{path.name}: not a readable Parquet file ({exc})") from exc
    columns = {f.name: str(f.type) for f in pf.schema_arrow}
    canonical = canonical_trip_columns(list(columns))
    missing = sorted(set(TLC_REQUIRED_COLUMNS) - set(canonical.values()))
    if missing:
        raise SchemaError(
            f"{path.name}: missing required columns {missing}. Found columns: {sorted(columns)}. "
            "If the publisher renamed a column, add the new name to _TRIP_ALIASES."
        )
    if pf.metadata.num_rows == 0:
        raise SchemaError(f"{path.name}: file contains no rows")
    return TripsFileInfo(path, pf.metadata.num_rows, columns, canonical)


def inspect_service_trips(path: Path, service: str) -> TripsFileInfo:
    """Footer check for a green or for-hire file: the columns the aggregation needs."""
    spec = SERVICE_SPECS[service]
    try:
        pf = pq.ParquetFile(path)
    except Exception as exc:
        raise SchemaError(f"{path.name}: not a readable Parquet file ({exc})") from exc
    columns = {f.name: str(f.type) for f in pf.schema_arrow}
    needed = (spec.pickup, spec.dropoff, spec.pu_zone, spec.distance, spec.amount)
    missing = sorted(set(needed) - set(columns))
    if missing:
        raise SchemaError(
            f"{path.name}: missing required columns {missing} for service {service!r}. "
            f"Found columns: {sorted(columns)}. Update SERVICE_SPECS if the publisher renamed them."
        )
    if pf.metadata.num_rows == 0:
        raise SchemaError(f"{path.name}: file contains no rows")
    return TripsFileInfo(path, pf.metadata.num_rows, columns, {c: c for c in needed})


def read_zone_lookup(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    missing = sorted(set(ZONE_LOOKUP_COLUMNS) - set(df.columns))
    if missing:
        raise SchemaError(f"{path.name}: missing columns {missing}. Found: {sorted(df.columns)}")
    df = df[list(ZONE_LOOKUP_COLUMNS)].copy()
    df["LocationID"] = pd.to_numeric(df["LocationID"], errors="raise").astype("int64")
    if df["LocationID"].duplicated().any():
        raise SchemaError(f"{path.name}: duplicate LocationID values")
    for c in ("Borough", "Zone", "service_zone"):
        df[c] = df[c].astype("string").str.strip()
    return df.reset_index(drop=True)


def read_zones_geojson(path: Path) -> pd.DataFrame:
    """Zone id, name, and a representative centroid (lon/lat) computed from the polygons."""
    try:
        gj = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise SchemaError(f"{path.name}: not valid JSON ({exc})") from exc
    rows = []
    for feat in gj.get("features", []):
        props = {k.lower(): v for k, v in (feat.get("properties") or {}).items()}
        geom = feat.get("geometry") or {}
        if "locationid" not in props:
            raise SchemaError(f"{path.name}: a feature has no LocationID property")
        if geom.get("type") == "Polygon":
            polys = [geom["coordinates"]]
        elif geom.get("type") == "MultiPolygon":
            polys = geom["coordinates"]
        else:
            raise SchemaError(f"{path.name}: unsupported geometry {geom.get('type')!r}")
        lon, lat, area = polygon_centroid(polys)
        rows.append(
            {
                "location_id": int(props["locationid"]),
                "zone": props.get("zone"),
                "borough": props.get("borough"),
                "centroid_lon": lon,
                "centroid_lat": lat,
                "area_deg2": area,
            }
        )
    if not rows:
        raise SchemaError(f"{path.name}: no features found")
    df = pd.DataFrame(rows)
    if df["location_id"].duplicated().any():
        # the real file has a few zones split over several features: merge by area-weighted centroid
        merged = []
        for loc, g in df.groupby("location_id", sort=True):
            w = g["area_deg2"]
            merged.append(
                {
                    "location_id": loc,
                    "zone": g["zone"].iloc[0],
                    "borough": g["borough"].iloc[0],
                    "centroid_lon": float(np.average(g["centroid_lon"], weights=w)),
                    "centroid_lat": float(np.average(g["centroid_lat"], weights=w)),
                    "area_deg2": float(w.sum()),
                }
            )
        df = pd.DataFrame(merged)
    return df.sort_values("location_id").reset_index(drop=True)


def read_weather(path: Path) -> pd.DataFrame:
    """NOAA daily summaries in metric units: precipitation/snow in mm, temperatures in Celsius."""
    df = pd.read_csv(path)
    missing = sorted(set(WEATHER_COLUMNS) - set(df.columns))
    if missing:
        raise SchemaError(f"{path.name}: missing columns {missing}. Found: {sorted(df.columns)}")
    out = pd.DataFrame({"date": pd.to_datetime(df["DATE"], errors="raise").dt.normalize()})
    renames = {"PRCP": "prcp_mm", "SNOW": "snow_mm", "TMAX": "tmax_c", "TMIN": "tmin_c"}
    for src, dst in renames.items():
        out[dst] = pd.to_numeric(df[src], errors="coerce")
    if out["date"].duplicated().any():
        raise SchemaError(f"{path.name}: duplicate dates")
    return out.sort_values("date").reset_index(drop=True)
