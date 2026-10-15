# Workflow engine rules: the finer points

## Purpose

The rules of the workflow engine that [workflow-schema.md](workflow-schema.md) states in short: how an `include` is
expanded, how the run reads the files of an included node, and how a loop group's body runs. The format itself is the schema's contract; the reasons
are in [ADR 0032](../adr/0032-workflow-engine.md).

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
- Without `fresh_context` (the default) a body agent resumes its own session of the previous iteration.
- A group's body counts toward the 512-node cap of an expansion.

## Invariants

- Expansion is deterministic and bounded: the same documents give the same expanded graph.
- No included node reads a node or an input of its caller that it was not given through `with`.

## Decisions

- [ADR 0032](../adr/0032-workflow-engine.md) (format, engine), [workflow-schema.md](workflow-schema.md) (the contract).

## Open questions

- Includes across packs, which would need each node to carry its own pack root.
