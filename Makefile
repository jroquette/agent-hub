# Gate commands: hub.json and CI call these. Prerequisites run left to right and stop at the
# first failure, so never run these targets with -j.

RUN := uv run --locked --all-packages

.PHONY: help format lint typecheck test-fast check-fast

help: ## List the targets
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk -F ':.*## ' '{printf "%-12s %s\n", $$1, $$2}'

format: ## ruff format --check
	$(RUN) ruff format --check .

lint: ## ruff check
	$(RUN) ruff check .

typecheck: ## mypy --strict (config in mypy.ini)
	$(RUN) mypy

test-fast: ## unit and contract tests
	$(RUN) pytest -m "unit or contract"

check-fast: format lint typecheck test-fast ## the fast gate, run while working
