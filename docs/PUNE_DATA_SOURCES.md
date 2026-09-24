# Pune data sources: what exists, what was verified, what is used

Investigated on **2026-09-24**. "Verified" means the endpoint was actually called (or the page actually read)
on that date and the fact below was observed; anything else is marked **not verified**. Nothing here is
assumed from a source's marketing text, and no source was scraped.

## The finding that shapes the product

**No open, live source of Pune taxi, ride-hail or bus *demand* was found.** New York publishes every taxi
trip (the TLC files this project already processes); Pune does not. The sources that do exist for Pune are
environmental context (weather, air quality), map data (OpenStreetMap), and static or annual transport data.
So the Pune part of MobilityOps is built as follows, and the interface says the same everywhere:

| Layer | Pune | Label shown |
|---|---|---|
| Weather now | Open-Meteo, real | NEAR-REAL-TIME (modelled, 15-minute steps) |
| Air quality now | Open-Meteo / CAMS model, real | NEAR-REAL-TIME, **MODELLED** (not a station reading) |
| Weather history | Open-Meteo archive (ERA5), real | HISTORICAL |
| Zones and map | OpenStreetMap place nodes, real | STATIC |
| Mobility **demand** | a documented generator conditioned on the real weather and the Indian calendar | **SIMULATED**, never LIVE |
| Forecasts, anomalies, scenarios | computed from the simulated demand | PREDICTED / SIMULATED |
| Traffic, transit feeds | adapters exist; **disabled** until an owner supplies a key or feed | not available |

The New York pipeline (real TLC data) stays as the reference city where every model was validated on real
observations; Pune runs the same pipeline on simulated demand. Results on Pune demand say nothing about real
Pune traffic, and the documentation and interface never suggest otherwise.

## Sources

| # | Source | Owner | Access | Licence | Update frequency | Status |
|---|---|---|---|---|---|---|
| 1 | Open-Meteo Forecast API, `current` | Open-Meteo | no key | data CC BY 4.0; free tier **non-commercial only** | `interval: 900` s (observed) | **Verified, used** |
| 2 | Open-Meteo Air Quality API, `current` | Open-Meteo (CAMS model data) | no key | as above | `interval: 3600` s (observed) | **Verified, used** |
| 3 | Open-Meteo Archive API (ERA5 reanalysis) | Open-Meteo | no key | as above | historical; hourly | **Verified, used** |
| 4 | OpenStreetMap place nodes via Overpass | OpenStreetMap contributors | no key | ODbL 1.0, attribution required | continuous; fetched once at build time | **Verified, used** |
| 5 | OSM administrative boundaries | OpenStreetMap contributors | no key | ODbL | continuous | Verified to exist, only the bounding box used |
| 6 | PMPML bus GTFS (`croyla/pmpml-gtfs`) | **unofficial**, community | GitHub | tool MIT-0; **data terms unknown** | unspecified | Not bundled; adapter reads a feed the operator supplies |
| 7 | PMPML live bus positions | PMPML | none found | none found | n/a | **No official open API found**; not integrated |
| 8 | Pune Metro (Maha Metro) GTFS | Maha Metro | none found | none found | n/a | **Not found**; not integrated |
| 9 | Pune Municipal Corporation open data portal | PMC | login link; no API | policy page states none | periodic | Exists; **licence not stated**, not integrated |
| 10 | OGD India / Smart Cities data portal | Government of India | portal | NDSAP | annual or static | Pune datasets exist (vehicle registrations 2014 to 2020); not verified in detail, not integrated |
| 11 | TomTom Traffic Flow (Flow Segment Data) | TomTom | **API key** | terms not verified | on request | Free tier of 20,000 requests a month per its pricing page; **adapter built, disabled without a key, never called** |
| 12 | OpenAQ v3 | OpenAQ | **API key** (HTTP 401 without one, verified) | CC BY 4.0 (not verified here) | station-dependent | Optional adapter, disabled without a key, never called |
| 13 | IISc PUDX (Pune Urban Data Exchange) | IISc | page returned 404 | unknown | unknown | Status unknown; not used |

### 1. Open-Meteo forecast (current weather)

* **Endpoint:** `https://api.open-meteo.com/v1/forecast?latitude=…&longitude=…&current=temperature_2m,relative_humidity_2m,precipitation,wind_speed_10m,weather_code&timezone=Asia/Kolkata`.
* **Verified:** HTTP 200 in about 0.55 s; the response carries `current.time` (the observation step, local time),
  `current.interval` (900 s) and the values; several locations can be requested at once (a 9-point grid answered in
  0.59 s with different values per point, 23.2 to 24.5 °C).
* **What "current" is:** the latest step of Open-Meteo's weather model blend at the requested coordinates, not a
  measurement at a weather station. It is near-real-time, not live, and is labelled that way.
* **Limits (from their terms page):** 600 calls a minute, 5,000 an hour, fewer than 10,000 a day; non-commercial use
  only; CC BY 4.0 attribution. The platform polls at most once every 15 minutes.
* **Redistribution:** allowed with attribution under CC BY 4.0; the interface shows "Weather data by Open-Meteo.com".

### 2. Open-Meteo air quality

* **Endpoint:** `https://air-quality-api.open-meteo.com/v1/air-quality?latitude=…&longitude=…&current=pm10,pm2_5,us_aqi`.
* **Verified:** HTTP 200; `interval: 3600`; PM2.5 21.2, PM10 24.7 and US AQI 117 at 20:30 IST on the test day.
* **Caveat that must stay visible:** these are *modelled* (atmospheric-composition model, coarse grid), not readings
  from a Pune monitoring station. They are labelled MODELLED wherever shown.

### 3. Open-Meteo archive (history)

* **Endpoint:** `https://archive-api.open-meteo.com/v1/archive?…&start_date=…&end_date=…&hourly=temperature_2m,precipitation,relative_humidity_2m`.
* **Verified:** HTTP 200 in about 0.55 s; 48 hourly values for two days. ERA5 reanalysis at roughly 10 km resolution;
  it lags real time by a few days, so it is history, never "current".

### 4. OpenStreetMap places (zone seeds)

* **Verified:** one Overpass query for `place=suburb|neighbourhood|quarter` nodes inside 18.40 to 18.68 N,
  73.70 to 74.02 E returned **134 named places** (69 suburbs, 65 neighbourhoods; 98 with an English name), in 5 s.
* **Policy (from the OSM wiki):** public Overpass instances are for light use (about 100 queries and 10 MB a day for a
  regular application), calls must be cached and rate-limited, and the client must send an identifying
  `User-Agent`. **So OSM is queried once by `scripts/build_pune_zones.py`, the result is committed, and nothing
  queries Overpass at run time.**
* **Licence:** ODbL 1.0. The committed zone file is a derived database and carries the attribution
  "© OpenStreetMap contributors" and the ODbL notice; the code stays MIT.
* **What the zones are:** each zone is the service area of one OSM suburb (the region closer to it than to any other
  suburb, clipped to the study area). They are an analytical tessellation, **not** official wards or
  administrative boundaries; no ward polygons were found in OSM.

### 6 to 10. Transit and municipal data

* `croyla/pmpml-gtfs` says of itself that it "connects to the Apli-PMPML (Chartr) API" to build a static GTFS (no
  real-time), is published by a private user, and states no terms for the underlying data. The generating tool is
  MIT-0; that does not license the upstream data. It is therefore not bundled or fetched. The GTFS adapter reads a
  zip the operator provides and reports its provenance.
* No official PMPML or Pune Metro real-time feed was found. The search that suggested one described community
  projects, not a published API.
* The PMC portal is a login-based site with no CKAN API (`/api/3/action/package_list` returned 404) and its policy page
  gives no licence text; datasets there would need a manual, reviewed download.

### 11 to 12. Sources that need a key

TomTom and OpenAQ adapters are implemented so a real feed can be plugged in, with the key read from the environment.
They are **off by default, were never called, and are not verified to work**. Enabling TomTom additionally
requires the owner to read its terms on caching and redistribution, which this investigation did not verify.

## What "live" means in this product

| Class | Meaning | Used for |
|---|---|---|
| LIVE | observations pushed or polled within seconds of being made | none in Pune (no such source) |
| NEAR-REAL-TIME | latest model or observation step, minutes old by design | weather (15 min), air quality (60 min) |
| RECENT | within the last day | recent computed windows |
| HISTORICAL | complete past data | ERA5 weather, NYC TLC |
| PREDICTED | a forecast | forecasts, always with a range |
| SIMULATED | produced by a model of how demand behaves | Pune mobility demand and scenarios |

The interface derives the freshness state (LIVE, DELAYED, STALE, OFFLINE) from the source's own timestamps and the
time we received the data, never from a flag we set.

## Re-running the investigation

```bash
curl -s "https://api.open-meteo.com/v1/forecast?latitude=18.5204&longitude=73.8567&current=temperature_2m&timezone=Asia/Kolkata"
curl -s "https://air-quality-api.open-meteo.com/v1/air-quality?latitude=18.5204&longitude=73.8567&current=pm2_5,us_aqi"
python scripts/build_pune_zones.py --dry-run     # one polite Overpass query; prints the count
```
