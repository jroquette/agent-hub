# Event derivations: Session, WorkflowRun and Learning

## Purpose

A sketch for Phases 2 and 3: how the three derived entities of the [domain model](domain-model.md) are computed from
canonical events ([SPEC](../SPEC.md#data-sources-and-event-model)). For each one it lists the event types and fields
that create, change and close it, and the properties any implementation must have. The payload keys named here are
proposals that the Phase 2 source adapters fix; mechanisms not yet chosen are listed under Open questions.

## Contract

### Sources and privacy

- Redact before append, a requirement the SPEC already sets
  ([event model](../SPEC.md#data-sources-and-event-model), "Privacy and redaction"): ingestion redacts key and token
  patterns before an event is written. A stored event is never changed, so a secret that reaches the store stays.
- Proposals for Phase 2, not decided (Open questions): redaction runs in the source adapter, the collector's own being
  a second line; and events carry no raw message, reasoning or tool-output text, so `message`, `reasoning` and
  `tool.result` events hold metadata (sizes, tool, status) and a reference to the redacted transcript blob, which has
  its own short retention (SPEC direction 3).
- The post-session extraction writes its results (summary, decisions, proposed learnings) as events, so they survive
  the deletion of the transcript. The Session records where its transcript is and when it is deleted.

### Fold: required properties

- A derivation is a pure function in core over stored events. Rebuilding from the events gives the same state; how
  and where the derived state is kept is open.
- The fold is idempotent: a duplicate never reaches the store, and folding the same events again, in any arrival
  order, gives the same state.
- One fact reported by several sources (hooks, transcript, OTel) counts once. Either each attribute has one
  authoritative source, or the sources share a correlation key; which one is open.
- State that depends on order (current step, last tool, first terminal event) follows one source's own sequence,
  never a sort of timestamps across sources, whose clocks and latencies differ.
- Costs and token counts are summed exactly (`Decimal`, never float).
- Tolerant: a missing or unknown payload key leaves the attribute empty; it never fails the fold.
- Proof (Phase 2): unit tests on the fold with shuffled, duplicated and multi-source input.

### Session

| Step | Events | Fields used |
|---|---|---|
| Create | the first event with a new `(project, session)` from `claude_code`, `transcript` or `otel` | `repo`, `agent`, `workflow`; start = `session.start`'s `timestamp` when present, else the earliest seen |
| Change | every later event of that session | last activity; `tool.call` → tool counts (`payload.tool`) and files touched (`payload.path`); `tool.result` → errors; `otel` → tokens and cost; `decision` → decisions; an open `gate.request` → waiting; the transcript reference and deletion date |
| Close | `session.end` | end = the last `session.end`; `payload.outcome` |

A resumed session (several start and end pairs under one `session`) is one Session. Events that arrive after its end
enrich it (a late cost, a PR link from `github`) but never reopen it. Events from `executor`, `github` or `linear`
that name an existing session enrich it but never create one. A session without `session.end` stays open.

### WorkflowRun

Created and moved by `executor` events that carry `workflow`, `step` and the run id. A retried step carries its
attempt number in `payload.attempt` and in the executor's `source_id`, so each attempt is a distinct event, and step
state is keyed by `(step, attempt)`. How a Session joins its run is open. Mapping of the current issue-to-PR runner,
whose per-transition log already records a run id, the issue, the repo and the state:

| Runner state | Event (proposed types, see Open questions) | Effect on the run |
|---|---|---|
| `PICKED` | `step.start`, step `pick`, `payload.issue` | creates it: workflow, issue, repo, start time |
| `WORKTREE` | `step.start`, step `worktree` | current step |
| `IMPLEMENTING` | `step.start`, step `implement` | current step; the agent sessions it starts join the run |
| `VERIFYING` | `step.start`, step `verify`; `gate.result` with the check outcome | current step and attempt; gate outcome |
| `PR_OPEN` | `step.start`, step `pr`, `payload.pr_url` | current step; PR link |
| `FAILED(stage, reason)` | `step.end` with `payload.status` failed, then `run.end` failed with `payload.stage`, `payload.reason` | closes it as failed with stage and reason |
| `REPORTED` | `step.end` of the last step, then `run.end` done | closes it: end time, final state |

A run ends only on its explicit terminal event, `run.end`, never because a step has a given name. A run with no
`run.end` stays in its current step. Approvals anywhere in a run are a `gate.request` (waiting) and a `gate.result`
(approver, decision), paired by `payload.gate_id`, never by adjacency.

### Learning

| Step | Events | Fields used |
|---|---|---|
| Create | `learning.proposed` | its `(source, source_id)` is the identity; `payload.text`, `payload.target` (the brain file it would change), `payload.author` (person or agent); `session` → source session, none for a person's proposal |
| Change | none | nothing changes a learning between proposal and close |
| Close | `learning.accepted` naming the proposal in `payload.proposal` | status accepted, who and when, `payload.brain_path` and `payload.commit` it became |
| Close | a rejection (`learning.rejected`, proposed type) | status rejected, reason |

The first terminal event, in its source's own order, wins; a later one stays in the store and the fold ignores it. An
accept whose proposal is not stored yet waits and is applied once the proposal arrives. A learning stays `proposed`
until closed. Accepting one records the fact; editing the brain stays a human act.

## Invariants

- The event store is the single input; derivations never write, change or delete an event.
- Same stored events, same derived state, whatever the arrival order or the number of rebuilds.
- A derived entity can always be dropped and rebuilt; it holds nothing the events do not.
- Every event is redacted before it is appended ([SPEC](../SPEC.md#data-sources-and-event-model)).

## Decisions

- [SPEC](../SPEC.md): the canonical event, idempotency by `(source, source_id)`, privacy and redaction, and
  direction 3 (structured events and derivatives are kept; raw transcripts are short-lived).
- [ADR 0002](../adr/0002-lean-hexagonal-architecture.md): folds are core functions over data; storage is an adapter.

## Open questions

- Proposed, a SPEC change for Phase 2 if adopted: events hold no raw message, reasoning or tool-output text, only
  metadata and a reference to the redacted transcript blob; redaction runs in the source adapter, with the
  collector's as a second line.

- Proposed event types, a compatible SPEC change for Phase 2: `step.start`, `step.end`, `run.end`,
  `learning.rejected` and a session summary type; the run id in `payload.run`.
- Counting a fact once: an authoritative source per attribute, or a correlation key shared by the sources.
- How a Session joins its WorkflowRun: a link event emitted by the executor, or the run id stamped on every event by
  the hooks (from the environment the executor sets).
- Each source's own sequence: in `source_id`, or a `payload.seq` the adapter assigns.
- Storage of derived state (tables, a cache, recomputed on read) and how it is kept in step with new events.
- Storage and retention of the transcript blob; the period is an open question of the SPEC.
- `session` is required on every event: which value executor events and a person's learning carry outside an agent
  session (the run id is the candidate for the executor), without the Session fold treating it as a session.
- When an open session with no `session.end` counts as abandoned (an idle timeout, or never).
- The exact payload keys per type, fixed by each source adapter's issue.
