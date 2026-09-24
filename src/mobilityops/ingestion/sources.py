"""Where the data comes from. Every URL is configurable and documented here.

Nothing downstream hard-codes a URL: change a source by changing this config (or the matching
environment variable), not by editing pipeline code.

Terms of use: these are public datasets published by their owners. Consult the owners' pages
listed in ``USAGE_NOTES`` for current terms before redistributing any data; this repository does
not redistribute the raw files.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date

USAGE_NOTES: dict[str, str] = {
    "tlc_trips": (
        "NYC Taxi & Limousine Commission Trip Record Data: "
        "https://www.nyc.gov/site/tlc/about/tlc-trip-record-data.page"
    ),
    "tlc_service_trips": (
        "NYC TLC Trip Record Data, green taxi and high-volume for-hire vehicle files: "
        "https://www.nyc.gov/site/tlc/about/tlc-trip-record-data.page"
    ),
    "tlc_zone_lookup": "NYC TLC taxi zone lookup table (same page as the trip records).",
    "zones_geojson": "NYC Open Data, NYC Taxi Zones: https://data.cityofnewyork.us/d/8meu-9t5y",
    "noaa_daily": "NOAA NCEI GHCN-Daily via the NCEI Access Data Service: https://www.ncei.noaa.gov/",
}


@dataclass(frozen=True)
class SourceConfig:
    tlc_trips_template: str = (
        "https://d37ci6vzurychx.cloudfront.net/trip-data/yellow_tripdata_{year}-{month:02d}.parquet"
    )
    # Same host and naming as the yellow files: green_tripdata_YYYY-MM, fhvhv_tripdata_YYYY-MM.
    service_template: str = (
        "https://d37ci6vzurychx.cloudfront.net/trip-data/{prefix}_{year}-{month:02d}.parquet"
    )
    zone_lookup_url: str = "https://d37ci6vzurychx.cloudfront.net/misc/taxi_zone_lookup.csv"
    zones_geojson_url: str = (
        "https://data.cityofnewyork.us/api/geospatial/8meu-9t5y?method=export&format=GeoJSON"
    )
    noaa_url: str = "https://www.ncei.noaa.gov/access/services/data/v1"
    noaa_station: str = "USW00094728"  # New York Central Park, the standard NYC reference station

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> SourceConfig:
        e = os.environ if env is None else env
        d = cls()
        return cls(
            tlc_trips_template=e.get("MOBILITYOPS_TLC_URL_TEMPLATE", d.tlc_trips_template),
            service_template=e.get("MOBILITYOPS_TLC_SERVICE_URL_TEMPLATE", d.service_template),
            zone_lookup_url=e.get("MOBILITYOPS_ZONE_LOOKUP_URL", d.zone_lookup_url),
            zones_geojson_url=e.get("MOBILITYOPS_ZONES_GEOJSON_URL", d.zones_geojson_url),
            noaa_url=e.get("MOBILITYOPS_NOAA_URL", d.noaa_url),
            noaa_station=e.get("MOBILITYOPS_NOAA_STATION", d.noaa_station),
        )

    def trips_url(self, year: int, month: int) -> str:
        return self.tlc_trips_template.format(year=year, month=month)

    def service_url(self, prefix: str, year: int, month: int) -> str:
        return self.service_template.format(prefix=prefix, year=year, month=month)

    def weather_url(self, start: date, end: date) -> str:
        """Daily summaries in metric units. ``end`` is inclusive, as the NCEI service expects."""
        return (
            f"{self.noaa_url}?dataset=daily-summaries&stations={self.noaa_station}"
            f"&startDate={start.isoformat()}&endDate={end.isoformat()}"
            "&dataTypes=PRCP,SNOW,TMAX,TMIN&format=csv&units=metric"
        )
