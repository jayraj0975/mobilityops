# Anomaly detection (real data)

_Generated 2026-09-25T08:36:45.700179+00:00 from data run `20260924T191303Z-e5b0f39f`; scored days 2024-11-06 to 2024-12-31. Produced by `python -m mobilityops.cli anomaly-report`; do not edit._

**Accuracy status: UNVERIFIED: real data has no anomaly labels; only injection-based sensitivity and manual plausibility review are available.**

**Method.** out-of-sample forecast residuals scaled by a tail-aware error curve; seed hours merged into events; pooled evidence standardised by an empirical null. Scores use only out-of-sample forecasts (353,472 zone-hours, 14,728 zone-days). Seed hours: |z| >= 2.0; an event is kept when its standardised pooled score is at least 5.0 and its total deviation is at least 10 pickups.

## Summary

* Events: **307** (20.8 per 1,000 zone-days)
* Severity (heuristic on |score|; low < 8 <= medium < 15 <= high): {'low': 244, 'medium': 54, 'high': 9}
* Direction: {'surge': 299, 'drop': 8}
* Scope (share of *other* zones deviating in the same hours): {'partly shared': 185, 'localised': 109, 'city-wide': 13}

### Days with the most events

| Date | Events | Share of all events |
|---|---:|---:|
| 2024-12-31 | 52 | 17% |
| 2024-11-28 | 44 | 14% |
| 2024-12-24 | 24 | 8% |
| 2024-12-11 | 19 | 6% |
| 2024-12-25 | 16 | 5% |
| 2024-11-21 | 12 | 4% |
| 2024-12-05 | 12 | 4% |
| 2024-12-12 | 9 | 3% |

## Top 15 events by size (coincidence, not cause)

1. Times Sq/Theatre District (Manhattan) had 355 pickups between 10:00 and 00:00 on Tue 31 Dec 2024, 0.1x the forecast of 2707 (drop; standardised score -8.9 over 14 h, largest single hour -4.8). This coincided with: the day before a US federal holiday; rain (10.2 mm recorded that day); events in 1 other zone in overlapping hours, same direction. This describes co-occurrence in the data, not a cause.
2. LaGuardia Airport (Queens) had 5923 pickups between Sun 01 Dec 07:00 and Mon 02 Dec 02:00 2024, 1.6x the forecast of 3811 (surge; standardised score +5.7 over 19 h, largest single hour +6.4). This coincided with: events in 3 other zones in overlapping hours, same direction. This describes co-occurrence in the data, not a cause.
3. LaGuardia Airport (Queens) had 1091 pickups between Tue 24 Dec 07:00 and Wed 25 Dec 01:00 2024, 0.3x the forecast of 3157 (drop; standardised score -6.8 over 18 h, largest single hour -3.8). This coincided with: the day before a US federal holiday; rain (2.5 mm recorded that day); snowfall; events in 2 other zones in overlapping hours, same direction. This describes co-occurrence in the data, not a cause.
4. Midtown East (Manhattan) had 1099 pickups between 15:00 and 23:00 on Tue 24 Dec 2024, 0.4x the forecast of 2703 (drop; standardised score -5.6 over 8 h, largest single hour -3.4). This coincided with: the day before a US federal holiday; rain (2.5 mm recorded that day); snowfall; events in 2 other zones in overlapping hours, same direction. This describes co-occurrence in the data, not a cause.
5. Upper West Side South (Manhattan) had 3025 pickups between Wed 27 Nov 15:00 and Thu 28 Nov 03:00 2024, 1.9x the forecast of 1559 (surge; standardised score +7.8 over 12 h, largest single hour +5.9). This coincided with: the day before a US federal holiday; events in 14 other zones in overlapping hours, same direction. This describes co-occurrence in the data, not a cause.
6. Midtown Center (Manhattan) had 933 pickups between 19:00 and 00:00 on Tue 24 Dec 2024, 0.4x the forecast of 2157 (drop; standardised score -5.0 over 5 h, largest single hour -3.3). This coincided with: the day before a US federal holiday; rain (2.5 mm recorded that day); snowfall; events in 2 other zones in overlapping hours, same direction. This describes co-occurrence in the data, not a cause.
7. LaGuardia Airport (Queens) had 1981 pickups between Sat 30 Nov 17:00 and Sun 01 Dec 02:00 2024, 2.2x the forecast of 888 (surge; standardised score +9.4 over 9 h, largest single hour +13.3). This coincided with: events in 1 other zone in overlapping hours, same direction. This describes co-occurrence in the data, not a cause.
8. LaGuardia Airport (Queens) had 601 pickups between Thu 28 Nov 14:00 and Fri 29 Nov 01:00 2024, 0.4x the forecast of 1671 (drop; standardised score -5.7 over 11 h, largest single hour -3.5). This coincided with: a US federal holiday; rain (21.8 mm recorded that day); events in 1 other zone in overlapping hours, same direction. This describes co-occurrence in the data, not a cause.
9. JFK Airport (Queens) had 2145 pickups between Sat 30 Nov 21:00 and Sun 01 Dec 06:00 2024, 1.7x the forecast of 1239 (surge; standardised score +5.1 over 9 h, largest single hour +5.1). This coincided with: events in 1 other zone in overlapping hours, same direction. This describes co-occurrence in the data, not a cause.
10. Penn Station/Madison Sq West (Manhattan) had 1892 pickups between 18:00 and 22:00 on Sun 01 Dec 2024, 1.8x the forecast of 1040 (surge; standardised score +6.3 over 4 h, largest single hour +7.4). This coincided with: events in 1 other zone in overlapping hours, same direction. This describes co-occurrence in the data, not a cause.
11. LaGuardia Airport (Queens) had 1577 pickups between Mon 02 Dec 21:00 and Tue 03 Dec 01:00 2024, 1.9x the forecast of 843 (surge; standardised score +6.1 over 4 h, largest single hour +10.6). This coincided with: no similar event in any other zone in overlapping hours. This describes co-occurrence in the data, not a cause.
12. Times Sq/Theatre District (Manhattan) had 244 pickups between 07:00 and 14:00 on Thu 28 Nov 2024, 0.3x the forecast of 912 (drop; standardised score -5.7 over 7 h, largest single hour -3.5). This coincided with: a US federal holiday; rain (21.8 mm recorded that day); no similar event in any other zone in overlapping hours. This describes co-occurrence in the data, not a cause.
13. Garment District (Manhattan) had 209 pickups between 15:00 and 00:00 on Tue 31 Dec 2024, 0.2x the forecast of 846 (drop; standardised score -6.0 over 9 h, largest single hour -3.6). This coincided with: the day before a US federal holiday; rain (10.2 mm recorded that day); events in 1 other zone in overlapping hours, same direction. This describes co-occurrence in the data, not a cause.
14. West Chelsea/Hudson Yards (Manhattan) had 1347 pickups between 13:00 and 20:00 on Mon 11 Nov 2024, 1.7x the forecast of 811 (surge; standardised score +5.2 over 7 h, largest single hour +3.6). This coincided with: a US federal holiday; rain (2.5 mm recorded that day); no similar event in any other zone in overlapping hours. This describes co-occurrence in the data, not a cause.
15. Upper East Side North (Manhattan) had 999 pickups between 19:00 and 23:00 on Sun 08 Dec 2024, 2.1x the forecast of 474 (surge; standardised score +7.3 over 4 h, largest single hour +6.5). This coincided with: no similar event in any other zone in overlapping hours. This describes co-occurrence in the data, not a cause.

## Sensitivity: what size of deviation would be noticed?

SEMI-SYNTHETIC: artificial surges/drops injected into real out-of-sample actuals; measures sensitivity, not real-world precision.

Share of injected events detected (`event_threshold` 5.0), by demand level, duration and multiplier. Multipliers below 1 are drops; a drop can never fall below zero, so drops are structurally harder to detect than surges of the same relative size.

**1-hour event**

| Forecast demand | x0.2 | x0.5 | x1.5 | x2 | x3 |
|---|---:|---:|---:|---:|---:|
| 1-5/h | 0% | 0% | 0% | 0% | 10% |
| 5-20/h | 0% | 0% | 5% | 10% | 30% |
| 20-100/h | 0% | 0% | 2% | 20% | 75% |
| >=100/h | 0% | 0% | 0% | 42% | 92% |

**3-hour event**

| Forecast demand | x0.2 | x0.5 | x1.5 | x2 | x3 |
|---|---:|---:|---:|---:|---:|
| 1-5/h | 0% | 0% | 10% | 18% | 32% |
| 5-20/h | 0% | 0% | 2% | 18% | 50% |
| 20-100/h | 5% | 2% | 15% | 52% | 85% |
| >=100/h | 82% | 0% | 12% | 80% | 98% |

**6-hour event**

| Forecast demand | x0.2 | x0.5 | x1.5 | x2 | x3 |
|---|---:|---:|---:|---:|---:|
| 1-5/h | 0% | 0% | 18% | 32% | 65% |
| 5-20/h | 0% | 0% | 8% | 38% | 88% |
| 20-100/h | 30% | 0% | 12% | 78% | 100% |
| >=100/h | 100% | 5% | 35% | 98% | 100% |

## Threshold trade-off

Lowering `event_threshold` finds more real deviations and more marginal ones. Recall is for injected events in zones forecast at 20+ pickups/hour.

| event_threshold | events | per 1,000 zone-days | surge x2, 3 h | surge x2, 6 h | drop x0.5, 3 h | drop x0.5, 6 h |
|---:|---:|---:|---:|---:|---:|---:|
| 4 | 581 | 39.4 | 75% | 92% | 6% | 22% |
| 5 | 307 | 20.8 | 57% | 85% | 1% | 2% |
| 6 | 179 | 12.2 | 44% | 69% | 1% | 0% |

## Error model

Residual spread by forecast level (95th-percentile based; the floor is 1 pickup):

| Forecast (mean) | rows | sigma |
|---:|---:|---:|
| 0.2 | 170,292 | 0.47 |
| 1.0 | 76,509 | 1.32 |
| 3.2 | 30,372 | 2.30 |
| 7.0 | 14,238 | 3.91 |
| 14.5 | 10,322 | 6.26 |
| 32.6 | 15,009 | 11.48 |
| 72.7 | 13,637 | 19.37 |
| 143.8 | 14,177 | 32.73 |
| 265.2 | 7,750 | 56.11 |
| 465.9 | 1,166 | 90.71 |

Spread of the pooled score by run length (empirical null; 1 = independent errors): {'1': 1.0, '2': 1.027, '3': 1.141, '6': 1.356, '12': 1.592, '24': 1.896, '48': 2.291}.

## Limitations

* Only the out-of-sample test days can be scored, not the whole history.
* Real-data precision is UNVERIFIED: there are no labelled anomalies. Events are candidates for a person to review.
* Explanations list calendar and weather context that *coincided* with an event; they do not establish a cause.
* Weather is daily and city-wide; it cannot resolve an hour or a neighbourhood.
* Drops are structurally harder to detect than surges (see sensitivity tables).
