# Workflow engine rules: the finer points

## Purpose

The rules of the workflow engine that [workflow-schema.md](workflow-schema.md) states in short: how an `include` is
expanded and how the run reads the files of an included node. The format itself is the schema's contract; the reasons
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

## Invariants

- Expansion is deterministic and bounded: the same documents give the same expanded graph.
- No included node reads a node or an input of its caller that it was not given through `with`.

## Decisions

- [ADR 0032](../adr/0032-workflow-engine.md) (format, engine), [workflow-schema.md](workflow-schema.md) (the contract).

## Open questions

- Includes across packs, which would need each node to carry its own pack root.
