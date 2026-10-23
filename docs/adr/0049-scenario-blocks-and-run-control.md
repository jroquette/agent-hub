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
  its condition, computed at translation (bounded: 8 atoms, 64 terms). Each block has an address (`2.3`, `2.3.then.1`,
  `2.3.p2.1`); ids are optional, and a block without one gets `<stage slug>--<its address in the stage>`
  (`payment--3-then-1`), which no other derived id can equal; an explicit id equal to another block's fails the load.
  An If with no else exits through its branch and the block before it in the same step list, so a false condition
  skips only the branch; such an If cannot open a step list. A branch's condition is put on every entry node of its
  first block, distributed over any condition already there.
  `version: 1` scenarios load exactly as before.
- **Translation at load.** `parse_workflow` translates a version-2 document to a version-1 `WorkflowDocument` plus a
  **block map** (block address → its node ids, its entry and exit nodes, its tree key path); an included version-2
  scenario is translated the same way before includes are expanded. Planning, policy gates, events,
  plan mode, investigation, workarounds and fixtures run on the graph unchanged; a problem on a generated node is put
  back on the tree's key path, as includes do. A run's snapshot keeps the tree; every resume translates it again,
  which is deterministic because ids come from positions and stage names.
- **One canonical form.** The builder's canonical YAML writer moves from `api` to `generator`, extended to the tree, so
  `hub scenario migrate` and hub web's Save write the same bytes. Saving an unchanged document writes nothing.
- **Run control.** `EnginePorts` gains an optional run-control port. Before visiting a node (after resume reuse,
  before `trigger_rule` and `when:`), the engine asks it whether to pause; a yes ends the pass as a gate pause does
  (the report is `paused`, with reason `breakpoint` or `step` and the block address; a pause inside a `loop_group`
  body holds its iteration as a body gate does). With a breakpoint or step mode on, a layer that holds a node to pause at runs
  its nodes one at a time in declaration order, so "before this block" is exact. The resume is today's resume; Step and Continue are
  recorded commands read by the port. Without the port, or with no breakpoint and no step, the engine behaves as
  before.
- **Breakpoints are run data.** Block addresses of the run's pinned tree, kept in the run folder, written whole by
  the CLI (hub web runs it as it runs gate decisions), read before each node. They are never in the document, so they
  change neither the plan nor the `content_hash`.
- **What the debugger never does.** It answers no gate (a breakpoint on a gated step pauses before its `<step>__ask`,
  and the ask still opens after Continue or Step), edits no value, re-runs or skips no block, and rewinds nothing.
- **Production.** Breakpoints, Step, Continue and a start with breakpoints are refused when the run's environment is
  `production: true` in the effective config as read then; clearing breakpoints and cancelling stay allowed, and
  scenario runs without breakpoints keep ADR 0041's policy there.
- **Inspect.** A paused run's values (its effective inputs, and each finished block's rendered inputs, status and last
  output) come from lines the run record already holds (already redacted of credential values), through a separate
  read that needs hub web's launch cookie, as the agent-session routes do, and never for a production run. The run
  view itself stays metadata plus the captures it already shows.
- **Migration.** hub web's builder opens a graph scenario read-only, with a Migrate action; the graph editing of the
  builder goes. `hub scenario migrate [NAME…] [--check]` writes a graph scenario as a tree (one stage named after
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
- Bad: while debugging, a layer holding a node to pause at runs one node at a time, so At the same time paths run in turn while
  debugging.
- Bad: inspect shows action inputs and outputs in hub web, which no screen showed before: whoever holds the launch
  cookie of the local `hub web` (the developer's browser) sees business values of a non-production run. Other local
  processes cannot read them, since the read needs the cookie; the record on disk was already readable by them.
- Bad: an Include is one block: nothing inside the scenario it includes takes a breakpoint.
- Neutral: a debug pause is not a gate; Approvals does not list it.

## Delivery notes (AGH-521)

This ADR stays proposed: nothing below the contract is built yet. The scenario builder that shipped with AGH-521 is
the one the owner validated in the playground, and where it differs from the decision above, the validated behavior
wins for what the screen shows:

- **Format.** The builder reads and writes `version: 1` graph scenarios. Its step list shows the graph as ordered
  steps with groups (Repeat, If, At the same time) and a Start row, which is the shape `version: 2` will store; there
  is no translator, no block map and no `hub scenario migrate` yet, and a graph that does not read as a list still
  opens in the builder (not read-only, as Migration above says).
- **Canonical writer.** Save goes through the API's builder (`api/scenario_builder.py`), not a `generator` writer;
  an unchanged document still writes nothing.
- **Blocks tab.** The block language is a palette of ready blocks (Do, Check, Control, You, and one Run block per hub
  action) dragged or added into the step list, not a separate block canvas.
- **Run values and environment values.** An action input a step leaves out takes the scenario run's input of the same
  name, and a run input the start does not give takes the environment's non-secret value of that name before its
  declared default (`hub env` sets them). The decision above does not cover them; they live beside it in
  [design/scenarios.md](../design/scenarios.md) and [design/environments.md](../design/environments.md).
- **Debugger.** Breakpoints, Step, Continue, the values read and their routes are not built: the API paths in
  [API.md](../API.md) marked AGH-507 are the contract for them.

## More Information

- Contract: [design/scenarios.md](../design/scenarios.md) § Tree format and § Debugging;
  [design/workflow-schema.md](../design/workflow-schema.md) (`version`).
- AGH-507: spec, research and plan in the hub (`brain/features/scenario-blocks/`).
- Option 2 was rejected because a breakpoint would be a node: setting one changes the plan, cannot happen while a run
  runs without re-planning, shows in Approvals, and two in a Together trip the "two unordered gates" rule. Option 3
  because the graph stays free-form, so loose blocks remain possible. Option 4 because it duplicates the engine and
  every rule ADR 0041 put on it.
