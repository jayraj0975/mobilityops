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
