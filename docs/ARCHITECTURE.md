# Architecture

MobilityOps is one Python package (`mobilityops`, see ADR-002) plus a React app and a native Android
app. It is local-first: DuckDB and Parquet files, no server processes beyond the API itself (ADR-001), and it
is built to be self-hosted (ADR-016).

```
 NYC TLC yellow trips   TLC zone lookup + geometry   NOAA daily weather   (optional: green + for-hire
          \                        |                         /             trips, aggregated to counts, ADR-014)
           v                       v                        v
   ┌──────────────── ingestion: download (retry, atomic, hash-checked) + manifest ───────────────┐
   │  bronze  raw files, untouched, with SHA-256 / row count / columns / window                   │
   ├────────────────────────────────────────────────────────────────────────────────────────────┤
   │  silver  ordered cleaning rules; every rejected row goes to quarantine with its reason        │
   ├────────────────────────────────────────────────────────────────────────────────────────────┤
   │  gold    DuckDB star schema: dim_zone / dim_date / dim_hour (DST flags) /                    │
   │          fact_zone_hourly_demand (zero-filled zone x valid-hour grid) / fact_weather_daily   │
   │          (+ fact_service_zone_hourly when green / for-hire files were ingested)              │
   │          + pipeline_run + quality_result. Built to a side file, promoted only if gates pass. │
   └───────┬────────────────────────────────────────────────────────────────────────────────────┘
           │ read-only
           v
   analytics (bounded, parameterised queries) ──────────────────────────────┐
   forecasting: leak-free features → baselines + LightGBM → walk-forward eval │
        │  predictions.parquet, evaluation.json, model registry               │
        v                                                                     │
   anomaly: out-of-sample residuals → scored events + context                 │
   optimization: MILP repositioning → SIMULATED scenarios and backtest        │
        │                                                                     │
        v                                                                     v
   API (FastAPI): typed, bounded, read-only, unified errors, request ids, metrics
        │                       │                        │
        v                       v                        v
   React UI (generated types)   AI analyst: rules or LLM   live hub (SSE): replay clock over the
   Android app (Gradle)         chooses among 13 read-only  held-out days + polled Citi Bike / NWS
                                tools; facts; grounding;    feeds, only while someone watches
                                refusals                    (ADR-015)
```

## Layers and their contracts

| Layer | Code | Contract |
|---|---|---|
| Ingestion | `ingestion/` | Downloads are atomic and retried; unchanged files are skipped only if the URL, size and hash match (a changed request forces a re-download). The manifest records what was fetched and when. |
| Silver | `transform/silver.py` | Rules run in a fixed order; a row is labelled with the *first* rule it fails and is quarantined, never silently dropped. |
| Gold | `transform/gold.py`, `quality/checks.py` | Built as `mobilityops.duckdb.building`, promoted atomically only if every FAIL-level gate passes; otherwise the previous good database is untouched. |
| Analytics | `analytics/queries.py` | Single data-access layer for everything user-facing: bound parameters, whitelisted identifiers, read-only connections, bounded outputs, explicit `NoData`/`InvalidQuery`. |
| Forecasting | `forecasting/` | Features use only days strictly before the forecast origin (proved by test); validation is chronological. |
| Anomaly | `anomaly/` | Scores only out-of-sample residuals; language is "coincided with". |
| Optimization | `optimization/` | Every result carries the SIMULATED label and its assumptions; infeasibility is a result. |
| Services | `transform/services.py` | Green and for-hire files are cleaned with the yellow rules and aggregated to zone-hour counts (rejected rows are counted, not kept); every service is reconciled to its cleaned trips on every build. Absent unless ingested. |
| API | `api/` | See below. |
| Live | `live/` | One shared replay clock and one poller per server, started by the first viewer and stopped by the last; feeds report the publisher's timestamp and keep the last good reading; each viewer has a bounded queue; the stream is capped. |
| Analyst | `analyst/` | Planner selects tools; tools return facts; sentences are built from facts and checked. |

## Modes and directories

`MOBILITYOPS_MODE` is `sample` (synthetic) or `real`. Every path is derived from the mode, so the
two can never share files (ADR-003):

```
data/raw/<mode>/  data/processed/<mode>/{silver,quality}/  data/processed/<mode>/mobilityops.duckdb
artifacts/<mode>/{forecast,anomaly,optimization,analyst}/
```

Only tiny synthetic samples and generated `reports/` are committed; raw data, databases and model
artifacts are git-ignored.

## API

`/health`, `/ready` (unauthenticated probes) and `/api/v1/...`: `meta`, `quality`, `zones`,
`demand/*` (series, top-zones, profiles, compare, growth, volatility, concentration,
weather-comparison), `forecast/*` (performance, model, backtest, next-day), `anomalies`,
`optimization/*` (backtest, scenario), `analyst/*` (status, tools, ask), `ops/metrics`.

* Inputs are typed and bounded; unknown fields are rejected; bodies over 16 KiB are refused.
* One error shape everywhere: `{"error": {"code", "message", "request_id", "details"}}`.
* Missing derived artifacts return `503 not_ready` naming the command that creates them.
* `X-Data-Label` and `X-Data-Mode` on every response say whether the data is synthetic.
* The single compute endpoint (scenario) has a 10 s solver limit and at most 2 concurrent solves.
* Expensive loads (the demand tensor, the next-day forecast) are cached per file version and use
  single-flight loading, so concurrent cold requests trigger one load.
* The OpenAPI document is committed (`apps/web/openapi.json`); the frontend's types are generated
  from it, and a test fails if the two drift.

## Frontend

`apps/web`: Vite, React 19, TypeScript (strict), Recharts. Seven sections (overview, live, demand,
forecast, anomalies, scenarios, analyst) and an About page. Nothing on screen is hard-coded: each view renders loading,
error and empty states, and a persistent banner states whether the data is real or synthetic. In
production the API serves the built UI at `/` with a strict Content-Security-Policy; in development
Vite proxies `/api` (and injects an API key server-side if one is configured). Against a server that needs a key,
the dashboard asks for it once and keeps it in that browser's local storage. The Live page reads the event stream
with `fetch` (not `EventSource`) so the key can travel in a header, and reconnects with backoff.

## Android app

`apps/android`: native Java, Gradle, platform networking and AndroidX only. Five tabs (Live, Overview,
Forecast, Anomalies, Settings) over the same API; the stream client reconnects with backoff and restarts a
connection that goes silent. The server address and key are set in the app.

## Trust boundaries

1. **Network → API**: validation, size cap, optional API key, CORS by explicit origin, no
   wildcard.
2. **API → data**: read-only DuckDB connections; user input never reaches SQL as text.
3. **Question → analyst**: screened, then only able to select fixed tools; the planner never sees
   tool outputs; every number in an answer is checked against tool facts.
4. **Container**: non-root user, no data or secrets in the image; the Compose file adds a read-only filesystem,
   no capabilities and read-only data mounts.
5. **Server → public feeds**: two fixed URLs, short timeouts, failures contained; nothing from a request is
   forwarded and the User-Agent names the project only.
6. **App → server**: plain HTTP is allowed for a home network (documented); use HTTPS beyond it.

## Deployment shapes

* Local process (`make serve`): the supported, tested path.
* Self-hosted with Docker Compose or systemd, with an API key (and optionally HTTPS): [SELF_HOSTING](SELF_HOSTING.md).
  The image was built and run with the Compose file's security options; the Compose file itself was not run.
* A public free-tier demo exists (see [DEPLOYMENT](DEPLOYMENT.md)); it serves the aggregate data bundle and is not part
  of the supported path.
* Anything internet-facing beyond that is **not** covered: it would need real authentication, per-user
  accounts, distributed-abuse protection and monitoring (see SECURITY).
