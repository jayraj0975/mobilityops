# Operations runbook (Pune)

Commands, what healthy looks like, and what to do when it is not. Everything here was exercised during development
unless it says otherwise.

## The commands

| Command (with `MOBILITYOPS_MODE=pune`) | What it does |
|---|---|
| `pune-build [--start D --end D] [--refresh-weather]` | Fetches the rain history (cached with provenance in `data/raw/pune`), builds the analytical database with simulated demand, runs the quality gate, and promotes it atomically. A failed gate leaves the previous database untouched. Default window: the last 365 days through yesterday. |
| `forecast-eval` / `forecast-train` / `anomalies` | The same commands as New York; they read the Pune database. |
| `pune-worker [--once]` | The ingestion worker. `--once` runs every job once and prints the results (useful as a smoke test). |
| `serve --port N` | The API and console. |
| `status` | Prints the latest quality report of the database build. |

## Order of a first start

`pune-build` → `forecast-eval` → `forecast-train` → `pune-worker` → `serve`. The worker needs the database and a trained
model; without a model it records a failed `model-forecast` run, keeps ingesting, and the console has no forecast.

## What healthy looks like

* Console header: **Data LIVE**, **Worker LIVE**, **Link CONNECTED**. On Data quality: every enabled source LIVE, three
  sources NOT CONFIGURED (traffic, station air quality, bus timetable: no adapters exist).
* `curl :8000/ready` → `{"status":"ready"}` with `live_worker: true`.
* The ingestion run log shows the weather and rain jobs every 15 minutes, air quality hourly, demand every minute.

## When it is not

| Symptom | Cause and action |
|---|---|
| Notice "The ingestion worker has stopped" | The worker process is down or wedged. `docker compose --profile pune logs worker` / `journalctl -u mobilityops-worker`. Values on screen are held from its last run and marked. Restarting it is safe. |
| One source STALE or OFFLINE | Data quality shows its last error and failed polls in a row. Open-Meteo unreachable (network, outage) or, for a source that answers but repeats an old timestamp, upstream trouble. Nothing is substituted: the source stays stale until it recovers. |
| Rain source shows DELAYED | Expected up to an hour by design (values are stamped at the start of their hour). Persistent beyond about 2 h is a real fault. |
| Notice "Reconnecting to the server" | The stream dropped. The client retries with backoff (1 s doubling to 30 s) and shows the last numbers as possibly out of date. If it never recovers behind a proxy, the proxy is buffering: disable buffering (`flush_interval -1` in Caddy). |
| `503 not_ready` on `/api/v1/state/*` | No worker has written yet (`the ingestion worker has not started`). Start it. |
| `404 no_data` "only available in pune mode" | The server is not in pune mode. |
| "Days behind" on Data quality is large | `pune-build` has not run for a while. The worker fills the gap by simulation, but rain for days older than about nine days is unknown (treated as no rain). Run `pune-build`. |
| Forecast looks high after a run of rainy days | Known limitation: the model has no weather input (`docs/LIVE_DATA.md`). |
| `429` from the API | The rate limit (`MOBILITYOPS_RATE_LIMIT`) or the viewer cap (`MOBILITYOPS_LIVE_MAX_STREAMS`, default 32). |
| Container cannot write `data/live` | The container user does not own the folder: set `MOBILITYOPS_UID/GID` to your ids or `chown` it. |

## Observability

* **Ingestion run records** (`ingestion_run` table, `/api/v1/state/runs`): source, start, end, ok, records in and accepted
  (the difference is what validation rejected), duration, error text.
* **Request ids:** every response carries `X-Request-ID`; the same id is in the JSON log line for that request.
* **Structured logs:** one JSON object per line on stdout (`ts`, `level`, `logger`, `msg`, and context fields).
* **Stream diagnostics:** `/api/v1/state/stream/status` (open viewers, published and dropped events) and, in the console, Data
  quality → This connection (link state, age of the last message, clock offset, store version).
* **Metrics:** `/api/v1/ops/metrics` (per-route counts and latencies).

## Performance (measured on the development machine, 4 cores)

| What | Measured |
|---|---|
| Simulate a full year of demand (91 zones) | 1.7 s |
| `pune-build`, one year, including the quality gate | about 2.5 s plus the rain download |
| One worker cycle (all jobs, including the forecast), warm | a few seconds; the forecast is remade once a day |
| Snapshot endpoint | one SQLite read and a small JSON (91 zones); see the request log for `ms` |
| Stream payload | one snapshot is about 12 KB, pushed when the store changes (every 15 s while the worker ticks) |
| Container stop with a viewer connected | API 5.6 s, worker 0.3 s |

The numbers are a snapshot of one machine, not a benchmark; the request log gives the per-request latency on yours.
