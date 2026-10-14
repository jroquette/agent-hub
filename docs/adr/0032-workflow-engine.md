# 0032. A graph workflow engine and format

- Status: proposed
- Date: 2026-10-14
- Deciders: José Henrique Roquette (decisions 1 to 7 and D-a to D-e approved with the AGH-213 plan on 2026-10-14)
- Supersedes, once accepted: [ADR 0027](0027-workflow-format-and-minimum-engine.md) (its format and minimum engine;
  its invariants are kept). ADR 0027 is not edited; only its status line changes when this ADR is accepted.

## Context and Problem Statement

[ADR 0027](0027-workflow-format-and-minimum-engine.md) chose a linear document with three engine step types and left
out `depends_on`, `trigger_rule`, `when:`, loops and includes until a workaround audit showed a need. Planning the
Phase 4 delivery (AGH-213) showed that need already. The work hub wants a lint node beside `implement`, an approval
before `pr`, review and deliver workflows with parallel reviewers, and a rework loop on a rejected gate. The linear
format would express each of these as a script that hides the control flow from the engine, the UI and the run's
events, which is the workaround pressure ADR 0027's own smells warn about.

The structure such workflows need is well understood: a graph of nodes with `depends_on` layers and `trigger_rule`
joins, a small `when:` language, typed outputs, loops, approval gates, waits, `include` composition, retry by failure
kind, the run's status kept apart from its authored outcome, and dry runs with stub fixtures.

How should agent-hub's workflow format and engine be built?

## Considered Options

1. Keep ADR 0027's linear format and grow it one key at a time.
2. Adopt an existing third-party workflow engine and drive it from agent-hub.
3. Write our own graph engine and format in Python, in core, with our own tests.

## Decision Outcome

Option 3. Option 1 grows the format one operator at a time, each step a workaround until the next. Option 2 brings
another runtime, a node surface we do not need and changes we would have to follow, and it would bypass agent-hub's
hooks, event pipeline and privacy rules.

1. **Our own graph engine and format.** It supersedes ADR 0027's linear format. ADR 0027's
   invariants stay: orchestration spends no tokens, runs are deterministic, a run pins its revision and content hash,
   and the admission rule and the five smells apply. The contract is
   [workflow-schema.md](../design/workflow-schema.md), at 150 lines or fewer.
2. **YAML through PyYAML with a strict loader**, in `generator`; core stays Pydantic-only
   ([ADR 0002](0002-lean-hexagonal-architecture.md)). Duplicate keys, anchors and aliases, tags and multiple documents
   are refused; a byte cap applies; JSON is accepted. Anchors are refused because reuse comes from `include`.
3. **`output_format` is JSON Schema**, validated by `jsonschema` behind a core port `OutputValidator` implemented in
   `generator`. The review and eval schemas of [ADR 0028](0028-agent-outputs-as-validated-json.md) plug in as plain
   schemas.
4. **The web starts runs as a child process** (`hub workflow run --run-id …`). The engine lives in core and the
   executors in cli; `api` still never imports `cli` ([ADR 0017](0017-api-second-composition-root.md)).
5. **Base workflows are seeded** into the hub's `workflows/` as packs (`<pack>/<workflow>.yaml` with `prompts/`,
   `scripts/`, `fixtures/`), and the project owns them ([ADR 0009](0009-hub-sync-by-file-ownership.md)). Discovery
   reads the hub's `workflows/`, then the built-ins, a hub workflow overriding a built-in of the same name.
6. **Steps call real `hub step …` subcommands** (`worktree`, `commits`, `pr`, `report`) from shell nodes. Agent nodes
   run `claude -p` with the hub's settings and plugin, so the guard, stop gate, readonly gate and event sensor apply.
7. **Typed failure kinds** (AGH-179): `transient`, `timeout`, `rate_limited` and `overloaded`
   retry with backoff; `exec_failed`, `output_contract`, `max_iterations` and `unknown` retry only when the node opts
   in; `config`, `auth`, `cancelled` and `fatal` never retry. A kind is set where the failure happens, never from
   message text.

Plan decisions, approved with the plan:

- **D-a Script runtimes:** `sh` and `python` (through `uv run`). Helpers in the seeded packs are Python.
- **D-b Delivery and outcome:** the authored outcome (`returns` plus `outcome_field`, a required `boolean` or an
  `enum` string of the `returns` node's output) goes to `run.end`'s `outcome`. issue-to-pr returns its `report` node,
  whose typed `delivery` (`delivered`, `no_changes`, `blocked`, `failed`) is its `outcome_field`, so
  [ADR 0030](0030-run-outcomes-in-the-tracker.md)'s outcomes, tracker writes and exit codes keep their meaning. No
  new key.
- **D-c Parallelism:** v1 runs a layer's nodes one at a time. Concurrency arrives with composition, and read-only nodes
  never share a layer with nodes that change the checkout.
- **D-d Left out** until a real need passes the admission rule: sub-runs, fan-out, containers, an evidence policy,
  persisted sessions and other providers.
- **D-e Naming:** each node declares `type:` (`agent`, `shell`, `script`, `loop`, `loop_group`, `approval`, `wait`,
  `halt`, `include`), which is easy to read, validate and show; an agent node takes `prompt:` or `prompt_file:`;
  commands are argv lists, as in ADR 0027. Joins and conditions are `depends_on`, `trigger_rule` (`all_success`,
  `one_success`, `none_failed_min_one_success`, `all_done`) and `when:`.

**What we keep of ours:** sessions are Claude Code with the hub's plugin; every event goes through `IngestEvents`
([ADR 0019](0019-metadata-only-events-and-redaction.md)), so outputs stay in run records and never in events; the hub
owns its workflows and hub web drives them. Runs, decisions and waits are events: there is no new table and no
migration.

### Consequences

- Good: lint nodes, approvals, rework loops and parallel reviewers are data the engine sees, the UI draws and the
  events record, instead of scripts that hide control flow.
- Good: dry runs with stub fixtures test every workflow in CI before it spends anything.
- Bad: a wider format than ADR 0027's, so the admission rule and the per-type keys must hold it at one screen.
- Bad: the `when:` grammar and `include` are now ours to maintain, and every later key must pass the admission rule.
- Neutral: ADR 0027's `human`, `gate`, `delivers` and `on_not_delivered` give way to `approval`, `shell` nodes,
  `returns`/`outcome_field` and `all_done` joins; no workflow file in the old format exists, so nothing migrates.

## More Information

[workflow-schema.md](../design/workflow-schema.md) (the contract); [SPEC](../SPEC.md) direction 1;
[event-derivations.md](../design/event-derivations.md) (how `run.end` folds into a WorkflowRun); AGH-213 plan and
research (hub `brain/features/workflows-engine/`).
