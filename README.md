# MobilityOps

Urban mobility demand forecasting, anomaly detection and decision support on public NYC taxi data.

**Status: under construction.** This README describes only what exists and has been verified; the
sections below are filled in phase by phase. See `docs/DECISIONS.md` for the design decisions made
so far.

## What it is for

A decision-support tool that helps answer: where is demand rising, what is expected soon, which
zones behave unusually, how accurate are the forecasts, and what would a simulated rebalancing of
limited fleet capacity change. It is **not** connected to any real transport network; optimisation
outputs are simulated scenarios under stated assumptions.

## Quick start (sample mode: synthetic data, no downloads)

```bash
make setup     # virtualenv + dependencies
make sample    # generate deterministic SYNTHETIC data
make test      # fast tests, synthetic data only
make check     # lint + types + tests (what CI runs)
```

Sample-mode data is labelled `TEST / SYNTHETIC DATA` and is never used for real-world results.

## License

MIT
