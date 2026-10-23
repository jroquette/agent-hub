# Scenarios: actions, scenarios and the access policy

## Purpose

How a project drives its own system through the workflow engine: **actions** (scripts with a declared effect),
**scenarios** (workflow documents of `kind: scenario`), the access policy checked before each action, credentials only
an action gets, and the two run modes. Why: [ADR 0041](../adr/0041-scenarios-actions-and-enforced-access.md). Format:
[workflow-schema.md](workflow-schema.md). Environments and `access`: [environments.md](environments.md).

## Contract

All optional and project-owned; a hub without `scenarios/`, `actions/` and `environments` behaves as before. Actions are
`actions/<pack>/<name>.yaml`, scripts under `actions/<pack>/scripts/` (by real path, no symlink); scenarios are
`scenarios/<pack>/<name>.yaml` with `kind: scenario` (each root refuses the other kind). Both load as workflows do
(strict YAML, 256 KiB, unknown keys refused, errors name file, line and key), ≤ 200 files per root. `hub init` writes
one example, each file only where absent: the read action `actions/demo/demo-get-status.yaml` (a Python script that
GETs one path of a `service` input's endpoint; plan mode prints the URL) and the scenario `demo-service-up` (an `expect`
until `/health` answers 200, then one `action`). They are the project's files: `hub sync` never adds them, `hub.lock`
does not list them, and the init report does not count them.

### Kind and node keys

- `kind`: `workflow` (default: documents load as before) or `scenario`. A scenario holds only `action`, `expect`,
  `approval`, `wait`, `loop_group` and `include` nodes; any other type (an included one too) fails the load, naming it.
- `action` node: the common keys, `action` (`<name>` in its pack, or `<pack>/<name>`), `with`, `capture`, `retry`,
  `timeout`; one JSON value out. `expect`: the same, plus `every`, `timeout` (both required), `until_when`.
- `capture: {<name>: <ref>}` gives `$CTX.<name>` to downstream nodes; a name not captured upstream, or by two nodes, is
  a load error, as is `$CTX` in a capture. `$self.output[.path]` (own output) reads only in `until_when` and `capture`.
- A process workflow may declare `environment: <name>` (`--env` overrides it): `shell`, `script` take `effect` (default
  `write`), `until_bash` is a `read`, an `action` needs one. Ids ending `__ask` or `__investigation`, `self`, are reserved.

### Tree format (version 2)

A scenario may be written as ordered blocks ([ADR 0049](../adr/0049-scenario-blocks-and-run-control.md)):
`version: 2` and `stages:` in place of `nodes:` (a version-2 document with `nodes`, `depends_on` or `trigger_rule` fails
the load; version 1 loads as before, with doctor's `scenarios.graph_format` warning).

- A stage is `name` (unique, case and blanks folded), optional `description`, and `steps`. Position is order: a block
  runs after the one before it, a stage after the stage before it.
- A step is one of `do: <action>` (an `action` node), `wait_until: <action>` with `until`, `every`, `timeout` (an
  `expect` node), `you: <message>` with optional `decisions`, `capture_response` (an `approval`), `wait:` with
  `duration`, `until` or `attention` (a `wait`) and `include: <scenario>` with `with` (an `include`). Common optional
  keys: `id`, `description`, `with`, `capture`, `retry`, `timeout` (on `do`).
- A container is `repeat: {max, until, steps}` (a `loop_group`; none inside another), `if: <cond>` with `then` and
  optional `else`, or `together: [[…], […]]` (two or more paths; the next block waits for every path).
- Conditions use the `when:` grammar. An else is the complement of its If's condition (each operator's opposite, `&&`
  and `||` swapped, expanded to or-of-ands); more than 8 atoms, or more than 64 terms after expansion, fails the load.
- A block without `id` gets `<stage slug>-<n>`, nested `<stage slug>-<n>-<m>`; an `id` follows the node id rules.
- Translation: core turns the tree into nodes at load, before includes are expanded: a block's entry nodes depend on
  the previous block's exit nodes; an If puts its condition (or the complement) on each branch's first node and the
  block after it takes `trigger_rule: none_failed_min_one_success`; a Together's paths start on the previous block and
  the next block depends on each path's last. It also keeps a **block map** (address such as `2.3` or `2.3.then.1` →
  node ids, entry nodes, key path). A problem on a generated node is reported on the tree's key path.
- One canonical YAML form, written by `generator`'s scenario writer, shared by hub web's Save and `hub scenario
  migrate`. Save writes nothing when the canonical bytes equal the file's, and keeps `revision` then.
- `hub scenario migrate [NAME…] [--check]` writes a graph scenario as a tree (one stage named after the scenario, each
  id kept as `id:` where it differs from the derived one) when the graph is series-parallel with only `all_success`
  joins, `when` branches and the joins an If makes; otherwise nothing is written and each node it cannot map is named
  with why (exit 1). The new file translates to the same nodes, edges and conditions.

### Debugging

A scenario run may pause before a block: by a **breakpoint**, or by **Step** ([ADR
0049](../adr/0049-scenario-blocks-and-run-control.md)). It is not a gate and Approvals does not list it.

- Breakpoints are block addresses of the run's pinned tree, kept in the run folder (`breakpoints.json`, written whole),
  set by `hub scenario run --break ADDR…`, `hub scenario break RUN ADDR… [--off]` (adds or removes), `hub scenario break RUN --set [ADDR…]` (replaces the set; none
  clears it) or hub web, read before each node:
  one set while the run runs takes effect at the next block. They are never in the document.
- Before a block means before its first node and before its `<step>__ask` gate; for a stage, before its first block;
  a Repeat, before the group (a body block's breakpoint pauses in every iteration); an If, before its condition is
  read; a Together, before any path. The pause answers no gate.
- `hub scenario step RUN` runs exactly the next leaf block (Do, Wait until, You, Wait, and an Include as one block) in declaration order and
  pauses before the one after it, entering containers; the run stays in step mode until `hub scenario continue RUN`,
  which runs to the next breakpoint or the end. A gate met meanwhile pauses as before; once answered, a stepping run
  pauses before the next block. Both are resumes, recorded with who sent them.
- With a breakpoint or step mode on, a layer holding a block to pause at runs one node at a time in declaration
  order; without either, the engine runs as before.
- A paused run shows its inputs (the effective ones, environment values included), every capture, and each finished block's rendered inputs, status and last output
  (a Wait until's last poll and its count), from its record.
- Breakpoints, Step, Continue and a start with breakpoints are refused, recording nothing, on a `production: true`
  environment; runs without them keep the policy above there.
- Nothing is rewound: no captured value is edited, no finished block re-run or skipped.

### Actions and the script contract

An action declares `version`, `name` (its file stem), `description`, `effect` (`read`, `write`, `destroy`), `runtime`
(`sh`, or `python` run by `uv run`), `script`, `timeout` (≤ 1 h, default 5 m), `inputs` and `output_format` (a JSON
Schema). An input is `string`, `integer`, `number`, `boolean` or `service`; a `service` value names a service in
`repos[].services`, resolved to its endpoint in the bound environment (none: `plan` fails naming both). The script reads
one JSON object on stdin, `{"mode": "plan" | "run", "inputs": {…}, "endpoint": {"<input>": {"url": …, "resource": …}}}`,
and prints one JSON value: in `run` mode the output matching `output_format` (else the step fails `output_contract`); in
`plan` mode `{"summary": "<one line>"}`, changing nothing, with no credential. An action is **committed** when its
document, script and its pack's other `scripts/` files (no other action's script, `__pycache__` or dot name) each match
the hub's `HEAD` (a local commit suffices); else it is a **draft**, listed but never run (outside a git checkout, all
are). A run pins each action's `content_hash` (`sha256:` over each file's path, length, bytes) and runs that snapshot.

**Run values.** A scenario input is a value of the run, set once when it starts. An action input a step leaves out of its
`with` takes the scenario input of the same name, at plan and at run time (`with_run_values`), included steps too; a
value the step gives always wins, and an input with neither takes the action's default. So a value every step needs (an
account, a stack name) is declared once as a scenario input, not repeated as `name: $INPUTS.name` in each step, and one
run cannot start in one account and end in another. The builder shows such an input as "from the run" and offers to
drop the repeats.

### Policy

`decide(effective access, production, effect, origin)` in core returns `allow`, `ask` or `deny`; the effective access is
`hub.json`'s tightened by `hub.local.json`, so a local file never loosens a decision:

| Environment | `read` | `write` | `destroy` |
|---|---|---|---|
| not declared | deny | deny | deny |
| `production: true`, any access | allow | deny | deny |
| access `read` | allow | deny | deny |
| access `ask` | allow | ask | ask |
| access `write` | allow | allow | ask |

Origin is `author` (a committed document), `human` (a person in a terminal) or `agent` (an investigation read or a
workaround); `agent` turns an `allow` of a write or destroy into `ask`. A draft action is `deny` (`draft action: commit
it to run`). A `deny` at plan time refuses the start. An `ask` is an `approval` node the planner inserts before the step
(`<step>__ask`), approved or rejected (reject cancels) in Approvals or with `hub workflow approve|reject`. Two
gate-needing steps that do not depend on each other are a plan error naming both. The same policy applies to the
`action`, `shell` and `script` nodes of a process workflow that declares `environment`.

### Credentials

- **Inputs from the environment:** a declared scenario input the request does not give takes the value of the same
  name in the environment's `values` ([environments.md § Values](environments.md)), typed as the input declares, before
  its declared default: given input > environment value > default. Core's `with_environment_values` holds the rule;
  the CLI's `plan` and `run` and hub web's plan and start call it before the defaults are filled, so the run record
  keeps the effective inputs. Values are never secrets: credentials stay in the `env_file` below.

- An environment's `credentials` (or an endpoint's, which wins when the action's endpoints declare exactly one set; two
  differing sets are a plan problem) may name `env_file`: a dotenv file relative to the workspace holding the hub and
  its repos (`demo-api/.env.staging`), ≤ 200 characters, no `..`, `~`, leading `/` or secret shape, in `hub.json` or
  `hub.local.json` (own environments), set by `hub env add|set --env-file`; AGENTS.md and the brief never show it.
- hub web may list the file's variable **names** (`GET /projects/{project}/env-file-keys?path=`), never a value: a
  regular file of at most 64 KiB held by the hub or a declared repo by real path and reached through no link, `NAME=`
  and `export NAME=` lines (a quoted value spanning lines is skipped), at most 200 names; it also says whether git
  ignores the file there.
- One loader, shared by `hub action run` and the engine's action executor, reads it when an action starts: in the hub
  or a declared repo by real path, reached through no link, a regular file, ≤ 64 KiB and 200 variables, `NAME=value`
  lines (`#` comments, optional `export `, quotes, no interpolation). It injects **every** variable, `AWS_PROFILE` from
  `aws_profile` and the `credentials.env` names from the developer's environment into that action's process only. A
  file missing, unreadable, too large, not regular, outside the hub and its repos, behind a link or not dotenv fails
  the action before its process starts: `environment <env>: env file <path> is <reason>`, a broken line by number,
  never a value. Plan mode never reads it. Injected values (≥ 4 characters) become `<credential NAME>` in its output.
- Declared `credentials.env` names and an `AWS_PROFILE` naming a declared profile are removed from every agent session
  (hub web's driven sessions included), shell, script and `until_bash` environment.
- The guard denies, in every session, a file tool on a declared env file (by real path: a symlink or `..` is caught),
  a `Grep` or `Glob` that can reach one, and a Bash command or WebFetch URL naming one (rule `env_file`, reason `env
  file: <tool> names the env file of <env>`). Doctor's `environments.env_file` warns when a declared file is missing,
  not ignored by the git checkout that holds it, outside the hub and every declared repo, or reached through a link.

### Plan and modes

`hub scenario plan <name> --env <env> [--input k=v]… [--json]` shows each step's action, args (run-time values as
`<$CTX.<name> from <node>>`), effect, service → endpoint, content hash, draft state and decision. It calls a script in
`plan` mode, with no credential, only when all its args are known (else `runs with values known at run time`), and
starts no run-mode process, agent, event or run; exit 1 on a `deny`. `hub scenario run` (same arguments, `--mode
interactive|regression`, interactive by default) refuses a plan problem or `deny` (exit 1, no scenario run),
pins its action files and gates, labels events `workflow: scenario:<name>`, and decides each action again as it runs.

- **Regression:** no agent, no token. A divergence (a failed action, an `expect` timeout, an output contract failure)
  fails the scenario run and prints `step <id>: <reason>`. Policy asks and `approval` nodes still pause it.
- **Interactive** (the default): a divergence of an `action` or `expect` step (not a `config` failure) pauses it at an
  investigation gate, `<step>__investigation` (`human_gate`, reason `investigation`), recorded instead of the run's end;
  independent steps run first; the CLI prints the screen's link. Past 10 investigations it fails as in regression.

### Investigation, answers and workarounds

Opening a paused run in hub web starts one session per gate (none if the hub or a declared repo is `/`, home or above), held by
a PreToolUse hook: reads only in the hub and its declared repos, never an env file, `Write` only under `actions/<pack>/`, Bash
only for `./hub action …` and `./hub scenario propose`; `hub action run --run <id>` needs an open investigation and runs only
`read` actions with its environment's env file. The agent records findings and options (a summary, `{action, with}` steps) with
`propose` (secret shapes redacted), each shown with its plan. The answer is `pick` (`--text <option id>`), `retry` or `stop`:
`hub workflow respond`, `decide` (hub web) or the Scenarios screen (Approvals sends the gate there). An option holding a `deny`,
a draft action or a plan changed since shown is refused, nothing recorded. A pick answers its steps' asks: `workaround.start`,
its actions (origin `agent`), `workaround.end`, then the diverged step as a new attempt; a failed or cut-short workaround (never
re-run) opens a new investigation. `retry` skips it; `stop` ends it `cancelled`, findings kept; nothing is rewound. `hub
scenario findings <run>` lists them; `--issue <id>` creates a tracker issue after a terminal `y` (MCP: `save_issue` only);
`--inbox <id>` writes a `brain/_inbox/` note (`provenance: agent-from-external`). A `finding-<id>.issue` marker shared with hub
web makes it once: a named issue or a running create refuses both; only a warned terminal retries a failed or unfinished one.

### Events and bounds

Metadata only ([ADR 0019](../adr/0019-metadata-only-events-and-redaction.md)), each with a `payload_keys` row:
`action.start`/`action.end` (`action`, `content_hash`, `environment`, `service`, `effect`, `origin`, `decision`,
`approver`, `status`, `failure_kind`), `policy.decision` (`action` or node, `environment`, `effect`, `origin`,
`decision`, `reason_kind`), `debug.pause` (`node`, `block`, `reason`), `debug.command` (`command`, `approver`),
`debug.breakpoints` (`count`), `expect.poll` (`poll`, `held`), `context.capture` (`name`), `finding` (`finding_id`,
`step`), `workaround.start`/`workaround.end` (`workaround_id`, `option`, `steps`, `status`); `gate.request` gains
`reason`. Args, outputs, captures, findings, chat stay in the run record. Bounds: `expect` `every` ≥ 5 s, `timeout` ≤ 24
h, ≤ 1000 polls (retries, resumes too); action stdout ≤ 512 KiB; plan mode ≤ 60 s; ≤ 64 `--input` values of ≤ 64 KiB; a
proposal ≤ 256 KiB, 20 findings, 5 options of ≤ 10 steps; ≤ 10 proposals per investigation; API record reads ≤ 8 MiB.

### Known limits

1. Agent nodes of a process workflow get a best-effort guard check (`environment_endpoint`); a hidden host passes.
2. The guard and the investigation hook are not a sandbox: a process outside the guarded tools can read an env file, and
   the hook judges the path it is given, not the links a recursive walk inside a root may follow.
3. A process that fakes a terminal bypasses `hub action run`'s terminal rule.
4. After a divergence, independent steps still run in that pass; a `loop_group` body step is not investigated.
5. Local only: cloud sessions have no `hub.local.json`, no env files and no credentials.
6. Policy gates (`<step>__ask`) of a process workflow run show in the run's steps but not in its graph.
7. Redaction replaces each injected value of 4 characters or more exactly as written; a shorter one, or an encoded or
   transformed form (base64 as in a Basic auth header, URL-encoded, escaped in stderr, split across strings), passes.
8. Investigation sessions run unheld with no link or run folder, or as a `resume_session_id`/`fork`; one per `hub web`.

## Invariants

- No document key and no flag turns an `ask` into an `allow`; a production write or destroy never runs.
- Credential values reach only the action's process; everything else holds names; output redaction is exact (limit 7).
- Agents run read actions only before a pick; a person picks every write. A run runs the action content it pinned.
  "Run" alone means a WorkflowRun; a scenario run is always qualified.

## Decisions

- [ADR 0049](../adr/0049-scenario-blocks-and-run-control.md): the tree format translated at load, the run-control
  port, breakpoints as run data, debugging off production only.
- [ADR 0041](../adr/0041-scenarios-actions-and-enforced-access.md): actions and scenarios on the engine, policy in
  core, env-file credentials, read-only investigation, no built-in action; partially supersedes ADR 0038 on `access`.

## Open questions

- Later deliveries: branching from a step, `observe` on `expect`, scenarios authored from a session, variations.
