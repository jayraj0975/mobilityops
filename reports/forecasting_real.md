# Forecast evaluation (real data)

_Generated 2026-09-25T08:33:33.693015+00:00 from data run `20260924T191303Z-e5b0f39f`; data days 2024-01-01 to 2024-12-31. This file is produced by `python -m mobilityops.cli forecast-report`; do not edit._

**Task.** day-ahead hourly pickups per zone; origin = 00:00 of the target day; history features use only earlier days; weather is not a feature.

**Test set.** 353,472 zone-hours, 56 days, 263 zones, 4 walk-forward folds (model refitted at each fold boundary; calibration block precedes each test block).

## Overall accuracy (all test folds pooled)

| Model | MAE | RMSE | WAPE | Bias |
|---|---:|---:|---:|---:|
| LightGBM (Poisson) | 3.62 | 12.15 | 19.5% | 0.2% |
| Seasonal mean (same weekday+hour, last 4 weeks) | 4.88 | 17.99 | 26.3% | 4.4% |
| Seasonal naive (same weekday+hour, last week) | 5.85 | 21.73 | 31.6% | 4.6% |
| Naive (same hour yesterday) | 5.57 | 20.24 | 30.0% | 0.2% |

Strongest baseline: **Seasonal mean (same weekday+hour, last 4 weeks)**. LightGBM's WAPE differs from it by 6.8 percentage points (25.9% relative; positive = LightGBM better); day-level bootstrap 95% interval for the difference [4.2, 10.2] percentage points (2000 resamples over 56 test days). All baselines:

| Baseline | WAPE difference (baseline - model), pp | 95% interval, pp | relative |
|---|---:|---|---:|
| Naive (same hour yesterday) | 10.5 | [7.8, 13.5] | 35.0% |
| Seasonal naive (same weekday+hour, last week) | 12.0 | [8.6, 16.3] | 38.2% |
| Seasonal mean (same weekday+hour, last 4 weeks) | 6.8 | [4.2, 10.2] | 25.9% |

WAPE = sum of absolute errors / sum of actual pickups. Bias = (sum forecast - sum actual) / sum actual. MAE and RMSE are in pickups per zone-hour.

## City-wide hourly total (zone forecasts summed)

| Model | MAE | RMSE | WAPE | Bias |
|---|---:|---:|---:|---:|
| LightGBM (Poisson) | 474.16 | 675.70 | 9.7% | 0.2% |
| Seasonal mean (same weekday+hour, last 4 weeks) | 836.30 | 1293.97 | 17.1% | 4.4% |
| Seasonal naive (same weekday+hour, last week) | 983.29 | 1576.17 | 20.2% | 4.6% |
| Naive (same hour yesterday) | 862.99 | 1315.23 | 17.7% | 0.2% |

## By fold

| Fold | test days | lightgbm WAPE | seasonal_mean_4w WAPE | seasonal_naive WAPE | naive WAPE |
|---|---|---:|---:|---:|---:|
| 0 | 2024-11-06 to 2024-11-19 | 16.0% | 16.4% | 21.7% | 30.1% |
| 1 | 2024-11-20 to 2024-12-03 | 21.0% | 30.0% | 33.3% | 31.9% |
| 2 | 2024-12-04 to 2024-12-17 | 16.8% | 20.4% | 27.8% | 28.8% |
| 3 | 2024-12-18 to 2024-12-31 | 26.1% | 43.2% | 47.6% | 29.4% |

## Error analysis

| Zone volume (mean pickups/hour, last 28 days) | rows | mean actual | lightgbm WAPE | seasonal_naive WAPE | seasonal_mean_4w WAPE |
|---|---:|---:|---:|---:|---:|
| <1/h | 202,176 | 0.30 | 118.2% | 132.7% | 121.8% |
| 1-5/h | 70,920 | 2.22 | 62.1% | 83.7% | 68.9% |
| 5-20/h | 17,208 | 9.88 | 35.8% | 50.6% | 41.7% |
| >=20/h | 63,168 | 97.61 | 17.0% | 28.7% | 23.9% |

| Day type | rows | mean actual | lightgbm WAPE | seasonal_naive WAPE | seasonal_mean_4w WAPE |
|---|---:|---:|---:|---:|---:|
| holiday | 18,936 | 11.90 | 38.1% | 90.4% | 78.2% |
| ordinary day | 334,536 | 18.92 | 18.9% | 29.5% | 24.5% |

| Weekday | rows | mean actual | lightgbm WAPE | seasonal_naive WAPE | seasonal_mean_4w WAPE |
|---|---:|---:|---:|---:|---:|
| Fri | 50,496 | 20.04 | 19.1% | 33.5% | 27.0% |
| Mon | 50,496 | 16.22 | 18.9% | 25.0% | 22.3% |
| Sat | 50,496 | 20.20 | 18.8% | 29.8% | 25.3% |
| Sun | 50,496 | 16.76 | 19.8% | 30.4% | 25.5% |
| Thu | 50,496 | 19.88 | 19.8% | 39.4% | 30.0% |
| Tue | 50,496 | 18.05 | 21.7% | 28.0% | 25.6% |
| Wed | 50,496 | 18.64 | 18.6% | 33.2% | 27.8% |

| Weather (context only, not a model input) | rows | mean actual | lightgbm WAPE | seasonal_naive WAPE | seasonal_mean_4w WAPE |
|---|---:|---:|---:|---:|---:|
| dry day | 220,920 | 18.76 | 18.6% | 31.0% | 25.2% |
| rain day | 132,552 | 18.18 | 21.0% | 32.6% | 28.3% |

| Borough | rows | mean actual | lightgbm WAPE | seasonal_naive WAPE | seasonal_mean_4w WAPE |
|---|---:|---:|---:|---:|---:|
| Bronx | 57,792 | 0.38 | 114.9% | 131.3% | 119.9% |
| Brooklyn | 81,984 | 1.39 | 69.5% | 90.5% | 75.8% |
| EWR | 1,344 | 0.78 | 93.2% | 111.4% | 93.2% |
| Manhattan | 92,736 | 62.93 | 17.3% | 29.2% | 24.3% |
| Queens | 92,736 | 6.26 | 27.9% | 39.7% | 33.6% |
| Staten Island | 26,880 | 0.01 | 206.3% | 190.0% | 187.5% |

### Largest zone-day errors (LightGBM)

| Zone | Borough | Date | Actual | Forecast | Abs. error | Federal holiday |
|---|---|---|---:|---:|---:|---|
| Upper East Side South | Manhattan | 2024-12-24 | 4,135 | 6,750 | 2,652 | no |
| Times Sq/Theatre District | Manhattan | 2024-12-31 | 754 | 3,191 | 2,589 | no |
| Midtown East | Manhattan | 2024-12-24 | 2,315 | 4,792 | 2,477 | no |
| Upper East Side North | Manhattan | 2024-12-24 | 4,035 | 6,243 | 2,285 | no |
| JFK Airport | Queens | 2024-12-02 | 8,198 | 6,021 | 2,195 | no |
| LaGuardia Airport | Queens | 2024-12-01 | 5,901 | 3,756 | 2,187 | no |
| Midtown Center | Manhattan | 2024-12-24 | 3,737 | 5,883 | 2,147 | no |
| Midtown Center | Manhattan | 2024-12-04 | 5,410 | 6,876 | 2,038 | no |
| LaGuardia Airport | Queens | 2024-12-24 | 1,166 | 3,193 | 2,032 | no |
| Penn Station/Madison Sq West | Manhattan | 2024-12-01 | 5,914 | 4,196 | 1,931 | no |

Wording note: dates listed here *coincided with* the largest misses; this evaluation does not establish why demand differed.

### Feature importance (gain share, last fold's model)

| Feature | Share |
|---|---:|
| `same_dow_hour_mean_4w` | 80.9% |
| `lag_7d` | 12.2% |
| `lag_14d` | 3.9% |
| `same_hour_mean_7d` | 1.9% |
| `lag_1d` | 0.4% |
| `location_id` | 0.1% |
| `mean_28d` | 0.1% |
| `days_to_holiday` | 0.1% |

## Prediction intervals

Nominal central coverage 80%; empirical coverage on the test days **79.6%**, mean width 10.00 pickups.

| Slice | coverage | mean width |
|---|---:|---:|
| fold 0 | 79.8% | 9.47 |
| fold 1 | 79.7% | 9.20 |
| fold 2 | 81.6% | 11.13 |
| fold 3 | 77.5% | 10.20 |
| volume <1/h | 82.4% | 0.86 |
| volume 1-5/h | 74.7% | 3.72 |
| volume 5-20/h | 78.1% | 11.01 |
| volume >=20/h | 76.9% | 46.01 |

Coverage by hour of day ranges from 76.1% to 85.0%. Coverage for near-zero demand is conservative because counts are discrete.

## Weather experiment (ORACLE, not a deployable result)

ORACLE: uses the target day's ACTUAL weather, which would have to be forecast in operation. An upper bound on what weather could add, not a result.

WAPE without weather 19.5%, with actual same-day weather 21.1%; MAE 3.619 vs 3.904.

## Baseline fallbacks

Rows where a baseline's primary value was missing and a fallback was used: {'naive': 526, 'seasonal_naive': 526, 'seasonal_mean_4w': 0}.
