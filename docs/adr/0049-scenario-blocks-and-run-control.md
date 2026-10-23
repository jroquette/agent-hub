# 0049. Scenarios as ordered blocks, and a debugger as engine run control

- Status: proposed
- Date: 2026-10-23
- Deciders: José Henrique Roquette (the debugger's scope, the migrate command, the format direction and the
  production rule were set by the owner for AGH-507)
- Extends: [ADR 0032](0032-workflow-engine.md) (workflow format and engine) with a second scenario format and one
  engine port; [ADR 0041](0041-scenarios-actions-and-enforced-access.md) (scenarios, actions, access policy), whose
  policy, gates, investigation and events are unchanged. Neither is edited.

## Context and Problem Statement

A scenario is a graph of nodes (`depends_on`, `trigger_rule`), but every real scenario is a sequence of stages: the
reference one is a chain where each node depends only on the one before. hub web's builder reads the graph as nested
blocks (Repeat, If/else, At the same time) and leaves what does not fit as loose blocks; it has been rewritten six
times against that mismatch. A scenario run pauses only at gates, so a person walking a real system step by step
cannot stop before a chosen block, step one block at a time, or look at the values so far. How should a scenario be
written so that it maps one-to-one to blocks, and how does a run stop before a block without weakening the policy, the
pinned content or the engine's determinism?

## Considered Options

1. **A tree format translated to today's graph at load, and a run-control port in the engine.** `version: 2`
   scenarios hold named `stages` of ordered steps and containers; core translates them to nodes before planning, as
   `include` is expanded. The engine asks a port, before it visits a node, whether to pause there.
2. **The same tree format, with breakpoints as gates the planner inserts** (`<step>__break`, like `<step>__ask`).
3. **The graph format with sugar**: `depends_on` defaults to the previous node, a `stage` label per node.
4. **The tree as the engine's own model**: a second interpreter that runs stages directly.

## Decision Outcome

Chosen option: 1.

- **Format.** A `kind: scenario` document with `version: 2` holds `stages:` (each `name`, optional `description`,
  `steps`) in place of `nodes:`; `depends_on` and `trigger_rule` are refused. Position is order. A step is one key of a
  fixed set: `do` (an action), `wait_until` (a read action polled with `until`, `every`, `timeout`), `you` (an
  approval), `wait` and `include`; a container is `repeat` (a `loop_group`), `if`/`then`/`else`, or `together`
  (parallel paths joined by the next step). Conditions use the existing `when:` grammar; an else is the complement of
  its condition, computed at translation (bounded: 8 atoms, 64 terms). Ids are optional: a block without one gets
  `<stage slug>-<n>`. `version: 1` scenarios load exactly as before.
- **Translation at load.** `parse_workflow` translates a version-2 document to a version-1 `WorkflowDocument` plus a
  **block map** (block address → its node ids, its entry nodes, its tree key path). Planning, policy gates, events,
  plan mode, investigation, workarounds and fixtures run on the graph unchanged; a problem on a generated node is put
  back on the tree's key path, as includes do. A run's snapshot keeps the tree; every resume translates it again,
  which is deterministic because ids come from positions and stage names.
- **One canonical form.** The builder's canonical YAML writer moves from `api` to `generator`, extended to the tree, so
  `hub scenario migrate` and hub web's Save write the same bytes. Saving an unchanged document writes nothing.
- **Run control.** `EnginePorts` gains an optional run-control port. Before visiting a node (after resume reuse,
  before `trigger_rule` and `when:`), the engine asks it whether to pause; a yes ends the pass as a gate pause does
  (the report is `paused`, with reason `breakpoint` or `step` and the block address; a pause inside a `loop_group`
  body holds its iteration as a body gate does). With breakpoints set, a layer that holds one runs its nodes one at a
  time in declaration order, so "before this block" is exact. The resume is today's resume; Step and Continue are
  recorded commands read by the port. Without the port, or with no breakpoint and no step, the engine behaves as
  before.
- **Breakpoints are run data.** Block addresses of the run's pinned tree, kept in the run folder, written whole by
  the CLI (hub web runs it as it runs gate decisions), read before each node. They are never in the document, so they
  change neither the plan nor the `content_hash`.
- **What the debugger never does.** It answers no gate (a breakpoint on a gated step pauses before its `<step>__ask`,
  and the ask still opens after Continue or Step), edits no value, re-runs or skips no block, and rewinds nothing.
- **Production.** Breakpoints, Step, Continue and a start with breakpoints are refused on an environment with
  `production: true`; scenario runs without them keep ADR 0041's policy there.
- **Inspect.** A paused run's view adds the run's inputs, each capture, and each finished block's rendered inputs,
  status and last output, from lines the run record already holds (already redacted of credential values).
- **Migration.** `hub scenario migrate [NAME…] [--check]` writes a graph scenario as a tree (one stage named after
  the scenario, ids kept where they differ from the derived ones) when its graph is series-parallel with the shapes the
  tree has; otherwise it writes nothing and names each node it cannot map. `hub doctor` warns
  (`scenarios.graph_format`) for each graph-format scenario. The graph format is removed in its own change, two minor
  releases after the one that ships migrate.
- **Events** (metadata only, ADR 0019): `debug.pause` (`node`, `block`, `reason`), `debug.command` (`command`,
  `approver`), `debug.breakpoints` (`count`), each with its `payload_keys` row.

### Why each new key and port passes ADR 0032's admission rule

| Key or port | Steers or records | Fixed meaning | Oversight a script cannot add |
|---|---|---|---|
| `version: 2`, `stages`, step and container keys | Translated to nodes the engine already steers | One node shape per key | Same as the node it becomes; the file now shows the order people read |
| Run-control port | Decides where a run pauses and records each pause and command | Pause before a node or not | A script cannot stop the engine before a step or show the run's values mid-way |

### Consequences

- Good: one file entry is one block; the builder edits the file without a graph reading and without loose blocks.
- Good: everything after translation is today's engine, so policy, gates, investigation, events and fixtures are
  untouched, and the seeded and existing scenarios keep running as version 1.
- Good: a person can stop before any block, step, continue and see the values, with the ask, the pin and determinism
  intact; a pause changes when a run stops, never its path or results.
- Bad: two scenario formats live side by side until the graph one is removed; doctor and migrate carry the window.
- Bad: a translator and a block map must stay in step with the builder's model (covered by round-trip tests).
- Bad: with breakpoints set, a layer holding one runs one node at a time, so At the same time paths run in turn while
  debugging.
- Bad: inspect shows action inputs and outputs in hub web, which no screen showed before; the session-token holder of
  the local `hub web` sees business values of a non-production run.
- Neutral: a debug pause is not a gate; Approvals does not list it.

## More Information

- Contract: [design/scenarios.md](../design/scenarios.md) § Tree format and § Debugging;
  [design/workflow-schema.md](../design/workflow-schema.md) (`version`).
- AGH-507: spec, research and plan in the hub (`brain/features/scenario-blocks/`).
- Option 2 was rejected because a breakpoint would be a node: setting one changes the plan, cannot happen while a run
  runs without re-planning, shows in Approvals, and two in a Together trip the "two unordered gates" rule. Option 3
  because the graph stays free-form, so loose blocks remain possible. Option 4 because it duplicates the engine and
  every rule ADR 0041 put on it.
