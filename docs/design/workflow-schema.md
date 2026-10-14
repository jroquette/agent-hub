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
| `agent` | `prompt` or `prompt_file` (one), `with`, `model`, `limits`, `context` | one `claude -p` session, with the hub's settings and plugin |
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
  `context` is `fresh` (default) or `{resume: <upstream agent node id>}`. Environments are today's: an agent gets
  `session_env`, a command starting `hub step` `child_env`, any other `untrusted_env`; `env` never adds a token.
- `loop`: `max_iterations` (1–50) and at least one channel: `until` (text the final line equals), `until_field` (a
  `required` boolean of its `output_format`), `until_bash` (argv; exit 0 is done). `fresh_context: false` (default)
  resumes the previous iteration's session. The output is the last iteration's; past the cap it fails.
- `loop_group`: body ids are recorded as `<group>__<id>`; `until_when` (the `when:` grammar) reads this iteration's
  body outputs, `$LOOP_PREV.<id>.output[.path]` the previous one (empty at first). The output maps body id → output.
- `approval`: `decisions` lists `{id, label}` (kebab-case; default `approve`, `reject`); the output is `{decision}`,
  plus `text` with `capture_response: true`. Rework is a `loop_group` whose `until_when` reads the decision.
- `wait`: `duration` (≤ 7d), `until` (ISO-8601 with offset, or a whole reference) or `attention` (a message answered
  with text, or an option id given `options`); output `{at}`, `{text}` or `{choice, text}`; an early resume re-pauses.
- `include` takes only `id`, `description`, `depends_on`, `when`, `trigger_rule`, `include`, `with`. `with` fills the
  included `inputs` (checked as at run start), replacing `$INPUTS.<name>` there at load. Nodes become
  `<include id>__<id>`; roots inherit the include's `depends_on`, `when` and `trigger_rule`; dependants wait for the
  primary sink (the included `returns`, else the single sink), read as `$<include id>.output`. Depth ≤ 3, no cycles.

### Planning, joins, conditions and outputs

Kahn layers over `depends_on`, in declaration order inside a layer. A cycle, an unknown id, a reference to a node not
upstream, or a bad `returns` or `outcome_field` is a load error. Layers run in order, and in v1 their nodes one at a
time; a failure does not stop later layers. A node first checks its `trigger_rule` against its dependencies:
`all_success` (default: every one completed), `one_success` (at least one), `none_failed_min_one_success`, or
`all_done` (every one ended, whatever its state). Then `when:` is evaluated: `atom (('&&' | '||') atom)*`, `&&`
binding tighter, no parentheses or negation. An atom is `<ref> <op> <literal>`: op `==`, `!=`, `<`, `>`, `<=`, `>=`;
literal `'text'`, a number, `true` or `false`. `==` and `!=` compare canonical text; ordering needs a numeric literal
and value, else the atom is a parse failure. A skipped producer reads as empty text; a failed one fails the node. A
node that does not run is skipped with a `skip_cause`: `upstream_failed` or `upstream_skipped` (`reason` names the
origin node, carried down the chain), `condition`, `condition_parse_error`, or `prior_success` (reused on resume).

References are `$INPUTS.<name>`, `$<node>.output`, `$<node>.output.<path>` (dot segments, `.0` for an array item),
`$LOOP_PREV…` and `$WITH.<name>`. They may appear in prompts, `command`, `args`, `cwd`, `env`, `with`, `until_bash`,
`wait.until`, `message` and `reason`, resolved in one pass (inserted text is never rescanned). An undeclared input, or
a path the producer's `output_format` lacks, is a load error; a failed producer is a runtime `config` failure. Values
render as canonical text: strings as is, numbers and booleans as JSON, null as empty, objects and arrays as compact
JSON with sorted keys. In argv a reference fills a whole element, except in the script of `[sh|bash, -c, <script>]`,
where it is inserted shell-quoted. A node's output is the agent's final message or the command's stdout (≤ 512 KiB).
With `output_format` (JSON Schema 2020-12, checked by the core port `OutputValidator`) it must be one JSON value
matching it, else `output_contract`. Outputs live in the run's record under `.agent-runs/`, never in events.

### Status, outcome, retry, failure kinds and events

A run is `running` or `paused`, then ends `done`, `failed` (a node failed after its retries) or `cancelled` (`halt`,
cancel, abandon). The outcome is apart: `outcome_field`'s value on the completed `returns` node (issue-to-pr returns
`report`, whose `delivery` is `delivered`, `no_changes`, `blocked` or `failed`). `hub workflow resume` continues a
paused or failed run on its pinned document, and refuses one whose content hash moved.

`retry: {max_attempts, delay, on_error}`: 0–5 retries after the first attempt, the delay (default `2s`) doubled each
time, `on_error` `transient` (default) or `all`. Without `retry`, a node gets one `transient` retry. A `failure_kind`
is set where the failure happens (exit status, exception type, validator result), never from message text.
`transient` (network), `timeout`, `rate_limited` and `overloaded` retry with backoff; `exec_failed` (non-zero exit),
`output_contract` (never for shell or script), `max_iterations` and `unknown` only with `on_error: all`; `config`
(the setup must change), `auth`, `cancelled` and `fatal` (a provider refusal) never.

Events go through `IngestEvents`: source `executor`, session `run:<run id>`, `workflow` the name, `step` the node
id as recorded (`a__b`), `source_id` `<run>:<step>:<attempt>:<type>`. Each attempt (and loop-body run) of a node is
one `step.start` (with `revision`, `content_hash`) and one `step.end` (`status` `ok`, `failed` or `skipped`;
`failure_kind`, `skip_cause`, `reason`). `approval` and `wait` add `gate.request` (`gate_id` `<run>:<step>:<attempt>`,
`kind` `approval` or `wait`) and `gate.result` (`result` the decision, `approver`, `where`). `run.end` carries
`status`, `outcome`, `reason`, `revision` and `content_hash` (`sha256:` over the expanded document's canonical JSON and
the bytes of every prompt and script it reads).

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

A stub is `{output: <value>}` (checked against `output_format`), `{fail: <kind>}`, `{decision, text}` (approval),
`{text}` or `{choice}` (attention wait) or `{}` (other wait); a loop iteration may add `until_exit` for `until_bash`. A
reachable node with no stub, or a stub list that runs out, fails the test; an approval or wait without one pauses.

## Invariants

- Orchestration spends no tokens: only `agent` and `loop` nodes reach a model, each with its own prompt and `with`.
- Deterministic: the same document, inputs and node results give the same path and end. A run pins its `revision` and
  `content_hash`; editing a file never changes a running or resumed run.
- **Admission rule:** the document coordinates, scripts compute, agents judge. A new key or type must be seen by the
  engine to steer or record a run, be data with a fixed meaning, and add oversight a script step cannot.
- **Five smells:** expression creep (the `when:` grammar, whole); composition metastasis (includes at load, depth 3);
  workaround pressure (audit hubs for copied blocks); schema width (provider tuning stays in agent definitions);
  implicit magic (only the default `transient` retry, seen in events).

## Decisions

- [ADR 0032](../adr/0032-workflow-engine.md) (format, engine); [ADR 0030](../adr/0030-run-outcomes-in-the-tracker.md)
  (issue-to-pr outcomes); [ADR 0028](../adr/0028-agent-outputs-as-validated-json.md) (`output_format` schemas);
  [ADR 0019](../adr/0019-metadata-only-events-and-redaction.md) (metadata-only events).

## Open questions

- How a UI edit is stored and versioned beside git; concurrent layers with `mutates_checkout` arrive with composition.
