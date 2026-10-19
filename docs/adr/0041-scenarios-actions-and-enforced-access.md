# 0041. Scenarios, actions and an engine-enforced access policy

- Status: proposed
- Date: 2026-10-19
- Deciders: José Henrique Roquette
- Partially supersedes: [ADR 0038](0038-declared-environments-and-blocked-words.md), for "`access` is not
  enforced by the guard: it is rendered as an instruction" — for actions and for the deterministic nodes of a workflow
  that declares an environment (0038 is not edited; its guard rules and its blocked words are unchanged)
- Extends: [ADR 0032](0032-workflow-engine.md) (workflow engine and format) with a document kind, two node types
  and four keys, each admitted below; [ADR 0019](0019-metadata-only-events-and-redaction.md) (metadata-only events)
  with eight event types that keep its rule

## Context and Problem Statement

Developers check their real system by hand: they send queue messages, poll tables, patch data, rerun jobs. Nothing is
written down, so the walk cannot be repeated, shared or audited. Agents reach those systems only through free tools
(`aws`, `psql`, `curl`), where the guard cannot tell a read from a write, so ADR 0038 kept `access` an instruction. No
run records which change ran where, with which effect, or who allowed it, and an agent session gets the developer's
credentials. How does a project drive its own system, step by step, through the workflow engine, so that every change
is declared, checked against the environment's access before it runs, and recorded?

## Considered Options

1. **Scenarios and actions on the existing engine.** A scenario is a workflow document of a new kind that may hold
   only `action`, `expect`, `approval`, `wait`, `loop_group` and `include` nodes. An action is a project-owned script
   with a declared effect, typed inputs and an output schema, in the hub's `actions/`. The engine decides each action
   with a fixed policy (environment, effect, origin) before it runs.
2. Built-in generic actions (`http-call`, `sql-query`) shipped by agent-hub, with infra clients in agent-hub.
3. A guard-side classifier of free commands (`psql`, `aws`, `curl`) into read and write.
4. A separate scenario engine and format, apart from ADR 0032.

## Decision Outcome

Chosen option: 1.

- **Document kind.** A workflow document takes `kind: workflow` (the default, so existing documents are unchanged) or
  `kind: scenario`. Scenarios live in the hub's `scenarios/<pack>/`; `workflows/` refuses them and `scenarios/`
  accepts nothing else. A scenario holding a `shell`, `script`, `agent`, `loop` or `halt` node is a load error.
- **Actions.** `actions/<pack>/<name>.yaml` declares `effect` (`read`, `write`, `destroy`), `runtime` (`sh`,
  `python`), `script` (under `actions/<pack>/scripts/`), `timeout` (≤ 1 h, default 5 m), typed `inputs` (`string`,
  `integer`, `number`, `boolean`, `service`) and `output_format` (JSON Schema). The script reads one JSON object on
  stdin (`mode` `plan` or `run`, `inputs`, `endpoint` per `service` input) and prints one JSON value: the output in
  `run` mode, `{"summary": …}` in `plan` mode, which changes nothing and gets no credential. An action is *committed*
  when its document and script equal the hub's `HEAD`; any other action is a draft and never runs. A run pins each
  action's `content_hash` and runs the copy in its snapshot.
- **Access policy.** `decide(effective access, production, effect, origin)` lives in core and returns `allow`, `ask`
  or `deny`: an undeclared environment denies; production denies `write` and `destroy`; access `read` allows only
  reads, `ask` asks for writes and destroys, `write` asks for destroys; origin `agent` turns an `allow` of a write or
  destroy into `ask`; a draft denies. The effective access is `hub.json`'s tightened by `hub.local.json` (ADR 0038),
  so a local file never loosens a decision. No document key and no CLI flag turns an `ask` into an `allow`. A `deny`
  at plan time refuses the start; an `ask` is an `approval` node the planner inserts before the step (`<id>__ask`),
  answered through the existing gate paths. The same policy applies to `action`, `shell` and `script` nodes of a
  process workflow that declares `environment` (`shell` and `script` take an optional `effect`, default `write`).
  Agent nodes there get `HUB_RUN_ENVIRONMENT`, and the guard asks when a command or URL names one of that
  environment's endpoints while its access is `read` or it is production: **best effort**, said so in the docs and UI.
- **Credentials.** An environment (or one of its endpoints, which wins) may name a dotenv file,
  `credentials.env_file`, a path relative to the workspace that holds the hub and its repos; `hub.json` and the
  developer's `hub.local.json` (for their own environments) accept it, `hub env add|set --env-file` writes it, and no
  rendered file or brief shows it. The action runner alone (`hub action run` and the engine's action executor, one
  loader) reads it at the moment an action starts, in memory, and injects all its variables, plus the environment's
  `AWS_PROFILE`, into that action's process only. This holds for authored steps and for the investigation's reads
  (`hub action run --run`), so nothing passes through an agent session. A missing or unusable file fails the action
  before its process starts, with a plain reason and no value. `credentials.env` (variable names taken from the
  developer's environment) stays accepted; the env file is the recommended form. Declared `credentials.env` names and
  an `AWS_PROFILE` naming a declared profile are removed from every agent session, shell, script and `until_bash`
  environment, hub web's driven sessions included. Every injected value of 4 characters or more is redacted from what
  the action prints (shorter values cannot be told apart from ordinary output).
- **Env files are out of the agents' reach.** The guard denies, in every session (process workflows included), any
  file tool on a declared env file (resolved by real path) and any Bash command or WebFetch URL naming one (rule
  `env_file`); the investigation session's own PreToolUse hook denies the same reads and allows Bash only for
  `hub action list|plan|run` and `hub scenario propose`. Doctor warns when a declared env file is missing or not
  ignored by the git checkout that holds it.
- **Modes.** `regression` starts no agent; a divergence (a failed action, an `expect` timeout, an output contract
  failure) fails the run. `interactive` pauses on a divergence: the scenario runner records an investigation gate
  instead of the run's end, and hub web starts one driven session limited to reading the hub, writing draft actions,
  `hub action list|plan|run` (read-only for it: the command refuses writes without a terminal or with `--run`) and
  `hub scenario propose`. The developer picks an option (its steps run as a recorded workaround, then the step is
  tried again as a new attempt), retries, or stops.
- **Events** (metadata only, ADR 0019): `action.start`, `action.end`, `policy.decision`, `expect.poll`,
  `context.capture`, `finding`, `workaround.start`, `workaround.end`, each with its `payload_keys` row; `gate.request`
  gains `reason`. Args, outputs, captured values, findings and the conversation stay in the run record.

### Why each new key passes ADR 0032's admission rule

The rule: the engine must see the key to steer or record a run, it must be data with a fixed meaning, and it must add
oversight a `script` step with today's keys cannot.

| Key | Steers or records | Fixed meaning | Oversight a script cannot add |
|---|---|---|---|
| `kind` | Chooses the allowed node types, the discovery root and the run's label | Two values | A script cannot keep agents and free commands out of a document |
| `action` (node) | The engine resolves the action, pins its hash, decides its policy and records `action.*` | A reference to a committed action file | A script's effect is unknown; an action's is declared and checked before it runs |
| `expect` (node) | The engine owns polling, its bounds and the timeout as a divergence | `every`, `timeout`, `until_when` (the `when:` grammar) | Each poll and its result is recorded; a script's private loop is invisible and unbounded |
| `capture` / `$CTX`, `$self` | The planner checks each name is captured once upstream; captures are recorded | A name bound to one reference | A value passed inside scripts cannot be shown in the plan or audited |
| `environment` (document) | The planner decides every deterministic node before the start | A declared environment name | A script cannot refuse its own start on production |
| `effect` (shell, script) | Input to the policy | `read`, `write`, `destroy` | Without it every command is a write; a declared read can run on a read-only environment |

### Consequences

- Good: a walk through the system becomes a reviewed document that runs the same way twice, with a plan shown before
  anything runs and a record of every change, its environment, effect, origin, decision and approver.
- Good: credentials live in one git-ignored file per environment, loaded only by the action runner; investigation
  reads use them without the agent session ever holding them.
- Good: `access` is enforced where the engine can see the effect (actions and declared deterministic nodes); a
  production write never runs.
- Good: agents diagnose with read-only means and propose; a person picks; nothing runs before the pick.
- Good: agent-hub ships no infra client; actions are the project's code, with their own dependencies.
- Bad: agent nodes are held only by the guard's best-effort endpoint check; a command that hides a host passes.
- Bad: a process that fakes a terminal can run a write through standalone `hub action run`.
- Bad: the guard and the session hook are not a sandbox: a process the developer's own shell starts, or any process
  outside the guarded tools, can still read an env file; the deny covers the agent's tools and the command text it
  shows.
- Bad: `hub.json` gains one more key (`credentials.env_file`) and doctor one more rule.
- Bad: retrying a diverged step acts on the system as it is; nothing rewinds state.
- Neutral: scenario runs are WorkflowRuns (events carry `workflow: scenario:<name>`); "run" alone still means a
  WorkflowRun and a scenario run is always qualified. Local only in v1.

## More Information

- Contract: [design/scenarios.md](../design/scenarios.md); keys in [design/workflow-schema.md](../design/workflow-schema.md);
  environments in [design/environments.md](../design/environments.md).
- AGH-350: spec, research and plan in the hub (`brain/features/scenarios/`).
- Option 2 was rejected because it needs infra libraries in agent-hub and a generic action would be a script with
  hidden effects; option 3 because a classifier over free commands is wrong often enough to give false safety (ADR
  0038's reason, still true); option 4 because gates, records, resume, events and the run views already exist.
