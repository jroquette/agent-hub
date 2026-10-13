# Workflow schema: workflows as data

## Purpose

A sketch for Phase 4: the declarative workflow document from [SPEC](../SPEC.md) direction 1, the minimum engine that
runs today's `hub run` from it, and the rule for growing the format; engine code, storage and UI come in Phase 4. The
reasons, and what we took from Archon, are in [ADR 0027](../adr/0027-workflow-format-and-minimum-engine.md) (proposed).

## Contract

### Document

YAML read by a strict loader (strings, lists and maps only, duplicate keys rejected) or the same structure in JSON,
then validated by a frozen Pydantic model in core that rejects unknown keys and exports a JSON Schema, as
[project-config.md](project-config.md) does for `hub.json`.

| Key | Type | Meaning |
|---|---|---|
| `version` | integer, `1` | format version; the engine refuses one it does not support |
| `name` | string, kebab-case | the workflow's name, unique in its hub |
| `revision` | integer | bumped by the author on each change; with the content hash, what a run used |
| `description` | string, optional | one line for people and the UI |
| `inputs` | map of name to `{type, required, description}` | what a run is started with (for example the issue) |
| `limits` | `{max_turns, max_cost_usd}` | caps for the whole run; exceeding one fails the step (class `quota`) |
| `steps` | list, at least one | run in order; each `id` unique |
| `delivers` | reference, optional | the output recorded as the run's delivery (`pr_url` for `hub run`) |
| `on_not_delivered` | list of `script` steps | run once when the run ends undelivered, failed or not; never retried |

### Steps

Every step has `id`, `type`, optional `inputs`, `outputs` and `limits` (within the run's). A reference is a whole
string, `${inputs.<name>}` or `${steps.<id>.outputs.<name>}`, resolved before the step starts; there are no other
expressions, and a reference to an output its step does not declare is a load error.

| `type` | Extra keys | What happens | Minimum engine |
|---|---|---|---|
| `agent` | `agent` (id `plugin:name`), `instruction` | one session gets only its instruction and inputs | yes |
| `script` | `command`, optional `cwd`, `env` | a deterministic command, no LLM; exit 0 passes | yes |
| `gate` | `command`, optional `cwd`, `env`, `on_fail` | an automatic check; `gate.request`, `gate.result` | yes |
| `human` | `approvers`, `prompt`, `on_fail` | waits for one of `approvers`; a rejection fails it | no: refused |

`command` is an argv list, never a shell string: a reference fills one whole element or reaches the command through
`env`. A gate's `on_fail` is `fail` (default) or `{goto: <earlier id>, max_attempts: N}`, the implement and verify loop;
each attempt is recorded with its number. An agent's model and tools belong to its own definition, not to steps.

### Outputs

`outputs` maps each name to a JSON Schema, inline or `{$ref: <file beside the workflow>}`; the producing step owns its
schema, and consumers never restate it. An `agent` step returns one JSON object in its final message; a `script` step
writes one to the file named by `HUB_STEP_OUTPUT`. The engine reads it up to a fixed size cap and validates it before
any later step reads it: a missing, oversized or invalid output fails the step with class `unknown`. The first shared
schemas are those of [AGH-139](https://linear.app/loki-trader/issue/AGH-139): the evaluator's verdict and the
reviewers' findings. The key `end` is reserved with a fixed schema, `{outcome: no_changes | blocked, reason}`: any step
may return it to end the run cleanly without delivering, with no later step run.

### Run result and failure classes

A run records two facts apart (AGH-140): its `status` on `run.end` (`done`, `failed`, `cancelled`) and its `outcome`:
`delivered` (every step passed; `delivers` names the value), `no_changes` or `blocked` (a step returned `end`; status
`done`), or `failed`. A failed step records `stage`, `reason` and a `failure_class`, decided from where it failed
(exit code, exception type, structured field), never from message text (AGH-179):

- `transient` (a timeout, a network error on fetch or push): the only class retried, once per step after a short
  wait, never past the run's `limits`; each attempt is recorded;
- `gate` (a check exited non-zero): never retried; a gate's `goto` re-runs earlier steps instead;
- `auth`, `quota`, `misconfigured` (the setup must change), `unknown`: never retried.

### Dry run and fixtures

`hub workflow test <name>` runs the engine in memory on each fixture in `workflows/<name>.fixtures/`: no session,
worktree, network call, tracker write or event. A fixture gives the inputs, each step's result (outputs, an exit code,
or a failure class; a list for successive attempts) and the expected step path, status and outcome. A reachable step
without a result fails the test. `make check` and a hub's CI run every workflow's fixtures from the engine's first
release; the base workflows ship with theirs. A sample fixture is in ADR 0027.

### Example: today's `hub run` as a document

The `hub tracker …`, `hub pr …` and `hub run commits` commands and the agent id are illustrative; the Phase 4 issue
fixes the real ones. PICKED is `pick`, WORKTREE `worktree`, IMPLEMENTING `implement` (and `commits`), VERIFYING
`verify`, PR_OPEN `pr`, REPORTED the run's end; FAILED is a failed step with its stage, then `on_not_delivered`.

```yaml
version: 1
name: issue-to-pr
revision: 1
inputs:
  issue: {type: string, required: true}
  repo: {type: string, required: true}
limits: {max_turns: 200, max_cost_usd: 10}
delivers: "${steps.pr.outputs.url}"
steps:
  - {id: pick, type: script, command: [hub, tracker, start, "${inputs.issue}"]}
  - id: worktree
    type: script
    command: [hub, worktree, "${inputs.issue}", --only, "${inputs.repo}"]
    outputs: {path: {type: string}}
  - id: implement                     # returns end: blocked when the session asks for a human
    type: agent
    agent: demo:implementer
    instruction: Implement the issue in the worktree and commit on its branch.
    inputs: {issue: "${inputs.issue}", path: "${steps.worktree.outputs.path}"}
    outputs: {summary: {type: string}}
  - {id: commits, type: script, command: [hub, run, commits], cwd: "${steps.worktree.outputs.path}"}
  - id: verify
    type: gate
    command: [make, check]
    cwd: "${steps.worktree.outputs.path}"
    on_fail: {goto: implement, max_attempts: 2}
  - {id: pr, type: script, command: [hub, pr, open, "${inputs.issue}"], outputs: {url: {type: string}}}
  - {id: report, type: script, command: [hub, tracker, review, "${inputs.issue}", --pr, "${steps.pr.outputs.url}"]}
on_not_delivered:
  - {id: mark, type: script, command: [hub, tracker, fail, "${inputs.issue}", --diagnosis-from-run]}
```

## Invariants

- Orchestration spends no tokens: only `agent` steps reach a model, and each sees its own instruction and inputs.
- Deterministic: the same document and the same step results always lead to the same next step.
- A run pins the `revision` and content hash it started with; editing the document never changes a running run.
- **Admission rule:** the document coordinates, scripts compute, agents judge. A new key or step type passes three
  questions: must the engine see it to steer or record a run; is it data with a fixed meaning, not evaluation; and
  could a `script` step with today's keys already do it (then it is admitted only for what it adds to oversight, what
  a run shows, resumes or audits, never for convenience)?
- **Five smells** and their levers: *expression creep*, no expressions beyond whole references (if conditions are
  ever needed, a specified language adopted whole in one version, never one operator at a time); *composition
  metastasis*, no includes or sub-runs until a workflow needs one, then resolved at load; *workaround pressure*, audit
  the hubs' workflows and run records for copied blocks, not the request queue; *schema width*, agent tuning stays in
  the agent definition and the keys fit on one screen; *implicit magic*, each implicit behaviour (today only the
  `transient` retry) is listed here, fail-safe and visible in the run's events.
- **Not copied** from Archon (reasons in ADR 0027): a wide node surface, breaking changes without a migration (here a
  format change bumps `version` and ships its migration), and telemetry on by default (nothing leaves the machine).

## Decisions

- [SPEC](../SPEC.md) direction 1: a declarative document, a Pydantic schema, a deterministic Python engine, the four
  step types, and a recorded version per execution.
- [ADR 0027](../adr/0027-workflow-format-and-minimum-engine.md) (proposed): this format and the minimum engine.
- [ADR 0010](../adr/0010-hub-json-config-contract.md): the same model-plus-exported-schema pattern as `hub.json`.
- AGH-139 (output schemas), AGH-140 (status apart from outcome), AGH-179 (failure classes).
- Informed by Archon (github.com/coleam00/archon, MIT; read at commit `a5834f2c`): its workflow-language constitution,
  node schema and authoring guide, paraphrased with no excerpt.

## Open questions

- The YAML library behind the strict loader, and whether JSON stays accepted once the UI edits documents.
- How long a `human` step waits and its quorum (one approver, or N of `approvers`); it arrives with UI approvals.
- Location and ownership: project workflows under the hub's `workflows/` ([hub-generator.md](hub-generator.md)) is the
  lean option; whether base workflows ship as managed templates, and how stored versions relate to git, stay open.
- Whether `revision` stays author-maintained or becomes the content hash alone.
- Parallel steps, conditions and loops beyond a gate's bounded `goto`: left out until a workaround audit shows a need.
