# Event derivations: Session, WorkflowRun and Learning

## Purpose

A sketch for Phases 2 and 3: how the three derived entities of the [domain model](domain-model.md) are computed from
canonical events ([SPEC](../SPEC.md), event model). For each one it lists the event types and fields that create,
change and close it. The payload keys named here are proposals that the Phase 2 source adapters fix; the SPEC only
says the payload is a JSON object.

## Contract

### Fold

- A derivation is a pure function in core that folds events into entity state. Its only input is the event store; it
  sorts by `(timestamp, source, source_id)`, a total order because the pair `(source, source_id)` is unique.
- Recomputable: the derived tables are projections, kept apart from the events table. Dropping them and folding the
  whole store again rebuilds them exactly.
- The fold is idempotent: a duplicate never reaches the store, and folding the same events again, in any arrival
  order, gives the same state. An incremental update must equal a full fold; an event older than the last one folded
  for an entity triggers a refold of that entity.
- Tolerant: a missing or unknown payload key leaves the attribute empty; it never fails the fold.
- Proof (Phase 2): unit tests on the fold with shuffled and duplicated input, and an integration test that drops the
  projections and rebuilds them from a SQLite store.

### Session

| Step | Events | Fields used |
|---|---|---|
| Create | the first event with a new `(project, session)` from `claude_code`, `transcript` or `otel`; normally `session.start` | `timestamp` (start), `repo`, `agent`, `workflow` |
| Change | every later event of that session | latest `timestamp` (last activity); `tool.call` → tool counts (`payload.tool`) and files touched (`payload.path`); `tool.result` → errors; `otel` → tokens and cost (`payload.cost_usd`); `decision` → decision count; an open `gate.request` → waiting |
| Close | `session.end` | `timestamp` (end), `payload.outcome` |

Events from `executor`, `github` or `linear` that name an existing session enrich it (for example a PR link) but never
create one. A session without `session.end` stays open.

### WorkflowRun

Created and moved by `executor` events that carry `workflow`, `step` and the run id. Sessions join a run when their
events carry the same `workflow` and run id. Mapping of the current issue-to-PR runner, whose per-transition log
already records a run id, the issue, the repo and the state:

| Runner state | Event (proposed types, see Open questions) | Effect on the run |
|---|---|---|
| `PICKED` | `step.start`, step `pick`, `payload.issue` | creates it: workflow, issue, repo, start time |
| `WORKTREE` | `step.start`, step `worktree` | current step |
| `IMPLEMENTING` | `step.start`, step `implement` | current step; the agent sessions it starts join the run |
| `VERIFYING` | `step.start`, step `verify`; `gate.result` with the check outcome | current step; gate outcome |
| `PR_OPEN` | `step.start`, step `pr`, `payload.pr_url` | current step; PR link |
| `FAILED(stage, reason)` | `step.end` with `payload.status` failed, `payload.stage`, `payload.reason` | marks it failed with stage and reason |
| `REPORTED` | `step.end`, step `report` | closes it: end time, final state done or failed |

Human approvals anywhere in a run are `gate.request` (waiting) and `gate.result` (approver, decision). A run with no
closing event stays in its current step.

### Learning

| Step | Events | Fields used |
|---|---|---|
| Create | `learning.proposed` | `payload.id`, `payload.text`, `payload.target` (the brain file it would change), author; `session` → source session |
| Close | `learning.accepted` with the same `payload.id` | status accepted, who accepted it, when |
| Close | a rejection (no event type today, see Open questions) | status rejected, reason |

A learning stays `proposed` until closed. Accepting one records the fact; editing the brain stays a human act.

## Invariants

- The event store is the single input; derivations never write, change or delete an event.
- Same stored events, same derived state, whatever the arrival order or the number of refolds.
- A derived entity can always be dropped and rebuilt; it holds nothing the events do not.

## Decisions

- [SPEC](../SPEC.md): the canonical event, idempotency by `(source, source_id)`, and direction 3 (structured events
  and derivatives are kept, raw transcripts are not working memory).
- [ADR 0002](../adr/0002-lean-hexagonal-architecture.md): folds are core functions over data; storage is an adapter.
- [ADR 0003](../adr/0003-persistence-sqlalchemy-core-and-alembic.md): projections are tables next to the events.

## Open questions

- Run id and step events: the canonical event has no run id and no step type today. Proposal, a compatible SPEC change
  for Phase 2: the run id in `payload.run`, and `type` widened with `step.start`, `step.end` and `learning.rejected`.
- `session` is required on every event: which value executor events carry outside an agent session (the run id is
  the candidate), without the Session fold treating it as a session.
- When an open session with no `session.end` counts as abandoned (an idle timeout, or never).
- The exact payload keys per type, fixed by each source adapter's issue.
