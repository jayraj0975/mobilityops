# Repositioning backtest (real data)

> **SIMULATED SCENARIO under explicit assumptions; not a forecast of real-world outcomes.**

_Generated 2026-09-25T08:42:44.364208+00:00 from data run `20260924T191303Z-e5b0f39f`; days 2024-11-06 to 2024-12-31. Produced by `python -m mobilityops.cli optimize-report`; do not edit._

## What this is and is not

For each out-of-sample day and window: vehicles start distributed by the previous 7 days' demand; a plan is computed from a demand source (LightGBM forecast, seasonal-mean forecast, or the actual demand as an unattainable oracle); the plan is then scored against the ACTUAL demand. The fleet is sized from the LightGBM forecast so no planner has hindsight about fleet size.

It measures how much a *better demand forecast* would change a stylised repositioning decision under the assumptions below. It is **not** evidence of what a real fleet would achieve: no fleet, dispatch or vehicle-location data exist in the open data, so supply and vehicle capacity are assumptions.

## Assumptions (all explicit; change them in `RebalanceParams` / `BacktestConfig`)

* Windows per day: 07:00-10:00, 17:00-20:00
* Fleet capacity = 85% of the LightGBM-forecast demand in the window (so some demand is unmet by construction); one vehicle serves 4.5 trips per window
* Repositioning: at most 30% of the fleet, at most 6 km centroid-to-centroid, cost 0.02 trips of value per vehicle-km
* no fleet data exist; supply is assumed (see design); a vehicle serves demand only in the zone where it stands
* Vehicles reach their destination before the window starts; the cost is linear in km; zones without a known centroid cannot send or receive vehicles

## Results

112 day-windows over 56 days (skipped for unobserved hours: 0). Served share = trips served / actual trips demanded.

| Planner | Served share | Vehicles moved / window | km / window |
|---|---:|---:|---:|
| No repositioning (vehicles stay where habit put them) | 81.13% | 0 | 0 |
| Plan with the seasonal-mean forecast | 81.66% | 121 | 331 |
| Plan with the LightGBM forecast | 81.62% | 104 | 309 |
| Plan with the actual demand (ORACLE, unattainable upper bound) | 83.69% | 153 | 418 |

Paired differences in served share (percentage points), day-level bootstrap 95% interval:

| Comparison | Difference (pp) | 95% interval (pp) |
|---|---:|---|
| LightGBM plan vs no repositioning | +0.50 | [+0.36, +0.65] |
| LightGBM plan vs seasonal-mean plan | -0.03 | [-0.14, +0.07] |
| Oracle plan vs no repositioning (the most repositioning could add here) | +2.56 | [+2.04, +3.14] |

Share of the oracle's improvement that the LightGBM plan captures: 19% (95% interval 15% to 25%).

### By day type and window

| Slice | windows | No repositioning | Plan with the seasonal-mean forecast | Plan with the LightGBM forecast | Plan with the actual demand |
|---|---:|---:|---:|---:|---:|
| federal holiday | 6 | 80.12% | 80.02% | 80.21% | 83.38% |
| weekday | 74 | 80.66% | 80.94% | 80.95% | 82.38% |
| weekend | 32 | 82.75% | 84.15% | 83.95% | 87.88% |
| window 07:00-10:00 | | 80.95% | 81.47% | 81.44% | 83.55% |
| window 17:00-20:00 | | 81.22% | 81.75% | 81.72% | 83.76% |

## Sensitivity to the assumptions

every 4th test day only, to keep run time small. Served share by planner; last column is LightGBM plan minus no repositioning, in percentage points.

| Scenario | windows | none | seasonal | LightGBM | oracle | LightGBM - none (pp) |
|---|---:|---:|---:|---:|---:|---:|
| coverage 0.70 (scarcer fleet) | 28 | 69.29% | 69.42% | 69.45% | 70.41% | +0.16 |
| coverage 1.00 (fleet matches demand) | 28 | 90.92% | 91.28% | 92.22% | 94.90% | +1.30 |
| only 10% of fleet may move | 28 | 81.63% | 82.14% | 82.08% | 84.20% | +0.45 |
| up to 50% of fleet may move | 28 | 81.63% | 82.14% | 82.08% | 84.25% | +0.45 |
| moves limited to 3 km | 28 | 81.63% | 82.12% | 82.03% | 84.07% | +0.40 |
| moves up to 10 km | 28 | 81.63% | 82.19% | 82.13% | 84.41% | +0.50 |

Solver status counts (repositioning plans): {'optimal': 336}.

## Limitations

* Supply, vehicle capacity and repositioning cost are assumptions; conclusions are conditional on them (see the sensitivity table).
* Demand is served only in the zone where a vehicle stands; real demand spills over to neighbouring zones, which would reduce the value of exact placement.
* Habit-based starting positions are a modelling choice; a different operator behaviour changes the baseline.
* Only the out-of-sample days are scored.
