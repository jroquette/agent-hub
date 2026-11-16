# 0008. CLI as the composition root

- Status: accepted
- Date: 2026-09-27
- Deciders: José Henrique Roquette

## Context and Problem Statement

[ADR 0001](0001-uv-workspace-with-namespace-packages.md) makes the packages independent: every package depends on `core`
and siblings never import each other. [ADR 0002](0002-lean-hexagonal-architecture.md) puts the use cases and ports in
`core` and their implementations in the adapter packages. A use case needs a real adapter to run: `hub` storing
ingested events needs the `storage` implementation of `EventStore` and the `collector` that produces the events. Some
package has to build those adapters and pass them to the use case, and with fully independent siblings no package may.
Which package wires adapters to use cases, and how is that rule enforced?

## Considered Options

- **`agent_hub.cli` as the composition root**: `cli` may import the adapter packages; nothing imports `cli`.
- **A dedicated bootstrap package** (for example `agent_hub.bootstrap`) that imports every adapter and exposes ready-made
  use cases to `cli` and later `api`.
- **Deferring to the collector issue**: keep every sibling independent now and decide when the first use case needs two
  adapters.

## Decision Outcome

Chosen option: **`agent_hub.cli` as the composition root**, because the command-line entry point is where the process
starts and where configuration (paths, database URL) is read, so building the adapters there needs no extra package and
no extra layer of indirection.

- `agent_hub.cli` may import `agent_hub.storage` and `agent_hub.collector` to construct adapters and pass them to core use
  cases as port implementations.
- Nothing imports `agent_hub.cli`.
- `agent_hub.storage` and `agent_hub.collector` stay independent of each other; they depend only on `core`.
- `core` is unchanged: it imports nothing internal and none of the adapter libraries.
- import-linter enforces it: the `.importlinter` layers contract `cli is the composition root` puts `agent_hub.cli` above
  the independent sibling layers `agent_hub.storage | agent_hub.collector`; the forbidden contract on `core` stays.
- This refines the sibling rule of ADR 0001 for `cli` only; every other part of that rule holds.

### Consequences

- Good: wiring lives in one known place per entry point; adapters and use cases stay free of construction code.
- Good: a wrong import (an adapter importing `cli` or another adapter) fails `make check` with the contract name.
- Bad: `agent_hub.api` becomes a second composition root in Phase 2, with its own wiring of the same adapters; the
  layers contract must then list `agent_hub.cli | agent_hub.api` as the top layer, and shared wiring, if it grows, is
  the moment to revisit a bootstrap package.
- Neutral: `cli` now depends on the adapter distributions, so `agent-hub-cli` declares them as dependencies when it first
  imports them.

## More Information

- [ARCHITECTURE.md](../ARCHITECTURE.md): the dependency rule and the "where does this code go" table.
- [ADR 0001](0001-uv-workspace-with-namespace-packages.md) and [ADR 0002](0002-lean-hexagonal-architecture.md).
