.DEFAULT_GOAL := help
PY ?= .venv/bin/python
PIP ?= .venv/bin/pip

.PHONY: help setup sample test test-all lint format typecheck check audit clean web-install web-types web-check web-build serve e2e-live e2e-browser

help:            ## Show available commands
	@grep -E '^[a-z-]+:.*##' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*## "}{printf "  make %-10s %s\n",$$1,$$2}'

setup:           ## Create the virtualenv and install the project with dev tools
	python3 -m venv .venv
	$(PIP) install --upgrade pip
	$(PIP) install -e ".[dev]"

sample:          ## Generate the deterministic SYNTHETIC sample data into data/raw/sample
	$(PY) -m mobilityops.cli sample

test:            ## Fast tests (synthetic data only, no downloads)
	$(PY) -m pytest -m "not real_data and not network"

lint:            ## Lint and check formatting
	$(PY) -m ruff check src tests
	$(PY) -m ruff format --check src tests

format:          ## Auto-format
	$(PY) -m ruff check --fix src tests
	$(PY) -m ruff format src tests

typecheck:       ## Static type check
	$(PY) -m mypy

check: lint typecheck test   ## Everything CI runs for the Python side

audit:           ## Scan dependencies for known vulnerabilities
	$(PY) -m pip_audit --skip-editable

clean:           ## Remove caches and build output (never touches data/)
	rm -rf .pytest_cache .mypy_cache .ruff_cache build dist *.egg-info

web-install:     ## Install the frontend dependencies (needs Node 20+)
	cd apps/web && npm ci

web-types:       ## Regenerate the frontend's API types from the running API's contract
	$(PY) -m mobilityops.cli openapi --out apps/web/openapi.json
	cd apps/web && npm run gen:api

web-check:       ## Frontend type-check and tests
	cd apps/web && npm run typecheck && npm test

web-build:       ## Build the frontend into apps/web/dist (served by `make serve`)
	cd apps/web && npm run build

serve:           ## Start the API (and the built UI at /) on http://127.0.0.1:8000
	$(PY) -m mobilityops.cli serve

e2e-live:        ## Run the UI against a live API: E2E_API_URL=http://127.0.0.1:8000 make e2e-live
	cd apps/web && npm run test:live

e2e-browser:     ## Real-browser tests + accessibility scans: start `make serve` first, then E2E_BASE=... make e2e-browser
	cd apps/web && npx playwright install chromium && npm run e2e
