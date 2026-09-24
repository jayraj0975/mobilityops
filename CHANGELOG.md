# Changelog

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
- CI actions moved to v7; Dependabot configured; `requirements.lock` records the versions the
  results were produced with; ESLint (React hooks and accessibility rules) added; frontend pages
  are code-split; dead code removed.
