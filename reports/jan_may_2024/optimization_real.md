# Repositioning backtest (real data)

> **SIMULATED SCENARIO under explicit assumptions; not a forecast of real-world outcomes.**

_Generated 2026-09-23T19:16:10.624983+00:00 from data run `20260923T183707Z-52b5c540`; days 2024-04-06 to 2024-05-31. Produced by `python -m mobilityops.cli optimize-report`; do not edit._

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
| No repositioning (vehicles stay where habit put them) | 83.48% | 0 | 0 |
| Plan with the seasonal-mean forecast | 84.19% | 136 | 377 |
| Plan with the LightGBM forecast | 84.01% | 102 | 304 |
| Plan with the actual demand (ORACLE, unattainable upper bound) | 86.05% | 151 | 402 |

Paired differences in served share (percentage points), day-level bootstrap 95% interval:

| Comparison | Difference (pp) | 95% interval (pp) |
|---|---:|---|
| LightGBM plan vs no repositioning | +0.53 | [+0.38, +0.70] |
| LightGBM plan vs seasonal-mean plan | -0.18 | [-0.27, -0.10] |
| Oracle plan vs no repositioning (the most repositioning could add here) | +2.57 | [+2.13, +3.05] |

Share of the oracle's improvement that the LightGBM plan captures: 20% (95% interval 15% to 27%).

### By day type and window

| Slice | windows | No repositioning | Plan with the seasonal-mean forecast | Plan with the LightGBM forecast | Plan with the actual demand |
|---|---:|---:|---:|---:|---:|
| federal holiday | 2 | 88.14% | 87.88% | 88.16% | 95.32% |
| weekday | 78 | 84.12% | 84.46% | 84.36% | 86.15% |
| weekend | 32 | 81.08% | 83.12% | 82.63% | 85.31% |
| window 07:00-10:00 | | 83.18% | 83.87% | 83.64% | 85.81% |
| window 17:00-20:00 | | 83.64% | 84.36% | 84.20% | 86.17% |

## Sensitivity to the assumptions

every 4th test day only, to keep run time small. Served share by planner; last column is LightGBM plan minus no repositioning, in percentage points.

| Scenario | windows | none | seasonal | LightGBM | oracle | LightGBM - none (pp) |
|---|---:|---:|---:|---:|---:|---:|
| coverage 0.70 (scarcer fleet) | 28 | 71.92% | 72.11% | 72.06% | 72.77% | +0.14 |
| coverage 1.00 (fleet matches demand) | 28 | 93.51% | 94.52% | 95.15% | 97.58% | +1.65 |
| only 10% of fleet may move | 28 | 84.92% | 85.58% | 85.44% | 87.64% | +0.51 |
| up to 50% of fleet may move | 28 | 84.92% | 85.58% | 85.44% | 87.64% | +0.51 |
| moves limited to 3 km | 28 | 84.92% | 85.56% | 85.42% | 87.44% | +0.49 |
| moves up to 10 km | 28 | 84.92% | 85.62% | 85.47% | 87.73% | +0.54 |

Solver status counts (repositioning plans): {'optimal': 336}.

## Limitations

* Supply, vehicle capacity and repositioning cost are assumptions; conclusions are conditional on them (see the sensitivity table).
* Demand is served only in the zone where a vehicle stands; real demand spills over to neighbouring zones, which would reduce the value of exact placement.
* Habit-based starting positions are a modelling choice; a different operator behaviour changes the baseline.
* Only the out-of-sample days are scored.
