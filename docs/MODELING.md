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

---

# Anomaly detection

STATUS: mechanism VERIFIED against planted ground truth on synthetic data; real-data precision
UNVERIFIED (no labels). Numbers below are generated into
[`reports/anomalies_real.md`](../reports/anomalies_real.md).

## Definition

An anomaly is a run of hours in which a zone's pickups differ from the *out-of-sample* forecast by
far more than the forecaster's usual error at that demand level. See ADR-010 for the method and for
how it was corrected after a first version flagged about 25 events per day.

Pipeline: residual -> per-demand-band scale (tail-aware, interpolated) -> hourly `z` -> seed hours
`|z| >= 2` -> merge same-sign runs -> pooled evidence over the run, standardised by the measured
spread of pooled scores for that run length -> keep if `|score| >= 5` and at least 10 pickups of
total deviation -> annotate.

## Explanations

Every event carries a generated sentence: what happened (actual vs forecast, hours, size), and
context that *coincided* with it: US federal holiday or adjoining weekend, recorded rain / snow /
freezing temperature for that day, and how many other zones had events in overlapping hours in the
same direction. Sentences always end "This describes co-occurrence in the data, not a cause."
Tests forbid causal wording ("because", "due to", "caused", ...).

## Verification

* **Planted truth (synthetic sample):** 3 of 3 planted anomalies found, 0 unplanted events. Only
  three anomalies exist, so this demonstrates the mechanism, not an error rate.
* **Injection experiment (real residuals):** artificial surges and drops are injected into real
  out-of-sample actuals to measure sensitivity by demand level, duration and size. Reported per cell.
* **Real events:** manually reviewed for plausibility only. The largest coincided with Memorial Day
  weekend (residential Manhattan zones near half the forecast on Sat 25 May, Penn Station above
  forecast on Mon 27 May). That is a consistency check, not verification.

## Known weaknesses

* Only 56 out-of-sample days can be scored.
* Drops are hard to detect: a 0.5x drop over 3 hours in busy zones is found about 8% of the time at
  the default threshold (45% at threshold 4, at roughly double the event count).
* Events cluster on a few city-wide days (three days hold about a quarter of all events); a person
  should read those as one disruption, not dozens of independent alarms. The `overlapping_events`
  field counts neighbours.
* Thresholds are conventions. Severity is a heuristic on score, not a probability.
* Weather is one daily value for the whole city.

## Reproduce

```bash
MOBILITYOPS_MODE=real python -m mobilityops.cli forecast-eval     # needed first: writes forecasts
MOBILITYOPS_MODE=real python -m mobilityops.cli anomalies
MOBILITYOPS_MODE=real python -m mobilityops.cli anomaly-report --out reports/anomalies_real.md
```

---

# Optimization (repositioning scenarios)

STATUS: engine VERIFIED (known-answer, brute-force and invariant tests). Backtest results are
**SIMULATED SCENARIOS under explicit assumptions**, generated into
[`reports/optimization_real.md`](../reports/optimization_real.md). They are not evidence of what a
real fleet would achieve.

## What it does

Given expected demand per zone for a window and a starting distribution of vehicles, a
mixed-integer program (`scipy.optimize.milp`, HiGHS) moves whole vehicles between zones at most
`max_km` apart, within a budget of moved vehicles, to maximise served trips minus a small per-km
cost. A requested service level that cannot be reached returns `infeasible` with the best
attainable level (ADR-011). The CLI runs a what-if for any out-of-sample date and window
(`optimize`), including demand shocks (`--surge ZONE:FACTOR`) and service-level requirements
(`--min-service`).

## Assumptions (no fleet data exist)

Fleet capacity is 85% of the forecast demand in the window; vehicles start distributed by the
previous 7 days' demand; one vehicle serves 4.5 trips per window; a vehicle serves demand only in the
zone where it stands; moves cost 0.02 trips per km, up to 6 km, up to 30% of the fleet. Every
assumption is echoed in each result, and the report varies them.

## Findings (real data, 112 day-windows over 56 out-of-sample days; see the report for all numbers)

* Repositioning adds a small amount. Planning with the LightGBM forecast raises the served share by
  0.53 percentage points (95% bootstrap interval 0.38 to 0.70). Even planning with the actual
  demand (an unattainable oracle) adds only 2.57 points, so under these assumptions there is little
  headroom, and the LightGBM plan captures about 20% of it.
* **The better forecast did not produce the better plan.** Planning with the simple seasonal-mean
  forecast served 0.18 points *more* than planning with LightGBM (interval excludes zero), although
  LightGBM has lower forecast error. This was not investigated further; one untested possibility is
  that window-level forecast bias matters more to this decision than average error.
* The value of repositioning depends strongly on fleet tightness: +1.65 points when the fleet
  matches demand, +0.14 when it is 30% short (sensitivity table, every 4th day).
* The move budget never binds (plans move roughly 100-150 vehicles per window out of 4,000+); the
  per-km cost is what limits moves, so 10% and 50% budgets give identical results.

## Limitations

Supply, capacity and cost are assumptions. Demand does not spill over to neighbouring zones, which
overstates the value of exact placement. Habit-based starting positions are a modelling choice.
Only out-of-sample days are scored.

## Reproduce

```bash
MOBILITYOPS_MODE=real python -m mobilityops.cli optimize-backtest    # ~25 minutes incl. sensitivity
MOBILITYOPS_MODE=real python -m mobilityops.cli optimize-report --out reports/optimization_real.md
MOBILITYOPS_MODE=real python -m mobilityops.cli optimize --date 2024-05-27 --start-hour 15 --end-hour 20
```
