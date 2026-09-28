# Domain model: the nine entities

## Purpose

A sketch, not a contract yet: names each of the nine entities of the [SPEC](../SPEC.md) core concepts with its
identity, main attributes, relations and the phase that introduces it, so later phases build on one shared model.
Phase 1 uses only Project, Hub and Repo, read from the validated `hub.json` ([project-config.md](project-config.md)),
and Agent as plugin files on disk. Nothing below is persisted before Phase 2.

## Contract

### Entities

| Entity | Identity | Main attributes | Relations | Phase |
|---|---|---|---|---|
| `Project` | `project.name` | tracker kind and team, author, branch prefix, default branch | has one Hub and 1..N Repos | 1 (config) |
| `Hub` | `project.hub_repo` | platform version, schema version, selected modules, lock | belongs to one Project; holds the Brain, Agents and Workflows | 1 (config) |
| `Repo` | `(project, dir)` | GitHub `owner/name`, role, fast and full check commands | belongs to one Project; events name it in `repo` | 1 (config) |
| `Workflow` | `(hub, name, revision)` | schema version, inputs, limits, ordered steps | belongs to one Hub; has many WorkflowRuns | 4 |
| `Agent` | `(plugin, name)`, written `plugin:name` (e.g. `hub-workflow:evaluator`) | instructions file, allowed tools, model | defined in a Hub plugin; events name it in `agent` | 1 (files), 2 (events) |
| `Session` | `(project, session)` from the canonical event | start and end, repo, agent, cost, outcome, run | belongs to one Project; at most one WorkflowRun | 2 |
| `WorkflowRun` | `(project, run)` | workflow and revision, issue, state, current step, failure stage and reason | runs one Workflow revision; contains its Sessions | 2 (derived), 4 (engine) |
| `Brain` | the hub's `brain/` tree | items with type, status, provenance, last verified, repos | belongs to one Hub; fed by accepted Learnings | 3 |
| `Learning` | `(project, learning id)` from its proposal event | text, status (proposed, accepted, rejected), source session, author, target | comes from one Session; may become a Brain item | 3 |

"Run" names a WorkflowRun only; a Session is never called a run.

### Where each one comes from

- **Configured** (Project, Hub, Repo): the `HubConfig` model is their source; later phases read them from the hub
  checkout, never from a second store.
- **Defined in files** (Agent, Workflow, Brain): the hub's plugin directories, workflow documents
  ([workflow-schema.md](workflow-schema.md)) and brain files with frontmatter. The platform reads them; only the owner
  edits the brain.
- **Derived from events** (Session, WorkflowRun, Learning): projections folded from the event store, as described in
  [event-derivations.md](event-derivations.md).

In core each becomes a frozen Pydantic model when its phase starts, following the canonical `Event`: strict fields,
unknown fields rejected. How Phase 2 proves it: unit tests per model, and contract tests for any store behind a port.

## Invariants

- Every entity belongs, directly or through its parents, to exactly one Project; no entity crosses projects.
- Derived entities are read models: rebuilding them from the events gives the same result, and they never feed back
  into the events.
- An agent proposes a Learning; only a person accepts it into the Brain.
- Identities are the ids the sources already carry (config keys, event fields); the platform mints none of its own in
  Phases 1 and 2.

## Decisions

- [SPEC](../SPEC.md) core concepts: the nine entities and the rule that a run is never a session.
- [ADR 0002](../adr/0002-lean-hexagonal-architecture.md): entities live in core; adapters come to them.
- [ADR 0010](../adr/0010-hub-json-config-contract.md): Project, Hub and Repo come from the validated `hub.json`.

## Open questions

- Whether a Brain item becomes its own entity (one per file) or stays an attribute list of Brain; decided in Phase 3
  together with the frontmatter schema.
- Agent identity across renames: whether events keep the old `plugin:name` or map it to the new one.
- The Workflow and WorkflowRun identity details depend on the run id question in
  [event-derivations.md](event-derivations.md).
