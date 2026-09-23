# Data dictionary

Everything here describes what the pipeline actually produces. Timestamps are **New York local
time, no timezone** (that is how the TLC publishes them); see "Time" below.

## Sources (bronze: `data/raw/<mode>/`, described by `data/manifests/<mode>/manifest.json`)

| Source | What | URL config | Notes |
|---|---|---|---|
| `tlc_trips` | NYC TLC yellow-taxi trip records, one Parquet file per month | `MOBILITYOPS_TLC_URL_TEMPLATE` | Terms: see the TLC Trip Record Data page (`ingestion/sources.py`). Not redistributed by this repo. |
| `tlc_zone_lookup` | Zone id -> borough / zone name / service zone | `MOBILITYOPS_ZONE_LOOKUP_URL` | Includes ids 264/265, which are "unknown", not real zones. |
| `zones_geojson` | Zone polygons (lon/lat) from NYC Open Data | `MOBILITYOPS_ZONES_GEOJSON_URL` | Some zone ids have no polygon (see `dim_zone`). |
| `noaa_daily` | NOAA GHCN-Daily summaries, station USW00094728 (Central Park), metric units | `MOBILITYOPS_NOAA_URL`, `MOBILITYOPS_NOAA_STATION` | One station stands in for the whole city (see limitations). |

The manifest records, per file: source URL, size, SHA-256, retrieval time (UTC), row count and the
column names/types actually found. Sample mode writes the same manifest with `synthetic: true`.

## Time

* TLC pickup/dropoff times are stored as **naive local timestamps**.
* Spring forward: the local hour 02:00-02:59 does not exist. `dim_hour.is_dst_gap = true`, and the
  hour is **absent from the demand grid** (`is_valid = false`), so it is never mistaken for a
  demand collapse.
* Fall back: the local hour 01:00-01:59 occurs twice, so a local-hour count merges two real hours.
  `dim_hour.is_dst_overlap = true`; the hour stays in the grid but `is_modelable = false`.

## Silver: `data/processed/<mode>/silver/`

### `trips.parquet` (grain: one cleaned trip; no primary key exists in the source)

| Column | Type | Meaning |
|---|---|---|
| `pickup_ts`, `dropoff_ts` | timestamp | Local times |
| `pu_zone`, `do_zone` | int | Pickup / dropoff zone id |
| `passenger_count` | double | As reported by the driver; may be 0 |
| `trip_distance` | double | Miles |
| `fare_amount`, `total_amount` | double | Dollars |
| `payment_type` | int | TLC code |
| `source_file` | string | Raw file the row came from |

### `trips_rejected.parquet` (the quarantine: same columns plus `reject_reason`)

Every rejected row is kept here with the **first** rule it failed, in this order:

| Rule | Why |
|---|---|
| `missing_required_value` | Cannot be timed or attributed to a zone |
| `pickup_out_of_window` | The TLC files contain rows dated years outside their month |
| `dropoff_before_pickup` | Impossible ordering |
| `excessive_duration` | Longer than 6 hours: almost always a meter left running |
| `negative_amount` | Refunds/disputes, not completed trips for demand purposes. **This is a judgement call and the largest rule by count on real data (~1.3%)** |
| `invalid_distance` | Negative, or over 200 miles |
| `unknown_pickup_zone` | TLC ids 264/265, or ids not in the zone table |
| `duplicate_row` | Exact duplicate of a kept row |

## Gold: `data/processed/<mode>/mobilityops.duckdb`

Built in a side file and promoted only if every quality check passes.

### `dim_zone` (grain: one taxi zone; PK `location_id`)

`location_id`, `borough`, `zone`, `service_zone` (from the lookup), `centroid_lon`, `centroid_lat`,
`area_deg2` (computed from the polygons; NULL when the source has no polygon), `is_real_zone`
(false for TLC ids 264/265).

Real data: 3 real zones have no polygon (57 Corona, 104 and 105 Governor's Island). They carry a
negligible amount of demand (11 pickups in January 2024) and are skipped by the optimisation.

### `dim_date` (grain: one local date; PK `date`)

`day_of_week` (Monday = 0), `day_name`, `is_weekend`, `is_holiday`, `holiday_name` (US federal
holidays from pandas' calendar).

### `dim_hour` (grain: one local hour; PK `hour_ts`)

`date`, `hour_of_day`, `day_of_week`, `is_weekend`, `is_holiday`, `is_dst_gap`, `is_dst_overlap`,
`is_valid` (= not a DST gap), `is_modelable` (= valid and not a DST overlap).

### `fact_zone_hourly_demand` (grain: real zone x valid local hour; PK `(location_id, hour_ts)`)

| Column | Meaning |
|---|---|
| `pickups` | Cleaned trips starting in that zone and hour. **Zero-filled**: a quiet hour is an explicit 0 |
| `dropoffs` | Cleaned trips ending in that zone and hour (by dropoff time) |
| `revenue` | Sum of `total_amount` of those pickups |
| `passengers` | Sum of `passenger_count` of those pickups |

Zones x hours is complete by construction and checked by a quality rule.

### `fact_weather_daily` (grain: one date; PK `date`)

`prcp_mm`, `snow_mm`, `tmax_c`, `tmin_c`, and derived flags `is_rain` (>= 1 mm), `is_snow` (> 0 mm),
`is_freezing` (max temperature <= 0 C). Days with no reading have NULL measurements.

### `pipeline_run` (one row per successful build)

`run_id`, `mode`, `built_at_utc`, `git_commit`, `window_start`/`window_end`, `rows_in`,
`rows_valid`, `rows_rejected`, library versions, and `synthetic` (true in sample mode).

### `quality_result` (grain: one check result per run)

`run_id`, `stage` (bronze/silver/gold), `check`, `status` (PASS/WARN/FAIL), `message`.

The trip-level table is not copied into DuckDB; it stays in Parquet and is queried in place.
