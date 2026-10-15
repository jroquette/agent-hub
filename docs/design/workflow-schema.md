# Workflow schema: workflows as data

## Purpose

The contract of agent-hub's workflow format and engine (Phase 4, [SPEC](../SPEC.md) direction 1): a graph of typed
nodes run by `hub workflow run|test` and `hub run`. The reasons for this design are in
[ADR 0032](../adr/0032-workflow-engine.md), superseding [ADR 0027](../adr/0027-workflow-format-and-minimum-engine.md).

## Contract

### Document and pack

A pack is a folder `workflows/<pack>/` with `<workflow>.yaml` files and optional `prompts/`, `scripts/` and `fixtures/`.
Discovery reads the hub's `workflows/`, then the built-ins; a hub workflow overrides a built-in of the same `name`. A
file is YAML through a strict loader (duplicate keys, anchors, aliases, tags and multiple documents refused; 256 KiB
cap) or JSON, then a frozen Pydantic model that forbids unknown keys. A load error names the file, line and key.

| Key | Type | Meaning |
|---|---|---|
| `version` | `1` | format version; the engine refuses one it does not know |
| `name`, `description` | kebab-case file stem; optional string | unique among the workflows discovered; one line for people |
| `revision` | integer ≥ 1 | bumped by the author on each change |
| `inputs` | map `^[a-z][a-z0-9_]*$` → `{type, required, default, description}` | `type`: `string` (default), `integer`, `number`, `boolean`; `required` excludes `default` |
| `returns` | node id, optional | the node whose output is the workflow's (and an include's) output |
| `outcome_field` | string, optional | a `required` property of `returns`' `output_format`, `boolean` or a `string` with `enum` |
| `nodes` | list, at least one | ids `^[a-z][a-z0-9_-]*$`, unique, never containing `__` |

### Nodes

Every node has `id`, `type` and optional `description`, `depends_on` (ids), `trigger_rule` and `when`. Executable
nodes (`agent`, `shell`, `script`, `loop`) also take `retry`, `always_run` (re-run on resume), `timeout`,
`output_format` and `mutates_checkout: false` (git status compared before and after; a change fails the node). A
duration is `^[1-9][0-9]*(s|m|h|d)$`. A key outside the node's row is a load error.

| `type` | Keys | What happens |
|---|---|---|
| `agent` | `prompt` or `prompt_file` (one), `with`, `model`, `limits`, `context`, `cwd` | one `claude -p` session, with the hub's settings and plugin |
| `shell` | `command` (argv list), `cwd`, `env` | runs the program, never through a shell; exit 0 passes |
| `script` | `runtime` (`sh` or `python`), `script`, `args`, `cwd`, `env` | `sh <file>` or `uv run <file>`; exit 0 passes |
| `loop` | the `agent` keys, `max_iterations`, `until`, `until_field`, `until_bash`, `fresh_context` | repeats one agent turn until done |
| `loop_group` | `nodes`, `max_iterations`, `until_bash`, `until_when` | repeats a body sub-graph until done |
| `approval` | `message`, `decisions`, `capture_response` | pauses the run for a human decision |
| `wait` | one of `duration`, `until`, `attention` (with `options`) | pauses the run until its condition holds |
| `halt` | `reason` | ends the run `cancelled`; nodes not yet run never run |
| `include` | `include` (a workflow name), `with` | replaced at load by that workflow's nodes |

- `prompt_file` and `script` are paths inside the pack's `prompts/` and `scripts/` (no `..`, not absolute). `with` maps
  names to values or `{from: <output ref>, if_skipped: <value>}`, read in a prompt as `$WITH.<name>`. `model` is a
  `hub.json` → `models.tiers` tier (default `medium`); `limits` is `{max_turns, max_cost_usd}` (default 40 and 3.0);
  `context` is `fresh` (default) or `{resume: <upstream agent node id>}`. A `cwd` (an agent's may be a reference) stays
  in the hub or a repo, else `config`; in a repo an agent runs as `hub run`'s session (hub and other repos attached).
- No child gets `LINEAR_API_KEY`. Agents run with `session_env`, other commands with `untrusted_env`; `env` adds no
  token. A `hub step` node (`command[0:2]` is `[hub, step]`) runs the engine's own hub with `child_env`, refuses `env`
  and a referenced `cwd`, and narrows per call (`push_env` only for fetch, push, gh). Tracker writes (ADR 0030) are the
  parent's, from `run.end`'s outcome. `hub run --live` is `issue-to-pr` (a hub's own first), its parent v0.14's `hub run`.
- `loop`: `max_iterations` (1–50) and at least one channel: `until` (text the final line equals), `until_field` (a
  `required` boolean of its `output_format`), `until_bash` (argv; exit 0 is done). `fresh_context: false` (default)
  resumes the previous iteration's session. The output is the last iteration's; past the cap it fails `max_iterations`.
- `loop_group`: body ids are recorded as `<group>__<id>`; `until_when` (the `when:` grammar) reads this iteration's
  body outputs, `$LOOP_PREV.<id>.output[.path]` the previous one (empty at first). The output maps body id → output.
- `approval`: `decisions` lists `{id, label}` (kebab-case; default `approve`, `reject`); the output is `{decision}`,
  plus `text` with `capture_response: true`. Rework is a `loop_group` whose `until_when` reads the decision.
- `wait`: `duration` (≤ 7d), `until` (ISO-8601 with offset, or a whole reference) or `attention` (a message answered
  with text, or an option id given `options`); output `{at}`, `{text}` or `{choice, text}`; an early resume re-pauses.
- `include` takes only `id`, `description`, `depends_on`, `when`, `trigger_rule`, `include`, `with`. `with` fills the
  included `inputs` (checked as at run start) and replaces `$INPUTS.<name>` there. Nodes, and references to them,
  become `<include id>__<id>`; roots inherit the include's graph keys; dependants wait for the primary sink (`returns`,
  else the single sink), read as `$<include id>.output`. Depth ≤ 3, no cycles; planning checks run after expansion.

### Running: joins, conditions, outputs, status, retry and events

Kahn layers over `depends_on`, in declaration order inside a layer. A cycle, an unknown id, a reference to a node not
upstream, or a bad `returns` or `outcome_field` is a load error. Layers run in order, in v1 one node at a time; a
failure does not stop later layers. A node first checks its `trigger_rule` against its dependencies: `all_success`
(default: every one completed), `one_success` (at least one), `none_failed_min_one_success` (none failed, at least one
completed) or `all_done` (every one ended). Then `when:`: `atom (('&&' | '||') atom)*`, `&&` binding tighter, no
parentheses or negation; an atom is `<ref> <op> <literal>` (op `==`, `!=`, `<`, `>`, `<=`, `>=`; literal `'text'`, a
number, `true`, `false`). A numeric literal compares numerically (a non-numeric value is a parse failure); other
literals compare canonical text with `==`, `!=`. A skipped producer reads as empty text; a failed one fails the node.
A node that does not run is skipped with a `skip_cause`: `upstream_failed` or `upstream_skipped` (`reason` names the
origin node, carried down the chain), `condition`, `condition_parse_error`, or `prior_success` (reused on resume).

References are `$INPUTS.<name>`, `$<node>.output`, `$<node>.output.<path>` (dot segments, `.0` for an array item; a
path needs the producer's `output_format`), `$LOOP_PREV…` and `$WITH.<name>`, in prompts, `command`, `args`, `cwd`,
`env`, `with`, `until_bash`, `wait.until`, `message` and `reason`, resolved in one pass (never rescanned). An
undeclared input or a path outside the producer's schema is a load error; a failed producer fails the node (`config`).
Values render as canonical text: strings as is, numbers and booleans as JSON, null as empty, objects and arrays as
compact JSON with sorted keys. In argv a reference fills a whole element, never `command[0]` nor a `-c` script, else a
load error; a script gets values only as positional parameters: `[sh, -c, 'gh pr view "$1"', sh, $pr.output.url]`. The
output is the agent's final message or the command's stdout (≤ 512 KiB). With `output_format` (JSON Schema 2020-12,
checked by the core port `OutputValidator`) it must be one matching JSON value, else `output_contract`. Outputs,
rendered text and human answers live in the run's record under `.agent-runs/`, never in events.

A run is `running` or `paused`, then ends `done`, `failed` (a node failed after its retries) or `cancelled` (`halt`,
cancel, abandon). The outcome is apart: `outcome_field`'s JSON value (boolean or string) on the completed `returns`
node; issue-to-pr returns `report`, whose `delivery` is `delivered`, `no_changes`, `blocked` or `failed`. A run copies
its document, prompts and scripts at start; `hub workflow resume` continues a paused or failed run on that snapshot.
`retry: {max_attempts, delay, on_error}`: 0–5 retries after the first attempt, the delay (default `2s`) doubled each
time, `on_error` `transient` (default) or `all`; without `retry`, a node gets one `transient` retry. A `failure_kind`
is set where the failure happens, never from message text; a shell or script exit is `exec_failed` or `timeout`.
`transient` (network), `timeout`, `rate_limited` and `overloaded` retry with backoff; `exec_failed`, `output_contract`
(never retried on shell or script), `max_iterations` and `unknown` retry only with `on_error: all`; `config` (the setup
must change), `auth`, `cancelled` and `fatal` (a provider refusal) never retry.
Events go through `IngestEvents`: source `executor`, session `run:<run id>`, `workflow` the name, `step` the node id as
recorded (`a__b`). `attempt` is per node and keeps counting across retries, iterations and resumes, so `source_id`
`<run>:<step>:<attempt>:<type>` never repeats. Each attempt is one `step.start` (`attempt`, `revision`, `content_hash`)
and one `step.end` (`attempt`, `status` `ok`, `failed` or `skipped`, `failure_kind`, `skip_cause`); a skipped node emits
only `step.end`. `reason` holds only engine metadata (a kind, an origin node id): a halt's rendered `reason` stays in
the record. `approval` and `wait` add `gate.request` (`gate_id` `<run>:<step>:<attempt>`, `kind` `approval` or `wait`);
one decision per `gate_id` comes back as a `control_plane` `gate.result` (`result`, `approver`, `where`), and a second
is refused. `run.end` (`source_id` `<run>:run:<n>:end`, n counting the run's ends from 0; the fold takes the highest n)
carries `status`, `outcome`, `reason`, `revision` and `content_hash` (`sha256:` over the run's snapshot).

### Dry run and fixtures

`hub workflow test [name]` runs each `fixtures/*.yaml` of a pack in memory: no child, network, tracker write or event.

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

A stub is `{output: <value>}` (checked against `output_format`), `{fail: <kind>}`, `{decision, text}`, `{text}`,
`{choice}` or `{}` (waits); a loop iteration may add `until_exit`. A reachable node with no stub, or a list that runs
out, fails the test, except an approval or wait with no stub: it pauses the run (`expect.status: paused`).

## Invariants

- No tokens on orchestration: only `agent` and `loop` nodes reach a model. Deterministic: the same document, inputs and
  node results give the same path and end. A run pins `revision` and `content_hash`; edits never change it.
- **Admission rule:** the document coordinates, scripts compute, agents judge. A new key or type must be seen by the
  engine to steer or record a run, be data with a fixed meaning, and add oversight a script step cannot.
- **Five smells:** expression creep (the whole `when:` grammar), composition metastasis (load-time includes, depth 3),
  workaround pressure (audit for copied blocks), schema width (tuning stays in agents), implicit magic (default retry).

## Decisions

- [ADR 0032](../adr/0032-workflow-engine.md) (format, engine), [ADR 0030](../adr/0030-run-outcomes-in-the-tracker.md)
  (outcomes, tracker writes), [ADR 0019](../adr/0019-metadata-only-events-and-redaction.md) (metadata-only events).

## Open questions

- UI edits beside git; concurrent layers (`mutates_checkout`); the `content_hash` framing; the reference regex.
