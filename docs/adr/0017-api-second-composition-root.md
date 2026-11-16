# 0017. `agent_hub.api` as a second composition root, served locally by `hub web`

- Status: accepted
- Date: 2026-10-11
- Deciders: José Henrique Roquette (delegated to the lead for AGH-200)

## Context and Problem Statement

Phase 2 adds a REST + SSE API and a web app (spec control-plane D1, D2, D25). ADR 0008 makes `cli` the only
composition root. The API needs storage, collector and generator adapters, and `hub web` must start it from the
installed `hub` command. How do the packages relate, and how is the local server kept local?

## Considered Options

1. `packages/api` as a second composition root, peer of `cli`; `cli` never imports it (separate `hub-web` script).
2. `packages/api` as a second composition root below `cli`: `cli` imports it in exactly one module (`web_command`).
3. API routes inside `cli`.

## Decision Outcome

Option 2. Layers in `.importlinter`: `agent_hub.cli` > `agent_hub.api` > `storage | collector | generator |
tracker_linear`, so `api` never imports `cli`; a forbidden contract stops `agent_hub.cli` importing `agent_hub.api` except
from `agent_hub.cli.web_command`. `core` may not import `fastapi`, `starlette`, `uvicorn`. Read routes call one method of
a read port declared in core (`EventReadModels`, `HubReadModels`), each method one read use case; the API builds the
adapters in `agent_hub.api.composition` (`build_app`) and nowhere else; `hub web` (`cli.web_command`) builds the
settings and starts uvicorn. Code that both roots need and that touched `typer` moves to
an adapter package (the doctor snapshot builder and the non-exiting `hub.json` readers go to `agent_hub.generator`).

Local-only server (D25): uvicorn bound to `127.0.0.1` (no host option), default port 7420; `Host` must be
`127.0.0.1:<port>`, `localhost:<port>` or `[::1]:<port>` (else 403); `POST`/`DELETE` with a foreign `Origin` are 403; bodies
over 1 MiB are 413; no CORS; `Cache-Control: no-store` on `/api`; a CSP of `'self'` for scripts, styles, fonts and
connections (`img-src 'self' data:`, `object-src 'none'`), in `agent_hub.api.local_security`.

### Consequences

- Good: one process serves API and app; the CLI stays the user's entry point; adapters stay independent.
- Bad: the AC "neither imports the other" is met as "api never imports cli; cli imports api in one module", pinned by
  `make imports` and `tests/e2e/test_import_contracts.py`.
- No auth: anything on the machine can read the API; DNS rebinding and CSRF are closed by the Host and Origin checks.

Built in Phase 2 as decided. A registered hub pinned to another platform version is read leniently (schema check
only, with a "pinned X, running Y" warning), so a portfolio can show hubs that upgrade on their own schedule.

## More Information

The control-plane feature spec (AGH-200, in the private hub) D1, D2, D25; [ADR 0002](0002-lean-hexagonal-architecture.md), [ADR 0004](0004-rest-api-standard.md),
[ADR 0008](0008-cli-as-composition-root.md); [API.md](../API.md); [ARCHITECTURE.md](../ARCHITECTURE.md).
