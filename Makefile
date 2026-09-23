.DEFAULT_GOAL := help
PY ?= .venv/bin/python
PIP ?= .venv/bin/pip

.PHONY: help setup sample test test-all lint format typecheck check audit clean

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
