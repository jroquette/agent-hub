# Event derivations: Session, WorkflowRun and Learning

## Purpose

A sketch for Phases 2 and 3: how the three derived entities of the [domain model](domain-model.md) are computed from
canonical events ([SPEC](../SPEC.md#data-sources-and-event-model)). For each one it lists the event types and fields
that create, change and close it, and the properties any implementation must have. Phase 2 built Session (with its
label, actors and problems, AGH-201), WorkflowRun, Learning and Approval as folds in `agent_hub.core` (`sessions/`,
`runs/`, `learnings/`, `approvals/`); the questions it decided are under "Phase 2 decisions".

## Contract

### Sources and privacy

- Redact before append, a requirement the SPEC already sets
  ([event model](../SPEC.md#data-sources-and-event-model), "Privacy and redaction"): ingestion redacts key and token
  patterns before an event is written. A stored event is never changed, so a secret that reaches the store stays.
- Decided in Phase 2: redaction runs once, in core's `IngestEvents`, for every entry point, and events carry no raw
  message, reasoning or tool-output text: each type keeps only the keys of the "Payload kept" table
  (`agent_hub.core.events.payload_keys`), and `IngestEvents` drops any other key. No transcript blob is stored;
  the one body excerpt is a failed tool's `error_message` (300 characters, redacted, [ADR 0023](../adr/0023-short-error-message.md)).
- The post-session extraction writes its results (summary, decisions, proposed learnings) as events, so they survive
  the deletion of the transcript. The Session records where its transcript is and when it is deleted.

### Fold: required properties

- A derivation is a pure function in core over stored events, taking `now` as an argument. Rebuilding from the
  events gives the same state. Derived state is recomputed on read and memoized in process, keyed by the store's
  high-water mark (D12); nothing derived is written to disk.
- The fold is idempotent: a duplicate never reaches the store, and folding the same events again, in any arrival
  order, gives the same state.
- One fact reported by several sources (hooks, transcript, OTel) counts once, by a fold-time fact key (D16): the tool
  use id; the transcript record uuid; `(run, step, attempt)` for steps; the transcript `message.id` for usage (E5).
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

A resumed session (several start and end pairs under one `session`) is one Session. Events from `executor`, `github` or
`linear` that name an existing session enrich it but never create one. Status (D14), with `now` injected: `waiting`
while a `gate.request` is unresolved; else `live` with an event in the last 5 minutes or a `tool.call` without its
result; else `idle`; `ended` on `session.end`. With no event for 30 minutes and no end it is `ended` with
`outcome: null` and `end_reason: "no_end_event"`, labelled inferred; a later event reopens it as a new segment. A
session started by `hub run` carries the run, step and attempt in `payload` (the sensor reads them from
`AGENT_HUB_RUN_ID`, `AGENT_HUB_STEP` and `AGENT_HUB_ATTEMPT`), which is how a Session joins its run.

Derived on read by AGH-201 (pure, order-independent, from stored events only; labels and problems carry `derived: true`):

| Part | Rule |
|---|---|
| `label` (S1, `sessions/session_label.py`) | `branch`: the latest non-empty `git_branch`; `repo`: the first event's; `worktree`: the folder after `.claude/worktrees/` in the last `session.start` `cwd`; `workflows`: the user prompts' slash commands and the Skill calls' `skill`, as `/<name>` (a `<plugin>:` prefix dropped), in order, once each; `workflow`: the first not in `ROUTINE_COMMANDS` (`/kickoff`, `/handoff`, `/clear`, `/compact`, `/model`, …), else the first; `issue`: set at read time with the hub's `LabelRules` (tracker teams, branch prefix), outside the memo, as `^(<prefix>)?<team>-<n>\b` on the branch (case-insensitive), else the worktree name, shown `<TEAM>-<n>`, else `null` |
| `actors` (S2, `sessions/session_actors.py`) | the main agent (no `agent_id`; `agent` empty or `main`), then each subagent by `(agent, agent_id)` in the order it first acted, linked to the main agent's Agent or Task call of the same `subagent_type` that starts before its first event and whose result, if any, comes after its last (its `description`, its event id); two such calls: no link. `parent_session_id` stays `null`: subagents share the session id |
| problem kinds (S4, `sessions/session_problems.py`) | one per failure fact (its fact-key winner): `tool_failed`; `command_exit` (Bash); `hook_failed` (an error whose `hook` is set and not `guard`); `interrupted` (an error whose text starts "interrupted"); `guard_denied` (`status: denied`); `guard_ask_open`, `guard_ask_declined` (a guard-ask Approval); `gate_failed` (`gate.result` `failed`, the Stop gate included). Each has `tool`, `where` (from the paired `tool.call`: command, pattern, URL, MCP tool, skill or path, 120 chars; a gate's name, path or command), `message` (`error_message`, else `error_line`, else the rule or command and exit code, so events stored before ADR 0023 still read), time and actor |
| resolutions | in canonical order: `interrupted` and a declined ask are `by_you`; an open ask `needs_you`; a later `ok` result of the same actor, tool and `where`, or a later pass of the same gate, `recovered`; a later tool call of the same actor `agent_continued`; else `open` while the session is `live` and the actor has not replied since, `needs_you` once it replied (ended its turn), waits, idles or ends |
| summary and counts | a counts line, then needs-you problems first, by time: at most 5 lines, each with its `event_id`; lists and tiles carry `{needs_you, open, handled, by_you}` |

### WorkflowRun

Created and moved by `executor` events that carry `workflow`, `step` and the run id. A retried step carries its
attempt number in `payload.attempt` and in the executor's `source_id`, so each attempt is a distinct event, and step
state is keyed by `(step, attempt)`. A Session joins its run through the run id its events carry (Session above). Mapping of the current issue-to-PR runner,
whose per-transition log already records a run id, the issue, the repo and the state:

| Runner state | Event | Effect on the run |
|---|---|---|
| `PICKED` | `step.start`, step `pick`, `payload.issue` | creates it: workflow, issue, repo, start time |
| `WORKTREE` | `step.start`, step `worktree` | current step |
| `IMPLEMENTING` | `step.start`, step `implement` | current step; the agent sessions it starts join the run |
| `VERIFYING` | `step.start`, step `verify`; `gate.result` with the check outcome | current step and attempt; gate outcome |
| `PR_OPEN` | `step.start`, step `pr`, `payload.pr_url` | current step; PR link |
| `FAILED(stage, reason)` | `step.end` with `payload.status` failed, then `run.end` failed with `payload.stage`, `payload.reason` | closes it as failed with stage and reason |
| `REPORTED` | `step.end` of the last step, then `run.end` done | closes it: end time, final state |

A run ends only on its explicit terminal event, `run.end`, never because a step has a given name. A run with no
`run.end` stays in its current step.

**Delivery (AGH-140).** Whether the run failed and what it delivered are two fields. `run.end` carries
`payload.outcome`: `delivered` (its PR), `failed`, or one of two ends that are not failures, `no_changes` (the
implementing session left no commit) and `blocked` (the session stopped and asked for a human). Those two come from a
`not_delivered` record instead of `failed`: their stage ends `ok`, the `run.end` is `done` with the reason in
`payload.reason`, and the run is `REPORTED` with no `failure`, its `delivery` and `delivery_reason` set. A `run.end`
stored before `outcome` existed reads `delivered` when it names a PR and did not fail, else `failed`. The tracker
report follows the outcome ([ADR 0030](../adr/0030-run-outcomes-in-the-tracker.md)): `no_changes` gets its own comment
and no label, and exits 0; `blocked` gets the blocked label (`tracker.blocked_label`, else `tracker.failed_label`) and a
comment carrying the session's question, and exits 3; only `failed` gets the failed label and the diagnosis, and exits
1. Every outcome but `failed` removes the failed and blocked labels the issue carries. Approvals anywhere in a run are a `gate.request` (waiting) and a `gate.result`
(approver, decision), paired by `payload.gate_id`, never by adjacency.

**Workflow engine runs (ADR 0032, AGH-225).** A run is the engine's when one of its events carries what only the engine
writes: `content_hash`, or a step's `failure_kind` or `skip_cause` ([workflow schema](workflow-schema.md)). Its steps
keep every node id as recorded (`a__b` inside an include), with `status` `ok`, `failed` or `skipped`, `failure_kind`
and `skip_cause`; a run with neither keeps `hub run`'s five steps and drops any other. Each engine `run.end`
(`<run>:run:<n>:end`, `n` at most 9 digits) is its own fact, and the one with the highest `n` decides the end, so
a resumed run ends on its latest end; a step after that end means a resume not ended yet, and the run is `running`
again. A `hub run` run keeps the first. The run has `status` (`running`, then the `run.end`'s `done`,
`failed` or `cancelled`), `outcome` (the `run.end`'s JSON boolean or string), and the pinned `revision` and
`content_hash` (the first event that carries them). Its `delivery` is the outcome when it names one, `failed` for a failed run with none, and none
otherwise. `stage` stays issue-to-pr's machine: an issue-to-pr engine run takes the stage of its latest node that has
one (`report` keeps the PR's), any other workflow's live run is `PICKED`, and an ended run is `REPORTED` or `FAILED`.
Events do not carry a node's type, so a step's `kind` is set only for issue-to-pr (`worktree`, `verify`, `pr` and
`report` are `shell`, `implement` is `loop`, `pick` none); the workflow's document gives the others. The runs list
filters by `workflow` and by the failing step's `failure_kind`; `runs_in_flight_by_stage` counts `running` runs.

### Learning

| Step | Events | Fields used |
|---|---|---|
| Create | `learning.proposed` | its `(source, source_id)` is the identity; `payload.text`, `payload.target` (the brain file it would change), `payload.author` (person or agent); `session` → source session, none for a person's proposal |
| Change | none | nothing changes a learning between proposal and close |
| Close | `learning.accepted` naming the proposal in `payload.proposal` | status accepted, who and when, `payload.brain_path` and `payload.commit` it became; from the app also `pr_url`, `branch`, `state` |
| Close | `learning.rejected` naming the proposal | status rejected, reason; from the app also `pr_url`, `branch`, `state` |

The first terminal event, in its source's own order, wins; a later one stays in the store and the fold ignores it. An
accept whose proposal is not stored yet waits and is applied once the proposal arrives. A learning stays `proposed`
until closed. An app decision (source `control_plane`, [ADR 0024](../adr/0024-learning-actions-from-the-app.md)) only
opens a hub PR; its `state` is `accepted_pr_open` or `rejected_pr_open`, read as `in_brain` or `archived` once the note
is at its destination in the hub checkout. The note's text and summary are read on request, never folded.

### Approval

An open `gate.request` (kinds `guard_ask`, `plan`, `spec`, `human_gate`, `permission`; a Notification hook whose type
is a permission prompt maps to `permission`) is decided by the `gate.result` with the same `payload.gate_id`. A guard
ask is keyed by its tool use id: a PostToolUse or PostToolUseFailure with that id decides it `approved` (the tool ran,
E3); the session's next UserPromptSubmit, Stop or SessionEnd without it decides it `declined`, labelled inferred.

## Phase 2 decisions

- **D5, stored ids.** The store mints `event_id` (UUIDv7) and `received_at` at append (ADR 0018); identity stays
  `(source, source_id)`. Order and SSE resume use the store's append sequence.
- **D8, source ids.** Hooks: `<session>:<hook>:<tool_use_id>`, else `<session>:<hook>:<sent_at>:<h16>` (the first 16 hex
  digits of the SHA-256 of the hook input's canonical JSON). Transcript: `<session>:<record uuid>[:<content index>]`.
  Executor: `<run>:<state>:<event>:<ts>:<type>` (E7: one record can yield the `step.end` of one stage and the
  `step.start` of the next). Executor events carry `session = run:<run id>` and `workflow = issue-to-pr`.
- **D12, storage of derived state.** Recomputed on read, memoized in process by high-water mark; no derived table.
- **D14, session status and abandonment.** As in Session above.
- **D16, one fact once.** Fact keys as above; precedence: tool call, status and timing from `claude_code` then
  transcript; tool errors from `claude_code` then transcript `is_error`; tokens and model from the transcript; step,
  gate and run state from the executor then `claude_code`. The losers stay in Raw events with a `conflict` flag.
- **D18, hubs.** The hub registry (`hubs.json`) mints a UUIDv7 per registered hub; Project, Hub and Repo are still read
  from each hub's `hub.json` and `hub.lock`.
- **E3, tool errors.** From PostToolUseFailure (`status: error`, `error_line` the first line, `error_message` the
  short text of ADR 0023, `interrupted` on an interrupt).
- **E4, triggers and subagents.** `session.start.trigger` is the hook's `source` (startup, resume, clear, compact,
  fork); `git_branch` comes only from the transcript, which writes it on every event of a line naming `gitBranch`.
  Events from inside a subagent carry `agent` = its type and `payload.agent_id`. Stop, SubagentStart, SubagentStop,
  PreCompact and a Notification that is not a permission prompt yield no event.
- **E6, subagent transcripts.** On SubagentStop the server tails `agent_transcript_path`.

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

- Storage and retention of a redacted transcript blob, if one is ever kept; the period is an open question of the SPEC.
- A person's learning outside an agent session: which `session` value it carries.
- Subagent lanes beyond `agent`/`agent_id` attribution and the Agent-call link of Actors above.
- Persisted derived tables, when folding on read stops scaling (past about 100,000 events).
