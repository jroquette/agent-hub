# Gate commands: hub.json and CI call these. Prerequisites run left to right and stop at the
# first failure, so never run these targets with -j.

RUN := uv run --locked --all-packages
# Coverage of every agent_hub package (the layout checker fails when one is missing). Unit and
# contract tests start the data, integration tests append to it, `coverage` checks the floors.
# Alembic loads the migration scripts by path under synthetic module names, which package sources
# never match, so their directory is a source of its own.
COV := --cov=agent_hub.core --cov=agent_hub.storage --cov=agent_hub.collector \
       --cov=agent_hub.generator --cov=agent_hub.tracker_linear --cov=agent_hub.cli \
       --cov=agent_hub.hub_git --cov=agent_hub.api \
       --cov=packages/storage/src/agent_hub/storage/migrations --cov-branch --cov-report=
ALEMBIC := $(RUN) python -m agent_hub.storage.migration
# The web app (apps/web): Node from apps/web/.node-version, dependencies from its package-lock.json.
WEB := npm --prefix apps/web
WEB_DIST := packages/api/src/agent_hub/api/web_dist
# Running the control plane (docs/USING.md "Run the control plane", ADR 0022). Compose reads
# these from the environment or .env; the hubs root defaults to the folder holding this repo.
# COMPOSE_BAKE=false: the classic builder, so a build CA outside the project needs no Bake --allow.
COMPOSE := COMPOSE_BAKE=false docker compose
AGENT_HUB_PORT ?= 7420
AGENT_HUB_HUBS_ROOT ?= $(abspath $(CURDIR)/..)
export AGENT_HUB_PORT AGENT_HUB_HUBS_ROOT
URL := http://127.0.0.1:$(AGENT_HUB_PORT)

.PHONY: help format lint typecheck layout lockstep test-fast check-fast test-integration test-e2e \
        imports migrations coverage check llms-txt hub-schema web-install web-fast web-build web-dist-check \
        openapi openapi-check test-docker test-live run up down logs ps dev demo connect

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

lockstep: ## agent-hub-cli and agent-hub share one version (scripts/check_release.py)
	$(RUN) python -m scripts.check_release

test-fast: ## unit and contract tests; starts fresh coverage data
	$(RUN) coverage erase
	$(RUN) pytest -m "unit or contract" $(COV)

web-install: ## install the web app's dependencies exactly as package-lock.json pins them
	$(WEB) ci --no-audit --no-fund

web-fast: web-install ## web app: typecheck, ESLint, Prettier check, tokens drift, Vitest with coverage
	$(WEB) run check

openapi-check: web-install ## the committed openapi.json and the generated TS types match the app
	$(RUN) python -m scripts.export_openapi --check && $(WEB) run gen:api:check

check-fast: format lint typecheck layout lockstep openapi-check test-fast web-fast ## the fast gate, run while working

test-integration: ## integration tests (real SQLite files under tmp_path), never live ones; appends coverage
	$(RUN) pytest -m "integration and not live" $(COV) --cov-append

test-e2e: ## e2e tests: hub installed with uv tool install, gate self-test (not in coverage)
	$(RUN) pytest -m "e2e and not docker and not live"

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

# Not part of check: test_build_llms_txt.py (in test-fast) fails while either file is stale.
llms-txt: ## regenerate llms.txt and llms-full.txt from the docs
	$(RUN) python -m scripts.build_llms_txt

# Not part of check: the drift tests in test-fast fail while the shipped file is stale.
hub-schema: ## regenerate the shipped hub.json schema from HubConfig
	$(RUN) python -m scripts.export_hub_schema

# Not part of check: openapi-check (in check-fast) fails while either file is stale.
openapi: web-install ## regenerate packages/api/openapi.json and apps/web/src/api/schema.d.ts
	$(RUN) python -m scripts.export_openapi && $(WEB) run gen:api

web-build: web-install ## build the web app into the API package (web_dist, committed)
	$(WEB) run build

web-dist-check: web-install ## rebuild the web app in a scratch dir and compare it with the committed web_dist
	dir="$$(mktemp -d)" && trap 'rm -rf "$$dir"' EXIT && \
	$(WEB) run build -- --outDir "$$dir" --emptyOutDir && \
	diff -r "$$dir" $(WEB_DIST)

check: check-fast test-integration test-e2e imports migrations coverage web-dist-check ## the full gate, run before a PR

# Not part of check: needs a Docker daemon (CI runs it in its own job).
test-docker: ## build the image, run its Compose service and test it (marker docker)
	$(RUN) pytest -m docker tests/e2e/test_docker.py

# Not part of check: runs a real `claude -p` session (a few cents), only when asked.
test-live: ## a real claude -p session in a temp hub, seen through hub web (marker live)
	AGENT_HUB_LIVE=1 $(RUN) pytest -m live tests/e2e/test_live_agent.py

run: ## serve the control plane locally, no Docker (Ctrl C stops it)
	$(RUN) hub web --port $(AGENT_HUB_PORT)

up: ## build and start the control plane in Docker, on 127.0.0.1 only
	$(COMPOSE) up -d --build --wait
	@echo "agent-hub at $(URL)"

down: ## stop the Docker control plane (its data volume is kept)
	$(COMPOSE) down

logs: ## follow the Docker control plane's log
	$(COMPOSE) logs -f

ps: ## show the Docker control plane's container and health
	$(COMPOSE) ps

# Both servers run in this shell's process group; Ctrl C (or either one failing to start and
# the other being stopped by hand) ends both.
dev: web-install ## API on 7420 and the web app with hot reload on http://127.0.0.1:5173 (Ctrl C stops both)
	@trap 'kill 0' INT TERM; \
	$(RUN) hub web --port 7420 & \
	$(WEB) run dev & \
	wait

demo: ## load synthetic demo data into the running control plane (make run or make up)
	$(RUN) python -m scripts.seed_demo --url $(URL)

connect: ## register a hub with the running control plane and check its sensor: make connect HUB=../my-hub
	@test -n "$(HUB)" || { echo "usage: make connect HUB=<path to the hub>" >&2; exit 2; }
	$(RUN) python -m scripts.connect_hub --url $(URL) "$(HUB)"
