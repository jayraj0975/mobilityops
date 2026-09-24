# Limitations

What these results cannot tell you. Each item is also stated where the result appears.

## Data

* **One year, one city.** All of 2024. Forecasts, anomalies and scenarios cover **yellow taxis only**, which
  are 14% of the pickups counted in the three TLC files (high-volume for-hire vehicles are 85%, green taxis
  0.2%). Green taxis and for-hire vehicles are in the data platform and the service view but not in the models.
  The older non-high-volume for-hire files are not used. "Demand" means completed yellow-taxi pickups, not
  mobility demand; the service shares are shares of the pickups counted in those files, not of all mobility
  (subways, buses, private cars and unlicensed trips are absent).
* **One year of seasonality.** The model has seen each season once, so a yearly pattern cannot be told apart
  from 2024's own events, and the test window (6 November to 31 December) is a holiday-heavy stretch, so
  headline accuracy figures describe that season, not an average year.
* **Completed trips only.** Unmet demand, cancellations and waiting time are invisible.
* **Weather is one daily station value** (Central Park) for the whole city. It cannot resolve an
  hour or a neighbourhood, and weather comparisons are associations.
* **Three zones have no centroid** and are excluded from movement in simulations.
* **Timestamps are local time.** The spring-forward hour (10 March) is excluded from the grid and the
  fall-back hour (3 November) is flagged and not modelled; both occur in this window.
* Cleaning rules are conservative conventions (for example a 6-hour duration cap); different rules
  would change counts slightly. The largest rule, dropping negative-amount rows as refunds, removed 1.27% of
  January's rows and 2.15% of December's, so late-month counts are understated relative to early months by up
  to about one percentage point if those rows are real trips. That drift is what makes the silver rejection-rate
  check WARN. For green and for-hire files exact-duplicate removal is not applied and rejected rows are counted
  but not kept.

## Forecasting

* The gain over the strongest simple baseline is **small on ordinary days** (16.0% against 16.4% on the
  mostly ordinary first fold) and large in the holiday weeks (26.1% against 43.2% at Christmas and New Year),
  which is where almost all of the pooled 6.8-point gap comes from. The weekly profile carries most of the
  signal on ordinary days.
* **Holidays are still forecast poorly** (WAPE 38.1% on federal-holiday hours against 18.9% otherwise). Two
  calendar features were pre-registered and adopted (20.2% to 19.5% overall), but the evidence is thin: three
  federal holidays in the test window, a secondary check on August to September that went the other way
  (-0.53 points), and a gain that also appears on ordinary days, so the features may partly be a season
  signal rather than a holiday effect.
* Hyper-parameters are fixed, not tuned. The final registered model has no held-out test of its own;
  the walk-forward numbers estimate the procedure.
* Prediction intervals are per zone-hour and cannot be added into an interval for a city total.
  Coverage for near-zero counts is conservative because counts are discrete. The interval method
  was corrected after seeing test-fold coverage (ADR-009).
* Only the day-ahead horizon exists; there is no intraday update.

## Anomaly detection

* **Real-data precision is unverified.** There are no labelled anomalies; the injection experiment
  measures sensitivity, not correctness.
* Only the 56 out-of-sample days can be scored, and they are the holiday-heavy 6 November to 31 December:
  17% of the events fall on 31 December and 14% on Thanksgiving, and holiday forecast error may inflate the
  count. Drops are structurally harder to detect than surges (0.5x drops over 3 hours are found 0 to 2.5% of
  the time at the default threshold), and sensitivity is lower than on the five months (a 2x, 3-hour surge is
  found 17.5% to 80% of the time by demand level, against 60% to 95%).
* Thresholds are conventions and severity is a heuristic, not a probability. One city-wide
  disruption produces many events; read them together.
* Explanations list coinciding calendar, weather and neighbouring-zone context. They never assert
  a cause, and the context is coarse (daily weather, federal holidays only, no local events).

## Optimisation

* **No fleet data exist.** Supply, vehicle capacity, movement limits and cost are assumptions.
  Results are simulated scenarios, not predictions.
* Vehicles serve demand only in the zone where they stand (no spill-over), which overstates the
  value of exact placement. Empty-travel cost is linear in distance; there is no traffic model.
* The finding that repositioning adds about half a point, and that a simpler forecast plans as well as
  LightGBM (-0.03 points, interval -0.14 to +0.07), holds under these assumptions only (see the sensitivity
  table). Demand here is yellow-taxi demand only.

## AI analyst

* The rule planner covers the intents it encodes: **77.5%, 60.0% and 80.0%** on the first runs of three
  sets of unseen questions (40 each, written by the author; 72.5% pooled), with some answers that used the wrong
  tool. All three sets were fixed against afterwards, so no unseen estimate remains beyond those three
  first runs. It handles English only.
* Re-running the four sets on the full-year data scored 185 of 200 and exposed two defects the earlier data had
  hidden (a "low severity" filter that was ignored, and a past date replaced by tomorrow's forecast); after
  fixing them 187 of 200 pass. Eleven of the 13 failures are questions naming May days that are no longer
  held-out days, so the analyst correctly has no data for them. A keyword planner tuned on one dataset should
  be expected to hide bugs like these.
* It does not cover the green-taxi and for-hire service view; asking about Uber or Lyft gets no answer.
* LLM mode is **UNVERIFIED** (mocked tests only).
* It cannot answer about anything outside the 13 tools, by design.

## Engineering

* **Concurrent CPU-heavy jobs can starve each other.** LightGBM uses every core by default, and
  oversubscribed OpenMP threads spin: two test suites started at once once took over 20 minutes
  instead of 50 seconds. Set `MOBILITYOPS_THREADS` (for example 4) when several jobs share a machine;
  the test suite does this itself. The API's prediction path is not thread-capped.
* Single-process, single-machine; the in-memory cache, metrics, rate limiter and the live viewer count reset on
  restart and are not shared between processes. Not hardened as a general internet service (see
  [SECURITY](SECURITY.md)): one shared API key, no user accounts, no audit trail, no distributed-abuse
  protection.
* **Real time is a replay plus two third-party feeds.** The taxi files are published monthly, so there is no
  live taxi feed; the replay is a replay of held-out days and is labelled as one. The Citi Bike and weather
  feeds depend on two public services outside this project: they can be down, slow or change their format,
  in which case the page shows the last good reading and says it is not current. Citi Bike availability is
  bikes, not taxis, and one weather station stands in for the whole city. Behaviour under sustained load with
  many viewers was not measured; the viewer cap (32) is a safeguard, not a tested capacity.
* **The Android app was verified on an Android 14 emulator, not on a physical phone**, and only in the
  configuration the emulator supports (the server on the host machine). It allows plain `http://` so a home
  server without a certificate works; anything beyond a local network should use HTTPS. The release APK is
  signed with a key generated on the developer's machine and kept out of the repository; losing it means an
  installed copy cannot be updated.
* **The Docker Compose file itself was not run**: the Compose plugin is not installed on the development
  machine. The container it describes was built and run with the same security options and tested (a key is
  required, the data mounts are read-only, the live stream works through it), and the file was checked as
  valid YAML, but `docker compose up` was not exercised.
* The container image is large (about 930 MB) because of the scientific stack. It is not published
  to a registry; the demo host and the Compose file build it from the Dockerfile.
* Browser tests cover Chromium only (they run in CI on the synthetic sample and were also run on the real data).
  Accessibility checks are automated scans, not assistive technology testing. Screenshots are of the real app
  on real data at one viewport.
* The concurrency numbers come from one 12-thread machine on the earlier data and are a sanity check, not a
  benchmark.
* The public demo runs on a free plan: it sleeps when idle (the first request afterwards takes tens of
  seconds), has one small instance, caps the Live tab at 8 concurrent viewers, and serves the aggregate
  data bundle (no trip-level rows). Details in [DEPLOYMENT](DEPLOYMENT.md).


## Pune (0.2.0)

* **Demand is simulated.** Every result computed on Pune data (forecast accuracy, events, coverage) describes the simulator,
  not Pune. The forecast beating its baselines shows the pipeline works and that the simulator has structure to learn.
* **"Weather now" and air quality are model output** on coarse grids (Open-Meteo, CAMS), not station readings, and are
  labelled MODELLED. Rain used by the simulator is ERA5 reanalysis (history) and Open-Meteo's recent-hours model output.
* **Zones are a tessellation of OpenStreetMap suburb points**, not wards. Zones on the edge of the study box are large
  (up to 90 km²) because nothing beyond the box competes for the space.
* **The forecast has no weather input**, so it over-forecasts a dry day after rainy ones (about 12% on 24 September 2026).
* **The city-level forecast range** sums the zone ranges and is wider than a true range for the total.
* **Live events are a fixed rule**, validated only against simulated planted events.
* **Not implemented:** traffic (TomTom), station air quality (OpenAQ), the PMPML timetable, any real trip source.
* **One machine, one writer.** The live store is SQLite (ADR-018); there is no failover or scale-out.
* **Not verified:** a public domain deployment, the phone app on a physical device or over HTTPS to a public name,
  `docker compose up` itself, systemd units on a real host, and screen-reader use of the map (only automated scans;
  the map has a keyboard route through the zone selector and a ranked table).
