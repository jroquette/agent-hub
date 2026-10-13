# 0027. The workflow format and the minimum engine

- Status: proposed
- Date: 2026-10-13
- Deciders: José Henrique Roquette (D-1 to D-9 and the answers to the open questions approved with the AGH-181 plan on
  2026-10-13; the ADR itself awaits review)

## Context and Problem Statement

SPEC direction 1 fixes the shape of Phase 4: a declarative workflow document, a Pydantic schema, a deterministic
Python engine, four step types and a recorded version per run. The sketch in
[workflow-schema.md](../design/workflow-schema.md) predates three changes to `hub run`. AGH-140 keeps a run's status
apart from what it delivered, so `no_changes` and `blocked` are not failures. AGH-179 plans typed failure classes that
decide retries. AGH-139 plans schema-validated JSON outputs between agents. The sketch also left open how a step hands
back its outputs, had no rule for admitting new keys, and no way to test a workflow without running it.

Archon (github.com/coleam00/archon, MIT) runs a mature YAML workflow engine for coding agents. We read its
workflow-language constitution, direction document, node schema and authoring guide at commit `a5834f2c`. They
record lessons that fit our case. A config format tends to grow into a poor programming language. Its growth needs a
written test for admission. Outputs need a contract owned by their producer. Lifecycle status and the authored outcome
are separate facts. Retries should follow a typed failure class, never message text. A dry run with stubs catches
routing mistakes before any spend. Archon also shows costs we do not want: 30 common node fields plus provider tuning,
breaking changes accepted without a migration, and anonymous telemetry on unless disabled.

What document format and what minimum engine should Phase 4 build first?

## Considered Options

1. Keep the sketch as it is: outputs as bare names, no admission rule, no fixtures, failure as one kind.
2. Adopt Archon's model: a DAG with `depends_on`, `trigger_rule` and a `when:` condition grammar, a wide node surface,
   loops, includes and sub-runs.
3. A linear, minimal document with an admission rule, producer-owned output schemas, status apart from outcome,
   engine-owned failure classes and fixtures, and a minimum engine of three step types.
4. Workflows as Python code (a library of step functions), with no document.

## Decision Outcome

Option 3. Option 1 cannot express AGH-140's outcomes or AGH-139's outputs. Option 2 brings a surface we would have to
maintain before any of our workflows needs it. Option 4 loses what direction 1 asks for: a document the UI can edit,
version and show, and an engine that can see every step.

- **D-1 Where it is written.** The contract lives in `workflow-schema.md` (150 lines or fewer); the reasons and this
  comparison live here.
- **D-2 Linear.** Steps run in order. The only jump is a gate's `on_fail: {goto, max_attempts}`, which is today's
  implement and verify loop. A DAG, conditions or loops come only when a workaround audit shows a real need.
- **D-3 Step types.** The format keeps all four types (`agent`, `script`, `gate`, `human`). The minimum engine runs
  `agent`, `script` and `gate`, which reproduce `hub run`. It refuses a `human` step at load until UI approvals exist.
- **D-4 Ending without delivering.** A reserved output, `end: {outcome: no_changes | blocked, reason}`, that any step
  may return. It ends the run with status `done` and that outcome, through a fixed mapping with no expression (the shape
  of Archon's `outcome_field`). `delivers` names the output recorded as the delivery. `on_not_delivered` replaces
  `on_failure`: it runs on any end without a delivery, as today's report does.
- **D-5 Failure classes belong to the engine.** AGH-179's classes (`auth`, `quota`, `misconfigured`, `transient`,
  `gate`, `unknown`), set where the failure happens and never read from text. Only `transient` retries, once per step,
  within the run's caps. There is no `retry` key in version 1, because a script can carry its own retry, and a
  per-step policy is schema width.
- **D-6 Outputs.** Each output is declared with a JSON Schema, and the producer owns it (Archon's producer ownership;
  no caller-side restatement). An agent step returns its outputs as one JSON object in its final message. A script
  step writes one JSON object to `$HUB_STEP_OUTPUT`. The engine reads at most a fixed size (set in Phase 4). A
  missing, oversized or invalid output fails the step as `unknown`.
  AGH-139's evaluator verdict and reviewer findings are the first shared schemas.
- **D-7 Fixtures from day one.** `hub workflow test <name>` runs each fixture in `workflows/<name>.fixtures/`, in
  memory and with no side effects. Coverage is strict: a reachable step with no result fails the test. `make check`
  and hub CI run the fixtures from the engine's first release. Sample:

  ```yaml
  inputs: {issue: AGH-1, repo: agent-hub}
  steps: {pick: {}, worktree: {outputs: {path: /w}}, implement: {outputs: {summary: s}},
          commits: {outputs: {end: {outcome: no_changes, reason: no commit}}}, mark: {}}
  expect: {path: [pick, worktree, implement, commits, mark], status: done, outcome: no_changes}
  ```

- **D-8 No excerpts.** Archon's ideas are paraphrased and credited. No text is copied, so `NOTICE` and `LICENSES/` do
  not change. Its motto is adapted as "the document coordinates, scripts compute, agents judge".
- **D-9 Parsing.** YAML is read through a strict loader (strings, lists and maps only, duplicate keys rejected), then
  validated by Pydantic. JSON is accepted as the same structure. Phase 4 picks the library. This avoids the implicit
  typing for which [ADR 0010](0010-hub-json-config-contract.md) chose JSON for `hub.json`; multi-line instructions are
  why workflows still prefer YAML.

**The admission rule** (adapted from Archon's admissibility test) applies to every future key or step type. Does the
engine need to see it to govern the run? Is it data with a fixed meaning, not evaluation? Could a `script` step with
today's keys already do it? If a script could, the key must earn its place by governance value. The five smells
(expression creep, composition metastasis, workaround pressure, schema width, implicit magic) and agent-hub's lever for
each are listed in the design file's Invariants.

**Not copied, and why:**

- *A wide node surface.* Archon's node base has 30 fields, about half of them provider tuning, and needs a matrix of
  parameters by node type. Here an agent's model and tools stay in its agent definition. The keys must fit on one
  screen, and a key that needs a compatibility table is refused.
- *Frequent breaking changes.* Archon shipped a behaviour change with no migration and does not keep bundled blocks
  stable across releases. Here a breaking format change bumps `version`, the engine refuses versions it does not know,
  and the release that bumps it ships the migration, through `hub sync` or a `hub doctor` fix. It is also listed in
  CHANGELOG under **Changed**.
- *Telemetry on by default.* Archon sends anonymous usage events unless an environment variable turns them off.
  agent-hub sends nothing off the machine. Its sensors post only to a loopback URL
  ([ADR 0021](0021-hook-event-sensor.md)).
- Also left out for now: `when:` conditions, `trigger_rule`, fan-out, loops, includes, sub-runs, durable waits, and
  per-node provider fields.

### Consequences

- Good: the document maps one to one onto today's `hub run` stages and its `run.end` keys. Every Phase 4 key has a
  written test to pass, and workflows are tested in CI before they spend anything.
- Bad: no parallel work and no conditions in version 1. A workflow that needs them waits for a version bump.
- Depends on AGH-139 for the first shared schemas and on AGH-179 for the failure classes. Until AGH-179 lands, older
  records read `unknown`.

## More Information

[workflow-schema.md](../design/workflow-schema.md) (the contract); [SPEC](../SPEC.md) direction 1;
[event-derivations.md](../design/event-derivations.md) (how `run.end` folds into a WorkflowRun); AGH-181 spec and plan
(hub `brain/features/phase4-workflow-schema/`).

Archon, Copyright (c) 2025-2026 Cole Medin, MIT License, https://github.com/coleam00/archon, commit
`a5834f2c27af98fe0585964f01e7364844306ad0`. Files read: `.archon/workflow-language-constitution.md`,
`.archon/direction.md`, `packages/workflows/src/schemas/dag-node.ts`, `packages/workflows/src/schemas/retry.ts`,
`packages/docs-web/src/content/docs/guides/authoring-workflows.md` and the CLI reference's dry-run section. Ideas are
paraphrased; no text is copied.
