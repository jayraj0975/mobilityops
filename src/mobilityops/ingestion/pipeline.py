"""Ingestion orchestration: fetch (or register) sources, validate them, and write the manifest.

Real mode downloads the TLC trip files for the requested months plus the zone tables and NOAA
weather. Sample mode registers the already-generated synthetic files. Either way the result is the
same: raw files under ``data/raw/<mode>/`` and a manifest describing exactly what is there.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import httpx

from mobilityops.config import Settings
from mobilityops.ingestion import adapters
from mobilityops.ingestion.download import download, sha256_file
from mobilityops.ingestion.manifest import Manifest, ManifestEntry, utc_now
from mobilityops.ingestion.sources import USAGE_NOTES, SourceConfig
from mobilityops.log import get_logger

log = get_logger("ingestion")

ZONE_LOOKUP_NAME = "taxi_zone_lookup.csv"
ZONES_GEOJSON_NAME = "zones.geojson"
WEATHER_NAME = "weather_daily.csv"


@dataclass(frozen=True)
class MonthRange:
    start: tuple[int, int]  # (year, month), inclusive
    end: tuple[int, int]  # (year, month), inclusive

    def months(self) -> list[tuple[int, int]]:
        (y, m), (ye, me) = self.start, self.end
        out = []
        while (y, m) <= (ye, me):
            out.append((y, m))
            y, m = (y + 1, 1) if m == 12 else (y, m + 1)
        if not out:
            raise ValueError("end month is before start month")
        return out

    def window(self) -> tuple[date, date]:
        """[start, end) half-open date window covered by the requested months."""
        ye, me = self.end
        end = date(ye + 1, 1, 1) if me == 12 else date(ye, me + 1, 1)
        return date(*self.start, 1), end


def parse_month(text: str) -> tuple[int, int]:
    try:
        y, m = text.split("-")
        year, month = int(y), int(m)
    except ValueError as exc:
        raise ValueError(f"expected YYYY-MM, got {text!r}") from exc
    if not (1 <= month <= 12 and 2009 <= year <= 2100):
        raise ValueError(f"month out of range: {text!r}")
    return year, month


def _entry(
    settings: Settings,
    source: str,
    url: str,
    path: Path,
    sha256: str,
    retrieved_at: str,
    *,
    rows: int | None = None,
    columns: dict[str, str] | None = None,
    synthetic: bool = False,
) -> ManifestEntry:
    return ManifestEntry(
        source=source,
        url=url,
        path=path.relative_to(settings.data_dir).as_posix(),
        bytes=path.stat().st_size,
        sha256=sha256,
        retrieved_at=retrieved_at,
        rows=rows,
        columns=columns,
        synthetic=synthetic,
        usage_note=USAGE_NOTES.get(source, ""),
    )


def _fetch(
    settings: Settings,
    manifest: Manifest,
    source: str,
    url: str,
    dest: Path,
    client: httpx.Client | None,
) -> tuple[Path, str, str]:
    known = manifest.get(dest.relative_to(settings.data_dir).as_posix())
    res = download(url, dest, client=client, known=known)
    return res.path, res.sha256, res.retrieved_at


def ingest_real(
    settings: Settings,
    months: MonthRange,
    sources: SourceConfig | None = None,
    client: httpx.Client | None = None,
) -> Manifest:
    """Download and validate real data. Existing valid files are kept; nothing is deleted."""
    if settings.mode != "real":
        raise RuntimeError("ingest_real requires MOBILITYOPS_MODE=real")
    sources = sources or SourceConfig.from_env()
    settings.ensure_dirs()
    manifest_path = settings.manifests_dir / "manifest.json"
    manifest = Manifest.load(manifest_path)
    start, end = months.window()

    for year, month in months.months():
        dest = settings.raw_dir / f"yellow_tripdata_{year}-{month:02d}.parquet"
        url = sources.trips_url(year, month)
        path, digest, when = _fetch(settings, manifest, "tlc_trips", url, dest, client)
        info = adapters.inspect_trips(path)  # raises SchemaError with an actionable message
        manifest.upsert(
            _entry(
                settings, "tlc_trips", url, path, digest, when, rows=info.rows, columns=info.columns
            )
        )
        log.info(
            "trips ingested", extra={"ctx": {"month": f"{year}-{month:02d}", "rows": info.rows}}
        )

    tables = (
        ("tlc_zone_lookup", sources.zone_lookup_url, ZONE_LOOKUP_NAME, adapters.read_zone_lookup),
        (
            "zones_geojson",
            sources.zones_geojson_url,
            ZONES_GEOJSON_NAME,
            adapters.read_zones_geojson,
        ),
        (
            "noaa_daily",
            sources.weather_url(start, end - timedelta(days=1)),
            WEATHER_NAME,
            adapters.read_weather,
        ),
    )
    for source, url, name, reader in tables:
        path, digest, when = _fetch(
            settings, manifest, source, url, settings.raw_dir / name, client
        )
        frame = reader(path)  # validates structure; raises SchemaError otherwise
        manifest.upsert(
            _entry(
                settings,
                source,
                url,
                path,
                digest,
                when,
                rows=len(frame),
                columns={str(c): str(t) for c, t in frame.dtypes.items()},
            )
        )

    manifest.window = {"start": start.isoformat(), "end": end.isoformat()}
    manifest.save(manifest_path)
    return manifest


def ingest_sample(settings: Settings) -> Manifest:
    """Register the already-generated SYNTHETIC files. Requires ``make sample`` first."""
    if settings.mode != "sample":
        raise RuntimeError("ingest_sample requires MOBILITYOPS_MODE=sample")
    raw = settings.raw_dir
    trips = raw / "yellow_tripdata_sample.parquet"
    meta = raw / "sample_meta.json"
    if not trips.exists() or not meta.exists():
        raise FileNotFoundError(f"no sample data in {raw}. Run `make sample` first.")
    settings.ensure_dirs()
    manifest = Manifest()
    when = utc_now()
    info = adapters.inspect_trips(trips)
    manifest.upsert(
        _entry(
            settings,
            "tlc_trips",
            "synthetic",
            trips,
            sha256_file(trips),
            when,
            rows=info.rows,
            columns=info.columns,
            synthetic=True,
        )
    )
    for source, name, reader in (
        ("tlc_zone_lookup", ZONE_LOOKUP_NAME, adapters.read_zone_lookup),
        ("zones_geojson", ZONES_GEOJSON_NAME, adapters.read_zones_geojson),
        ("noaa_daily", WEATHER_NAME, adapters.read_weather),
    ):
        p = raw / name
        frame = reader(p)
        manifest.upsert(
            _entry(
                settings,
                source,
                "synthetic",
                p,
                sha256_file(p),
                when,
                rows=len(frame),
                columns={str(c): str(t) for c, t in frame.dtypes.items()},
                synthetic=True,
            )
        )
    manifest.window = json.loads(meta.read_text())["window"]
    manifest.save(settings.manifests_dir / "manifest.json")
    return manifest


def load_manifest(settings: Settings) -> Manifest:
    path = settings.manifests_dir / "manifest.json"
    if not path.exists():
        raise FileNotFoundError(f"no manifest at {path}. Run the ingest command first.")
    return Manifest.load(path)
