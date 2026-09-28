# Workflow schema: workflows as data

## Purpose

A sketch for Phase 4: the shape of the declarative workflow document from [SPEC](../SPEC.md) direction 1, so that
Phase 2 events and the Workflow entity ([domain-model.md](domain-model.md)) already fit it. It designs the document
only; the engine that runs it, its storage and its UI are out of scope here. Keys marked as proposals are listed again
under Open questions.

## Contract

### Document

A YAML document (or the same structure in JSON), validated by a frozen Pydantic model in core that rejects unknown
keys and exports a JSON Schema, the pattern [project-config.md](project-config.md) uses for `hub.json`.

| Key | Type | Meaning |
|---|---|---|
| `version` | integer, `1` | schema version of the document format; the engine refuses one it does not support |
| `name` | string, kebab-case | the workflow's name, unique in its hub |
| `revision` | integer | bumped by the author on each change; with the content hash it identifies what a run used |
| `description` | string, optional | one line for people and the UI |
| `inputs` | map of name to `{type, required, description}` | what a run is started with (for example the issue) |
| `limits` | `{max_turns, max_cost_usd}` (proposal) | caps for the whole run; exceeding one fails the current step with reason `limit` |
| `steps` | list, at least one | run in order; each `id` unique |
| `on_failure` | list of `script` steps (proposal) | run once after the run fails, with the failed step and reason as inputs; their own failure is recorded, never retried |

### Steps

Every step has `id`, `type`, optional `inputs` (values, possibly references), optional `outputs` (the names it
promises) and optional `limits` (within the run's, proposal). A reference is a whole string, `${inputs.<name>}` or
`${steps.<id>.outputs.<name>}`, resolved before the step starts; there are no other expressions. How a step hands its
outputs to the engine is open.

| `type` | Extra keys | What happens | Events |
|---|---|---|---|
| `agent` | `agent` (id `plugin:name`), `instruction` | one agent session gets only this instruction and the step inputs | its session events carry `workflow` and `step` |
| `script` | `command`, optional `cwd`, `env` | a deterministic command, no LLM; exit 0 passes | executor step events |
| `gate` | `command` (the check), optional `cwd`, `env`, `on_fail` | an automatic pass or fail | `gate.request`, `gate.result` |
| `human` | `approvers`, `prompt`, `on_fail` | waits for a decision by one of `approvers` (proposal); a rejection fails the step | `gate.request`, `gate.result` with the approver |

`command` is an argv list, never a shell string: a reference fills one whole element, or reaches the command through
`env`, so a value can never be parsed as shell syntax. `on_fail` (proposal) is `fail` (default) or
`{goto: <id>, max_attempts: N}`; each new attempt of a step is recorded with its attempt number. A step that fails
ends the run as failed, recording the step as the stage and the reason, unless its `on_fail` sends it back to an
earlier step; then `on_failure` runs. How a run shows in events is in [event-derivations.md](event-derivations.md).

### Example: today's issue-to-PR flow

The `hub tracker …` and `hub pr …` commands and the agent id are illustrative: they do not exist, and the Phase 4
issue fixes the real ones. `on_failure` reproduces today's failure label and diagnosis.

```yaml
version: 1
name: issue-to-pr
revision: 1
description: Take one ready tracker issue to an open pull request.
inputs:
  issue: {type: string, required: true}
  repo: {type: string, required: true}
limits: {max_turns: 200, max_cost_usd: 10}
steps:
  - id: pick
    type: script
    command: [hub, tracker, start, "${inputs.issue}"]
  - id: worktree
    type: script
    command: [hub, worktree, "${inputs.issue}", --only, "${inputs.repo}"]
    outputs: [path]
  - id: implement
    type: agent
    agent: demo:implementer
    instruction: Implement the issue in the worktree and commit on its branch.
    inputs: {issue: "${inputs.issue}", path: "${steps.worktree.outputs.path}"}
    limits: {max_turns: 150}
  - id: verify
    type: gate
    command: [make, check]
    cwd: "${steps.worktree.outputs.path}"
    on_fail: {goto: implement, max_attempts: 2}
  - id: pr
    type: script
    command: [hub, pr, open, "${inputs.issue}"]
    outputs: [url]
  - id: report
    type: script
    command: [hub, tracker, review, "${inputs.issue}", --pr, "${steps.pr.outputs.url}"]
on_failure:
  - id: mark-failed
    type: script
    command: [hub, tracker, fail, "${inputs.issue}", --diagnosis-from-run]
```

## Invariants

- Orchestration spends no tokens: only `agent` steps reach a model, and each sees its own instruction and inputs.
- Deterministic: the same document and the same step results always lead to the same next step.
- A run pins the `revision` and content hash it started with; editing the document never changes a running run.
- The document is data: no code and no expressions beyond whole-value references; nothing is run through a shell.

## Decisions

- [SPEC](../SPEC.md) direction 1: a declarative document, a Pydantic schema, a deterministic Python engine, the four
  step types, and a recorded version per execution.
- [ADR 0010](../adr/0010-hub-json-config-contract.md): the same model-plus-exported-schema pattern as `hub.json`.

## Open questions

- YAML parsing and typing: ADR 0010 rejected YAML for `hub.json` because of its implicit typing. For workflows the
  mitigation would be a strict loader (a safe loader limited to strings, lists and maps, duplicate keys rejected)
  followed by the Pydantic validation; the parser and whether JSON stays accepted are chosen in Phase 4.
- Step outputs: how a step returns them (a JSON file whose path the engine passes, or an agent's final structured
  message) and how a missing promised output fails the step.
- The proposals above: retries (`on_fail` with `goto` and `max_attempts`), run and step `limits`, run-level
  `on_failure`, the `human` quorum (one approver, or N of `approvers`), and conditionals (none beyond `on_fail`).
- How long a `human` step waits, and what happens at the bound (fail, or keep waiting with a reminder).
- Location and ownership: project workflows as project-owned files under the hub's `workflows/`
  ([hub-generator.md](hub-generator.md)) is the lean option; whether base workflows also ship as managed templates, and
  how the platform's stored versions and history (SPEC direction 1) relate to git, are open until Phase 4.
- Whether `revision` stays author-maintained or becomes the content hash alone.
- Parallel steps and loops beyond a gate's bounded `goto`: left out until a real workflow needs them.
