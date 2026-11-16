# 0002. Lean hexagonal architecture

- Status: accepted
- Date: 2026-09-27
- Deciders: José Henrique Roquette

## Context and Problem Statement

The [SPEC](../SPEC.md) expects several things to be swapped over time: the task tracker (Linear first, then GitHub Issues
or Jira), the agent source (Claude Code first, then other agents) and the event store (SQLite first, Postgres later). The
CLI, the collector and the future API must also behave the same for the same operation. How do we structure the code so
those swaps stay local and the three entry points share one behavior?

## Considered Options

- **Lean hexagonal (ports and adapters)**: the domain and use cases in `core`, adapters in the other packages.
- **Classic layers**: presentation, service and data-access layers.
- **Vertical slices**: one folder per feature, each with its own handlers and data access.

## Decision Outcome

Chosen option: **lean hexagonal**, because the swap points named in the SPEC are exactly ports, and use cases in `core`
give the CLI, the collector and the API one place to call.

- `core` (`agent_hub.core`) holds the entities (frozen Pydantic models), the use cases and the ports.
- Use cases are named verb + object: `IngestTranscript`, `GenerateHub`.
- Ports are interfaces owned by `core`: `EventStore`, `TrackerClient`, `TranscriptSource`.
- The other packages are adapters: `storage` implements `EventStore`, `collector` feeds events in, `cli` (and later `api`)
  turn user input into use-case calls.
- "Lean": a port exists only where the SPEC expects a swap (tracker, agent source, store). Everything else is a plain
  function or class in `core`, with no interface in front of it.
- `core` imports nothing internal and none of the adapter libraries (`sqlalchemy`, `alembic`, `typer`); import-linter
  enforces it ([ADR 0001](0001-uv-workspace-with-namespace-packages.md)).

### Consequences

- Good: a new tracker or agent source is a new adapter; `core` and its tests do not change.
- Good: use cases are unit-tested against in-memory fakes, and each port has one contract suite that runs against the fake
  and the real adapter ([ADR 0005](0005-testing-strategy.md)).
- Bad: adapters map between external shapes and domain models, which is extra code at every boundary.
- Bad: judging "is a swap expected here?" is a review call; too many ports would add indirection, too few would leak
  adapter details into `core`.

## More Information

- [ARCHITECTURE.md](../ARCHITECTURE.md): the hexagonal layout and the "where does this code go" table.
