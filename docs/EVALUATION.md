# Evaluation

Every result in this project is produced by a command and written to a file; the committed
reports in `reports/` are generated from those files, not typed. This page says what each result
means, how to reproduce it, and what it does **not** show.

| Result | Command | Committed report | Raw output (git-ignored) |
|---|---|---|---|
| Data quality | `build`, `status` | (quality JSON) | `data/processed/<mode>/quality/*.json` |
| Forecast | `forecast-eval` then `forecast-report --out reports/forecasting_real.md` | [forecasting_real.md](../reports/forecasting_real.md) | `artifacts/<mode>/forecast/evaluation.json`, `predictions.parquet` |
| Anomalies | `anomalies` then `anomaly-report --out reports/anomalies_real.md` | [anomalies_real.md](../reports/anomalies_real.md) | `artifacts/<mode>/anomaly/` |
| Repositioning | `optimize-backtest` then `optimize-report --out reports/optimization_real.md` | [optimization_real.md](../reports/optimization_real.md) | `artifacts/<mode>/optimization/` |
| AI analyst | `analyst-benchmark` (and `--holdout`) then `analyst-benchmark-report` | [ai_evaluation_real.md](../reports/ai_evaluation_real.md), [raw runs](../reports/ai_benchmark_real.json) | `artifacts/<mode>/analyst/benchmark.json` |

All headline numbers below are from **real data, January to May 2024**, run on 2026-09-23.

## Data platform (VERIFIED)

* 16,792,900 raw trips → 16,465,849 valid; 327,051 rejected (1.95%), each in quarantine with its
  first failing rule: negative amount 254,741, unknown pickup zone 62,188, excessive duration
  9,391, invalid distance 395, dropoff before pickup 292, pickup outside the window 43, duplicate 1.
* 18 quality checks (3 bronze, 9 silver, 6 gold), all PASS. The gold fact table has 959,161 rows,
  exactly 263 zones × 3,647 valid hours, and its pickups equal the silver trip count to the trip.
* The pipeline is verified against synthetic data with recorded ground truth (planted defects
  reconcile exactly) and against real data (reconciliation and sanity checks such as quiet days and
  the evening peak). One bug found by a real-data check: the weather file was not re-downloaded when
  the window widened; fixed and regression-tested (a changed URL now forces a re-download).

## Forecast (VERIFIED)

Task: hourly pickups per zone, day ahead, forecast from 00:00 using only earlier days. Rolling-origin
validation over the last 56 days in four folds, refitted between folds, with an 80% conformal
interval calibrated on the preceding two weeks.

| Model | WAPE | MAE | RMSE |
|---|---:|---:|---:|
| LightGBM (Poisson) | 17.8% | 3.26 | 10.64 |
| Seasonal mean, last 4 weeks | 19.1% | 3.49 | 11.78 |
| Seasonal naive, last week | 22.4% | 4.09 | 13.74 |
| Naive, yesterday | 30.4% | 5.57 | 20.82 |

* The model beats the strongest baseline by 1.3 percentage points; a day-level bootstrap gives a
  95% interval of 0.7 to 2.1. The improvement is real but modest; most accuracy comes from the
  weekly pattern.
* Federal-holiday days are forecast far worse (WAPE 43.7% vs 17.5% on ordinary days); the largest
  zone-day misses coincided with Memorial Day weekend.
* Intervals: 79.6% empirical coverage overall, 74-82% within each volume band. A first version was
  badly miscalibrated for busy zones (41% coverage); it was fixed and the change is recorded in
  ADR-009 because it was made after seeing test-fold coverage.
* An "oracle weather" experiment (actual same-day weather as a feature) did not improve accuracy.
  It is labelled ORACLE and is not a deployable result.
* Not done: hyper-parameter tuning (avoided to prevent selection bias), a "long weekend" feature
  (suggested by the test folds, so adding it would be tuning on the test set), an annual cycle
  (only five months of data).

## Anomaly detection (mechanism VERIFIED, real precision UNVERIFIED)

* Synthetic data with planted anomalies: 3 of 3 found, 0 unplanted events. Three anomalies cannot
  give an error rate; this shows the mechanism works.
* Real data has no labels. 277 events over 56 days (204 low, 68 medium, 5 high severity; 264
  surges, 13 drops); 27% of events fall on three city-wide days. Manual review found the largest
  events plausible (Memorial Day weekend patterns) but that is a consistency check, not
  verification.
* Sensitivity was measured by injecting artificial surges and drops into real out-of-sample
  residuals: 2x surges lasting 3 hours are found 60% (20-100 pickups/hour zones) to 95% (100+) of
  the time, but a 0.5x drop over 3 hours only 8% at the default threshold. Drops are structurally
  harder. The first version of the method flagged about 25 events a day on real data; ADR-010
  records the correction.

## Repositioning (engine VERIFIED; outcomes SIMULATED)

The optimiser is checked against known answers, brute-force enumeration on small instances, and
invariants (conservation, budget, distance, never worse than not moving). The backtest plans with a
forecast and scores against actual demand, under assumed supply, capacity and costs (no fleet data
exist): the LightGBM plan raises served share by 0.53 points (interval 0.38 to 0.70), the oracle by
2.57. Planning with the seasonal-mean forecast did slightly better than with LightGBM (-0.18 points
for LightGBM, interval excludes zero), so the lower forecast error did not carry over to this
decision. The value depends on how tight the fleet is (+1.65 points when it matches demand, +0.14
when 30% short).

## AI analyst (VERIFIED as measured; LLM mode UNVERIFIED)

See [AI_EVALUATION](AI_EVALUATION.md). In short: 80 development questions scored 90.0% on the first
run and 100% after general fixes made against them; three held-out sets of 40 questions, each run once
without tuning, scored 77.5%, 60.0% and 80.0% (72.5% pooled; each was written after the previous had been used). The safety-related checks (grounding, refusals, no causal wording) held on
every run.

## Engineering checks (VERIFIED)

| Check | Result |
|---|---|
| Python tests | 416 passing, 97% line coverage (`pytest --cov`) |
| Lint, format, types | ruff, ruff format, mypy: clean; frontend ESLint (React hooks + jsx-a11y) and strict TypeScript: clean |
| Python versions | full suite passes on 3.12, 3.13 and 3.14 (Docker containers); the synthetic pipeline gives identical results on all three (LightGBM WAPE 22.3%, interval coverage 80.8%, 3 planted anomalies found); CI runs the matrix |
| Reproducibility | regenerating the real-data forecast and anomaly reports with today's code gives files identical to the committed ones (apart from the timestamp); `requirements.lock` records the versions used |
| Frontend | 32 unit tests (also under Pacific/Auckland, Los Angeles, Kolkata, UTC); TypeScript strict |
| Browser | 18 Playwright tests: 12 axe-core WCAG 2.1 A/AA scans (6 sections × light/dark), keyboard use, analyst, scenario, filtering, phone width |
| Dependencies | `pip-audit` and `npm audit`: no known vulnerabilities |
| Secrets | none in the tree or in the full git history (pattern scan) |
| Concurrency smoke | 420 requests, 16 threads, real data: 0 errors, p95 415 ms, 62 requests/s (a sanity check on one 12-thread machine, not a benchmark) |
| Container | image built; full sample pipeline and server run inside it as uid 10001; healthcheck healthy; results identical to the host's |

Real-browser and accessibility tests found and fixed three defects the unit tests could not: the
skip link never received the first Tab stop, a 63 px horizontal overflow at phone width, and
mid-animation chart captures. Automated accessibility scans cover a subset of WCAG; they do not
replace testing with assistive technology, which was not done.
