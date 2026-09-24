"""Ingestion end to end, against a mocked publisher (no real network)."""

import io
import json
from pathlib import Path

import httpx
import pandas as pd
import pytest

from mobilityops.config import Settings
from mobilityops.ingestion.adapters import SchemaError
from mobilityops.ingestion.download import DownloadError
from mobilityops.ingestion.pipeline import (
    MonthRange,
    ingest_real,
    ingest_sample,
    load_manifest,
    parse_month,
)
from mobilityops.ingestion.sources import SourceConfig


class FakePublisher:
    """Serves small valid files for every URL the pipeline asks for, and counts requests."""

    def __init__(self, sample_files, *, missing_months: set[str] | None = None) -> None:  # type: ignore[no-untyped-def]
        trips = pd.read_parquet(sample_files.trips).head(3000)
        buf = io.BytesIO()
        trips.to_parquet(buf, index=False)
        self.trips_bytes = buf.getvalue()
        self.lookup = sample_files.zone_lookup.read_bytes()
        self.geojson = sample_files.zones_geojson.read_bytes()
        self.weather = sample_files.weather.read_bytes()
        self.requests: list[str] = []
        self.missing = missing_months or set()
        stamp = pd.Timestamp("2024-01-10 08:00")
        self.service_bytes: dict[str, bytes] = {}
        for prefix, cols in (
            (
                "green_tripdata",
                ("lpep_pickup_datetime", "lpep_dropoff_datetime", "trip_distance", "fare_amount"),
            ),
            (
                "fhvhv_tripdata",
                ("pickup_datetime", "dropoff_datetime", "trip_miles", "base_passenger_fare"),
            ),
        ):
            frame = pd.DataFrame(
                {
                    cols[0]: [stamp],
                    cols[1]: [stamp + pd.Timedelta(minutes=10)],
                    "PULocationID": [3],
                    cols[2]: [1.0],
                    cols[3]: [8.0],
                }
            )
            out = io.BytesIO()
            frame.to_parquet(out, index=False)
            self.service_bytes[prefix] = out.getvalue()

    def __call__(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        self.requests.append(url)
        if "yellow_tripdata_" in url:
            month = url.rsplit("_", 1)[-1].removesuffix(".parquet")
            if month in self.missing:
                return httpx.Response(404)
            return httpx.Response(200, content=self.trips_bytes)
        for prefix, content in self.service_bytes.items():
            if f"/{prefix}_" in url:
                return httpx.Response(200, content=content)
        if "taxi_zone_lookup" in url:
            return httpx.Response(200, content=self.lookup)
        if "geospatial" in url:
            return httpx.Response(200, content=self.geojson)
        if "ncei.noaa.gov" in url:
            return httpx.Response(200, content=self.weather)
        return httpx.Response(404)

    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self), follow_redirects=True)


@pytest.fixture()
def real_settings(tmp_path: Path) -> Settings:
    return Settings.from_env(
        {"MOBILITYOPS_DATA_DIR": str(tmp_path / "data"), "MOBILITYOPS_MODE": "real"}
    )


def test_month_range_and_window() -> None:
    r = MonthRange((2023, 11), (2024, 2))
    assert r.months() == [(2023, 11), (2023, 12), (2024, 1), (2024, 2)]
    start, end = r.window()
    assert (start.isoformat(), end.isoformat()) == ("2023-11-01", "2024-03-01")
    assert MonthRange((2024, 12), (2024, 12)).window()[1].isoformat() == "2025-01-01"
    with pytest.raises(ValueError, match="before start"):
        MonthRange((2024, 3), (2024, 1)).months()


@pytest.mark.parametrize("bad", ["2024", "2024-13", "24-01", "abc", "2024-00"])
def test_parse_month_rejects_garbage(bad: str) -> None:
    with pytest.raises(ValueError):
        parse_month(bad)


def test_real_ingest_writes_files_and_manifest(sample_files, real_settings: Settings) -> None:  # type: ignore[no-untyped-def]
    pub = FakePublisher(sample_files)
    m = ingest_real(real_settings, MonthRange((2024, 1), (2024, 2)), SourceConfig(), pub.client())
    names = sorted(Path(e.path).name for e in m.entries.values())
    assert names == [
        "taxi_zone_lookup.csv",
        "weather_daily.csv",
        "yellow_tripdata_2024-01.parquet",
        "yellow_tripdata_2024-02.parquet",
        "zones.geojson",
    ]
    trips = m.get("raw/real/yellow_tripdata_2024-01.parquet")
    assert trips is not None and trips.rows == 3000 and not trips.synthetic
    assert "tpep_pickup_datetime" in (trips.columns or {})
    assert m.window == {"start": "2024-01-01", "end": "2024-03-01"}
    # the manifest on disk is what the rest of the pipeline reads
    assert load_manifest(real_settings).window == m.window


def test_weather_request_covers_the_whole_window_inclusively(
    sample_files, real_settings: Settings
) -> None:  # type: ignore[no-untyped-def]
    pub = FakePublisher(sample_files)
    ingest_real(real_settings, MonthRange((2024, 2), (2024, 2)), SourceConfig(), pub.client())
    weather_url = next(u for u in pub.requests if "ncei.noaa.gov" in u)
    assert (
        "startDate=2024-02-01" in weather_url and "endDate=2024-02-29" in weather_url
    )  # leap year


def test_rerunning_ingestion_downloads_nothing_and_does_not_duplicate(
    sample_files, real_settings: Settings
) -> None:  # type: ignore[no-untyped-def]
    first = FakePublisher(sample_files)
    m1 = ingest_real(
        real_settings, MonthRange((2024, 1), (2024, 1)), SourceConfig(), first.client()
    )
    second = FakePublisher(sample_files)
    m2 = ingest_real(
        real_settings, MonthRange((2024, 1), (2024, 1)), SourceConfig(), second.client()
    )
    assert second.requests == []  # idempotent: everything unchanged, no network at all
    assert len(m1.entries) == len(m2.entries) == 4
    assert {e.sha256 for e in m1.entries.values()} == {e.sha256 for e in m2.entries.values()}


def test_unreleased_month_fails_clearly_and_keeps_earlier_months(
    sample_files, real_settings: Settings
) -> None:  # type: ignore[no-untyped-def]
    pub = FakePublisher(sample_files, missing_months={"2024-02"})
    with pytest.raises(DownloadError, match="HTTP 404"):
        ingest_real(real_settings, MonthRange((2024, 1), (2024, 2)), SourceConfig(), pub.client())
    assert (
        real_settings.raw_dir / "yellow_tripdata_2024-01.parquet"
    ).exists()  # valid data preserved
    assert not (real_settings.raw_dir / "yellow_tripdata_2024-02.parquet").exists()


def test_interrupted_ingestion_keeps_finished_files_and_resumes(
    sample_files, real_settings: Settings
) -> None:  # type: ignore[no-untyped-def]
    broken = FakePublisher(sample_files, missing_months={"2024-02"})
    with pytest.raises(DownloadError):
        ingest_real(
            real_settings, MonthRange((2024, 1), (2024, 2)), SourceConfig(), broken.client()
        )
    saved = load_manifest(real_settings)  # read back from disk: January survived the failure
    assert [e.path for e in saved.entries.values()] == ["raw/real/yellow_tripdata_2024-01.parquet"]
    fixed = FakePublisher(sample_files)
    ingest_real(real_settings, MonthRange((2024, 1), (2024, 2)), SourceConfig(), fixed.client())
    assert not any("yellow_tripdata_2024-01" in u for u in fixed.requests)  # not fetched again
    assert any("yellow_tripdata_2024-02" in u for u in fixed.requests)


def test_service_files_are_fetched_validated_and_recorded(
    sample_files, real_settings: Settings
) -> None:  # type: ignore[no-untyped-def]
    pub = FakePublisher(sample_files)
    m = ingest_real(
        real_settings,
        MonthRange((2024, 1), (2024, 1)),
        SourceConfig(),
        pub.client(),
        services=("green", "fhvhv"),
    )
    svc = sorted(e.path for e in m.entries.values() if e.source == "tlc_service_trips")
    assert svc == [
        "raw/real/fhvhv_tripdata_2024-01.parquet",
        "raw/real/green_tripdata_2024-01.parquet",
    ]
    assert all(e.rows == 1 for e in m.entries.values() if e.source == "tlc_service_trips")


def test_unknown_service_and_missing_columns_are_refused(
    sample_files, real_settings: Settings
) -> None:  # type: ignore[no-untyped-def]
    pub = FakePublisher(sample_files)
    with pytest.raises(ValueError, match="unknown service"):
        ingest_real(
            real_settings,
            MonthRange((2024, 1), (2024, 1)),
            SourceConfig(),
            pub.client(),
            services=("uber",),
        )
    bad = pd.DataFrame({"pickup_datetime": [pd.Timestamp("2024-01-10")], "PULocationID": [3]})
    out = io.BytesIO()
    bad.to_parquet(out, index=False)
    pub.service_bytes["fhvhv_tripdata"] = out.getvalue()
    with pytest.raises(SchemaError, match="trip_miles"):
        ingest_real(
            real_settings,
            MonthRange((2024, 1), (2024, 1)),
            SourceConfig(),
            pub.client(),
            services=("fhvhv",),
        )


def test_publisher_schema_change_is_caught_at_ingestion(
    sample_files, real_settings: Settings
) -> None:  # type: ignore[no-untyped-def]
    pub = FakePublisher(sample_files)
    buf = io.BytesIO()
    pd.read_parquet(io.BytesIO(pub.trips_bytes)).drop(columns=["PULocationID"]).to_parquet(
        buf, index=False
    )
    pub.trips_bytes = buf.getvalue()
    with pytest.raises(SchemaError, match="PULocationID"):
        ingest_real(real_settings, MonthRange((2024, 1), (2024, 1)), SourceConfig(), pub.client())


def test_real_ingest_refuses_sample_mode(sample_files, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    s = Settings.from_env({"MOBILITYOPS_DATA_DIR": str(tmp_path), "MOBILITYOPS_MODE": "sample"})
    with pytest.raises(RuntimeError, match="MOBILITYOPS_MODE=real"):
        ingest_real(
            s,
            MonthRange((2024, 1), (2024, 1)),
            SourceConfig(),
            FakePublisher(sample_files).client(),
        )


def test_sample_ingest_registers_synthetic_files(sample_files, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    s = Settings.from_env(
        {"MOBILITYOPS_DATA_DIR": str(tmp_path / "d"), "MOBILITYOPS_MODE": "sample"}
    )
    s.ensure_dirs()
    for f in sample_files.directory.iterdir():
        (s.raw_dir / f.name).write_bytes(f.read_bytes())
    m = ingest_sample(s)
    assert len(m.entries) == 4 and all(e.synthetic for e in m.entries.values())
    assert m.window == {"start": "2024-01-01", "end": "2024-02-26"}  # 56 days
    assert json.loads((s.manifests_dir / "manifest.json").read_text())["window"] == m.window


def test_sample_ingest_without_data_says_what_to_do(tmp_path: Path) -> None:
    s = Settings.from_env({"MOBILITYOPS_DATA_DIR": str(tmp_path), "MOBILITYOPS_MODE": "sample"})
    with pytest.raises(FileNotFoundError, match="make sample"):
        ingest_sample(s)
