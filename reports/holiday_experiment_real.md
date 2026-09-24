# Holiday and long-weekend features: pre-registered experiment (real data)

Generated 2026-09-24T13:47:08.680106+00:00 from data run `20260924T132214Z-17545894`. Hypothesis, features, evaluation and decision rule were committed before any of this was run: [docs/PREREGISTRATION_HOLIDAY.md](../docs/PREREGISTRATION_HOLIDAY.md). Both models use identical settings and folds; only the two calendar features differ.

## Primary test

Test days 2024-11-06 to 2024-12-31 (4 folds of 14 days, 353,472 zone-hours). Positive differences mean the holiday features are better (WAPE of `base` minus WAPE of `holiday`, in percentage points).

| Slice | Zone-hours | Days | Base WAPE | Holiday-features WAPE | Difference (pp) |
|---|---:|---:|---:|---:|---:|
| All test hours | 353,472 | 56 | 20.2% | 19.5% | +0.72 |
| Federal-holiday hours | 18,936 | 3 | 40.7% | 38.1% | +2.59 |
| Days adjoining a holiday | 44,184 | 7 | 32.9% | 31.8% | +1.11 |
| Long-weekend days | 18,936 | 3 | 20.0% | 20.4% | -0.41 |

Federal holidays in this test window: 2024-11-11, 2024-11-28, 2024-12-25.

Day-level bootstrap (2,000 resamples of 56 test days): pooled difference +0.72 pp, 95% interval +0.38 to +1.15; the holiday features were better in 100.0% of resamples.

### Decision rule (fixed in advance)

1. Pooled WAPE improves and the 95% interval excludes zero: **yes**
2. Holiday-hour WAPE does not get worse: **yes**
3. No weekday, holiday or volume slice worsens by more than one point (worst slice -0.08 pp): **yes**

Result: features **ADOPTED** on this test.

### Slices

**weekday**

| Segment | Zone-hours | Base | Holiday features | Difference (pp) |
|---|---:|---:|---:|---:|
| Fri | 50,496 | 19.6% | 19.1% | +0.52 |
| Mon | 50,496 | 20.7% | 18.9% | +1.79 |
| Sat | 50,496 | 19.2% | 18.8% | +0.45 |
| Sun | 50,496 | 20.6% | 19.8% | +0.72 |
| Thu | 50,496 | 20.4% | 19.8% | +0.53 |
| Tue | 50,496 | 22.4% | 21.7% | +0.68 |
| Wed | 50,496 | 19.2% | 18.6% | +0.55 |

**holiday**

| Segment | Zone-hours | Base | Holiday features | Difference (pp) |
|---|---:|---:|---:|---:|
| holiday | 18,936 | 40.7% | 38.1% | +2.59 |
| ordinary day | 334,536 | 19.5% | 18.9% | +0.65 |

**volume**

| Segment | Zone-hours | Base | Holiday features | Difference (pp) |
|---|---:|---:|---:|---:|
| <1/h | 202,176 | 118.1% | 118.2% | -0.08 |
| 1-5/h | 70,920 | 62.5% | 62.1% | +0.39 |
| 5-20/h | 17,208 | 36.6% | 35.8% | +0.80 |
| >=20/h | 63,168 | 17.7% | 17.0% | +0.74 |

## Secondary check (cannot overrule the primary)

Test days 2024-08-06 to 2024-09-30 (4 folds of 14 days, 353,472 zone-hours). Positive differences mean the holiday features are better (WAPE of `base` minus WAPE of `holiday`, in percentage points).

| Slice | Zone-hours | Days | Base WAPE | Holiday-features WAPE | Difference (pp) |
|---|---:|---:|---:|---:|---:|
| All test hours | 353,472 | 56 | 19.6% | 20.2% | -0.53 |
| Federal-holiday hours | 6,312 | 1 | 26.1% | 26.5% | -0.32 |
| Days adjoining a holiday | 12,624 | 2 | 21.1% | 21.2% | -0.12 |
| Long-weekend days | 18,936 | 3 | 22.6% | 22.1% | +0.46 |

Federal holidays in this test window: 2024-09-02.

Day-level bootstrap (2,000 resamples of 56 test days): pooled difference -0.53 pp, 95% interval -0.74 to -0.35; the holiday features were better in 0.0% of resamples.

### Decision rule (fixed in advance)

1. Pooled WAPE improves and the 95% interval excludes zero: **NO**
2. Holiday-hour WAPE does not get worse: **NO**
3. No weekday, holiday or volume slice worsens by more than one point (worst slice -0.84 pp): **yes**

Result: features **NOT ADOPTED** on this test.

### Slices

**weekday**

| Segment | Zone-hours | Base | Holiday features | Difference (pp) |
|---|---:|---:|---:|---:|
| Fri | 50,496 | 18.6% | 19.0% | -0.40 |
| Mon | 50,496 | 21.5% | 21.9% | -0.47 |
| Sat | 50,496 | 21.0% | 21.7% | -0.71 |
| Sun | 50,496 | 21.4% | 21.7% | -0.38 |
| Thu | 50,496 | 18.1% | 18.6% | -0.50 |
| Tue | 50,496 | 19.9% | 20.7% | -0.84 |
| Wed | 50,496 | 17.5% | 17.9% | -0.42 |

**holiday**

| Segment | Zone-hours | Base | Holiday features | Difference (pp) |
|---|---:|---:|---:|---:|
| holiday | 6,312 | 26.1% | 26.5% | -0.32 |
| ordinary day | 347,160 | 19.5% | 20.1% | -0.54 |

**volume**

| Segment | Zone-hours | Base | Holiday features | Difference (pp) |
|---|---:|---:|---:|---:|
| <1/h | 211,896 | 112.9% | 112.8% | +0.11 |
| 1-5/h | 62,208 | 60.1% | 60.1% | +0.00 |
| 5-20/h | 17,640 | 35.6% | 35.8% | -0.20 |
| >=20/h | 61,728 | 16.9% | 17.4% | -0.57 |
