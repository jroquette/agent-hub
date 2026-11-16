# Workflow engine rules: the finer points

## Purpose

The rules of the workflow engine that [workflow-schema.md](workflow-schema.md) states in short: how an `include` is
expanded, how the run reads the files of an included node, how a loop group's body runs, and how a layer's nodes run
together. The format is the schema's contract; the reasons are in [ADR 0032](../adr/0032-workflow-engine.md).

## Contract

### Include expansion

- An include names a workflow of its own pack: a node's `prompt_file` and `script` are paths inside its pack.
- `with` is checked as at run start: no unknown name, every required input given, defaults filled in. Each
  `$INPUTS.<name>` of the block is replaced by its value in one pass. A text value is parent text, so a reference in it
  reads the parent's node; a default or a non-text value has its `$` escaped (`$$`) and stays text. In a block's
  `when:` an input must be given a reference: a literal in place of a reference breaks the grammar (a load error).
- A block is hermetic: it reads only its own nodes and inputs. An include's `with` reads only `$INPUTS` and node
  outputs.
- The include's `depends_on` becomes each root's; its `when:` joins a root's own as `A && B`, refused when either holds
  `||` (no parentheses); its `trigger_rule` goes to the roots that set none.
- `depends_on: [I]` waits on every sink of the block. `$I.output`, `returns: I`, a binding's `from` and
  `context.resume: I` read the primary sink: the included workflow's `returns`, else its single sink; with several sinks
  and no `returns` that reading is a load error.
- Includes nest at most 3 levels, with cycles found first. Each workflow is expanded once per depth in one expansion.
  An expanded document holds at most 512 nodes; past that the node that crosses the cap is a load error.
- Planning runs on the expanded document; its problems are put back on the parent's node (an included node's on its
  `include` key, naming the namespaced id).

### Prompt files and scope

- A node keeps the reference scope its texts went through (renames, input values), and the runner renders its
  `prompt_file` through it: the file reads its own workflow's inputs and nodes, as an inline prompt does.
- Planning reads no file, so a prompt file's references are checked when it renders: one that does not resolve fails
  the node `config`.
- A run snapshots each workflow it includes (`includes/<name>.json`, covered by `content_hash`); a resume plans them
  from the snapshot.

### Loop group bodies

- A body holds no `include` or `loop_group`. Its ids are new to the document (an included group's, to its own block)
  and its `depends_on` stay inside it; a body node reads body nodes upstream of it and outer nodes upstream of the
  group, and `$LOOP_PREV.<body id>` any body node. Body ids are recorded as `<group>__<id>`, prompt files included.
- Each iteration runs the body's layers; each body visit takes the node's next attempt, counted over the run.
- A failed body node does not stop the iteration, so `all_done` body nodes still run; then the group fails with that
  node's failure kind. A halt in a body ends the group `cancelled`.
- Otherwise `until_when` (over the iteration's outputs), then `until_bash` (exit 0) end the group; past
  `max_iterations` it fails `max_iterations`. A group is never retried. A completed group is reused whole on resume.
- Without `fresh_context` (the default) a body agent resumes its own session of the previous iteration, unless it
  sets `context: fresh` itself (a reviewer that starts afresh each round).
- A group's body counts toward the 512-node cap of an expansion.

### Concurrent layers

- A layer's nodes run concurrently in threads; at most 4 attempts run at once across the run, nested group layers
  included. Nodes record as they end, through one lock; the run's `reason` is the first failed node in declaration
  order.
- Planning splits a layer, first fit in declaration order: a node that reads the checkout (`mutates_checkout: false`,
  or a group whose body holds one) never shares a run with one that may change it, and two agents resuming one session
  never run together. Each kind skips, for good, the batches that can no longer take it, so splitting is near-linear.
- A layer holding a `halt`, or a group whose body holds one, runs one node at a time and stops at the halt.
- A read-only node's attempt reads `git status` of the hub and its repos before and after; a change fails it `config`
  (never retried). A folder that is not a git checkout is not watched; the run's start record lists it
  (`checkout_unwatched`).
- A run that `hub web` started by itself records `trigger` (`schedule` or `event`) in its start record
  ([ADR 0048](../adr/0048-scheduled-and-event-starts-in-hub-web.md)); a run started by hand has no `trigger`.
- Ctrl-C stops the run: no attempt, retry or group iteration starts after it, a retry's backoff wakes, and the
  running children's process groups are killed.

### Gates

- A gate in a concurrent layer lets its siblings finish, then the run pauses; a body gate holds its group's
  iteration open (the resume goes on in it, with the body nodes it ended and `$LOOP_PREV`); two suspendable nodes (a
  gate, or a group whose body holds one) with no order between them are a load error. After Ctrl-C no gate opens.

### Run control

A debug pause stops a run before a node by a breakpoint or by Step ([ADR
0049](../adr/0049-scenario-blocks-and-run-control.md), [scenarios.md](scenarios.md) § Debugging). The engine knows
only nodes: the run-control port maps blocks to the nodes they enter by, and decides which ones Step pauses before.

- Without the port, or while it is not debugging (no breakpoint, no step mode), the engine asks nothing more. A resume
  from a debug pause goes on with its pass (below) even once every breakpoint is cleared.
- When a layer starts (a group body's layer in each iteration), the port is asked, once per node, about each node the
  pass is about to visit. It is not asked about a node whose end or open state from an earlier pass this pass takes
  as is: a reused node (`prior_success`), a skip that is not stale (it skips again, the same way), a gate or a held
  group it takes up. A breakpoint set while a layer runs takes effect from the next layer. Resume reuse comes first,
  then run control, then `trigger_rule` and `when:`.
- A layer holding a node to pause at runs one node at a time in declaration order and stops before the first such
  node: the nodes of that layer before it run, it and the nodes after it do not start, and no later layer starts. A
  group whose body pauses holds its iteration there, as with a body gate, and the other nodes of the outer layer still
  run. Nothing is recorded for the node; the report is `paused`, its `reason` that node, and the run state holds the
  pause (node, block, `breakpoint` or `step`) and the pass it stopped: the layer, the pass's ends, the results those
  nodes had before it, its changed and stale nodes, and the gate it opened that is still open.
- The resume goes on with that pass, as if the process had never stopped. It restores the pass and visits the rest of
  the stopped layer, then the layers after it; nothing the pass already handled is visited again, so a failure is not
  run again and a stale node runs as that pass would have run it. The first visit of the node it stopped before runs,
  and so does the first visit of each node the port names the same block for (an If's or a Together's other entry
  nodes). That is each node's first visit in the resumed process, once, whether or not the port is asked then and
  whether it answers a stop or releases that visit itself; a later visit (a body node's in the next iteration) is
  asked and pauses as any other.
- The resume runs on the plan the stopped pass ran on, with the same layers: a scenario run's plans with the policy
  asks that pass planned with, kept in its `debug.pause` line, even a re-ask no longer owed because its step ended
  since. The stopped pass names its layer by position, so the engine refuses (`WorkflowEngineError`) a plan whose
  layers do not hold that pass as it ran (a node of an earlier layer with no end in it, or a stopped layer without
  the paused node or its group); it never goes on from another layer.
- A gate that opened in the stopped pass stays open: the report is the debug pause, the gate is in the run state, and
  its answer is not read again in that pass. Once the stopped layer ends, the pass pauses on the gate, as it does with
  no breakpoint, and the resume after it takes up the answer. What an earlier pass left open that the stopped pass
  had not reached (a gate, a held group) stays in the run state for the pass that reaches it.
- So a pause changes when a run stops, never what it does: with the same inputs and stub results, a run with no
  pause, one paused before every node and one stepped node by node end with the same status, outcome, node results,
  captures and recorded step attempts. When a group runs beside an open gate, whether it holds its iteration depends
  on thread timing, with or without a pause.

## Invariants

- Expansion is deterministic and bounded: the same documents give the same expanded graph.
- No included node reads a node or an input of its caller that it was not given through `with`.

## Decisions

- [ADR 0032](../adr/0032-workflow-engine.md) (format, engine), [workflow-schema.md](workflow-schema.md) (the contract).

## Open questions

- Includes across packs, which would need each node to carry its own pack root.
