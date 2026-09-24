# Changelog

## Unreleased

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
- Second held-out set (40 questions) frozen before its first run: **60.0%** (24/40); the first held-out set had scored 77.5%. Both are development data after the fixes; see `docs/AI_EVALUATION.md`.

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
