# Gate commands: hub.json and CI call these. `check-fast` and `check` run two lanes at once
# (GATE_LANES below): the checks, and the test runners that use every CPU (pytest-xdist, then
# Vitest), which never overlap each other. Each lane runs its steps left to right and stops at the
# first failure. They set -j themselves: never run these targets with -j.

RUN := uv run --locked --all-packages
# Coverage of every agent_hub package (the layout checker fails when one is missing). Unit and
# contract tests start the data, integration tests append to it, `coverage` checks the floors.
# Alembic loads the migration scripts by path under synthetic module names, which package sources
# never match, so their directory is a source of its own.
COV := --cov=agent_hub.core --cov=agent_hub.storage --cov=agent_hub.collector \
       --cov=agent_hub.generator --cov=agent_hub.tracker_linear --cov=agent_hub.cli \
       --cov=agent_hub.hub_git --cov=agent_hub.claude_sessions --cov=agent_hub.api \
       --cov=agent_hub.mcp_server \
       --cov=packages/storage/src/agent_hub/storage/migrations --cov-branch --cov-report=
# pytest-xdist workers for the test targets: one per CPU by default; PYTEST_N=0 runs in one process.
# Tests marked serial assert a wall-clock budget, so they run alone after the parallel run.
PYTEST_N ?= auto
XDIST := -n $(PYTEST_N)
# Narrows test-suite, test-suite-serial and test-e2e-serial to part of the tree: paths, or
# --ignore=<path> for the rest (CI's shards, .github/workflows/ci.yml). Empty: every test.
TESTS ?=
E2E_MARK := e2e and not docker and not live
# The gates' lanes: one make job per lane, each lane a make of its own that runs its steps in
# order (LANE=1 below). Each lane's output is printed when it ends (make 4 and newer).
OUTPUT_SYNC := $(if $(filter output-sync,$(.FEATURES)),--output-sync=target)
GATE_LANES := --no-print-directory -j2 $(OUTPUT_SYNC)
IN_ORDER := --no-print-directory LANE=1
ifdef LANE
.NOTPARALLEL:
endif
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
# `make live`: this checkout's hub web, restarted on every Python change (the stable hub web that
# drives the Claude sessions stays on AGENT_HUB_PORT, started apart).
LIVE_API_PORT ?= 7421

.PHONY: help format lint typecheck layout lockstep test-fast check-fast test-integration test-e2e \
        test-e2e-parallel test-e2e-serial test-suite test-suite-serial pr-title \
        lane-checks-fast lane-checks lane-tests-fast lane-tests web-static web-test \
        imports migrations coverage check llms-txt hub-schema output-schemas web-install web-fast web-build web-dist-check \
        openapi openapi-check test-docker test-live run up down logs ps dev live playground playground-stop playground-export demo connect

help: ## List the targets
	@grep -E '^[a-z0-9-]+:.*## ' $(MAKEFILE_LIST) | awk -F ':.*## ' '{printf "%-16s %s\n", $$1, $$2}'

format: ## ruff format --check
	$(RUN) ruff format --check .

lint: ## ruff check
	$(RUN) ruff check .

typecheck: ## mypy --strict (config in mypy.ini); each hyphenated pack's scripts in a run of their own
	$(RUN) mypy
	@for dir in packages/core/src/agent_hub/core/workflows/builtin/*-*/scripts; do \
	  echo "mypy $$dir"; $(RUN) mypy $$dir/*.py || exit 1; \
	done

layout: ## test layout and names, forbidden modules, packages listed in gate configs
	$(RUN) python -m scripts.check_test_layout

lockstep: ## agent-hub-cli and agent-hub share one version (scripts/check_release.py)
	$(RUN) python -m scripts.check_release

test-fast: ## unit and contract tests; starts fresh coverage data
	$(RUN) coverage erase
	$(RUN) pytest -m "unit or contract" $(XDIST) $(COV)

# npm ci only when package-lock.json is newer than the last install (npm writes
# node_modules/.package-lock.json), so a gate run reuses an install that is already current.
web-install: ## install the web app's dependencies exactly as package-lock.json pins them
	@[ apps/web/node_modules/.package-lock.json -nt apps/web/package-lock.json ] || \
	$(WEB) ci --no-audit --no-fund

web-fast: web-static web-test ## web app: typecheck, ESLint, Prettier check, tokens drift, Vitest with coverage

web-static: web-install ## web app: typecheck, ESLint, Prettier check, tokens drift
	$(WEB) run typecheck && $(WEB) run lint && $(WEB) run format:check && $(WEB) run gen:tokens:check

web-test: web-install ## web app: Vitest with coverage
	$(WEB) run coverage

openapi-check: web-install ## the committed openapi.json and the generated TS types match the app
	$(RUN) python -m scripts.export_openapi --check && $(WEB) run gen:api:check

# check-fast runs the web app's steps (5 min, mostly Vitest) when a file under apps/web/ differs
# from origin/main (committed, staged, unstaged or new), when origin/main is missing, or with
# WEB_FAST=1; WEB_FAST=0 skips them. check runs them always. openapi-check always runs: it is
# what catches an API change the web app has not followed.
WEB_FAST ?= auto
WEB_UNCHANGED := base="$$(git merge-base HEAD origin/main 2>/dev/null)" && \
	[ -z "$$(git diff --name-only "$$base" -- apps/web)$$(git ls-files --others --exclude-standard -- apps/web)" ]
IF_WEB = $(if $(filter 1,$(WEB_FAST)),$(1))

# web-install first, so the two lanes never run npm ci at once.
check-fast: web-install ## the fast gate, run while working: checks and tests in two lanes at once
	@web=$(WEB_FAST); \
	if [ "$$web" = auto ]; then \
	  if $(WEB_UNCHANGED); then web=0; \
	    echo "check-fast: web app skipped, nothing under apps/web/ differs from origin/main (WEB_FAST=1 runs it)"; \
	  else web=1; fi; \
	fi; \
	$(MAKE) $(GATE_LANES) lane-checks-fast lane-tests-fast WEB_FAST=$$web

lane-checks-fast:
	@$(MAKE) $(IN_ORDER) format lint typecheck layout lockstep $(call IF_WEB,web-static) openapi-check

lane-tests-fast:
	@$(MAKE) $(IN_ORDER) test-fast $(call IF_WEB,web-test)

test-integration: ## integration tests (real SQLite files under tmp_path), never live ones; appends coverage
	$(RUN) pytest -m "integration and not live and not serial" $(XDIST) $(COV) --cov-append
	$(RUN) pytest -m "integration and not live and serial" $(COV) --cov-append

test-e2e: test-e2e-parallel test-e2e-serial ## e2e tests: hub installed with uv tool install, gate self-test (not in coverage)

test-e2e-parallel: ## the e2e tests that are not serial, with pytest-xdist
	$(RUN) pytest -m "$(E2E_MARK) and not serial" $(XDIST)

test-e2e-serial: ## the serial e2e tests (web smoke and visual: wall-clock budgets; TESTS narrows), alone
	$(RUN) pytest -m "$(E2E_MARK) and serial" $(TESTS)

# check's tests in two runs instead of three: unit, contract and integration share one pytest
# session (one collection, one set of workers), then the serial ones run alone after every lane.
test-suite: ## unit, contract and integration tests that are not serial (TESTS narrows); starts fresh coverage data
	$(RUN) coverage erase
	$(RUN) pytest -m "(unit or contract or integration) and not live and not serial" $(XDIST) $(COV) $(TESTS)

# pytest exits 5 when TESTS holds no serial test (a CI shard can have none): that is a pass here.
test-suite-serial: ## the serial integration tests (TESTS narrows), alone; appends coverage
	$(RUN) pytest -m "integration and not live and serial" $(COV) --cov-append $(TESTS) || [ $$? -eq 5 ]

imports: ## import-linter contracts (config in .importlinter)
	$(RUN) lint-imports

migrations: ## upgrade a scratch SQLite database to head, then alembic check (no drift)
	dir="$$(mktemp -d)" && trap 'rm -rf "$$dir"' EXIT && \
	$(ALEMBIC) -x db_url="sqlite:///$$dir/alembic-check.db" upgrade head && \
	$(ALEMBIC) -x db_url="sqlite:///$$dir/alembic-check.db" check

# Reads the data that test-suite (erase) and test-suite-serial (append) collect, or test-fast and
# test-integration, so run it after them, as `make check` does; on its own it checks stale or
# missing data.
coverage: ## per-package floors (core 90%, others 80%) over the collected coverage data
	$(RUN) coverage json -q -o coverage.json && $(RUN) python -m scripts.check_coverage coverage.json

# Not part of check: test_build_llms_txt.py and test_build_flow_catalog.py (in test-fast) fail
# while a file is stale.
llms-txt: ## regenerate the flow catalog in USING.md, llms.txt and llms-full.txt
	$(RUN) python -m scripts.build_flow_catalog
	$(RUN) python -m scripts.build_llms_txt

# Not part of check: the drift tests in test-fast fail while the shipped file is stale.
hub-schema: ## regenerate the shipped hub.json schema from HubConfig
	$(RUN) python -m scripts.export_hub_schema

# Not part of check: the drift tests in test-fast fail while either shipped file is stale.
output-schemas: ## regenerate the shipped review, eval and preflight output schemas from their models
	$(RUN) python -m scripts.export_output_schemas

# Not part of check: openapi-check (in check-fast) fails while either file is stale.
openapi: web-install ## regenerate packages/api/openapi.json and apps/web/src/api/schema.d.ts
	$(RUN) python -m scripts.export_openapi && $(WEB) run gen:api

web-build: web-install ## build the web app into the API package (web_dist, committed)
	$(WEB) run build

# Only the bundle: the type check is web-static's, and it does not change the output.
web-dist-check: web-install ## rebuild the web app in a scratch dir and compare it with the committed web_dist
	dir="$$(mktemp -d)" && trap 'rm -rf "$$dir"' EXIT && \
	$(WEB) run bundle -- --outDir "$$dir" --emptyOutDir && \
	diff -r "$$dir" $(WEB_DIST)

# The serial tests wait for every lane, so nothing else loads the machine while they time.
check: web-install ## the full gate, run before a PR: two lanes at once, then the serial tests, then coverage
	@$(MAKE) $(GATE_LANES) lane-checks lane-tests
	@$(MAKE) $(IN_ORDER) test-suite-serial test-e2e-serial coverage

lane-checks:
	@$(MAKE) $(IN_ORDER) format lint typecheck layout lockstep imports migrations web-static openapi-check web-dist-check

lane-tests:
	@$(MAKE) $(IN_ORDER) test-suite test-e2e-parallel web-test

# Not part of check: CI no longer checks PR titles. Run it before opening a PR (docs/CONTRIBUTING.md).
pr-title: ## check a PR title against Conventional Commits: make pr-title TITLE="feat(cli): ..."
	@test -n "$(TITLE)" || { echo 'usage: make pr-title TITLE="<type>(<scope>): <subject>"' >&2; exit 2; }
	$(RUN) python scripts/check_pr_title.py "$(TITLE)"

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

# The live loop: this checkout's API on LIVE_API_PORT, restarted on each Python change, and the web
# app with hot reload on 5173. The agent-session routes go to the stable hub web on AGENT_HUB_PORT,
# which drives the sessions and must already run, so a restart here never ends a session.
live: web-install ## live loop: API on 7421 (restarts on change), web app on 5173, sessions on 7420 (Ctrl C stops)
	@curl -s -o /dev/null $(URL)/ || { echo "start the stable hub web on $(URL) first" >&2; exit 1; }
	@trap 'kill 0' INT TERM; \
	$(RUN) python -m scripts.live_api --port $(LIVE_API_PORT) & \
	AH_API_TARGET=http://127.0.0.1:$(LIVE_API_PORT) AH_SESSIONS_TARGET=$(URL) $(WEB) run dev & \
	wait

playground: ## the whole live playground (conductor, make live, hub registration), then opens http://127.0.0.1:5173
	./scripts/playground.sh

# SINCE=<ref> exports from that commit instead of the last export (docs/design/playground-export.md).
playground-export: ## the playground's validated commits as a delivery's input, in .playground/exports/
	$(RUN) python -m scripts.playground_export $(if $(SINCE),--since $(SINCE))

playground-stop: ## stop the playground's servers (7420, 7421 and this checkout's web app)
	./scripts/playground.sh stop

demo: ## load synthetic demo data into the running control plane (make run or make up)
	$(RUN) python -m scripts.seed_demo --url $(URL)

connect: ## register a hub with the running control plane and check its sensor: make connect HUB=../my-hub
	@test -n "$(HUB)" || { echo "usage: make connect HUB=<path to the hub>" >&2; exit 2; }
	$(RUN) python -m scripts.connect_hub --url $(URL) "$(HUB)"
