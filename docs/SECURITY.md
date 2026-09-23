# Security

Scope: a local analytics tool with an HTTP API and a browser UI. It handles public open data only
(NYC TLC trips, NOAA weather); there are no accounts and no personal data. It is designed to run
on localhost. **It is not hardened for exposure to the internet** (see "Not covered").

## Assets and threats considered

| Asset | Threat | Control |
|---|---|---|
| Database and artifacts | modification through the API or the analyst | all connections are `read_only`; the analyst has no write tool (a test asserts no tool name suggests writing); requests to write are refused |
| Database | SQL injection | user input is never interpolated into SQL: bound parameters, whitelisted identifiers, typed and bounded API parameters; injection-style inputs are tested and rejected |
| Pipeline SQL | injection via file names / settings | values go through `quote_literal`; the ruff `S608` exemption is limited to the pipeline modules and documented in `pyproject.toml` |
| Service availability | oversized bodies, expensive requests | 16 KiB body cap (checked from `Content-Length`; see below); bounded query sizes; scenario solves capped at 10 s and 2 concurrent (429 beyond that); single-flight caching |
| Secrets (LLM key, API key) | leakage through logs, errors, git | read only from the environment; never logged (tests check logs, request bodies and reprs); `Settings.__repr__` masks them; the UI never receives a key (the dev proxy adds it server-side); secret scan of tree and full history: none |
| Analyst | prompt injection from questions or data | screening; planner sees only the question and can only pick fixed tools; never sees tool outputs; numbers are grounded in tool facts; a poisoned zone name is shown as data and changes nothing (test) |
| Browser | XSS, clickjacking, mixed content | React escapes output; served UI carries a strict Content-Security-Policy (`script-src 'self'`, no `unsafe-eval`, `frame-ancestors 'none'`), `X-Frame-Options: DENY`, `nosniff`, `no-referrer` |
| Cross-origin use | other sites calling the API | CORS by explicit origin list; a wildcard is rejected at startup |
| Error output | stack traces and paths in responses | one error shape; unhandled errors return a generic message plus a request id; details go to the structured log |
| Supply chain | vulnerable dependencies | `pip-audit` and `npm audit`: no known vulnerabilities on the date below; lock file for the frontend; Dependabot-style updates are not configured |
| Container | privilege, baked-in secrets | non-root uid 10001; no data or keys in the image; localhost publish documented; refuses a non-local bind without a key or an explicit flag |

## API key

If `MOBILITYOPS_API_KEY` is set, every `/api/v1/*` route requires it in `X-API-Key` (compared in
constant time); `/health` and `/ready` stay open for probes. This is a single shared secret, not
user authentication. `serve` refuses a non-local `--host` unless a key is set or
`--allow-unauthenticated` is passed (which the Dockerfile does, expecting localhost-only publishing).

## Logging

Structured JSON logs with a request id. Access logs record the route template, method, status and
duration, never query strings or request bodies. `/api/v1/ops/metrics` exposes counters by route
template and analyst outcomes (refusals, injection flags, withheld statements), and never content.

## Verified

Test coverage for the controls above lives in `tests/integration/test_api.py`,
`test_analyst.py`, `test_web.py`, `test_cli.py`, `tests/unit/test_analyst_guard.py` and
`test_config.py`. Scans run on 2026-09-23: `pip-audit` (no known vulnerabilities), `npm audit`
(0 vulnerabilities), regex scan of the working tree and full git history for common key and
token formats (0 matches), no tracked file over 1 MB, only `.env.example` tracked.

## Not covered (do not deploy this to the internet as is)

* **Authentication and authorisation** beyond one optional shared key; no users, roles or audit trail.
* **TLS**: terminate it in a reverse proxy; the app speaks plain HTTP.
* **Body size for chunked uploads**: the 16 KiB cap reads `Content-Length`, so a chunked request without
  that header is not capped by this app (a reverse proxy should enforce it).
* **Rate limiting** per client (only the solver has a concurrency cap) and abuse protection.
* **A web application firewall, intrusion detection, alerting.**
* **Penetration testing**: none was done; the controls above are tested by the project's own tests.
* **LLM-specific risks in LLM mode** (UNVERIFIED): only mocked-transport tests exist.
* **Assistive-technology testing**: only automated accessibility scans.
* **Supply-chain hardening** such as pinned hashes, SBOM or image signing.

## Reporting a problem

This is a portfolio project without a security contact. Open an issue on the repository and do not
include credentials.
