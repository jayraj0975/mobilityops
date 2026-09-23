# Anomaly detection (real data)

_Generated 2026-09-23T19:05:13.150083+00:00 from data run `20260923T183707Z-52b5c540`; scored days 2024-04-06 to 2024-05-31. Produced by `python -m mobilityops.cli anomaly-report`; do not edit._

**Accuracy status: UNVERIFIED: real data has no anomaly labels; only injection-based sensitivity and manual plausibility review are available.**

**Method.** out-of-sample forecast residuals scaled by a tail-aware error curve; seed hours merged into events; pooled evidence standardised by an empirical null. Scores use only out-of-sample forecasts (353,472 zone-hours, 14,728 zone-days). Seed hours: |z| >= 2.0; an event is kept when its standardised pooled score is at least 5.0 and its total deviation is at least 10 pickups.

## Summary

* Events: **277** (18.8 per 1,000 zone-days)
* Severity (heuristic on |score|; low < 8 <= medium < 15 <= high): {'low': 204, 'medium': 68, 'high': 5}
* Direction: {'surge': 264, 'drop': 13}
* Scope (share of *other* zones deviating in the same hours): {'localised': 154, 'partly shared': 123}

### Days with the most events

| Date | Events | Share of all events |
|---|---:|---:|
| 2024-05-26 | 26 | 9% |
| 2024-05-27 | 25 | 9% |
| 2024-05-29 | 24 | 9% |
| 2024-04-10 | 20 | 7% |
| 2024-05-05 | 13 | 5% |
| 2024-04-06 | 10 | 4% |
| 2024-04-09 | 10 | 4% |
| 2024-04-22 | 10 | 4% |

## Top 15 events by size (coincidence, not cause)

1. Upper East Side North (Manhattan) had 2301 pickups between Sat 25 May 07:00 and Sun 26 May 01:00 2024, 0.5x the forecast of 4287 (drop; standardised score -6.2 over 18 h, largest single hour -3.0). This coincided with: a weekend adjoining a US federal holiday; events in 6 other zones in overlapping hours, same direction. This describes co-occurrence in the data, not a cause.
2. East Village (Manhattan) had 1708 pickups between Sat 25 May 16:00 and Sun 26 May 03:00 2024, 0.5x the forecast of 3661 (drop; standardised score -6.8 over 11 h, largest single hour -3.8). This coincided with: a weekend adjoining a US federal holiday; events in 6 other zones in overlapping hours, same direction. This describes co-occurrence in the data, not a cause.
3. Upper East Side South (Manhattan) had 2768 pickups between Sat 25 May 08:00 and Sun 26 May 01:00 2024, 0.6x the forecast of 4599 (drop; standardised score -5.3 over 17 h, largest single hour -2.9). This coincided with: a weekend adjoining a US federal holiday; events in 6 other zones in overlapping hours, same direction. This describes co-occurrence in the data, not a cause.
4. East Village (Manhattan) had 1292 pickups between Fri 24 May 21:00 and Sat 25 May 03:00 2024, 0.5x the forecast of 2616 (drop; standardised score -6.0 over 6 h, largest single hour -4.0). This coincided with: no similar event in any other zone in overlapping hours. This describes co-occurrence in the data, not a cause.
5. Penn Station/Madison Sq West (Manhattan) had 2982 pickups between 14:00 and 00:00 on Mon 27 May 2024, 1.8x the forecast of 1691 (surge; standardised score +8.8 over 10 h, largest single hour +6.2). This coincided with: a US federal holiday; rain (24.4 mm recorded that day); events in 8 other zones in overlapping hours, same direction. This describes co-occurrence in the data, not a cause.
6. Gramercy (Manhattan) had 1366 pickups between Sat 25 May 10:00 and Sun 26 May 02:00 2024, 0.5x the forecast of 2539 (drop; standardised score -6.0 over 16 h, largest single hour -3.3). This coincided with: a weekend adjoining a US federal holiday; events in 6 other zones in overlapping hours, same direction. This describes co-occurrence in the data, not a cause.
7. Greenwich Village South (Manhattan) had 1249 pickups between Sat 25 May 16:00 and Sun 26 May 03:00 2024, 0.5x the forecast of 2323 (drop; standardised score -5.3 over 11 h, largest single hour -3.3). This coincided with: a weekend adjoining a US federal holiday; events in 6 other zones in overlapping hours, same direction. This describes co-occurrence in the data, not a cause.
8. LaGuardia Airport (Queens) had 451 pickups between 07:00 and 13:00 on Thu 23 May 2024, 0.4x the forecast of 1284 (drop; standardised score -6.5 over 6 h, largest single hour -4.8). This coincided with: rain (19.8 mm recorded that day); no similar event in any other zone in overlapping hours. This describes co-occurrence in the data, not a cause.
9. Lenox Hill West (Manhattan) had 846 pickups between Sat 25 May 15:00 and Sun 26 May 02:00 2024, 0.5x the forecast of 1631 (drop; standardised score -5.4 over 11 h, largest single hour -2.9). This coincided with: a weekend adjoining a US federal holiday; events in 6 other zones in overlapping hours, same direction. This describes co-occurrence in the data, not a cause.
10. Yorkville West (Manhattan) had 741 pickups between Sat 25 May 15:00 and Sun 26 May 01:00 2024, 0.5x the forecast of 1380 (drop; standardised score -5.1 over 10 h, largest single hour -3.0). This coincided with: a weekend adjoining a US federal holiday; events in 6 other zones in overlapping hours, same direction. This describes co-occurrence in the data, not a cause.
11. West Chelsea/Hudson Yards (Manhattan) had 449 pickups between Mon 27 May 15:00 and Tue 28 May 01:00 2024, 0.4x the forecast of 1084 (drop; standardised score -6.0 over 10 h, largest single hour -3.5). This coincided with: a US federal holiday; rain (24.4 mm recorded that day); events in 1 other zone in overlapping hours, same direction. This describes co-occurrence in the data, not a cause.
12. West Chelsea/Hudson Yards (Manhattan) had 1734 pickups between 13:00 and 20:00 on Sat 04 May 2024, 1.5x the forecast of 1124 (surge; standardised score +5.7 over 7 h, largest single hour +4.1). This coincided with: events in 1 other zone in overlapping hours, same direction. This describes co-occurrence in the data, not a cause.
13. LaGuardia Airport (Queens) had 1085 pickups between Mon 27 May 23:00 and Tue 28 May 04:00 2024, 2.3x the forecast of 478 (surge; standardised score +8.4 over 5 h, largest single hour +15.8). This coincided with: a US federal holiday; rain (24.4 mm recorded that day); events in 3 other zones in overlapping hours, same direction. This describes co-occurrence in the data, not a cause.
14. Union Sq (Manhattan) had 566 pickups between Mon 27 May 16:00 and Tue 28 May 01:00 2024, 0.5x the forecast of 1153 (drop; standardised score -5.3 over 9 h, largest single hour -3.2). This coincided with: a US federal holiday; rain (24.4 mm recorded that day); events in 1 other zone in overlapping hours, same direction. This describes co-occurrence in the data, not a cause.
15. Morningside Heights (Manhattan) had 1198 pickups between Sat 20 Apr 07:00 and Sun 21 Apr 03:00 2024, 1.9x the forecast of 626 (surge; standardised score +7.8 over 20 h, largest single hour +5.0). This coincided with: rain (1.3 mm recorded that day); events in 9 other zones in overlapping hours, same direction. This describes co-occurrence in the data, not a cause.

## Sensitivity: what size of deviation would be noticed?

SEMI-SYNTHETIC: artificial surges/drops injected into real out-of-sample actuals; measures sensitivity, not real-world precision.

Share of injected events detected (`event_threshold` 5.0), by demand level, duration and multiplier. Multipliers below 1 are drops; a drop can never fall below zero, so drops are structurally harder to detect than surges of the same relative size.

**1-hour event**

| Forecast demand | x0.2 | x0.5 | x1.5 | x2 | x3 |
|---|---:|---:|---:|---:|---:|
| 1-5/h | 0% | 0% | 2% | 2% | 12% |
| 5-20/h | 0% | 0% | 0% | 2% | 32% |
| 20-100/h | 0% | 0% | 5% | 20% | 78% |
| >=100/h | 0% | 0% | 0% | 35% | 90% |

**3-hour event**

| Forecast demand | x0.2 | x0.5 | x1.5 | x2 | x3 |
|---|---:|---:|---:|---:|---:|
| 1-5/h | 0% | 0% | 5% | 10% | 38% |
| 5-20/h | 0% | 0% | 2% | 15% | 65% |
| 20-100/h | 55% | 0% | 15% | 60% | 100% |
| >=100/h | 100% | 8% | 45% | 95% | 100% |

**6-hour event**

| Forecast demand | x0.2 | x0.5 | x1.5 | x2 | x3 |
|---|---:|---:|---:|---:|---:|
| 1-5/h | 0% | 0% | 12% | 25% | 57% |
| 5-20/h | 0% | 0% | 15% | 35% | 82% |
| 20-100/h | 80% | 2% | 28% | 80% | 98% |
| >=100/h | 100% | 52% | 55% | 95% | 100% |

## Threshold trade-off

Lowering `event_threshold` finds more real deviations and more marginal ones. Recall is for injected events in zones forecast at 20+ pickups/hour.

| event_threshold | events | per 1,000 zone-days | surge x2, 3 h | surge x2, 6 h | drop x0.5, 3 h | drop x0.5, 6 h |
|---:|---:|---:|---:|---:|---:|---:|
| 4 | 524 | 35.6 | 82% | 92% | 45% | 65% |
| 5 | 277 | 18.8 | 68% | 85% | 8% | 30% |
| 6 | 172 | 11.7 | 57% | 81% | 1% | 4% |

## Error model

Residual spread by forecast level (95th-percentile based; the floor is 1 pickup):

| Forecast (mean) | rows | sigma |
|---:|---:|---:|
| 0.2 | 182,755 | 0.46 |
| 1.0 | 71,386 | 1.26 |
| 3.2 | 24,053 | 2.26 |
| 7.0 | 12,836 | 3.77 |
| 14.6 | 9,802 | 5.83 |
| 32.9 | 15,064 | 9.94 |
| 73.4 | 13,455 | 16.40 |
| 144.6 | 15,358 | 28.48 |
| 268.5 | 7,835 | 47.21 |
| 465.0 | 928 | 82.90 |

Spread of the pooled score by run length (empirical null; 1 = independent errors): {'1': 1.0, '2': 1.0, '3': 1.08, '6': 1.254, '12': 1.482, '24': 1.76, '48': 2.128}.

## Limitations

* Only the out-of-sample test days can be scored, not the whole history.
* Real-data precision is UNVERIFIED: there are no labelled anomalies. Events are candidates for a person to review.
* Explanations list calendar and weather context that *coincided* with an event; they do not establish a cause.
* Weather is daily and city-wide; it cannot resolve an hour or a neighbourhood.
* Drops are structurally harder to detect than surges (see sensitivity tables).
