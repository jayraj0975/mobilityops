# Security

Scope: a local analytics tool with an HTTP API and a browser UI. It handles public open data only
(NYC TLC trips, NOAA weather); there are no accounts and no personal data. It is designed to run
on localhost. The public demo (see DEPLOYMENT.md) is a read-only, rate-limited deployment of that
same public data with no secrets or accounts. **It is not hardened as a general internet service**
(see "Not covered").

## Assets and threats considered

| Asset | Threat | Control |
|---|---|---|
| Database and artifacts | modification through the API or the analyst | all connections are `read_only`; the analyst has no write tool (a test asserts no tool name suggests writing); requests to write are refused |
| Database | SQL injection | user input is never interpolated into SQL: bound parameters, whitelisted identifiers, typed and bounded API parameters; injection-style inputs are tested and rejected |
| Pipeline SQL | injection via file names / settings | values go through `quote_literal`; the ruff `S608` exemption is limited to the pipeline modules and documented in `pyproject.toml` |
| Service availability | oversized bodies, floods, expensive requests | 16 KiB body cap enforced even for chunked uploads (the body is buffered, then refused with 413); per-client rate limits (`MOBILITYOPS_RATE_LIMIT`, and a tighter `_HEAVY` budget for the analyst and scenario endpoints; 429 with `Retry-After`); `MOBILITYOPS_TRUST_PROXY` is the number of your own proxies in front: the client address is then that entry counted from the right of `X-Forwarded-For` (proxies append, so a prefix the client forges is ignored; it was verified against the live deployment that a forged first entry does not dodge the limit once this is set). With `0` the header is ignored. While a limit is on, the request log records the address the limit counts by; bounded query sizes; scenario solves capped at 10 s and 2 concurrent (429 beyond that); single-flight caching |
| Secrets (LLM key, API key) | leakage through logs, errors, git | read only from the environment; never logged (tests check logs, request bodies and reprs); `Settings.__repr__` masks them; no key is ever built into the page or the app: a person types the API key, the dashboard keeps it in that browser's local storage (readable only by script from the app's own origin, which the CSP restricts to `'self'`) and the Android app in private app preferences (`allowBackup` is off); secret scan of tree and full history: none |
| Analyst | prompt injection from questions or data | screening; planner sees only the question and can only pick fixed tools; never sees tool outputs; numbers are grounded in tool facts; a poisoned zone name is shown as data and changes nothing (test) |
| Browser | XSS, clickjacking, mixed content | React escapes output; served UI carries a strict Content-Security-Policy (`script-src 'self'`, no `unsafe-eval`, `frame-ancestors 'none'`), `X-Frame-Options: DENY`, `nosniff`, `no-referrer` |
| Cross-origin use | other sites calling the API | CORS by explicit origin list; a wildcard is rejected at startup |
| Error output | stack traces and paths in responses | one error shape; unhandled errors return a generic message plus a request id; details go to the structured log |
| Supply chain | vulnerable dependencies | `pip-audit` and `npm audit`: no known vulnerabilities on the date below; lock files for the frontend and the Python environment (`requirements.lock`); Dependabot opens weekly grouped updates for pip, npm, Gradle, GitHub Actions and Docker (`.github/dependabot.yml`), and CI runs `pip-audit`, `npm audit` and CodeQL |
| Container | privilege, baked-in secrets | non-root uid 10001; no data or keys in the image; localhost publish documented; refuses a non-local bind without a key or an explicit flag. The Compose file adds a read-only root filesystem, all capabilities dropped, `no-new-privileges`, read-only data mounts, and refuses to start without `MOBILITYOPS_API_KEY` (verified by running the image with those flags) |
| Live stream | many long-lived connections exhausting the server | at most `MOBILITYOPS_LIVE_MAX_STREAMS` (32) concurrent streams, then 429 with `Retry-After`; each viewer has a bounded queue and a viewer that stops reading loses its oldest events instead of blocking others; the replay and feed pollers run only while someone is watching; a stream needs the API key like any other route (the dashboard uses `fetch` streaming so the key travels in a header, never in a URL) |
| Outbound feed calls | server-side request forgery, leaking who runs the server | the two feed URLs are constants in code, never taken from a request; 15 s timeouts; failures are contained and reported as a feed status; the `User-Agent` names the project and its repository only, never a person or address; nothing from a request is forwarded |
| Android app | traffic interception on a shared network | `http://` is allowed because a home server rarely has a certificate (documented in the app and in SELF_HOSTING); use the HTTPS profile and an `https://` address for anything beyond the local network; the API key is sent as a header, never in a URL |

## API key

If `MOBILITYOPS_API_KEY` is set, every `/api/v1/*` route requires it in `X-API-Key` (compared in
constant time); `/health` and `/ready` stay open for probes. This is a single shared secret, not
user authentication. `serve` refuses a non-local `--host` unless a key is set or
`--allow-unauthenticated` is passed (which the Dockerfile's default command does, expecting
localhost-only publishing; the Compose file does not, so a key is mandatory there). The live stream
is under `/api/v1/live/`, so it needs the key too.

## Logging

Structured JSON logs with a request id. Access logs record the route template, method, status and
duration, never query strings or request bodies. `/api/v1/ops/metrics` exposes counters by route
template and analyst outcomes (refusals, injection flags, withheld statements), and never content.

## Verified

Test coverage for the controls above lives in `tests/integration/test_api.py`,
`test_analyst.py`, `test_web.py`, `test_cli.py`, `tests/unit/test_analyst_guard.py` and
`test_config.py`, `tests/integration/test_live.py` and `test_services.py`. Scans run on 2026-09-24: `pip-audit`
(no known vulnerabilities), `npm audit` (0 vulnerabilities), regex scan of the working tree and full git history
for common key and token formats and private-key headers (0 matches; no keystore or `local.properties` is
tracked, and the Android signing key lives outside the repository), only `.env.example` tracked. The one tracked
file over 1 MB is `reports/ai_benchmark_real.json` (1.7 MB, the raw analyst benchmark runs).

## The Pune live layer (added in 0.2.0)

| Risk | Control | Tested |
|---|---|---|
| The API writing to the live state | The API opens the SQLite file `query_only`; the worker is the only writer | `test_read_only_connections_cannot_write` |
| Injection through path or query parameters | Zone ids are typed integers; `at` is an enumeration; `limit`, `back`, `ahead` are bounded; the store is only reached through parameterised statements | `test_hostile_input_is_rejected_or_harmless` (SQL-shaped paths, negative and enormous ids, oversized limits) |
| Flooding the state endpoints or the stream | The `/api/v1/` rate limit covers them; viewers are capped (`MOBILITYOPS_LIVE_MAX_STREAMS`); each viewer has a bounded queue and a slow viewer loses old events instead of growing memory | `test_state_endpoints_are_rate_limited`, `test_hub_caps_viewers...`, `test_a_slow_viewer_loses_old_events...` |
| Unauthenticated access | The same API key as the rest of `/api/v1/`, including the stream | `test_state_endpoints_require_the_api_key...` |
| Cross-origin reads | No CORS grant for an unlisted origin; a wildcard is refused at start-up | `test_state_responses_carry_the_security_headers_and_no_cors_wildcard` |
| SSRF, open redirects through sources | Sources are three fixed Open-Meteo hosts; nothing from a request reaches a fetch; redirects are not followed by the worker; requests time out at 20 s | adapter tests (HTTP errors, invalid JSON, timeouts) |
| Hostile or corrupt upstream data | Values are range-checked and typed; out-of-range values are dropped and counted as rejected; a payload with nothing usable is an error, not an empty success | `tests/unit/test_openmeteo.py` |
| Untrusted text rendered in the UI | Zone names (OpenStreetMap) and error strings are rendered as text by React and Android `setText`, never as markup | e2e and unit tests render them; no `dangerouslySetInnerHTML` |
| Container escape and privilege | The container runs unprivileged with a read-only root filesystem, no capabilities and `no-new-privileges`; the live folder is the one writable mount | run with those options on 2026-09-24 (`docs/PRODUCTION.md`) |
| A hung shutdown holding the process | Graceful shutdown is bounded (5 s); the worker handles SIGTERM | `test_serve_bounds_graceful_shutdown`, `test_the_loop_stops_at_once_when_asked` |
| API keys in the repository | None; the signing key lives outside it; `TOMTOM`/`OPENAQ` sources have no adapter and read no key | scan of the tree, 2026-09-24 |

Also scanned on 2026-09-24 for this release: `pip-audit` (no known vulnerabilities, including the new `holidays`
dependency), `npm audit --omit=dev` (0), and a scan of tracked files for key and token shapes (0 matches).

## Not covered (do not treat this as a hardened internet service)

* **Authentication and authorisation** beyond one optional shared key; no users, roles or audit trail.
* **TLS**: terminate it in a reverse proxy; the app speaks plain HTTP.
* **Distributed abuse protection.** The rate limiter is in-memory and per process: it stops a single
  client hammering one instance, not a distributed flood (use a CDN / WAF for that).
* **A web application firewall, intrusion detection, alerting.**
* **Penetration testing**: none was done; the controls above are tested by the project's own tests.
* **LLM-specific risks in LLM mode** (UNVERIFIED): only mocked-transport tests exist.
* **Assistive-technology testing**: only automated accessibility scans.
* **Supply-chain hardening** such as pinned hashes, SBOM or image signing.

## Reporting a problem

This is a portfolio project without a security contact. Open an issue on the repository and do not
include credentials.
