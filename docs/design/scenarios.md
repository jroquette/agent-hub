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
one example action (`effect: read`) and scenario; `hub sync` never adds them and `hub.lock` does not list them.

### Kind and node keys

- `kind`: `workflow` (default: documents load as before) or `scenario`. A scenario holds only `action`, `expect`,
  `approval`, `wait`, `loop_group` and `include` nodes; any other type (an included one too) fails the load, naming it.
- `action` node: the common keys, `action` (`<name>` in its pack, or `<pack>/<name>`), `with`, `capture`, `retry`,
  `timeout`; one JSON value out. `expect`: the same, plus `every`, `timeout` (both required), `until_when`.
- `capture: {<name>: <ref>}` gives `$CTX.<name>` to downstream nodes; a name not captured upstream, or by two nodes, is
  a load error, as is `$CTX` in a capture. `$self.output[.path]` (own output) reads only in `until_when` and `capture`.
- A process workflow may declare `environment: <name>` (`hub workflow run --env` overrides it); its `shell` and `script`
  nodes then take `effect` (default `write`). Ids ending `__ask` or `__investigation`, and `self`, are reserved.

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

- An environment's `credentials` (or an endpoint's, which wins when the action's endpoints declare exactly one set; two
  differing sets are a plan problem) may name `env_file`: a dotenv file relative to the workspace holding the hub and
  its repos (`demo-api/.env.staging`), ≤ 200 characters, no `..`, `~`, leading `/` or secret shape, in `hub.json` or
  `hub.local.json` (own environments), set by `hub env add|set --env-file`; AGENTS.md and the brief never show it.
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
  not ignored by the git checkout that holds it, or outside the hub and every declared repo.

### Plan and modes

`hub scenario plan <name> --env <env> [--input k=v]… [--json]` shows each step's action, args (run-time values as
`<$CTX.<name> from <node>>`), effect, service → endpoint, content hash, draft state and decision. It calls a script in
`plan` mode, with no credential, only when all its args are known (else `runs with values known at run time`), and
starts no run-mode process, agent, event or run; exit 1 on a `deny`. `hub scenario run` (same arguments, `--mode
interactive|regression`) plans first, refuses to start on a `deny` or an undeclared environment (exit 1, no scenario
run), and labels its events `workflow: scenario:<name>`.

- **Regression:** no agent, no token. A divergence (a failed action, an `expect` timeout, an output contract failure)
  fails the scenario run and prints `step <id>: <reason>`. Policy asks and `approval` nodes still pause it.
- **Interactive** (the default): a divergence of an `action` or `expect` step (not a `config` failure) pauses it at an
  investigation gate, `<step>__investigation` (`human_gate`, reason `investigation`), recorded instead of the run's end;
  steps that do not depend on it run first. The CLI prints the Scenarios screen link. After 10 investigations the next
  divergence fails the scenario run as in regression.

### Investigation, answers and workarounds

Opening the paused scenario run in hub web (`POST /scenario-runs/{id}/investigation`) starts one driven session per
gate, its tools held by a PreToolUse hook: `Read`, `Glob`, `Grep` except on a declared env file, `Write` only under
`actions/<pack>/` (draft actions), Bash only for `./hub action list|plan|run …` and `./hub scenario propose --run <id>`
and no shell metacharacter. `hub action run --run <id>` needs that run paused at an open investigation, uses its
environment and env file, records origin `agent`, and runs only `read` actions (a write exits 1 and records
`policy.decision` `deny`). The agent records findings and options (a summary and `{action, with}` steps each) with
`./hub scenario propose` (JSON on stdin, secret shapes redacted); each option is shown with its plan. The answer is
`pick` (with the option id), `retry` or `stop`: `hub workflow respond <run> --node <step>__investigation --choice …`,
`hub workflow decide` from hub web, or the Scenarios screen (Approvals sends the gate there). An option holding a
`deny` step or a draft action cannot be picked (the reason is shown). A pick answers its steps' asks; a step whose
plan changed since it was shown asks again. The option runs as `workaround.start`, its actions (origin `agent`),
`workaround.end`, then the diverged step again as a new attempt; `retry` skips the workaround; `stop` ends the scenario
run `cancelled`, findings kept. Nothing rewinds the system. `hub scenario findings <run> --issue <id>` creates a tracker
issue after a terminal `y`; `--inbox <id>` writes a `brain/_inbox/` note (`provenance: agent-from-external`).

### Events and bounds

Metadata only ([ADR 0019](../adr/0019-metadata-only-events-and-redaction.md)), each with a `payload_keys` row:
`action.start`/`action.end` (`action`, `content_hash`, `environment`, `service`, `effect`, `origin`, `decision`,
`approver`, `status`, `failure_kind`), `policy.decision` (`action` or node, `environment`, `effect`, `origin`,
`decision`, `reason_kind`), `expect.poll` (`poll` count, `held` bool), `context.capture` (`name`), `finding`
(`finding_id`, `step`), `workaround.start`/`workaround.end` (`workaround_id`, `option` id, `steps` count, `status`);
`gate.request` gains `reason`. Args, outputs, captures, findings, chat stay in the run record (`.agent-runs/`). Bounds:
`expect` `every` ≥ 5 s, `timeout` ≤ 24 h, ≤ 1000 polls (retries, resumes too); action stdout ≤ 512 KiB; plan mode ≤ 60 s;
≤ 64 `--input` values of ≤ 64 KiB; a proposal ≤ 256 KiB, 20 findings, 5 options of ≤ 10 steps; API record reads ≤ 8 MiB.

### Known limits

1. Agent nodes of a process workflow get a best-effort guard check (`environment_endpoint`); a hidden host passes.
2. The guard and the investigation hook are not a sandbox: a process outside the guarded tools can read an env file.
3. A process that fakes a terminal bypasses `hub action run`'s terminal rule.
4. After a divergence, steps that do not depend on it still run in that pass.
5. Local only: cloud sessions have no `hub.local.json`, no env files and no credentials.
6. Policy gates (`<step>__ask`) of a process workflow run show in the run's steps but not in its graph.
7. Credential values shorter than 4 characters are not redacted: they cannot be told apart from ordinary output.

## Invariants

- No document key and no flag turns an `ask` into an `allow`; a production write or destroy never runs.
- Credential values exist only in the action's process; configs, plans, records, events and the UI hold names.
- Agents run read actions only before a pick; a person picks every write. A run runs the action content it pinned.
  "Run" alone means a WorkflowRun; a scenario run is always qualified.

## Decisions

- [ADR 0041](../adr/0041-scenarios-actions-and-enforced-access.md): actions and scenarios on the engine, policy in
  core, env-file credentials, read-only investigation, no built-in action; partially supersedes ADR 0038 on `access`.

## Open questions

- Later deliveries: branching from a step, `observe` on `expect`, scenarios authored from a session, variations.
