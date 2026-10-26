# Workflow schema: workflows as data

## Purpose

The contract of agent-hub's workflow format and engine (Phase 4, [SPEC](../SPEC.md) direction 1): a graph of typed
nodes run by `hub workflow run|test` and `hub run`. Why: [ADR 0032](../adr/0032-workflow-engine.md), superseding
[ADR 0027](../adr/0027-workflow-format-and-minimum-engine.md); finer rules: [workflow-engine-rules.md](workflow-engine-rules.md).

## Contract

### Document and pack

A pack is a folder `workflows/<pack>/` with `<workflow>.yaml` files and optional `prompts/`, `scripts/` and `fixtures/`.
Discovery reads the hub's `workflows/`, then the built-ins; a hub workflow overrides a built-in of the same `name`. A
file is YAML through a strict loader (duplicate keys, anchors, aliases, tags and multiple documents refused; 256 KiB
cap) or JSON, then a frozen Pydantic model that forbids unknown keys. A load error names the file, line and key.

| Key | Type | Meaning |
|---|---|---|
| `version` | `1`, or `2` for a `kind: scenario` tree | format version; the engine refuses one it does not know. A `version: 2` scenario (`stages` instead of `nodes`) is translated to this graph at load ([ADR 0049](../adr/0049-scenario-blocks-and-run-control.md), accepted; [scenarios.md](scenarios.md) § Tree format) |
| `kind` | `workflow` (default) or `scenario` | a scenario holds only `action`, `expect`, `approval`, `wait`, `loop_group`, `include` ([scenarios.md](scenarios.md)) |
| `name`, `description` | kebab-case file stem; optional string | unique among the workflows discovered; one line for people, whose first sentence says when to use the flow: the "Use when" column of the flow catalog (`flow_catalog.py`) and the first line of hub web's Workflows card; a built-in's must hold at least four words |
| `revision` | integer ≥ 1 | bumped by the author on each change |
| `inputs` | map `^[a-z][a-z0-9_]*$` → `{type, required, default, description}` | `type`: `string` (default), `integer`, `number`, `boolean`; `required` excludes `default` |
| `returns` | node id, optional | the node whose output is the workflow's (and an include's) output |
| `outcome_field` | string, optional | a `required` property of `returns`' `output_format`, `boolean` or a `string` with `enum` |
| `environment` | a declared environment's name, optional (refused in a scenario) | the run's environment (`hub workflow run --env` overrides it): before the start the access policy decides each `shell` and `script` node by its `effect`, each `until_bash` as a `read`, and each `action` and `expect` as a scenario's (pinned at the start, credentials only to the action); an undeclared environment, a plan problem or a `deny` refuses the start, an `ask` is a `<step>__ask` approval (a policy gate, known from the run's record), and each node is decided again before it runs (a write that started and never ended asks again on resume); each decision is a `policy.decision` event; an include declaring another environment refuses the start, and `issue-to-pr` takes none; agents get `HUB_RUN_ENVIRONMENT`. Agent steps are checked on a best-effort basis; deterministic steps are enforced ([scenarios.md](scenarios.md)) |
| `nodes` | list, at least one | ids `^[a-z][a-z0-9_-]*$`, unique, never containing `__` (nor, in a scenario, `self`) |

### Nodes

Every node has `id`, `type` and optional `description`, `depends_on`, `trigger_rule` and `when`. Executable nodes
(`agent`, `shell`, `script`, `loop`) also take `retry`, `always_run` (rerun on resume, except a resume from a debug
pause: [workflow-engine-rules.md](workflow-engine-rules.md) § Run control), `timeout`, `output_format` and
`mutates_checkout: false` (a change fails it). Durations: `^[1-9][0-9]*(s|m|h|d)$`. Other keys fail the load.

| `type` | Keys | What happens |
|---|---|---|
| `agent` | `prompt` or `prompt_file` (one), `with`, `model`, `limits`, `context`, `cwd` | one `claude -p` session under the hub's hooks (a repo `cwd`: through `--settings`) |
| `shell` | `command` (argv list), `cwd`, `env`, `stdin`, `effect` (`read`, `write`, `destroy`: under an `environment`, the policy's input, `write` when absent) | runs the program, never through a shell; exit 0 passes |
| `script` | `runtime` (`sh` or `python`), `script`, `args`, `cwd`, `env`, `stdin`, `effect` (as `shell`'s) | `sh <file>` or `uv run <file>`; exit 0 passes |
| `loop` | the `agent` keys, `max_iterations`, `until`, `until_field`, `until_bash`, `fresh_context` | repeats one agent turn until done |
| `loop_group` | `nodes`, `max_iterations`, `until_bash`, `until_when`, `fresh_context` | repeats a body sub-graph until done |
| `approval` | `message`, `decisions`, `capture_response` | pauses the run for a human decision |
| `wait` | one of `duration`, `until`, `attention` (with `options`) | pauses the run until its condition holds |
| `halt` | `reason` | ends the run `cancelled`; nodes not yet run never run |
| `include` | `include` (a workflow name), `with` | replaced at load by that workflow's nodes |
| `action` | `action` (`<name>` or `<pack>/<name>`), `with`, `capture` (`{<name>: <ref>}`: `$CTX.<name>` downstream, one capture per name), `retry` (none by default), `timeout` (≤ 1h) | one action call, its output one JSON value; only in a scenario run or a workflow with an `environment` (else the start is refused) ([scenarios.md](scenarios.md)) |
| `expect` | the `action` keys, `every` (≥ 5s), `timeout` (≤ 24h), `until_when` (the `when:` grammar; it and `capture` read `$self.output[.path]`) | polls a read action until `until_when` holds (≤ 1000 polls a run, retries and resumes included), else `timeout` |

- `prompt_file` and `script` are paths inside the pack's `prompts/` and `scripts/` (no `..`, not absolute). `with` maps
  names to values or `{from: <output ref>, if_skipped: <value>}`, read in a prompt as `$WITH.<name>`. `model` is a
  `hub.json` → `models.tiers` tier (default `medium`); `limits` is `{max_turns, max_cost_usd}` (default 40 and 3.0);
  `context` is `fresh` (default; an explicit one in a `loop_group` body never resumes) or `{resume: <upstream agent node id>}`.
  A `cwd` (an agent's may be a reference) stays in the hub or a repo (else `config`); there an agent runs as `hub run`'s. `stdin`: a literal or one whole reference.
- No child gets `LINEAR_API_KEY`. Agents run with `session_env`, other commands with `untrusted_env`; `env` adds no
  token; every child gets the run's id as `AGENT_HUB_RUN_ID` (a node's `env` cannot set it). A `hub step` node
  (`command[0:2]` is `[hub, step]`) runs the engine's own hub with `child_env`, refuses `env`
  and a referenced `cwd`, and narrows per call (`push_env` only for fetch, push, gh). Tracker writes (ADR 0030) are the
  parent's; `hub run --live`'s (`issue-to-pr`) runs `hub step` in process: per-call tokens and timeouts, no `timeout`.
  A pack script gets `hub.json` values from a `config` node (`[hub, step, config]`, read-only, its output passed as an
  argument), never by opening `hub.json` or `hub.local.json`.
- `loop`: `max_iterations` (1–50) and at least one channel: `until` (text the final line equals), `until_field` (a
  `required` boolean of its `output_format`), `until_bash` (argv; exit 0 is done). `fresh_context: false` (default)
  resumes the previous iteration's session. The output is the last iteration's; past the cap it fails `max_iterations`.
- `loop_group`: body ids are recorded as `<group>__<id>`; `until_when` (the `when:` grammar) reads this iteration's body
  outputs, `$LOOP_PREV.<id>.output[.path]` the previous one (empty at first); the output maps body id → output.
- `approval`: `decisions` `{id, label}` (default `approve`, `reject`); output `{decision}` (+ `text` with
  `capture_response`, + the `approver` a person's recorded decision names); rework is a `loop_group` reading it; an unread default `reject` cancels the run. Gates (and
  groups holding one) are ordered; a body gate pauses its iteration. `wait`: `duration`, `until` (ISO-8601 + offset, or a
  reference), `attention` (text, or an `options` id), ≤ 7d; output `{at}`, `{text}`, `{choice, text}`; ends on a resume.
- `include` takes only `id`, `description`, `depends_on`, `when`, `trigger_rule`, `include`, `with` and names a workflow
  of its pack: `with` fills its `inputs`, its nodes become `<include id>__<id>`, its roots take the include's graph
  keys, depending on it waits on every sink, and `$<include id>.output` reads `returns` or the single sink. A
  workflow can be included and also run on its own: the built-in `sdlc` pack's `preflight-check` (a ticket's
  read-only preflight, its plan change gate and re-check, `returns` a summary node) is included by `ticket-pass` and
  by `preflight`, the standalone run `/merge` starts for a merged ticket's dependents; a parent reads only its
  `returns` (`$check.output.status`), never a node inside it.

### Running: joins, conditions, outputs, status, retry and events

Kahn layers over `depends_on`, in declaration order inside a layer. A cycle, an unknown id, a reference to a node not
upstream, or a bad `returns` or `outcome_field` is a load error. Layers run in order, a layer's nodes concurrently (≤ 4
at once); a failure does not stop later layers. A node first checks its `trigger_rule` against its dependencies:
`all_success` (default: every one completed), `one_success` (at least one), `none_failed_min_one_success` (none failed,
at least one completed) or `all_done` (every one ended). Then `when:`: `atom (('&&' | '||') atom)*`, `&&` binding
tighter, no parentheses or negation; an atom is `<ref> <op> <literal>` (op `==`, `!=`, `<`, `>`, `<=`, `>=`; literal
`'text'`, a number, `true`, `false`). A numeric literal compares numerically (a non-numeric value is a parse failure);
other literals compare canonical text with `==`, `!=`. A skipped producer reads as empty text; a failed one fails the
node. A node that does not run is skipped with a `skip_cause`: `upstream_failed` or `upstream_skipped` (`reason` names
the origin node, carried down the chain), `condition`, `condition_parse_error`, or `prior_success` (reused on resume).

References are `$INPUTS.<name>`, `$<node>.output`, `$<node>.output.<path>` (dot segments, `.0` for an array item; a path
needs the producer's `output_format`), `$LOOP_PREV…`, `$WITH.<name>`, `$CTX.<name>`, `$self…` (scenario), in prompts, `command`,
`args`, `cwd`, `env`, `stdin`, `with`, `until_bash`, `wait.until`, `message` and `reason`, resolved in one pass (never
rescanned). An undeclared input or a path outside the producer's schema is a load error; a failed producer fails the
node (`config`). Values render as canonical text: strings as is, numbers and booleans as JSON, null as empty, objects
and arrays as compact JSON with sorted keys. In argv a reference fills a whole element, never `command[0]` nor a `-c`
script, else a load error; a script gets values only as positional parameters: `[sh, -c, 'gh pr view "$1"', sh,
$pr.output.url]`. The output is the command's stdout (≤ 512 KiB) or the agent's final message (≤ 1 MiB, as is a
`stdin`). With `output_format` (JSON Schema 2020-12, via core's `OutputValidator`) it must be one matching JSON value,
else `output_contract`. Outputs, rendered text and answers stay in the run's record (`.agent-runs/`), never in events.

A run is `running` or `paused`, then ends `done`, `failed` (a node failed after its retries) or `cancelled` (`halt`,
cancel, abandon). The outcome is apart: `outcome_field`'s JSON value (boolean or string) on the completed `returns`
node; issue-to-pr returns `report`, whose `delivery` is `delivered`, `no_changes`, `blocked` or `failed`. A run copies
its document, prompts and scripts at start; `hub workflow resume` continues a paused or failed run on that snapshot.
`retry: {max_attempts, delay, on_error}`: 0–5 retries after the first attempt, the delay (default `2s`) doubled each
time, `on_error` `transient` (default) or `all`; without `retry`, a node gets one `transient` retry. A `failure_kind` is
set where the failure happens, never from message text; a shell or script exit is `exec_failed` or `timeout`.
`transient` (network), `timeout`, `rate_limited` and `overloaded` retry with backoff; `exec_failed`, `output_contract`
(never retried on shell or script), `max_iterations` and `unknown` retry only with `on_error: all`; `config` (the setup
must change), `auth`, `cancelled` and `fatal` (a provider refusal) never retry. Events go through `IngestEvents`: source
`executor`, session `run:<run id>`, `workflow` the name, `step` the node id as recorded (`a__b`). `attempt` is per node
and keeps counting across retries, iterations and resumes, so `source_id` `<run>:<step>:<attempt>:<type>` never repeats.
Each attempt is one `step.start` (`attempt`, `revision`, `content_hash`) and one `step.end` (`attempt`, `status` `ok`,
`failed` or `skipped`, `failure_kind`, `skip_cause`); a skipped node emits only `step.end`. `reason` holds only engine
metadata (a kind, an origin node id): a halt's rendered `reason` stays in the record. `approval` and `wait` add
`gate.request` (`gate_id` `<run>:<step>:<attempt>`, `kind` `human_gate` if a person answers, else `wait`); one decision
per `gate_id` comes back as a `control_plane` `gate.result` (`result`, `approver`, `where`), a second is refused, and
so is one whose approver names no person (empty or `unknown`, case and blanks ignored; `hub workflow approve|reject|respond`
refuses when no account name is known, never falling back to `unknown`): nothing is recorded and the run stays paused.
`run.end` (`source_id` `<run>:run:<n>:end`, n from 0; the fold takes the highest n) carries `status`, `outcome`,
`reason`, `revision` and `content_hash` (`sha256:` of the snapshot).

### Dry run and fixtures

```yaml
workflow: issue-to-pr
inputs: {issue: AGH-1, repo: agent-hub}
stubs:   # node id (namespaced for includes) → a stub, or a list for successive attempts or iterations
  implement: [{output: {done: false}}, {output: {done: true}}]
  verify: {fail: exec_failed}
  report: {output: {delivery: failed}}
expect: {status: failed, outcome: failed}
failed: [verify]                                  # exactly the nodes that failed
reached: [implement, verify, report]              # exactly the nodes that ran
```

`hub workflow test [name]...` runs a pack's `fixtures/*.yaml` in memory: no child, network, tracker write or event. A
stub is `{output: <value>}` (fitting `output_format`), `{fail: <kind>}`, `{decision, text, approver}`, `{text}`,
`{choice}` or `{}` (waits); a loop iteration may add `until_exit`; an `expect`, one per poll. A reachable node with no stub, or a list
that runs out, fails the test, but an approval or wait with none pauses the run (`expect.status: paused`).

## Invariants

- No tokens on orchestration: only `agent` and `loop` nodes reach a model. Deterministic: the same document, inputs and
  node results give the same path and end. A run pins `revision` and `content_hash`; edits never change it.
- **Admission rule:** the document coordinates, scripts compute, agents judge. A new key or type must be seen by the
  engine to steer or record a run, be data with a fixed meaning, and add oversight a script step cannot.
- **Five smells:** expression creep (the whole `when:` grammar), composition metastasis (load-time includes, depth 3),
  workaround pressure (audit for copied blocks), schema width (tuning stays in agents), implicit magic (default retry).

## Decisions

- [ADR 0032](../adr/0032-workflow-engine.md) (format, engine), [ADR 0030](../adr/0030-run-outcomes-in-the-tracker.md) (outcomes, tracker writes), [ADR 0019](../adr/0019-metadata-only-events-and-redaction.md) (metadata-only events), [ADR 0041](../adr/0041-scenarios-actions-and-enforced-access.md) (`environment`, `effect`).

## Open questions

- UI edits beside git; the `content_hash` framing; the reference regex.
