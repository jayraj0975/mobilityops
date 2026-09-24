# Decision log

Significant decisions only: context, decision, alternatives, consequences. Trivial implementation
details are not recorded here.

---

## ADR-001: Local-first stack: Python, DuckDB, Parquet

**Context.** The project must run on an ordinary laptop and in CI, over months of NYC taxi trips
(roughly 3 million rows per month).

**Decision.** Python 3.12, DuckDB as the analytical engine, Parquet for stored layers. No server
database, Spark, Kafka, Airflow, Redis or Kubernetes.

**Alternatives.** PostgreSQL (needs a server for no analytical gain here); Spark (data is far below
the scale that justifies it); dbt (adds a toolchain, and the transformations are a handful of SQL
statements that are easier to test as plain functions).

**Consequences.** One process, no services to start, fast tests. If the data ever outgrew one
machine this decision would need revisiting; that is a documented limitation, not a hidden one.

---

## ADR-002: One Python package instead of top-level `pipelines/`, `ml/`, `ai/` directories

**Context.** The brief suggests separate top-level directories for pipelines, ML and AI.

**Decision.** A single installable package `mobilityops` (under `src/`) with one subpackage per
concern (`ingestion`, `transform`, `quality`, `analytics`, `forecasting`, `anomaly`,
`optimization`, `ai`, `api`). The web app stays separate under `apps/web`.

**Alternatives.** Separate top-level directories, each with its own import root.

**Consequences.** One dependency set, one test configuration, ordinary imports between layers, and
no `sys.path` tricks. The layer boundaries are still visible in the directory names.

---

## ADR-003: Sample mode and real mode never share data

**Decision.** Synthetic and real data live in separate directories and separate DuckDB files
(`data/raw/{sample,real}`, `data/processed/{sample,real}`), selected by `MOBILITYOPS_MODE`.
Every synthetic artifact carries the label `TEST / SYNTHETIC DATA`, and the CLI refuses to write
synthetic data while in real mode.

**Consequences.** A synthetic result cannot be mistaken for a real-world one.

---

## ADR-004: No LLM key is assumed; the AI analyst has a deterministic mode

**Context.** No LLM API key is available in the development environment, and the analytical
product must keep working when an LLM is unavailable.

**Decision.** The AI analyst is built as a planner interface with two implementations: a
deterministic planner (maps a question to controlled tools with fixed rules) and an LLM planner
(provider-backed, enabled only when `ANTHROPIC_API_KEY` and `MOBILITYOPS_LLM_MODEL` are set).
Tools are read-only deterministic functions in both modes.

**Consequences.** Everything, including the benchmark, runs offline. LLM-mode results are reported
as `STATUS: UNVERIFIED` unless the benchmark has actually been run against a real model, and no
LLM-mode number is ever fabricated.

---

## ADR-005: Python 3.12 minimum

**Context.** The current numpy type stubs use Python 3.12 syntax, and CI and development both run
3.12.

**Decision.** `requires-python >= 3.12`. Claiming 3.11 support that is never tested would be a
false claim.

---

## ADR-006: Day-ahead framing, walk-forward validation, no hyper-parameter search

**Context.** "Forecast demand" can mean many things, and most ways of evaluating it leak the future.

**Decision.** The task is fixed as: at 00:00 local of day D, forecast pickups per zone for each hour
of D, using only days before D. Validation is rolling-origin: the last 56 days are test days in
four consecutive folds; each fold's model is fitted on earlier days and its interval width is
calibrated on the block immediately before the fold. There is no random split. LightGBM parameters
are fixed a priori (`forecasting/model.py:DEFAULT_PARAMS`) and are not tuned.

**Consequences.** Results estimate a scheduled-retrain deployment. Not tuning gives up some
accuracy but keeps every reported number free of selection bias; a nested search is future work.
Only ~5 months of history exist, so annual seasonality cannot be learned (see LIMITATIONS).

---

## ADR-007: Same-period weather is not a model feature

**Context.** Weather explains some demand variation, but at forecast time the target day's weather
is not known; using observed weather would be a form of leakage.

**Decision.** Weather is excluded from the model. It is used only as *context* in error analysis
and anomaly explanation. A clearly labelled ORACLE experiment adds the target day's actual weather
to measure an upper bound on what a weather forecast could add.

**Consequences.** On the real data the oracle experiment did not improve accuracy, so nothing is
lost by the exclusion. That is a measurement on five months, not proof weather is irrelevant.

---

## ADR-008: A JSON model registry instead of MLflow

**Context.** The project trains one model type on a single machine.

**Decision.** A model is `model.txt` plus a `meta.json` sidecar (data run id, train/calibration
windows, features, parameters, interval quantiles, metrics source, library versions) under
`artifacts/<mode>/forecast/models/<id>/`, with `latest.json` pointing at the newest.

**Consequences.** No server, no extra dependency, fully inspectable. It does not support
concurrent experiments, lineage across many runs, or a UI; adopt MLflow if that becomes necessary.

---

## ADR-009: Prediction bands are calibrated per predicted-demand band (Mondrian conformal)

**Context.** The first version used one conformal quantile scaled by `sqrt(prediction + 1)`. Its
overall test coverage was 79.7% (nominal 80%), which looked fine, but sliced by zone volume it was
94.8% for quiet zones and only 41.4% for zones above 20 pickups/hour: real demand is
over-dispersed, so the Poisson-style scaling badly understated busy-zone uncertainty.

**Decision.** Compute the residual quantile separately for each band of predicted pickups
(edges 0.5, 2, 5, 10, 20, 50; pooled quantile for bands with fewer than 200 calibration rows).

**Consequences.** Per-volume coverage after the change: 74-82%. This change was made after
looking at test-fold coverage. It is a calibration correction with no effect on point accuracy
(identical MAE/WAPE before and after), but it means the interval numbers are not a pristine
out-of-sample estimate of a design fixed in advance. Counts near zero are discrete, so coverage
there is conservative (at least nominal), never exact.

---

## ADR-010: Anomalies are events on out-of-sample residuals, scored against an empirical null

**Context.** Anomaly detection has no ground truth on real data, so the method must be defensible
on its own terms and its failure modes stated.

**Decision.**
1. Score only out-of-sample forecast residuals (the walk-forward test days), so a hard-to-predict
   day is not flagged because the model fitted on it.
2. Scale residuals by a spread that grows with forecast demand, measured from the 95th percentile
   of `|residual - median|` (tail-aware) per demand band and interpolated.
3. Group consecutive same-sign hours into events and pool the evidence, because a drop cannot fall
   below zero: per hour a collapse to a fifth of normal reaches only about -3, but over six hours it
   is unmistakable.
4. Standardise the pooled score by its *measured* spread over all windows of the same length,
   because forecast errors are correlated across hours (spread grows from 1.0 at 1 h to 1.8 at 24 h).
5. Ship defaults chosen a priori (seed |z| >= 2, event threshold 5, at least 10 pickups of total
   deviation) and publish a threshold trade-off table instead of tuning on real events.

**How the method got here (recorded because it changed after seeing real output).** The first
version used a MAD-based scale with a log-log line through the bands and an independence
assumption for pooling. It passed the synthetic check (3 of 3 planted anomalies) but produced 1,407
events in 56 days of real data (about 25 a day): the scale line was dominated by the quiet-zone band
where MAD collapses, and real errors are heavy-tailed. It was replaced by items 2 and 4 above. The
fix used unlabelled residuals only to model the *noise*; no real event was inspected to decide
what "counts".

**Consequences.** 277 real events in 56 days (73 medium/high). Real-data precision is
`UNVERIFIED` (no labels). Sensitivity is measured by injection into real residuals: surges of 2x or
more for 3+ hours in busy zones are found 60-100% of the time; a 0.5x drop for 3 hours is found 8%
of the time at the default threshold (65% at threshold 4 for 6 hours). Drops are structurally harder
than surges. Explanations are template text that says a deviation *coincided with* calendar,
weather or other-zone context, and never asserts a cause.

---

## ADR-011: Optimization outputs are simulations, and infeasibility is a result

**Context.** The open data contain no fleet, dispatch or vehicle-location information, so any
"rebalancing" result depends on assumed supply, vehicle capacity and repositioning cost.

**Decision.** Repositioning is a mixed-integer linear program (`scipy.optimize.milp`, HiGHS): move
whole vehicles between zones at most `max_km` apart, within a budget of moved vehicles, to maximise
served trips minus a small per-km cost. Every result carries the label *SIMULATED SCENARIO under
explicit assumptions* and echoes its assumptions. A request the model cannot satisfy (for example a
99% service level) returns status `infeasible` with the best attainable level, never a silent
best-effort plan. Plans are evaluated retrospectively: plan with a forecast, score against the
actual demand, and compare with no repositioning and with an unattainable oracle.

**Consequences.** Results are conditional on stated assumptions and a sensitivity table is part of
the report. Optimality is checked against brute force on small instances. Demand is served only in
the zone where a vehicle stands (no spill-over), which overstates the value of exact placement.

---

## ADR-012: The analyst only selects tools; sentences and numbers come from tool facts

**Context.** An AI analyst that writes free text can invent numbers, follow injected instructions,
or state causes the data cannot support. No LLM key exists, and the analyst must still work offline.

**Decision.**
1. A planner (deterministic rules, or an LLM when a key is set) only chooses among 13 fixed
   read-only tools and their arguments. Arguments are validated and bounded by the tool layer.
2. Every tool returns *facts* (named values with display strings). Answer sentences are built from
   facts, each labelled FACT / INTERPRETATION / ASSUMPTION / LIMITATION, and cite the facts used.
3. A grounding check rejects any FACT/INTERPRETATION sentence containing a number or date that is
   not in the facts it cites; the sentence is replaced by a notice, not shown.
4. The planner never sees tool outputs, so data (zone names, event text) cannot inject
   instructions. Requests to modify data, run code/SQL, reveal secrets or instructions, or ask about
   other services are refused before planning; instruction-override phrasing is flagged and ignored.
5. Ambiguity produces a clarification (which zone? which date?), and every default the planner
   applies (for example "no period given: last 7 days") is stated as an ASSUMPTION.
6. The response shows the tools used with their arguments and returned facts. No chain of thought.

**Consequences.** Answers are less fluent than free text but traceable. LLM mode exists but is
`UNVERIFIED`: it has only been tested against a mocked transport. The rule planner is limited to
the intents it encodes; the benchmark (Phase 10) measures where it fails.

---

## ADR-013: Test the holiday features under a pre-registered rule, on months the model had not seen

**Context.** On the first five months the model was far worse on federal holidays (WAPE 43.7% against
17.5%), and a long-weekend feature was obvious. It had been deliberately withheld because the test folds
suggested it, so adding it and reporting the improvement would have been tuning on the test set. Extending the
data to a full year created months that had not been looked at.

**Decision.** Write down, and commit, the hypothesis, the exact definitions of two features (`is_long_weekend`,
`days_to_holiday`), the evaluation (identical folds and settings, a paired day-level bootstrap), a three-part
decision rule and a secondary check (`docs/PREREGISTRATION_HOLIDAY.md`, commit `ee6d727`) **before any forecast on
June to December was evaluated**. The experiment code computes the verdict; it is not judged afterwards. The
features stay opt-in (`holiday_features`, off by default) until the rule says otherwise.

**Alternatives.** Adding the features and reporting the gain (rejected: unfalsifiable after the fact); tuning
them (rejected: no search over definitions); using January to May as the test (rejected: already seen).

**Consequences.** The rule was met (overall WAPE 20.2% to 19.5%, interval +0.38 to +1.15 points), so the features
were adopted and became the default. The result is reported with its weaknesses: three holidays in the window, a
secondary check (August to September, one holiday) that went the other way, and a gain that also appears on
ordinary days. Regenerating the experiment on a rebuilt database reproduced every number.

---

## ADR-014: Green taxis and for-hire vehicles are aggregated to counts, not kept trip by trip

**Context.** The high-volume for-hire files are about 470 MB and 20 million trips a month (240 million a year),
six times the yellow volume. The yellow pipeline keeps every cleaned trip in Parquet and every rejected trip in a
quarantine file. Doing the same for the other services would add gigabytes and hours for no analytical gain, since
a demand model needs pickups per zone and hour.

**Decision.** Each service is cleaned with the same ordered rules and aggregated straight to pickups per zone-hour
(`transform/services.py`), one file at a time through DuckDB. Rejected rows are counted by reason and file, not
stored. Exact-duplicate removal is skipped for these services (it needs the whole table; yellow has 4 in 41
million). The gold layer gets one zero-filled `fact_service_zone_hourly` table, and every service is reconciled
to its cleaned trips on every build. Yellow's tables and results are untouched; a build without other services has
no service table.

**Alternatives.** A common trip schema for all services (rejected: forces the largest file through the slowest
path); adding services to the yellow silver layer (rejected: changes every yellow result).

**Consequences.** The service view is cheap and exactly reconciled. Forecasts, anomalies and scenarios remain
yellow-only, and yellow is now 14% of the counted pickups; that limitation is stated wherever the results are.

---

## ADR-015: "Real time" means a labelled replay plus genuinely live public feeds

**Context.** The requested real-time dashboard cannot be built on the taxi data honestly: the TLC publishes
trips monthly, so there is no live taxi feed. Presenting historical data as live would mislead.

**Decision.** The Live view streams two clearly separate things over server-sent events, each labelled on screen.
(1) A **replay** of the held-out days: the forecasts the model made before those days against what happened, on
a clock shared by every viewer, labelled REPLAY, not live. (2) **Live feeds** that are real: Citi Bike station
availability and Central Park weather, each with the publisher's own timestamp, the last good reading kept and
marked not current when a source fails. Both feeds are polled only while someone watches. Feed URLs are constants;
the User-Agent names the project and repository, never a person.

**Alternatives.** Simulated random "live" numbers (rejected: fabricated); polling from each browser (rejected:
many viewers would multiply calls to third-party services); WebSockets (rejected: the traffic is one-way and
server-sent events reconnect and pass through proxies simply).

**Consequences.** The real-time claim is true and checkable. The running error shown for the replay is a
city-total figure, much easier than the per-zone figure, and the screens say so. The stream is capped (32 viewers)
and needs the API key like any route; behind a proxy, response buffering must be off (documented).

---

## ADR-016: Self-hosted deployment and a native Android app, without a hosting platform

**Context.** The public demo runs on a free hosting tier that sleeps when idle and is outside the owner's control.
The owner asked for a properly deployable product (a real website with a full dashboard and an APK built with
Gradle) without depending on such platforms.

**Decision.** The project is built to be self-hosted: a Docker Compose file that runs a hardened container
(read-only filesystem, no capabilities, read-only data mounts) and refuses to start without an API key, a
systemd unit for a plain Linux server, and an optional HTTPS proxy with buffering off. The dashboard gained API-key
support (kept in the browser, sent as a header). The Android app is native (Java, Gradle, platform networking and
AndroidX only) with the same screens over the same API and a stream client that reconnects. Release builds are
signed from environment variables, never from files in the repository.

**Alternatives.** A wrapper around the website (rejected: not a real app, no streaming control); Kotlin
multiplatform or a cross-platform framework (rejected: large dependency surface for five screens).

**Consequences.** Anyone can run the whole stack on their own machine. The app was verified on an emulator, not
a phone; the Compose file was validated as YAML and its container run with the same options, but `compose up`
itself was not run (the plugin is not installed here). The existing hosted demo was left in place and, at the owner's request,
later redeployed with the full-year bundle.

