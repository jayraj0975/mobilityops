# Contributing

## Setup

```bash
make setup                       # Python 3.12+, virtualenv, dev tools
make web-install                 # Node 20+, frontend dependencies
make check                       # ruff, ruff format, mypy, pytest (what CI runs)
make web-check                   # eslint (incl. accessibility rules) + tsc --noEmit + vitest
```

CI (`.github/workflows/ci.yml`) runs the Python checks with synthetic data only (it never
downloads the real datasets) and a web job (type generation drift, typecheck, tests, build,
`npm audit`).

## Dependencies

* Python ranges live in `pyproject.toml`; `requirements.lock` records the exact versions the
  reported results were produced with and is used as pip constraints by the Docker build.
  After upgrading, run `make lock`, then re-run `forecast-eval`, `anomalies` and the analyst
  benchmark: library versions can change numeric results, and the committed reports must still
  match (`tests/unit/test_docs_consistency.py` checks the documents against them).
* CI installs Python dependencies against `requirements.lock` (so a run is reproducible), audits
  them with `pip-audit`, audits the web app with `npm audit`, scans the code with CodeQL, validates
  the Gradle wrapper, and builds and starts the Docker image. Every GitHub Action is pinned to a
  commit SHA (the tag is in the comment beside it); Dependabot proposes the bumps.
* Dependabot opens weekly grouped updates for pip, npm, Gradle, GitHub Actions and Docker. TypeScript is
  held at 5.x because `openapi-typescript` needs its JavaScript compiler API (TypeScript 7 removed
  it); ESLint is held at 9 until the React and accessibility plugins support 10.

## Rules that keep the results honest

1. **Never invent a number.** Metrics, coverage, benchmark scores and performance claims come from a
   command's output. Reports in `reports/` are generated; do not edit them.
2. **Label everything.** Synthetic data is `TEST / SYNTHETIC DATA` and never mixed with real data.
   Optimisation outputs are `SIMULATED SCENARIO under explicit assumptions`. Unverified things are
   marked `UNVERIFIED`.
3. **No leakage.** Forecast features may use only days strictly before the origin; split by time,
   never at random. `tests/unit/test_forecast_features.py` must keep passing.
4. **No causal claims.** Anomaly and analyst text says "coincided with". Tests forbid causal wording.
5. **If you tune, say so.** Changes made after seeing test results are recorded in
   `docs/DECISIONS.md` (see ADR-009 and ADR-010). Do not tune to the held-out benchmark set.
6. **Bounded and parameterised.** New queries use bound parameters and whitelisted identifiers,
   with bounded outputs. Add a test for bad input.
7. **Secrets** only from environment variables. Never commit `.env`, keys, raw data, databases,
   model artifacts, `node_modules` or virtual environments (all git-ignored).

## Changing the API

The frontend's types are generated from the API's OpenAPI document. After changing the API:

```bash
make web-types      # regenerates apps/web/openapi.json and src/api/schema.d.ts
make web-check
```

`tests/integration/test_web.py` fails if the committed contract is stale.

## Adding an analyst tool

1. Add an argument model, a function returning **facts**, and a `ToolSpec` in `analyst/tools.py`.
2. Add a composer in `analyst/answer.py` that builds sentences from facts, labelled by kind.
3. Teach `RulePlanner` when to call it, stating any default as an assumption.
4. Add benchmark questions (development set for regressions; do not touch the held-out set) and
   tests. A tool must be read-only.

## Adding a benchmark question

Development questions live in `benchmarks/analyst_questions.json`. Give it an `expect_status`,
expected tools and, where possible, an `oracle` whose value is computed from independent SQL.
Run `analyst-benchmark`; runs are appended to the history and never overwrite earlier ones.

## Tests

* `tests/unit`: pure logic. `tests/integration`: pipeline, API, analyst and CLI on the synthetic
  sample (session-scoped fixtures in `tests/conftest.py`).
* Tests that need real data are marked `real_data` or `network` and are excluded from CI.
* Browser tests: start `make serve`, then `E2E_BASE=http://127.0.0.1:8000 make e2e-browser`
  (set `E2E_SCREENSHOTS=1` to regenerate `docs/images`).

## Commits

Small, meaningful commits with a plain message that says what changed and why. Do not commit
generated artifacts other than the small reports in `reports/`.

## Versions and releases

The Python package, the API, the web app and the changelog share one version (`pyproject.toml`,
`mobilityops.__version__`, `apps/web/package.json` and its lockfile; a test keeps them equal). Unreleased
work sits under `## Unreleased` in `CHANGELOG.md`; a release gives it a version heading and tags the commit
(`vX.Y.Z`). The Android app has its own `versionName` and tags (`android-vX.Y.Z`), because an installed app
is updated on a different schedule from the server.

## Recommended repository settings

`main` is **not protected** at the time of writing (checked with the GitHub API; secret scanning, push
protection and Dependabot security updates are on). Protection was deliberately not switched on
automatically, because it changes how the owner pushes. To require the CI checks and pull requests, with the
owner still able to bypass in an emergency (`enforce_admins` false), run once as the repository admin:

```bash
gh api -X PUT repos/OWNER/REPO/branches/main/protection --input - <<'JSON'
{
  "required_status_checks": {
    "strict": true,
    "contexts": ["python (3.12)", "python (3.13)", "python (3.14)", "web", "e2e", "android", "audit", "docker"]
  },
  "enforce_admins": false,
  "required_pull_request_reviews": {"required_approving_review_count": 0},
  "restrictions": null,
  "required_linear_history": true,
  "allow_force_pushes": false,
  "allow_deletions": false
}
JSON
```

Also worth enabling in the repository settings: automatic deletion of merged branches, and CodeQL results under
Security. The job names above must match `.github/workflows/ci.yml`.

