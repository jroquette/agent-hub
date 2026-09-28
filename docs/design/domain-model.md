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
| `Workflow` | `(hub, name, revision, content hash)` | schema version, inputs, limits, ordered steps | defined in one Hub, or shipped as a base workflow; has many WorkflowRuns | 4 |
| `Agent` | `(plugin, name)`, written `plugin:name` (e.g. `hub-workflow:evaluator`) | instructions file, allowed tools, model | defined in a plugin (base agents are shared by every hub); events name it in `agent` | 1 (files), 2 (events) |
| `Session` | `(project, session)` from the canonical event | start and end, repo, agent, cost, outcome, run, transcript reference and its deletion date | belongs to one Project; at most one WorkflowRun | 2 |
| `WorkflowRun` | `(project, run)` | workflow and revision, issue, state, steps by `(step, attempt)`, failure stage and reason | runs one Workflow revision; contains its Sessions | 2 (derived), 4 (engine) |
| `Brain` | the hub's `brain/` tree | items with type, status, provenance, last verified, repos | belongs to one Hub; fed by accepted Learnings | 3 |
| `Learning` | `(source, source_id)` of its `learning.proposed` event | text, status (proposed, accepted, rejected), author (person or agent), optional source session, target, resulting brain file and commit | may come from one Session; may become a Brain item | 3 |

"Run" names a WorkflowRun only; a Session is never called a run.

A Workflow's content hash is part of its identity: two documents with the same name and revision but different bytes
are different workflows, so a run always names exactly what it executed ([workflow-schema.md](workflow-schema.md)).

A Session's transcript is never copied into the events: the Session keeps a reference to the redacted transcript blob
and the date it will be deleted, per the short retention of SPEC direction 3. What outlives the transcript is only
what the post-session extraction wrote back as events ([event-derivations.md](event-derivations.md)).

A Learning is proposed by a person or by an agent. A person's proposal has no source session. Its provenance chain is
session (when there is one) → proposal → accepted → the brain file and commit it became.

### Where each one comes from

- **Configured** (Project, Hub, Repo): in Phase 1 the `HubConfig` model is their source, read from the hub checkout,
  never from a second store. How a Phase 2 portfolio finds several hubs is open.
- **Defined in files** (Agent, Workflow, Brain): the plugin directories, workflow documents
  ([workflow-schema.md](workflow-schema.md)) and brain files with frontmatter. The platform reads them; only the owner
  edits the brain. Where workflows and their history are stored in Phase 4 is open.
- **Derived from events** (Session, WorkflowRun, Learning): projections folded from the event store, as described in
  [event-derivations.md](event-derivations.md).

In core each becomes a frozen Pydantic model when its phase starts, following the canonical `Event`: strict fields,
unknown fields rejected. How Phase 2 proves it: unit tests per model, and contract tests for any store behind a port.

## Invariants

- Every derived entity (Session, WorkflowRun, Learning) belongs to exactly one Project and never crosses projects.
  Hub, Repo, Brain and project workflows belong to one Project; Agents and base workflows are shared across hubs.
- Derived entities are read models: rebuilding them from the events gives the same result, and they never feed back
  into the events.
- Anyone, person or agent, proposes a Learning; only a person accepts it into the Brain.
- Identities are the ids the sources already carry (config keys, event fields, event keys); the platform mints none
  of its own in Phases 1 and 2.
- No entity holds raw transcript text; a Session only points to the blob while its retention lasts.

## Decisions

- [SPEC](../SPEC.md) core concepts: the nine entities and the rule that a run is never a session; direction 3 for
  the transcript's retention.
- [ADR 0002](../adr/0002-lean-hexagonal-architecture.md): entities live in core; adapters come to them.
- [ADR 0010](../adr/0010-hub-json-config-contract.md): Project, Hub and Repo come from the validated `hub.json`.

## Open questions

- Hub registry: how the Phase 2 portfolio lists several hubs (a list of checkouts in local config, or a registry
  store), and whether Project, Hub and Repo are then cached outside the checkout.
- Workflow storage and history (SPEC direction 1 says the platform stores versions and history): how that relates to
  the hub's git history, and where base workflows live.
- Whether a Brain item becomes its own entity (one per file) or stays an attribute list of Brain; decided in Phase 3
  together with the frontmatter schema.
- Agent identity across renames: whether events keep the old `plugin:name` or map it to the new one.
- Which source emits `learning.proposed`: a hook on the propose-a-learning skill, or a watcher on the brain inbox.
- The WorkflowRun and Session link depends on the open questions in [event-derivations.md](event-derivations.md).
