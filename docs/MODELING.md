# Modeling

STATUS: VERIFIED for the forecasting model on real 2024 data, January to December (numbers in
[`reports/forecasting_real.md`](../reports/forecasting_real.md), generated from
`artifacts/real/forecast/evaluation.json`, never typed by hand). The earlier five-month results are archived
in [`reports/jan_may_2024`](../reports/jan_may_2024/README.md); they are not directly comparable, because the
test window moved from April and May to November and December.

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
* Calendar features (hour, weekday, federal holiday, day before/after a holiday, and the two holiday
  features adopted under a pre-registered rule) describe the target time and are known in advance. Same-period weather is *not* a feature (ADR-007).

## Features

History (all from earlier days): the same local hour 1, 2, 7 and 14 days back; mean of the same hour
over the previous 7 days; mean of the same weekday+hour over the previous 4 weeks; previous day's
mean, 7- and 28-day means, and previous evening's mean. Calendar: hour, weekday, weekend, holiday,
day after / before a holiday, `is_long_weekend` (a Friday to Monday inside a run of three or more days off) and
`days_to_holiday` (signed distance to the nearest federal holiday, clipped to three days). The last two were
pre-registered and adopted by a rule fixed in advance ([PREREGISTRATION_HOLIDAY](PREREGISTRATION_HOLIDAY.md),
[result](../reports/holiday_experiment_real.md)); models registered before that keep working. Zone: id (categorical), borough (categorical), centroid lon/lat.

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

* LightGBM has the lowest WAPE (19.5%), ahead of the strongest baseline, the 4-week seasonal mean
  (26.3%). The 6.8-point gap is statistically distinguishable from zero in the day-level bootstrap
  (95% interval 4.2 to 10.2 points), but **almost all of it comes from the holiday weeks**: on the first fold
  (mostly ordinary days) the two are 16.0% and 16.4%, on the Christmas and New Year fold 26.1% and 43.2%. On
  ordinary days the weekly profile carries most of the signal, as it did on the earlier data (a 1.3-point gap).
* The advantage over yesterday-persistence (10.5 points) and last-week copying (12.0 points) is large.
* Errors are largest at holidays and quiet zones: federal-holiday WAPE is 38.1% against 18.9% on ordinary days
  (only three holidays are in the window). The two calendar features added in response were tested under a
  pre-registered rule and adopted: 20.2% to 19.5% overall, 40.7% to 38.1% on holiday hours. The gain also
  appears on ordinary days, so they may partly act as a season signal, and a secondary check on August to
  September, with one holiday, went the other way (-0.53 points).
* The 80% interval covers 79.6% overall. It was 41% for busy zones before ADR-009 (see there).
* Actual same-day weather ("oracle") made accuracy worse on this year (19.5% to 21.1%); it is an experiment,
  not a deployable feature.

## Reproduce

```bash
MOBILITYOPS_MODE=real python -m mobilityops.cli forecast-eval      # a few minutes on 12 cores
MOBILITYOPS_MODE=real python -m mobilityops.cli forecast-report --out reports/forecasting_real.md
MOBILITYOPS_MODE=real python -m mobilityops.cli forecast-train
```

## Not done / caveats

* One year supports no annual-cycle feature: a yearly pattern cannot be separated from 2024's own events,
  and the model has seen each season once.
* Hyper-parameters are untuned.
* The final model has no held-out test of its own; the walk-forward numbers estimate the procedure.
* One year, one city, yellow taxis only. Green taxis and high-volume for-hire vehicles are in the data
  platform and the service view, but not in these models; yellow taxis are 14% of the pickups counted in the
  three TLC files.
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
* **Real events:** not verified. The largest fall in the holiday period (LaGuardia surges around 1 December,
  the Thanksgiving weekend, 31 December), which is consistent with the method working but is not a check
  of precision; holiday forecast error may also inflate the count. On the earlier data the largest events
  coincided with Memorial Day weekend.

## Known weaknesses

* Only 56 out-of-sample days can be scored.
* Drops are hard to detect: a 0.5x drop over 3 hours is found 0 to 2.5% of the time at the default threshold
  in every band on the full-year data (8% in busy zones on the earlier data). Surges of 2x over 3 hours are
  found 17.5% (1 to 20 pickups an hour), 52.5% (20 to 100) and 80% (100 or more) of the time.
* Events cluster on a few days (31 December and Thanksgiving hold 31% of all events); a person
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
  0.50 percentage points (95% bootstrap interval 0.36 to 0.65). Even planning with the actual
  demand (an unattainable oracle) adds only 2.56 points, so under these assumptions there is little
  headroom, and the LightGBM plan captures about 19% of it. (Earlier data: 0.53 and 2.57.)
* **The better forecast still did not produce a better plan.** Planning with the simple seasonal-mean
  forecast is now indistinguishable from planning with LightGBM (-0.03 points, interval -0.14 to +0.07);
  on the earlier data it was slightly better (0.18 points). LightGBM has much lower forecast error on this
  window, so the lower error does not carry over to this decision. This was not investigated further; one
  untested possibility is that window-level forecast bias matters more to this decision than average error.
* The value of repositioning depends strongly on fleet tightness: +1.30 points when the fleet
  matches demand, +0.16 when it is 30% short (sensitivity table, every 4th day).
* The move budget never binds (plans move roughly 100-150 vehicles per window); the per-km cost is what
  limits moves, so 10% and 50% budgets give identical results for the forecast-based plans.

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
