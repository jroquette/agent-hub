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
  its condition, computed at translation (bounded: 8 atoms and 1,024 characters per If, 64 terms per joined
  condition, 262,144 characters of conditions written in all). Each block has an address (`2.3`, `2.3.then.1`,
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
  before `trigger_rule` and `when:`), the engine asks it whether to pause; a yes stops the pass as a gate pause does
  (the report is `paused`, with reason `breakpoint` or `step` and the block address; a pause inside a `loop_group`
  body holds its iteration as a body gate does). With a breakpoint or step mode on, a layer that holds a node to pause at runs
  its nodes one at a time in declaration order, so "before this block" is exact. The resume is today's resume, except
  that it goes on with the paused pass as if the process had never stopped (the run state keeps that pass: nothing
  it handled runs again, and the rest runs as it would have, on the plan that pass ran on), so a pause never changes
  what a run does; Step and Continue are recorded commands read by the port. Without the port, or with no breakpoint
  and no step, the engine behaves as before.
- **Breakpoints are run data.** Block addresses of the run's pinned tree, kept in the run folder, written whole by
  the CLI (hub web runs it as it runs gate decisions), read as each layer of nodes starts. They are never in the
  document, so they change neither the plan nor the `content_hash`.
- **What the debugger never does.** It answers no gate (a breakpoint on a gated step pauses before its `<step>__ask`,
  and the ask still opens after Continue or Step), edits no value, re-runs or skips no block, and rewinds nothing.
- **Production.** Breakpoints, Step, Continue and a start with breakpoints are refused when the run's environment is
  `production: true` in the effective config as read then; clearing breakpoints and cancelling stay allowed, and
  scenario runs without breakpoints keep ADR 0041's policy there.
- **Inspect.** A paused run's values (its effective inputs, and each finished block's rendered inputs, status and last
  output) come from lines the run record already holds (already redacted of credential values), through a separate
  read that needs hub web's launch cookie, as the agent-session routes do, and never for a production run. The run
  view itself stays metadata plus the captures it already shows.
- **Migration.** hub web's builder keeps editing a graph scenario as it does, and offers a Migrate action for it
  (a check first, whose result it shows, then the write); a scenario written as blocks it edits as its stages, with
  no loose block. `hub scenario migrate [NAME…] [--check]` writes a graph scenario as a tree (one stage named after
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
  untouched, and existing scenarios keep running as version 1; `hub init` seeds its example as version 2 (delivery
  notes, AGH-513).
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

## Delivery notes (AGH-507, AGH-521)

This ADR stays proposed. The whole decision above is built (AGH-507), in these parts:

- **Translation at load.** `parse_workflow` reads a `version: 2` scenario into the node graph, with its block map and
  its problems on the tree's key paths; a plan problem of a `version: 2` scenario names its block by address and tree
  key path ([design/scenarios.md](../design/scenarios.md) § Tree format).
- **Run control.** `EnginePorts.control` pauses a run before a node, and the resume goes on with the pass it stopped
  ([design/workflow-engine-rules.md](../design/workflow-engine-rules.md) § Run control).
- **Record.** `run_record` folds a run's debug pause, breakpoints and commands, reads a `debug.pause` line back so a
  run rebuilt from its record resumes with the pass it stopped (and plans with the policy asks that pass planned
  with), and folds the values a paused run shows; the `debug.*` event types have their `payload_keys` rows
  ([design/scenarios.md](../design/scenarios.md) § Debugging).
- **Canonical writer.** `generator`'s `scenario_yaml.render_document` writes a `version: 2` tree, and a `version: 1`
  graph as before, in the canonical key order ([design/scenarios.md](../design/scenarios.md) § Tree format), so a
  canonical tree file reads back to its own bytes; the API's builder validate and Save use it and take a `version: 2`
  document (its action references checked through its translated blocks, its callers listed in the action library),
  and Save of an unchanged document writes nothing and keeps its revision.
- **Doctor and the seed.** `scenarios.graph_format` warns on each `version: 1` scenario of the hub, at its `version`
  line, with `hub scenario migrate` as its fix ([design/hub-doctor.md](../design/hub-doctor.md)); `hub init` seeds
  `demo-service-up` as `version: 2`, so a fresh hub has no such warning, and its `version: 1` text stays as a test
  fixture.
- **The CLI's debugger.** `hub scenario run --break ADDR`, `hub scenario break RUN ADDR… [--off|--set]`, `hub scenario
  step RUN` and `hub scenario continue RUN` keep a run's breakpoints in `breakpoints.json`, give the engine a run
  control over that file and the record (step mode while the last debug command is a Step), write the debug record
  lines and emit the `debug.*` events, and refuse a start with breakpoints, a breakpoint, a Step and a Continue on a
  production environment, recording nothing ([design/scenarios.md](../design/scenarios.md) § Debugging); a run
  resumed on an environment that became production gets no run control.
- **Migrate.** `hub scenario migrate [NAME…] [--check]`: core's `tree_migrate` reads a `version: 1` graph by the
  translation's rules run the other way and gives the tree that translates back to the same nodes, edges and
  conditions (one stage named after the scenario, ids kept where they differ from the derived ones, its revision
  kept), or names each node it cannot map and why; the CLI writes each file in place with `generator`'s canonical
  writer, never through a link, and writes nothing at all when any scenario asked cannot be migrated, each checked
  (its text loaded again, and translated back to the same graph) before the first write
  ([design/scenarios.md](../design/scenarios.md) § Tree format). A tree has no `returns` or `outcome_field`, so a
  graph that sets them is not migrated; it does not split the conditions of nested Ifs joined on one node either.
- **The API** ([API.md](../API.md) § Scenarios): `PUT /scenario-runs/{run_id}/breakpoints` waits for `hub scenario
  break RUN --set -- ADDR…`, and `POST …/step|continue` resume a run in a debug pause through `hub scenario
  step|continue RUN`, detached; a start takes `breakpoints`. The server checks each address against the address
  grammar and the run's pinned tree (422), and the production rule as read then (409), before the CLI runs, which
  checks again and records nothing when it refuses. `GET …/values` gives a paused run's inputs and each finished
  block's values from its record, behind the launch cookie and never on production; the run view names the debug
  pause, the breakpoints and step mode, and a scenario's detail its version and blocks. `POST
  /scenarios/{project}/{name}/migrate` migrates one scenario in the server, as the CLI does, through the item write
  step the builder's Save uses, over the bytes the builder last read when it sends their hash.
- **hub web's builder** ([screen spec 23](../design/control-plane/specs/23-scenarios.md)): a `version: 2` file is
  edited as its stages. The builder's model reads `stages` straight into its blocks, each keyed by its address, and
  writes them back to the same JSON the server parsed (its keys in the canonical order), so no block is left loose
  and a file opened and saved unchanged writes nothing; a block's id is written only when it gives one (the one its
  place gives too, which it then keeps when it moves; without one it runs under the id its place gives, and an edit
  that gives it another place rewrites the references to it, so no reference starts reading another block;
  `$self.output` stays a block's own output). The step list shows a header per stage (added from the Blocks tab's
  Stage block or a "+" between stages, renamed in its editor, moved and removed as a step is), each block numbered by
  its address; a block's editor has no "runs after", no `when` and no join rule; the Graph view draws how the blocks
  run and edits nothing; Claude's prompt teaches the tree's keys, and its proposal is reviewed change by change, by
  address: the changes are read once, when the review opens, and the draft is always the one the decisions give from
  the draft the review opened on and the proposal (every change taken gives the proposal, none the draft). A
  `version: 1` file is edited as AGH-521 shipped it, and More offers Migrate: the check's text, or each node it cannot
  map, shown before anything is written, then the write over the file the check read.
- **hub web's debugger** ([screen spec 23](../design/control-plane/specs/23-scenarios.md) § Debugging a run written
  as blocks): a scenario run's page lists the blocks the run pinned (the run view's `blocks`, read from its snapshot
  as breakpoints are checked, and each timeline line's `block`), each with its state in the run and a breakpoint
  toggle that sends the run's whole set; in a debug pause, a bar names the block and why and offers Step and
  Continue; while the run is paused, the Facts column shows its inputs and each finished block's values, folded until
  opened. Breakpoints, Step, Continue and the values are offered only off production (a scenario that no longer reads
  leaves it to the server's refusal, so a paused run keeps its Continue). The scenario page's step cards of a
  `version: 2` scenario carry a toggle each, passed as the start's breakpoints. Since everything comes from the run,
  an edit in the builder while a run is paused changes neither the page nor what Continue runs. The screens add no
  rule of their own: a breakpoint toggle sends the whole set, as `hub scenario break RUN --set` does, and Step and
  Continue are the CLI's commands, run by the API.

The scenario builder that shipped with AGH-521 is the one the owner validated in the playground, and where it differs
from the decision above, the validated behavior wins for what the screen shows:

- **Format.** The builder reads and writes `version: 1` graph scenarios as it shipped: its step list shows the graph
  as ordered steps with groups (Repeat, If, At the same time) and a Start row, which is the shape `version: 2`
  stores; it edits a `version: 2` file as its stages (above), and offers Migrate for a graph. A graph that is not
  nested paths still opens and can be edited (as Migration above says): what the list cannot show stays as loose
  steps under it, and a Graph view and the YAML are a tab away.
- **Canonical writer.** The builder shipped with its writer in the API's builder (`api/scenario_builder.py`); Save
  still goes through the API, but writes with `generator`'s scenario writer (`generator/scenario_yaml.py`), as
  decided, and an unchanged document writes nothing.
- **Blocks tab.** The block language is a palette of ready blocks (Do, Check, Control, You, a Stage block for a file
  written as blocks, and one Run block per hub action) dragged or added into the step list, not a separate block
  canvas.
- **Run values and environment values.** An action input a step leaves out takes the scenario run's input of the same
  name, and a run input the start does not give takes the environment's non-secret value of that name before its
  declared default (`hub env` sets them). The decision above does not cover them; they live beside it in
  [design/scenarios.md](../design/scenarios.md) and [design/environments.md](../design/environments.md).

## More Information

- Contract: [design/scenarios.md](../design/scenarios.md) § Tree format and § Debugging;
  [design/workflow-schema.md](../design/workflow-schema.md) (`version`).
- AGH-507: spec, research and plan in the hub (`brain/features/scenario-blocks/`).
- Option 2 was rejected because a breakpoint would be a node: setting one changes the plan, cannot happen while a run
  runs without re-planning, shows in Approvals, and two in a Together trip the "two unordered gates" rule. Option 3
  because the graph stays free-form, so loose blocks remain possible. Option 4 because it duplicates the engine and
  every rule ADR 0041 put on it.
