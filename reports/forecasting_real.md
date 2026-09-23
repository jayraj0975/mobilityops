# Forecast evaluation (real data)

_Generated 2026-09-23T18:46:01.659103+00:00 from data run `20260923T183707Z-52b5c540`; data days 2024-01-01 to 2024-05-31. This file is produced by `python -m mobilityops.cli forecast-report`; do not edit._

**Task.** day-ahead hourly pickups per zone; origin = 00:00 of the target day; history features use only earlier days; weather is not a feature.

**Test set.** 353,472 zone-hours, 56 days, 263 zones, 4 walk-forward folds (model refitted at each fold boundary; calibration block precedes each test block).

## Overall accuracy (all test folds pooled)

| Model | MAE | RMSE | WAPE | Bias |
|---|---:|---:|---:|---:|
| LightGBM (Poisson) | 3.26 | 10.64 | 17.8% | 2.8% |
| Seasonal mean (same weekday+hour, last 4 weeks) | 3.49 | 11.78 | 19.1% | 0.7% |
| Seasonal naive (same weekday+hour, last week) | 4.09 | 13.74 | 22.4% | 2.0% |
| Naive (same hour yesterday) | 5.57 | 20.82 | 30.4% | 0.3% |

Strongest baseline: **Seasonal mean (same weekday+hour, last 4 weeks)**. LightGBM's WAPE differs from it by 1.3 percentage points (6.8% relative; positive = LightGBM better); day-level bootstrap 95% interval for the difference [0.7, 2.1] percentage points (2000 resamples over 56 test days). All baselines:

| Baseline | WAPE difference (baseline - model), pp | 95% interval, pp | relative |
|---|---:|---|---:|
| Naive (same hour yesterday) | 12.6 | [9.7, 15.8] | 41.5% |
| Seasonal naive (same weekday+hour, last week) | 4.6 | [3.9, 5.5] | 20.5% |
| Seasonal mean (same weekday+hour, last 4 weeks) | 1.3 | [0.7, 2.1] | 6.8% |

WAPE = sum of absolute errors / sum of actual pickups. Bias = (sum forecast - sum actual) / sum actual. MAE and RMSE are in pickups per zone-hour.

## City-wide hourly total (zone forecasts summed)

| Model | MAE | RMSE | WAPE | Bias |
|---|---:|---:|---:|---:|
| LightGBM (Poisson) | 401.18 | 617.65 | 8.3% | 2.8% |
| Seasonal mean (same weekday+hour, last 4 weeks) | 486.03 | 737.92 | 10.1% | 0.7% |
| Seasonal naive (same weekday+hour, last week) | 555.23 | 832.36 | 11.5% | 2.0% |
| Naive (same hour yesterday) | 867.10 | 1337.89 | 18.0% | 0.3% |

## By fold

| Fold | test days | lightgbm WAPE | seasonal_mean_4w WAPE | seasonal_naive WAPE | naive WAPE |
|---|---|---:|---:|---:|---:|
| 0 | 2024-04-06 to 2024-04-19 | 17.1% | 17.2% | 21.6% | 31.8% |
| 1 | 2024-04-20 to 2024-05-03 | 18.0% | 18.5% | 21.1% | 30.1% |
| 2 | 2024-05-04 to 2024-05-17 | 15.4% | 17.0% | 18.9% | 28.7% |
| 3 | 2024-05-18 to 2024-05-31 | 21.0% | 24.2% | 28.3% | 31.3% |

## Error analysis

| Zone volume (mean pickups/hour, last 28 days) | rows | mean actual | lightgbm WAPE | seasonal_naive WAPE | seasonal_mean_4w WAPE |
|---|---:|---:|---:|---:|---:|
| <1/h | 216,336 | 0.30 | 113.4% | 124.9% | 113.4% |
| 1-5/h | 57,408 | 2.18 | 60.5% | 75.6% | 63.7% |
| 5-20/h | 15,936 | 10.36 | 35.5% | 43.2% | 37.3% |
| >=20/h | 63,792 | 95.78 | 15.4% | 19.6% | 16.7% |

| Day type | rows | mean actual | lightgbm WAPE | seasonal_naive WAPE | seasonal_mean_4w WAPE |
|---|---:|---:|---:|---:|---:|
| holiday | 6,312 | 11.22 | 43.7% | 74.3% | 71.4% |
| ordinary day | 347,160 | 18.42 | 17.5% | 21.8% | 18.5% |

| Weekday | rows | mean actual | lightgbm WAPE | seasonal_naive WAPE | seasonal_mean_4w WAPE |
|---|---:|---:|---:|---:|---:|
| Fri | 50,496 | 19.06 | 17.1% | 21.1% | 17.8% |
| Mon | 50,496 | 15.12 | 19.0% | 25.1% | 21.9% |
| Sat | 50,496 | 19.47 | 19.3% | 24.0% | 20.1% |
| Sun | 50,496 | 16.55 | 20.7% | 25.7% | 22.0% |
| Thu | 50,496 | 20.58 | 15.9% | 19.5% | 16.8% |
| Tue | 50,496 | 17.89 | 16.9% | 21.1% | 18.3% |
| Wed | 50,496 | 19.38 | 16.3% | 21.3% | 17.8% |

| Weather (context only, not a model input) | rows | mean actual | lightgbm WAPE | seasonal_naive WAPE | seasonal_mean_4w WAPE |
|---|---:|---:|---:|---:|---:|
| dry day | 258,792 | 17.91 | 17.7% | 22.3% | 18.7% |
| rain day | 94,680 | 19.34 | 17.9% | 22.5% | 20.2% |

| Borough | rows | mean actual | lightgbm WAPE | seasonal_naive WAPE | seasonal_mean_4w WAPE |
|---|---:|---:|---:|---:|---:|
| Bronx | 57,792 | 0.35 | 112.2% | 126.0% | 113.1% |
| Brooklyn | 81,984 | 1.10 | 72.1% | 85.3% | 74.0% |
| EWR | 1,344 | 0.75 | 92.3% | 106.7% | 90.3% |
| Manhattan | 92,736 | 62.13 | 16.1% | 20.4% | 17.4% |
| Queens | 92,736 | 6.39 | 22.6% | 27.8% | 24.1% |
| Staten Island | 26,880 | 0.01 | 201.4% | 185.7% | 174.9% |

### Largest zone-day errors (LightGBM)

| Zone | Borough | Date | Actual | Forecast | Abs. error | Federal holiday |
|---|---|---|---:|---:|---:|---|
| East Village | Manhattan | 2024-05-25 | 2,634 | 5,076 | 2,442 | no |
| Penn Station/Madison Sq West | Manhattan | 2024-05-27 | 4,383 | 3,171 | 2,057 | yes |
| Upper East Side North | Manhattan | 2024-05-25 | 2,358 | 4,366 | 2,009 | no |
| Upper East Side South | Manhattan | 2024-05-25 | 2,899 | 4,765 | 1,866 | no |
| West Village | Manhattan | 2024-05-25 | 2,714 | 4,476 | 1,762 | no |
| LaGuardia Airport | Queens | 2024-05-23 | 4,160 | 4,696 | 1,521 | no |
| East Village | Manhattan | 2024-05-26 | 2,321 | 3,636 | 1,494 | no |
| Midtown Center | Manhattan | 2024-05-24 | 4,184 | 5,560 | 1,439 | no |
| Upper East Side South | Manhattan | 2024-05-27 | 2,253 | 3,671 | 1,431 | yes |
| LaGuardia Airport | Queens | 2024-05-26 | 2,653 | 4,008 | 1,379 | no |

Wording note: dates listed here *coincided with* the largest misses; this evaluation does not establish why demand differed.

### Feature importance (gain share, last fold's model)

| Feature | Share |
|---|---:|
| `same_dow_hour_mean_4w` | 67.3% |
| `lag_7d` | 20.8% |
| `lag_14d` | 9.4% |
| `same_hour_mean_7d` | 1.8% |
| `lag_1d` | 0.2% |
| `location_id` | 0.1% |
| `mean_28d` | 0.1% |
| `hour` | 0.1% |

## Prediction intervals

Nominal central coverage 80%; empirical coverage on the test days **79.6%**, mean width 9.56 pickups.

| Slice | coverage | mean width |
|---|---:|---:|
| fold 0 | 80.8% | 10.45 |
| fold 1 | 80.8% | 9.29 |
| fold 2 | 78.7% | 9.41 |
| fold 3 | 78.3% | 9.08 |
| volume <1/h | 81.5% | 0.83 |
| volume 1-5/h | 73.7% | 3.57 |
| volume 5-20/h | 77.5% | 11.35 |
| volume >=20/h | 79.0% | 44.11 |

Coverage by hour of day ranges from 75.9% to 87.1%. Coverage for near-zero demand is conservative because counts are discrete.

## Weather experiment (ORACLE, not a deployable result)

ORACLE: uses the target day's ACTUAL weather, which would have to be forecast in operation. An upper bound on what weather could add, not a result.

WAPE without weather 17.8%, with actual same-day weather 18.6%; MAE 3.256 vs 3.409.

## Baseline fallbacks

Rows where a baseline's primary value was missing and a fallback was used: {'naive': 263, 'seasonal_naive': 263, 'seasonal_mean_4w': 0}.
