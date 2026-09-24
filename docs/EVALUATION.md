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
| Holiday features | `forecast-holiday-experiment --out reports/holiday_experiment_real.md` | [holiday_experiment_real.md](../reports/holiday_experiment_real.md) | (the report has a `.json` twin) |
| AI analyst | `analyst-benchmark` (and `--holdout`) then `analyst-benchmark-report` | [ai_evaluation_real.md](../reports/ai_evaluation_real.md), [raw runs](../reports/ai_benchmark_real.json) | `artifacts/<mode>/analyst/benchmark.json` |

All headline numbers below are from **real data, all of 2024**, regenerated on 2026-09-24 after the data was
extended from five months to a full year. The January to May results are archived, unchanged, in
[reports/jan_may_2024](../reports/jan_may_2024/README.md). The two are **not directly comparable**: the test
window moved from 6 April to 31 May (ordinary days) to 6 November to 31 December (Thanksgiving, Christmas and
New Year), and the training history grew from five months to a year.

## Data platform (VERIFIED)

* 41,169,720 raw yellow-taxi trips → 40,268,069 valid; 901,651 rejected (2.19%), each in quarantine with its
  first failing rule: negative amount 733,774, unknown pickup zone 143,167, excessive duration 22,001,
  dropoff before pickup 1,575, invalid distance 1,074, pickup outside the window 56, duplicate 4.
* 28 quality checks (3 bronze, 9 silver, 6 services, 10 gold): 27 PASS and one **WARN**. The warning is the
  rejection rate: 2.19% against a 2% threshold that was set before the data was extended and deliberately not
  moved to make the run pass. The cause is a real drift in the source: refunds and adjustments (the
  `negative_amount` rule) rose from 1.27% of raw rows in January to 2.15% in December, while unknown pickup
  zones stayed flat at about 0.3 to 0.4%. Because those trips are excluded as not completed, late-month counts
  would be understated by up to about one percentage point relative to January, if those rows are real trips
  (a judgement call recorded in the data dictionary).
* The gold fact table has 2,309,929 rows, exactly 263 zones × 8,783 valid hours (one nonexistent spring-forward
  hour excluded; the fall-back hour is flagged and not modelled), and its pickups equal the silver trip count to
  the trip.
* The pipeline is verified against synthetic data with recorded ground truth (planted defects reconcile
  exactly) and against real data (reconciliation and sanity checks such as quiet days and the evening peak).
  One bug found by a real-data check earlier: the weather file was not re-downloaded when the window widened;
  fixed and regression-tested. Another, found by extending the data: an interrupted ingestion lost its record of
  finished downloads because the manifest was saved only at the end; it is now saved after every file and an
  interrupted run resumes (regression-tested).

## Services (VERIFIED)

Green taxis and high-volume for-hire vehicles (`ingest --services green,fhvhv`) are aggregated straight to
pickups per zone-hour with the same ordered cleaning rules as yellow taxis (duplicate removal is the one rule
not applied: it needs the whole trip table in memory; the yellow data has 4 duplicates in 41 million rows).

| Service | Raw rows | Valid | Rejected | Pickups in the gold table |
|---|---:|---:|---:|---:|
| Yellow taxis | 41,169,720 | 40,268,069 | 2.19% | 40,268,069 (14.4%) |
| Green taxis | 660,218 | 653,351 | 1.04% | 653,351 (0.2%) |
| High-volume for-hire | 239,470,448 | 239,431,770 | 0.016% | 239,431,692 (85.4%) |

Every service's gold total equals its cleaned trips in valid hours exactly (checked on every build), and the
yellow rows of the service table equal the yellow zone fact. Rejection rates are not comparable across
services because the source files differ (yellow carries refund rows that the for-hire files mostly do not).
The shares are of the pickups **counted in these three files**, not of mobility in New York. The forecasting,
anomaly and repositioning results below cover yellow taxis only, which are now a minority of the pickups.

## Forecast (VERIFIED)

Task: hourly pickups per zone, day ahead, forecast from 00:00 using only earlier days. Rolling-origin
validation over the last 56 days (6 November to 31 December) in four folds, refitted between folds, with an 80%
conformal interval calibrated on the preceding two weeks. The model uses the two holiday features adopted below.

| Model | WAPE | MAE | RMSE |
|---|---:|---:|---:|
| LightGBM (Poisson) | 19.5% | 3.62 | 12.15 |
| Seasonal mean, last 4 weeks | 26.3% | 4.88 | 17.99 |
| Seasonal naive, last week | 31.6% | 5.85 | 21.73 |
| Naive, yesterday | 30.0% | 5.57 | 20.24 |

* The model beats the strongest baseline by 6.8 percentage points; a day-level bootstrap gives a 95% interval
  of 4.2 to 10.2. **Where that comes from matters:** per fold, LightGBM against the seasonal mean is 16.0% vs
  16.4% (6 to 19 November, mostly ordinary days; it contains Veterans Day), 21.0% vs 30.0% (Thanksgiving), 16.8% vs 20.4% and 26.1% vs 43.2%
  (Christmas and New Year). On ordinary days the model's edge is small, as it was on the earlier data (1.3
  points); around holidays it is large.
* Summed to a city total, the hourly WAPE is 9.7% (17.1% for the seasonal mean). That is a much easier number
  than the per-zone figure and is not comparable to it.
* Federal-holiday hours are forecast far worse than ordinary hours (WAPE 38.1% vs 18.9%), and there are only
  three federal holidays in the test window (Veterans Day, Thanksgiving, Christmas).
* Intervals: 79.6% empirical coverage overall, 75 to 82% within each volume band. A first version was badly
  miscalibrated for busy zones (41% coverage); it was fixed and the change is recorded in ADR-009 because it was
  made after seeing test-fold coverage.
* An "oracle weather" experiment (actual same-day weather as a feature) made accuracy **worse** (19.5% to 21.1%).
  It is labelled ORACLE and is not a deployable result.
* Not done: hyper-parameter tuning (avoided to prevent selection bias); an annual-cycle feature (there is only
  one year, so a yearly pattern cannot be separated from 2024's own events).

## Holiday features: a pre-registered test (VERIFIED as measured; the mechanism is not established)

On the earlier five months the model scored 43.7% on holiday hours against 17.5% on ordinary days, and a
"long weekend" feature was deliberately not added because the test folds had suggested it. With a full year that
could be tested fairly: [PREREGISTRATION_HOLIDAY](PREREGISTRATION_HOLIDAY.md) fixed the hypothesis, the two
feature definitions (`is_long_weekend`, `days_to_holiday`), the evaluation and a three-part decision rule, and was
committed (`ee6d727`) before any forecast on June to December was evaluated.

| Slice (primary test, 6 Nov to 31 Dec) | Base | With the features | Difference |
|---|---:|---:|---:|
| All hours | 20.2% | 19.5% | +0.72 pp (95% interval +0.38 to +1.15) |
| Federal-holiday hours | 40.7% | 38.1% | +2.59 pp |
| Days adjoining a holiday | 32.9% | 31.8% | +1.11 pp |
| Long-weekend days | 20.0% | 20.4% | -0.41 pp |

All three conditions held (pooled interval excludes zero, holiday hours not worse, no slice worse than one point;
the worst was -0.08), so the features were **adopted**. Reading it honestly:

* The gain is not confined to holidays (ordinary days improved by 0.65 points), so the features may be acting
  partly as a "holiday season" signal; the test cannot separate the two.
* The **secondary check** (test folds ending 30 September, containing one holiday) went the other way: 19.6% to
  20.2%, -0.53 points. The pre-registration says the secondary cannot overrule the primary, and it did not; but it
  is evidence the result is not robust across seasons.
* The whole primary result rests on three holidays.
* Regenerating the experiment on the rebuilt database reproduced every number exactly.

## Anomaly detection (mechanism VERIFIED, real precision UNVERIFIED)

* Synthetic data with planted anomalies: 3 of 3 found, 0 unplanted events. Three anomalies cannot give an error
  rate; this shows the mechanism works.
* Real data has no labels. 307 events over 56 days (244 low, 54 medium, 9 high severity; 299 surges, 8 drops);
  17% of events fall on 31 December and 14% on Thanksgiving, and three of the five busiest days are holiday days
  or eves (31 December, Thanksgiving, Christmas Eve; the others are 11 December and Christmas Day). The largest
  events (for example the LaGuardia surges around 1 December) fall in the holiday period, which is consistent
  with the method working but is not verification, and holiday-driven forecast error may inflate the count.
  No manual review of these events was done.
* Sensitivity was measured by injecting artificial surges and drops into real out-of-sample residuals: a 2x surge
  lasting 3 hours is found 17.5% of the time in zones with 1 to 20 pickups an hour, 52.5% at 20 to 100 and 80% at
  100 or more; a 0.5x drop over 3 hours is essentially never found (0 to 2.5%). On the earlier data the same
  surge was found 60 to 95% of the time. A plausible reason is that the holiday weeks widen the error scale that
  events are measured against, but that was not tested. Drops are structurally harder than surges.

## Repositioning (engine VERIFIED; outcomes SIMULATED)

The optimiser is checked against known answers, brute-force enumeration on small instances, and invariants
(conservation, budget, distance, never worse than not moving). The backtest plans with a forecast and scores
against actual demand, under assumed supply, capacity and costs (no fleet data exist): the LightGBM plan raises
served share by 0.50 points (interval 0.36 to 0.65), the oracle by 2.56 (earlier data: 0.53 and 2.57). Planning
with the seasonal-mean forecast is now indistinguishable from planning with LightGBM (-0.03 points, interval
-0.14 to +0.07), so, as before, the lower forecast error does not carry over to this decision. The value depends
on how tight the fleet is (+1.30 points when it matches demand, +0.16 when 30% short).

## AI analyst (VERIFIED as measured; LLM mode UNVERIFIED)

See [AI_EVALUATION](AI_EVALUATION.md). In short: 80 development questions scored 90.0% on the first run and 100%
after general fixes made against them; three held-out sets of 40 questions, each run once without tuning,
scored 77.5%, 60.0% and 80.0% (72.5% pooled; each was written after the previous had been used). On the
full-year data the same four sets score 187 of 200 after two fixes (see AI_EVALUATION for the breakdown). The
safety-related checks (grounding, refusals, no causal wording) held on every run.

## Real time (VERIFIED)

The Live tab and the Android app read one server-sent-events stream: a replay of the held-out days on a shared
clock (labelled REPLAY: the taxi files are monthly, so no live taxi feed exists) and two genuinely live public
feeds (Citi Bike GBFS, National Weather Service). Checked: the replay's arithmetic and clock, the feed parsers
and failure behaviour (last good data kept and marked not current), the hub's lifecycle and viewer cap (unit and
integration tests); the browser (a dropped stream recovers; axe scans pass with the stream running); the Android
client against a local server; and the whole path against the real Citi Bike and NWS services, on the host and
inside the hardened container. Not measured: behaviour under sustained load with many viewers.

## Engineering checks (VERIFIED)

| Check | Result |
|---|---|
| Python tests | 486 passing, 95% line coverage (`pytest --cov`); the pre-registered experiment's decision rule and bootstrap, the service transform (one planted defect per rule), the live hub and the stream have their own tests |
| Lint, format, types | ruff, ruff format, mypy: clean; frontend ESLint (React hooks + jsx-a11y) and strict TypeScript: clean; Android lint: no errors |
| Python versions | CI runs the suite on 3.12, 3.13 and 3.14; earlier, the synthetic pipeline gave identical results on all three (LightGBM WAPE 22.3%, interval coverage 80.8%, 3 planted anomalies found) |
| Reproducibility | regenerating the holiday experiment on the rebuilt database reproduced every number; earlier, regenerating the five-month forecast and anomaly reports gave files identical to the committed ones (apart from the timestamp); `requirements.lock` records the versions used |
| Documents vs reports | `tests/unit/test_docs_consistency.py` fails when a number in the README or these documents drifts from the generated reports (it caught every stale figure when the data was extended) |
| Frontend | 57 unit tests (also under Pacific/Auckland, Los Angeles, Kolkata, UTC); TypeScript strict |
| Browser | 24 Playwright tests on the real-data server: 16 axe-core WCAG 2.1 A/AA scans (8 sections × light/dark, including the Live page with the stream running), keyboard use, analyst, scenario, filtering, phone width, and a dropped live stream being reported and recovered |
| Android | 27 unit tests, including the stream client against a local server (order, key header, reconnect, refusal message, malformed event, backoff); lint clean; debug and signed minified release builds; every screen run on an Android 14 emulator against the real-data server; the Gradle build also passes in CI |
| Dependencies | `pip-audit` and `npm audit`: no known vulnerabilities |
| Secrets | none in the tree or in the full git history (pattern scan); the Android signing key is outside the repository |
| Concurrency smoke | 420 requests, 16 threads, real data: 0 errors, p95 415 ms, 62 requests/s (a sanity check on one 12-thread machine on the earlier data, not a benchmark) |
| Container | image built with the current code; run with the Compose file's security options (read-only filesystem, no capabilities, read-only data mounts) against the real data: healthy, 401 without an API key, data with it, live stream with both feeds |

Real-browser and accessibility tests found and fixed three defects the unit tests could not (the skip link never
received the first Tab stop, a 63 px horizontal overflow at phone width, and mid-animation chart captures), and
running the Android app on an emulator found two more (a reversed week-over-week comparison and a chart axis
below zero). Automated accessibility scans cover a subset of WCAG; they do not replace testing with assistive
technology, which was not done.
