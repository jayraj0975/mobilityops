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
