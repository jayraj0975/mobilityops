# Data dictionary

Everything here describes what the pipeline actually produces. Timestamps are **New York local
time, no timezone** (that is how the TLC publishes them); see "Time" below.

## Sources (bronze: `data/raw/<mode>/`, described by `data/manifests/<mode>/manifest.json`)

| Source | What | URL config | Notes |
|---|---|---|---|
| `tlc_trips` | NYC TLC yellow-taxi trip records, one Parquet file per month | `MOBILITYOPS_TLC_URL_TEMPLATE` | Terms: see the TLC Trip Record Data page (`ingestion/sources.py`). Not redistributed by this repo. |
| `tlc_service_trips` | Optional: NYC TLC green-taxi (`green_tripdata_*`) and high-volume for-hire (`fhvhv_tripdata_*`, Uber/Lyft and similar) files, one Parquet file per month and service | `MOBILITYOPS_TLC_SERVICE_URL_TEMPLATE` | Fetched with `ingest --services green,fhvhv`. The for-hire files are about 470 MB and 20 million trips a month. The older "FHV" (non high-volume) files are not used. Not redistributed by this repo. |
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
| `negative_amount` | Refunds/disputes, not completed trips for demand purposes. **This is a judgement call and the largest rule by count on real data (1.8% of all 2024 rows; 1.3% of January's, 2.2% of December's)** |
| `invalid_distance` | Negative, or over 200 miles |
| `unknown_pickup_zone` | TLC ids 264/265, or ids not in the zone table |
| `duplicate_row` | Exact duplicate of a kept row |

### `service_<name>_hourly.parquet` (green taxis and for-hire vehicles; grain: zone x local hour)

These services are aggregated straight to pickup counts instead of being kept trip by trip (the
for-hire file alone would add gigabytes). Columns: `service`, `location_id`, `hour_ts`, `pickups`
(only hours that had trips). The same ordered rules as for yellow taxis are applied to each
family's own columns (`schema.SERVICE_SPECS`: pickup and dropoff time, pickup zone, `trip_distance`
or `trip_miles`, and `fare_amount` or `base_passenger_fare` for the refund rule). Rejected rows are
**counted** by first failing rule and by file in `service_<name>_hourly.summary.json` but not
written out. Exact-duplicate removal is the one rule not applied (it needs the whole trip table in
memory; the yellow data has 4 duplicates in 41 million rows).

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

### `dim_service` and `fact_service_zone_hourly` (only when a green or for-hire file was ingested)

`fact_service_zone_hourly` has one row per service x real zone x valid local hour (PK
`(service, location_id, hour_ts)`), zero-filled like the yellow fact table. Its `pickups` column
is a BIGINT because for-hire counts are large. The `yellow` rows are copied from
`fact_zone_hourly_demand`, and a quality check confirms they match. Each other service is checked
against its cleaned trips in valid hours.

### `dq_unallocated_dropoffs` (grain: reason x dropoff zone)

Trips whose **dropoff** is not in `fact_zone_hourly_demand`: `reason` is `unknown_dropoff_zone` (the id is
missing, or is one of the TLC's "unknown" ids 264 and 265, or is not a real zone; `do_zone` says which) or
`dropoff_outside_grid` (the dropoff hour is outside the window, for example a trip that ends after midnight on the
last day; `do_zone` is null). Pickups are validated by *rejecting* the trip; dropoffs are validated by
*accounting*: the trip's pickup is real demand, so it stays, and its dropoff is counted here. A quality check
requires placed dropoffs + this table = silver trips exactly, and warns above 2%. On the 2024 yellow data 273,264
trips (0.68%) are here: 158,436 to zone 265, 114,324 to zone 264 and 504 after the window ends.

### `fact_weather_daily` (grain: one date; PK `date`)

`prcp_mm`, `snow_mm`, `tmax_c`, `tmin_c`, and derived flags `is_rain` (>= 1 mm), `is_snow` (> 0 mm),
`is_freezing` (max temperature <= 0 C). Days with no reading have NULL measurements.

### `pipeline_run` (one row per successful build)

`run_id`, `mode`, `built_at_utc`, `git_commit`, `window_start`/`window_end`, `rows_in`,
`rows_valid`, `rows_rejected`, library versions, and `synthetic` (true in sample mode).

### `quality_result` (grain: one check result per run)

`run_id`, `stage` (bronze/silver/gold), `check`, `status` (PASS/WARN/FAIL), `message`.

The trip-level table is not copied into DuckDB; it stays in Parquet and is queried in place.

---

# Derived artifacts

Generated by the commands in [EVALUATION](EVALUATION.md); written to `artifacts/<mode>/`
(git-ignored). Every JSON document carries `mode`, `data_label` (`TEST / SYNTHETIC DATA` or
`real data`) and `data_run_id`, the `pipeline_run.run_id` of the database it was computed from.
Timestamps are New York local time with no timezone.

## `forecast/predictions.parquet` (grain: zone x hour, out-of-sample test days only)

| Column | Meaning |
|---|---|
| `fold` | walk-forward fold whose model produced the row (0 = earliest) |
| `zone_index`, `location_id` | position in the demand tensor / TLC location id |
| `day_index`, `hour`, `hour_ts` | day position in the tensor, local hour 0-23, local timestamp |
| `y` | actual pickups |
| `lightgbm`, `lo`, `hi` | forecast and the 80% interval bounds |
| `naive`, `seasonal_naive`, `seasonal_mean_4w` | baseline forecasts (yesterday; last week; mean of the last 4 same weekday+hour) |

## `forecast/evaluation.json`

`overall` and `by_fold` metrics per model (`mae`, `rmse`, `wape`, `bias`, `n`); `by_volume`,
`by_hour`, `by_weekday`, `by_holiday`, `by_weather_context`, `by_borough` error analysis;
`city_total_hourly`; `bootstrap` (day-level intervals and improvement over each baseline);
`interval` (nominal and empirical coverage overall, by fold, volume and hour); `worst_zone_days`;
`feature_importance_last_fold`; `oracle_weather_experiment` (labelled ORACLE); `config`, `folds`
(train/calibration/test day ranges per fold); `baseline_fallback_rows`.
WAPE = sum of absolute errors / sum of actual pickups. Bias = (sum forecast - sum actual) / sum actual.

## `forecast/models/<id>/`

`model.txt` (LightGBM booster) and `meta.json`: `features`, `categorical`, `params`,
`conformal_q_bins` with `pred_bin_edges` (absolute-residual quantile per prediction band),
`nominal_coverage`, `train_days`, `calibration_days`, `data_run_id`, `metrics` (the walk-forward
summary; the final model has no held-out test of its own), `versions`. `models/latest.json` points at
the newest.

## `anomaly/events.parquet` (grain: one anomaly event)

| Column | Meaning |
|---|---|
| `event_id`, `location_id`, `zone`, `borough` | identity |
| `direction` | `surge` (above forecast) or `drop` |
| `start`, `end` | first flagged hour; end of the last flagged hour (exclusive) |
| `hours_flagged`, `hours_span` | seed hours in the run; hours from first to last seed |
| `actual`, `forecast`, `excess`, `ratio` | pickups over the span, the forecast, actual - forecast, actual / forecast |
| `peak_z` | largest single-hour standardised residual |
| `event_z` | pooled evidence over the span, divided by the empirically measured spread for a run of that length |
| `severity` | heuristic on `abs(event_z)`: low < 8 <= medium < 15 <= high |
| `scope`, `citywide_share`, `overlapping_events` | whether other zones deviated in the same hours (`localised`, `partly shared`, `city-wide`), that share, and the count of other zones with overlapping events |
| `context` | list of coinciding calendar/weather/other-zone context |
| `explanation` | generated sentence; always ends "This describes co-occurrence in the data, not a cause." |

`anomaly/report.json`: method and thresholds, the fitted error scale by demand band and the
empirical null, event counts by severity, direction and scope, busiest days,
`injection_experiment` (SEMI-SYNTHETIC sensitivity by demand level, duration and size),
`threshold_sensitivity`, `accuracy_status`, and on synthetic data `planted_truth`.

## `optimization/`

* `backtest_rows.parquet`: per test day, window and planner: `fleet`, `actual_demand`, `served`,
  `vehicles_moved`, `km`, solver `status`.
* `backtest.json`: `planners` (served share, moves), paired differences with day-level bootstrap
  intervals, `by_day_type`, `by_window`, `sensitivity`, and the `assumptions` every number depends
  on. Labelled SIMULATED.
* `scenario_<date>.json`: one what-if (CLI).

## `analyst/benchmark.json`

`history`: an append-only list of benchmark runs (`label`, `question_set`, per-question `results`
with checks and reasons, per-check and per-category summaries, safety counts, latency).

## Question sets

`benchmarks/analyst_questions.json` (development) and `benchmarks/analyst_questions_holdout.json`
(held-out): per question `id`, `category`, `question`, `expect_status`, optional `expect_tools`,
`oracle` (independent ground-truth spec), `must_state`, `forbid`, `expect_assumption`, and `data`
(`any` or `real`).
