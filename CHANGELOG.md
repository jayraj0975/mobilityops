# Changelog

## Unreleased

- **Android toolchain upgraded together** (the Dependabot bumps each needed the others): Gradle 9.7.1 (wrapper regenerated,
  checksum pinned), Android Gradle Plugin 9.4.1 with built-in Kotlin, compileSdk 36, androidx appcompat 1.8.0, Material 1.14.0,
  org.json 20260814. 45 unit tests, lint, debug, minified release and AAB builds pass, and the app was re-run on the emulator.
  `targetSdk` stays 34 (raising it changes window-inset behaviour and needs its own pass).
- **Second weather provider (MET Norway)** after Open-Meteo answered HTTP 429 to Render's shared address: weather is one need with
  two providers, healthy if either is. Attribution added everywhere; see `docs/PUNE_DATA_SOURCES.md` (source 14).
- **Pune console on Render's free plan:** `serve --with-worker` runs the worker on a thread (free web services have no background
  workers); `pack_demo.py --mode pune`; the `mobilityops-pune` service in `render.yaml`.

## 0.2.0 (2026-09-25)

### Pune: a real-time platform on simulated demand
- **What is real and what is not.** No open source of Pune taxi, ride-hail or bus demand exists (checked source by
  source, `docs/PUNE_DATA_SOURCES.md`), so demand is **SIMULATED** by a documented model and labelled so in the API,
  the console, the Android app and the docs. Real inputs: hourly rain (Open-Meteo: ERA5 history and recent-hours model
  output), the Maharashtra holiday calendar, and 91 zones built from OpenStreetMap suburbs (ODbL, attributed).
  Live sources polled on their own schedules: current weather (15 min), modelled air quality (60 min), recent rain.
  Traffic, station air quality and the PMPML timetable are listed as not implemented; nothing pretends otherwise.
- **City profiles** (`city.py`): timezone, holiday calendar and wording per city; `MOBILITYOPS_MODE=pune`. New York
  behaviour is unchanged (every existing test passes on the defaults). New dependency: `holidays`.
- **Live layer:** a separate worker process (sole writer) fills a SQLite (WAL) store; freshness (LIVE, DELAYED,
  STALE, OFFLINE) is derived from each source's own timestamps; `/api/v1/state/*` and a server-sent event stream with
  heartbeats and a viewer cap; a rule finds events among today's completed hours; `/ready` reports the worker.
- **Console** (web, when the server is in pune mode): design-system components, an SVG zone map with layers, a NOW /
  -15m / -1h / -6h / TODAY / FORECAST time control, forecast ranges, events, a data-quality centre, connection and
  worker notices, light and dark themes. 24 browser tests including axe WCAG A/AA scans of every page in both themes.
- **Android** (Gradle, now Kotlin as well as Java): the app asks the server for its mode and shows Home, Map, Forecast,
  Alerts and Status (plus zone details) for Pune. 45 unit tests, lint clean, run on an emulator against the live server
  including a server that is killed and restarted. Version 2.0.0; debug and release APKs and an AAB build with
  `./gradlew assembleDebug assembleRelease bundleRelease`. Not tested on a physical phone.
- **Deployment:** a worker service in Compose and systemd, split www/api hostnames behind Caddy (validated with the
  Caddy image), and a hardened container run (read-only filesystem, no capabilities, unprivileged user) that served
  the live data. No public domain was deployed; `docs/PRODUCTION.md` says what that needs.

### Defects found and fixed while building it
- Counts drawn directly from a Poisson sampler consumed a rate-dependent amount of randomness, so new rain data or a
  planted event reshuffled every later cell of the day (history would have been rewritten every 15 minutes). Counts now
  come from a fixed uniform per cell through the Poisson quantile function. Caught by tests, twice.
- `docker stop` / `systemctl stop` hung: uvicorn waits for open event streams, and a connected viewer never ends one.
  Graceful shutdown is bounded to 5 s (measured: 5.6 s with a viewer connected). The worker, as PID 1, ignored SIGTERM
  (10.1 s, then killed); it now stops in 0.3 s.
- Adapters stamped `received_at` from the wall clock instead of their caller's; hourly rain was flagged DELAYED at 39
  minutes because its expected interval was 15 minutes; analyst and anomaly text said "US federal holiday" on Pune
  dates; a hard-coded "about five months of history" note was stale on a year of data.
- Documentation claimed TomTom, OpenAQ and GTFS "adapters" that did not exist; corrected, and an unimplemented source
  can no longer be marked enabled by setting a key.

### Known defects fixed earlier in this release
- Concentration (HHI) is computed over every zone, not the top 100; unbounded and error solver statuses are reported
  as such; dropoffs are reconciled by accounting (ADR-017); CI is hardened (SHA-pinned actions, pip-audit, CodeQL,
  Dependabot, Gradle wrapper checksum, Docker build); versions are tested for consistency.

### Real data: full year, services and a holiday test
- Real data extended from January to May to all of 2024. Results regenerated; the earlier ones are archived in
  `reports/jan_may_2024`. The test window is now 6 November to 31 December, so results are not directly
  comparable. Headline: LightGBM WAPE 19.5% against 26.3% for the best baseline, almost all of the gap in the
  holiday weeks (16.0% against 16.4% on the first fold).
- The silver quality gate now **WARNs** (2.19% rejected against a 2% threshold set beforehand): refunds and
  adjustments grew from 1.3% to 2.2% of rows over the year. The threshold was not moved.
- Green taxis and high-volume for-hire vehicles (`ingest --services green,fhvhv`), aggregated to zone-hour counts
  with the same cleaning rules, reconciled on every build, and shown in the API (`/demand/services`), the
  dashboard and the app. Forecasts, anomalies and scenarios stay yellow-only.
- Two holiday features, pre-registered (`docs/PREREGISTRATION_HOLIDAY.md`) before the test and adopted by the rule
  fixed in advance (20.2% to 19.5%); a secondary check went the other way and is reported. New command
  `forecast-holiday-experiment`.
- Ingestion saves its manifest after every file, so an interrupted download resumes instead of starting again.

### Real time, Android and self-hosting
- The public demo was redeployed with the full-year bundle (`demo-data-v2`) and the Live tab; measured under the
  free plan's 512 MB cap before deploying (peak 370 MB with scenario solves, analyst questions and six streams).
- A Live view: a labelled replay of the held-out days plus live Citi Bike and Central Park weather feeds over a
  server-sent-events stream (`/api/v1/live/*`), in the dashboard and the app.
- A native Android app built with Gradle (`apps/android`): five screens, a reconnecting stream client, 27 unit
  tests, a CI job, a signed and minified release build. Found by running it on an emulator: a reversed
  week-over-week comparison and a chart axis below zero, both fixed.
- Self-hosting: `docker-compose.yml` (hardened, key required), a systemd unit, an HTTPS proxy config that does
  not buffer the stream, `docs/SELF_HOSTING.md`. The dashboard can hold and send the API key.

### Analyst
- Re-running the four question sets on the full-year data (185 of 200) exposed two defects the earlier data had
  hidden, both fixed: a "low severity" filter that was ignored, and a past date silently replaced by tomorrow's
  forecast. Anomaly answers now state the filters applied. After the fixes 187 of 200 pass.

### Public demo
- Public repository and a hosted demo (free Render plan) serving the real-data snapshot from an
  aggregate-only release bundle; About page; installable web app manifest and icons;
  `docs/DEPLOYMENT.md`, `render.yaml`, `scripts/pack_demo.py`, `scripts/fetch_demo.py`.
- Per-client rate limits (a lower budget for the analyst and scenario endpoints), request-body cap
  that also covers chunked uploads, HSTS behind a trusted proxy. `MOBILITYOPS_TRUST_PROXY` is the
  number of proxies in front; the client address is counted from the right of `X-Forwarded-For`.
  A first version trusted the leftmost entry and a forged header dodged the limit on the live site;
  fixed, tested and measured (Render is three proxies deep).
- Next-day forecast keeps only the history it needs (peak memory 413 to 248 MB, same forecasts).

### Analyst
- General planner fixes for the failures found by the held-out sets (weather, forecast-error,
  anomaly, repositioning and definition phrasings; "drop-off" no longer read as the anomaly word
  "drop"; a month followed by a full stop no longer read as an unknown place; more refusals for
  shell commands and model replacement).
- Second and third held-out sets (40 questions each) frozen before their first runs: **60.0%** and **80.0%**; the first set had scored 77.5% (72.5% pooled). All are development data after the fixes; see `docs/AI_EVALUATION.md`. Round-three fixes: `march 2024` and `first week of May` periods, `earners`, `rush hour timing`, `any zone`, refusal to export data.

## 0.1.0 - 2026-09-24

First complete version: data platform with quarantine and quality gates, analytics, day-ahead
forecasting with walk-forward evaluation and conformal intervals, residual-based anomaly detection,
simulated repositioning scenarios, a FastAPI service, a React interface and a controlled AI analyst
with a benchmark. See `README.md` for results and `docs/` for methods and limitations.

### Corrections made after seeing results (also in `docs/DECISIONS.md`)
- Prediction intervals are calibrated per demand band; a single scaled quantile covered only 41% of
  busy-zone hours (ADR-009).
- Anomaly scoring uses a tail-aware error scale and an empirical null for pooled evidence; the first
  version flagged about 25 events a day on real data (ADR-010).
- Ingestion re-downloads a file when the requested URL changes (a widened weather window had kept a
  stale file).

### Hardening
- Thread cap (`MOBILITYOPS_THREADS`) so concurrent jobs cannot starve each other; single-flight
  cache loading; CLI reports missing prerequisites; non-root container image; browser tests with
  accessibility scans.

### Dependencies and tooling
- CI runs the Python job on 3.12, 3.13 and 3.14 (verified to give identical sample results), Node 24, and a real-browser end-to-end job with accessibility scans; Docker image now Python 3.14 / Node 24;
- CI actions moved to v7; Dependabot configured; `requirements.lock` records the versions the
  results were produced with; ESLint (React hooks and accessibility rules) added; frontend pages
  are code-split; dead code removed.
