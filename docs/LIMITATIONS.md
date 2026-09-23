# Limitations

What these results cannot tell you. Each item is also stated where the result appears.

## Data

* **Five months, one city, one taxi type.** Jan to May 2024, yellow taxis only: no green cabs,
  for-hire vehicles or ride-hail (which carry most of NYC's app-based trips). "Demand" here means
  completed yellow-taxi pickups, not mobility demand.
* **No annual seasonality.** The model has never seen a summer, a December or a year boundary.
* **Completed trips only.** Unmet demand, cancellations and waiting time are invisible.
* **Weather is one daily station value** (Central Park) for the whole city. It cannot resolve an
  hour or a neighbourhood, and weather comparisons are associations.
* **Three zones have no centroid** and are excluded from movement in simulations.
* **Timestamps are local time.** The spring-forward hour is excluded and the fall-back hour is not
  modelled; only the spring case occurs in this window.
* Cleaning rules are conservative conventions (for example a 6-hour duration cap); different rules
  would change counts slightly.

## Forecasting

* The gain over the strongest simple baseline is **small** (1.3 points of WAPE). The weekly profile
  carries most of the signal.
* **Holidays and long weekends are forecast poorly** (WAPE 43.7% on federal holidays). A
  long-weekend feature would likely help; it was deliberately not added because the test folds
  suggested it.
* Hyper-parameters are fixed, not tuned. The final registered model has no held-out test of its own;
  the walk-forward numbers estimate the procedure.
* Prediction intervals are per zone-hour and cannot be added into an interval for a city total.
  Coverage for near-zero counts is conservative because counts are discrete. The interval method
  was corrected after seeing test-fold coverage (ADR-009).
* Only the day-ahead horizon exists; there is no intraday update.

## Anomaly detection

* **Real-data precision is unverified.** There are no labelled anomalies; the injection experiment
  measures sensitivity, not correctness.
* Only the 56 out-of-sample days can be scored. Drops are structurally harder to detect than
  surges (0.5x drops over 3 hours are found 8% of the time at the default threshold).
* Thresholds are conventions and severity is a heuristic, not a probability. One city-wide
  disruption produces many events; read them together.
* Explanations list coinciding calendar, weather and neighbouring-zone context. They never assert
  a cause, and the context is coarse (daily weather, federal holidays only, no local events).

## Optimisation

* **No fleet data exist.** Supply, vehicle capacity, movement limits and cost are assumptions.
  Results are simulated scenarios, not predictions.
* Vehicles serve demand only in the zone where they stand (no spill-over), which overstates the
  value of exact placement. Empty-travel cost is linear in distance; there is no traffic model.
* The finding that repositioning adds about half a point, and that a simpler forecast planned
  slightly better than LightGBM, holds under these assumptions only (see the sensitivity table).

## AI analyst

* The rule planner covers the intents it encodes: **77.5% on unseen questions**, with some
  answers that used the wrong tool. It handles English only.
* LLM mode is **UNVERIFIED** (mocked tests only).
* It cannot answer about anything outside the 13 tools, by design.

## Engineering

* Not internet-ready (see SECURITY). Single-process, single-machine; the in-memory cache and
  metrics reset on restart and are not shared between processes.
* The container image is large (925 MB) because of the scientific stack. It was built and run
  locally; it is not published anywhere.
* Browser tests cover Chromium only. Accessibility checks are automated scans, not assistive
  technology testing. Screenshots are of the real app on real data at one viewport.
* The concurrency numbers come from one 12-thread machine and are a sanity check, not a benchmark.
* No hosted demo exists; nothing here has been deployed.
