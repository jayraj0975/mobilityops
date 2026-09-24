# Live data: classes, freshness, and how "real time" is defined here

## Data classes (what kind of data it is)

| Class | Meaning | Used in Pune for |
|---|---|---|
| LIVE | Observations delivered within seconds of being made | **Nothing.** No such source exists for Pune. |
| NEAR-REAL-TIME | The latest model or observation step, minutes old by design | Current weather (15-minute steps), air quality (hourly, modelled) |
| RECENT | Within the last day or so | Hourly rain for the recent days |
| HISTORICAL | Complete past data | ERA5 rain history |
| PREDICTED | A forecast, always with a range | The day-ahead demand forecast |
| SIMULATED | Produced by a model of behaviour, not observed | **All trip counts**, events and scenarios |
| STATIC | Does not change with time | Zones (OpenStreetMap), holidays |

`MODELLED` is added where a value is model output rather than an instrument reading: weather "now" is Open-Meteo's
model blend at nine grid points, not a station; air quality is a CAMS model on a coarse grid, not a monitor.

## Freshness (how old it is)

Separate from the class. Computed by the server, from timestamps, on every snapshot:

| State | Age of the value, against how often the source should update |
|---|---|
| LIVE | up to 2.5x the interval |
| DELAYED | up to 5x |
| STALE | up to 12x |
| OFFLINE | beyond that, or never received |
| NOT CONFIGURED | the source has no adapter or is not enabled: not a failure |

`observed_at` is when the source says a value applies; `received_at` is when this system got it. Age is measured from
`observed_at`, so a provider that answers every minute with the same three-hour-old value goes STALE while our own poller
looks healthy. A SIMULATED value can be LIVE-fresh: that only means the simulator ran on schedule. The reasoning for the
2.5x bound is in ADR-020.

## Sources and schedules

| Source | Interval | Class | Notes |
|---|---|---|---|
| Open-Meteo forecast, `current` | 15 min | NEAR-REAL-TIME, MODELLED | 9 points over the study area; values validated against physical ranges |
| MET Norway locationforecast | 30 min (hourly data) | NEAR-REAL-TIME, MODELLED | Second weather provider, one point; used when Open-Meteo is unavailable. A need with several providers is healthy if any one is |
| Open-Meteo air quality, `current` | 60 min | NEAR-REAL-TIME, MODELLED | PM2.5, PM10, US AQI |
| Open-Meteo hourly, recent days | 60 min data, polled 15 min | RECENT | Only hours up to the current one are stored as observations; the rest are forecasts and are not |
| Simulated demand | 1 min | SIMULATED | yesterday and today, pro-rated inside the running hour |
| Forecast | daily | PREDICTED | made from data up to yesterday; remade when the day changes |
| ERA5 history, OpenStreetMap zones | at build | HISTORICAL, STATIC | committed or cached with provenance |

## The simulated demand

Per zone, day and hour: `city trips per day × zone weight × hour shape × day factors × rain multiplier`, realised as a
Poisson count. Zone weights come from a gravity model over ten approximate landmarks (hubs), the hour shapes mix
residential, business and leisure profiles, weekends lower business zones, a holiday cuts them further, and rain lifts
demand by 6% per millimetre of that hour (capped at 30%). All constants are in `pune/simulate.py` and `model_card()`
returns them; they are assumptions, not measurements. Roughly 5% of days carry a planted surge or drop at a busy zone,
recorded so a detector can be scored against them.

## Live events

A rule, not a trained detector, applied to the completed hours of today. Each hour's deviation is
`(actual − forecast) / sqrt(forecast + (0.15·forecast)²)` (Poisson noise plus typical model error). Consecutive hours
of one sign with |z| ≥ 2.5 form a run; the run is an event if its pooled deviation reaches 5, the ratio is at least 1.5×
(or at most 0.6×) and the forecast total is at least 30 trips. The running hour is never used. Events describe a
departure from the forecast; they never explain it. On real data this would need validating against labelled events;
on simulated data it can only show the rule works.

## Known limitations of the forecast

* The day-ahead model has no weather input. After rainy days it over-forecasts a dry day (seen on 24 September 2026:
  the day ran about 12% under its forecast). It is visible in the console, not hidden.
* The 80% range is per zone-hour; the city-level "range" sums the zones' ranges and is wider than a true city range.
  The interface says so.
* Accuracy figures are measured on simulated demand and show the pipeline works, not how well it would forecast Pune.
