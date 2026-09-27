# Gate commands: hub.json and CI call these. Prerequisites run left to right and stop at the
# first failure, so never run these targets with -j.

RUN := uv run --locked --all-packages
# Coverage of every agent_hub package (the layout checker fails when one is missing). Unit and
# contract tests start the data, integration tests append to it, `coverage` checks the floors.
COV := --cov=agent_hub.core --cov=agent_hub.storage --cov=agent_hub.collector \
       --cov=agent_hub.cli --cov-branch --cov-report=
ALEMBIC := $(RUN) alembic -c packages/storage/alembic.ini

.PHONY: help format lint typecheck layout test-fast check-fast test-integration test-e2e imports \
        migrations coverage check

help: ## List the targets
	@grep -E '^[a-z0-9-]+:.*## ' $(MAKEFILE_LIST) | awk -F ':.*## ' '{printf "%-16s %s\n", $$1, $$2}'

format: ## ruff format --check
	$(RUN) ruff format --check .

lint: ## ruff check
	$(RUN) ruff check .

typecheck: ## mypy --strict (config in mypy.ini)
	$(RUN) mypy

layout: ## test layout and names, forbidden modules, packages listed in gate configs
	$(RUN) python -m scripts.check_test_layout

test-fast: ## unit and contract tests; starts fresh coverage data
	$(RUN) coverage erase
	$(RUN) pytest -m "unit or contract" $(COV)

check-fast: format lint typecheck layout test-fast ## the fast gate, run while working

test-integration: ## integration tests (real SQLite files under tmp_path); appends coverage
	$(RUN) pytest -m integration $(COV) --cov-append

test-e2e: ## e2e tests: hub installed with uv tool install, gate self-test (not in coverage)
	$(RUN) pytest -m e2e

imports: ## import-linter contracts (config in .importlinter)
	$(RUN) lint-imports

migrations: ## upgrade a scratch SQLite database to head, then alembic check (no drift)
	dir="$$(mktemp -d)" && trap 'rm -rf "$$dir"' EXIT && \
	$(ALEMBIC) -x db_url="sqlite:///$$dir/alembic-check.db" upgrade head && \
	$(ALEMBIC) -x db_url="sqlite:///$$dir/alembic-check.db" check

# Reads the data that test-fast (erase + unit/contract) and test-integration (append) collect,
# so run it after them, as `make check` does; on its own it checks stale or missing data.
coverage: ## per-package floors (core 90%, others 80%) over the collected coverage data
	$(RUN) coverage json -q -o coverage.json && $(RUN) python -m scripts.check_coverage coverage.json

# openapi: added when packages/api exists (the spec is regenerated and diffed in check).
check: check-fast test-integration test-e2e imports migrations coverage ## the full gate, run before a PR
