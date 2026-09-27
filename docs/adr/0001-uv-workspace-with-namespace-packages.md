# 0001. uv workspace with namespace packages

- Status: accepted
- Date: 2026-09-27
- Deciders: José Henrique Roquette

## Context and Problem Statement

agent-hub will ship a CLI, a collector, a storage layer and later an API and a web app (see [SPEC](../SPEC.md)). They
share one domain, but each part has its own dependencies (Typer, SQLAlchemy, FastAPI) and must not drift into the others.
How do we organize the code so the parts stay separate, the domain is shared, and one command still installs everything?

## Considered Options

- **uv workspace with one distribution per component** under `packages/`, all in the implicit namespace package `agent_hub`.
- **Single-package monorepo**: one distribution `agent_hub` with subpackages.
- **One repo per component**: core, storage, collector and cli in separate repositories.

## Decision Outcome

Chosen option: **uv workspace with one distribution per component**, because it keeps the dependency rule checkable per
package, keeps one lockfile and one set of gates, and still installs as a whole.

- The root `pyproject.toml` is a virtual workspace (no `[project]` table, `package = false`); members are `packages/*`.
- Phase 0 distributions: `agent-hub-core` (`agent_hub.core`: domain, canonical event, Pydantic schemas, ports),
  `agent-hub-storage` (`agent_hub.storage`), `agent-hub-collector` (`agent_hub.collector`) and `agent-hub-cli`
  (`agent_hub.cli`, command `hub`). Later: `agent_hub.api` (FastAPI) and `apps/web` (React), both in Phase 2.
- `agent_hub` is an implicit namespace package: there is no `agent_hub/__init__.py` in any `packages/*/src/`.
- The meta-package `agent-hub` (`packages/agent-hub/`) depends on every distribution and declares the `hub` script, so
  `uv tool install agent-hub` installs everything.
- Dependency rule: every package depends on `core`; `core` depends on nothing internal (nor on `sqlalchemy`, `alembic` or
  `typer`); sibling packages never import each other. `.importlinter` enforces it (`make imports`, part of `make check`).
- Python 3.14 for the workspace (`.python-version`, `requires-python = ">=3.14"`); uv 0.9.0 or newer (`required-version`).

### Consequences

- Good: import-linter contracts map one to one onto distributions, so a wrong import fails `make check`.
- Good: one `uv.lock`, one `make check`, one CI job for all packages.
- Bad: each new package must be registered in `mypy.ini`, `.importlinter` and the Makefile `COV` list; the layout checker
  rule `package-registered` fails `make check-fast` until it is.
- Bad: hatchling refuses to build a wheel with no files, so the meta-package ships a placeholder module
  `agent_hub_meta` (outside the `agent_hub` namespace, so type checking, import contracts and coverage ignore it).
- Neutral: hatchling is pinned for every member through `build-constraint-dependencies`.

## More Information

- [ARCHITECTURE.md](../ARCHITECTURE.md): packages, dependency rule and where code goes.
- [ADR 0002](0002-lean-hexagonal-architecture.md): what lives in `core` versus the adapters.
