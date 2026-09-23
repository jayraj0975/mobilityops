# Modeling

STATUS: VERIFIED for the forecasting model on real Jan-May 2024 data (numbers in
[`reports/forecasting_real.md`](../reports/forecasting_real.md), generated from
`artifacts/real/forecast/evaluation.json`, never typed by hand).

## Problem

Day-ahead hourly pickups per taxi zone. At 00:00 local time on day D, forecast every zone's pickups
for each of the 24 hours of D. Zones are the 263 real TLC zones; the unit is *pickups per zone-hour*.
57% of real zone-hours are zero, and the busiest exceed 800, so metrics are reported by volume band.

## Data and leakage controls

* Source: the gold `fact_zone_hourly_demand` grid (see DATA_DICTIONARY). The daylight-saving
  spring-forward hour does not exist and the fall-back hour is ambiguous; both are `NaN`, never
  zero, and never a target.
* Every history feature is a function of days strictly before D. `tests/unit/test_forecast_features.py`
  proves this by overwriting all values from D onwards with garbage and asserting D's features are
  byte-identical.
* No random split anywhere. Folds are chronological and validated by test
  (`test_fold_windows_are_strictly_chronological_and_never_overlap`).
* Calendar features (hour, weekday, federal holiday, day before/after a holiday) describe the target
  time and are known in advance. Same-period weather is *not* a feature (ADR-007).

## Features

History (all from earlier days): the same local hour 1, 2, 7 and 14 days back; mean of the same hour
over the previous 7 days; mean of the same weekday+hour over the previous 4 weeks; previous day's
mean, 7- and 28-day means, and previous evening's mean. Calendar: hour, weekday, weekend, holiday,
day after / before a holiday. Zone: id (categorical), borough (categorical), centroid lon/lat.

## Models

| Model | Definition |
|---|---|
| Naive | same local hour yesterday |
| Seasonal naive | same weekday+hour last week |
| Seasonal mean | mean of the same weekday+hour over the last 4 weeks |
| LightGBM | Poisson objective, fixed parameters (`DEFAULT_PARAMS`), 400 rounds, no tuning |

Baselines use the same features and identical missing-value fallbacks, and the number of fallbacks
is reported.

## Validation

Rolling origin: the last 56 days are test days in 4 folds of 14. For each fold: train on days
`[14, F-14)`, calibrate intervals on `[F-14, F)`, score on `[F, F+14)`. The model is refitted at each
fold boundary, as a scheduled retrain would be. Metrics: MAE, RMSE, WAPE and relative bias, overall
and by fold, hour, weekday, volume band, borough, day type and weather context, plus city-wide
hourly totals. Uncertainty on the model-vs-baseline difference comes from a day-level bootstrap.

## Uncertainty

80% central intervals by split-conformal calibration, computed per predicted-demand band (ADR-009).
Reported: empirical coverage overall, by fold, volume band and hour, and mean width.

## Findings (real data; see the generated report for every number)

* LightGBM has the lowest WAPE (17.8%), ahead of the strongest baseline, the 4-week seasonal mean
  (19.1%). The 1.3-point gap is statistically distinguishable from zero in the day-level bootstrap
  (95% interval 0.7 to 2.1 points) but modest; much of the achievable accuracy comes from the
  weekly profile itself, which the top feature (same weekday+hour mean) confirms.
* The advantage over yesterday-persistence (12.6 points) and last-week copying (4.6 points) is large.
* Errors are largest at holidays and quiet zones. Federal-holiday WAPE is far higher than on
  ordinary days, and the biggest single zone-day misses *coincided with* Memorial Day weekend
  (Sat 25 and Mon 27 May). A "long weekend" feature is a natural improvement, deliberately **not**
  added: it was suggested by the test folds, so adding it now would be tuning on the test set.
* The 80% interval covers 79.6% overall. It was 41% for busy zones before ADR-009 (see there).
* Actual same-day weather ("oracle") did not improve accuracy on this five-month history.

## Reproduce

```bash
MOBILITYOPS_MODE=real python -m mobilityops.cli forecast-eval      # ~1 minute on 12 cores
MOBILITYOPS_MODE=real python -m mobilityops.cli forecast-report --out reports/forecasting_real.md
MOBILITYOPS_MODE=real python -m mobilityops.cli forecast-train
```

## Not done / caveats

* Five months cannot support annual seasonality; the model has never seen a full year or a
  December holiday season.
* Hyper-parameters are untuned.
* The final model has no held-out test of its own; the walk-forward numbers estimate the procedure.
* One month set, one city, yellow taxis only (no green cabs, FHV, or ride-hail).
* Results are for pickups, not for unmet demand.
