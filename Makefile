# Gate commands: hub.json and CI call these. Prerequisites run left to right and stop at the
# first failure, so never run these targets with -j.

RUN := uv run --locked --all-packages
# Coverage of every agent_hub package (the layout checker fails when one is missing). Unit and
# contract tests start the data, integration tests append to it, `coverage` checks the floors.
COV := --cov=agent_hub.core --cov=agent_hub.storage --cov=agent_hub.collector \
       --cov=agent_hub.cli --cov-branch --cov-report=

.PHONY: help format lint typecheck layout test-fast check-fast imports coverage

help: ## List the targets
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk -F ':.*## ' '{printf "%-12s %s\n", $$1, $$2}'

format: ## ruff format --check
	$(RUN) ruff format --check .

lint: ## ruff check
	$(RUN) ruff check .

typecheck: ## mypy --strict (config in mypy.ini)
	$(RUN) mypy

layout: ## test layout and names, forbidden modules, packages listed in gate configs
	$(RUN) python -m scripts.check_test_layout

test-fast: ## unit and contract tests
	$(RUN) pytest -m "unit or contract" $(COV)

check-fast: format lint typecheck layout test-fast ## the fast gate, run while working

imports: ## import-linter contracts (config in .importlinter)
	$(RUN) lint-imports

coverage: ## per-package floors (core 90%, others 80%) over the collected coverage data
	$(RUN) coverage json -q -o coverage.json && $(RUN) python -m scripts.check_coverage coverage.json
