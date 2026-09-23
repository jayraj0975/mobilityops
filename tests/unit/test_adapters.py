import json
from pathlib import Path

import pandas as pd
import pytest

from mobilityops.ingestion.adapters import (
    SchemaError,
    canonical_trip_columns,
    inspect_trips,
    read_weather,
    read_zone_lookup,
    read_zones_geojson,
)


def test_inspect_real_shaped_file(sample_files) -> None:  # type: ignore[no-untyped-def]
    info = inspect_trips(sample_files.trips)
    assert info.rows > 100_000
    assert "tpep_pickup_datetime" in info.columns
    assert set(info.canonical.values()) >= {"PULocationID", "fare_amount"}


def test_column_name_variants_are_recognised() -> None:
    m = canonical_trip_columns(
        ["lpep_pickup_datetime", "PULocationID", "extra_col", "DOLOCATIONID"]
    )
    assert m == {
        "lpep_pickup_datetime": "tpep_pickup_datetime",
        "PULocationID": "PULocationID",
        "DOLOCATIONID": "DOLocationID",
    }


def test_missing_required_column_gives_an_actionable_error(tmp_path: Path) -> None:
    p = tmp_path / "bad.parquet"
    pd.DataFrame(
        {"tpep_pickup_datetime": pd.to_datetime(["2024-01-01"]), "fare_amount": [5.0]}
    ).to_parquet(p)
    with pytest.raises(SchemaError) as e:
        inspect_trips(p)
    msg = str(e.value)
    assert "PULocationID" in msg and "Found columns" in msg  # says what is missing AND what exists


def test_corrupt_parquet_is_a_schema_error_not_a_crash(tmp_path: Path) -> None:
    p = tmp_path / "corrupt.parquet"
    p.write_bytes(b"this is not parquet")
    with pytest.raises(SchemaError, match="not a readable Parquet"):
        inspect_trips(p)


def test_empty_file_is_rejected(tmp_path: Path, sample_files) -> None:  # type: ignore[no-untyped-def]
    p = tmp_path / "empty.parquet"
    pd.read_parquet(sample_files.trips).head(0).to_parquet(p)
    with pytest.raises(SchemaError, match="no rows"):
        inspect_trips(p)


def test_zone_lookup_validation(sample_files, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    df = read_zone_lookup(sample_files.zone_lookup)
    assert len(df) == 12 and df["LocationID"].is_unique
    dup = tmp_path / "dup.csv"
    dup.write_text("LocationID,Borough,Zone,service_zone\n1,A,B,C\n1,A,B,C\n")
    with pytest.raises(SchemaError, match="duplicate"):
        read_zone_lookup(dup)


def test_geojson_centroids_are_the_square_centres(sample_files) -> None:  # type: ignore[no-untyped-def]
    z = read_zones_geojson(sample_files.zones_geojson).set_index("location_id")
    # zone 1 is the square with corner (-74.02, 40.70), side 0.02
    assert z.loc[1, "centroid_lon"] == pytest.approx(-74.01)
    assert z.loc[1, "centroid_lat"] == pytest.approx(40.71)
    assert len(z) == 12


def test_geojson_split_zones_are_merged(tmp_path: Path) -> None:
    def feat(x0: float) -> dict[str, object]:
        ring = [[x0, 0], [x0 + 1, 0], [x0 + 1, 1], [x0, 1], [x0, 0]]
        return {
            "type": "Feature",
            "properties": {"locationid": "5", "zone": "Z", "borough": "B"},
            "geometry": {"type": "Polygon", "coordinates": [ring]},
        }

    p = tmp_path / "z.geojson"
    p.write_text(json.dumps({"type": "FeatureCollection", "features": [feat(0), feat(2)]}))
    z = read_zones_geojson(p)
    assert len(z) == 1 and z.loc[0, "centroid_lon"] == pytest.approx(1.5)


def test_weather_reader_converts_units_and_names(sample_files) -> None:  # type: ignore[no-untyped-def]
    w = read_weather(sample_files.weather)
    assert list(w.columns) == ["date", "prcp_mm", "snow_mm", "tmax_c", "tmin_c"]
    assert w["date"].is_monotonic_increasing and w["date"].is_unique
    assert (w["prcp_mm"] >= 0).all()


def test_weather_duplicate_dates_rejected(tmp_path: Path) -> None:
    p = tmp_path / "w.csv"
    p.write_text("STATION,DATE,PRCP,SNOW,TMAX,TMIN\nX,2024-01-01,0,0,5,1\nX,2024-01-01,1,0,5,1\n")
    with pytest.raises(SchemaError, match="duplicate dates"):
        read_weather(p)
