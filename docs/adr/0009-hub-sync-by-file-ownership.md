# 0009. Hub sync by per-file ownership

- Status: proposed
- Date: 2026-09-28
- Deciders: José Henrique Roquette

## Context and Problem Statement

Phase 1 makes `hub init` generate a hub from templates and `hub sync` bring an existing hub up to a newer template
release (see [SPEC](../SPEC.md)). A generated hub does not stay pristine: each project adds its own rules, Makefile
targets, Claude Code settings and plugin content. A sync that overwrites those edits loses project work; a sync that
never touches a file lets hubs drift apart until the templates stop describing them. How does `hub sync` update a
customized hub without losing a project edit, and in a way that is deterministic and testable?

## Considered Options

- **Per-file ownership plus a lock file**: every generated file is either owned by the templates or owned by the
  project, and a lock records what the generator last wrote.
- **3-way merge**: keep the previous template output, the new one and the file on disk, and merge them like git does.
- **Marker-delimited blocks**: the generator owns only the text between begin and end markers inside a file.
- **Generate once, never sync**: `hub init` writes the hub and later template releases are applied by hand.
- For project additions to a managed JSON file (Claude Code settings, the marketplace): a seeded sibling file merged
  over the template, or **new `hub.json` keys** rendered into the file.

## Decision Outcome

Chosen option: **per-file ownership plus a lock file**, because it gives every file exactly one owner, so a sync is a
plain comparison of bytes and hashes that never has to merge text, and every outcome (write, skip, stop) can be tested
with fixed inputs. Project additions to managed JSON come from a seeded sibling file.

- Every file the generator writes is `managed` or `seeded`. `hub sync` may rewrite a `managed` file. A `seeded` file
  is written once, when it is absent, and the generator never touches it again, even to recreate it after the project
  deleted it. `hub.json` itself is seeded: the project owns its configuration.
- `hub.lock`, a JSON file at the hub root, records the platform version the hub was generated with and, for each
  managed file, its path and the SHA-256 hash of the bytes written. Seeded files are listed without a hash.
- The generated output is a function of three inputs only: `hub.json`, the platform version, and the seeded extension
  inputs (`*.project.json` files, `AGENTS.project.md`, and the entries present under `plugin/<project>/`).
- Sync plans every path before writing anything:
  - A file whose bytes equal the new render is clean whatever the lock says; sync only records it. This makes an
    interrupted run, and a re-run of `init`, `sync` or `adopt`, safe.
  - A managed file whose hash equals its lock entry is rewritten with the new render; a missing managed file is
    written again (the templates own it, and nothing of the project is lost).
  - A managed file that differs from both its lock hash and the render (an edit), or a rendered managed path on disk
    without a managed lock entry, is a conflict: sync prints a diff per file, writes nothing and exits with a distinct
    code. The way out is to move the change into an extension file, then restore the file from git or delete it (git
    keeps its history), and re-run; plain sync has no flag that overwrites an edit.
  - A managed file that left the template is deleted when it still matches its lock hash, and is a conflict otherwise.
    A rename is a delete plus a create.
  - A path whose ownership changes from managed to seeded keeps its file; only its lock entry changes. A path that
    changes from seeded to managed follows the rule for a rendered path without a managed lock entry: clean when it
    equals the render, else a conflict with the guidance above.
- A project customizes a managed file only through `hub.json` or a seeded sibling extension file:
  - Markdown: `X.md` is paired with an optional seeded `X.project.md`; the managed `CLAUDE.md` imports both
    `AGENTS.md` and `AGENTS.project.md`, so project rules take effect without a sync and the lock stays stable.
  - Makefile: the managed `Makefile` ends by including a seeded `Makefile.project` if it exists, also without a sync.
  - JSON: a seeded `*.project.json` sibling (for example `.claude/settings.project.json`) is deep-merged over the
    template output; the merged file is managed and hashed like any other, so a change to the sibling takes effect at
    the next sync. The same holds for the links to a new entry under `plugin/<project>/`.
- An existing hand-made hub joins this model through `hub sync --adopt`, which can be re-run: files equal to the
  render become managed, the others are listed and left untouched, and `--accept PATH` takes the template version of
  one listed file. Until every rendered managed path is in the lock, plain `hub sync` stops on the rest as conflicts.
  Git history is never rewritten.

### Consequences

- Good: a project edit is never silently lost; the worst case is a sync that stops and shows a diff.
- Good: sync and adopt are pure planning over (render, lock, disk) and are unit-tested without a real hub; the same
  inputs always give the same bytes, and a no-op sync writes nothing.
- Good: the lock makes drift visible to `hub doctor` without rendering the templates.
- Bad: a project cannot change one line of a managed file in place; it needs an extension point, and a missing one
  becomes a template change in agent-hub.
- Bad: each file type needs its own extension mechanism (import, include, deep merge), and the managed files must be
  written so the extension point exists.
- Neutral: 3-way merge was rejected because it produces conflicts inside rule and prompt files, which are hard to test
  and hard for an agent to resolve correctly; marker blocks were rejected because a hand edit can break the markers
  and because they are useless for JSON (no comment syntax) and fragile in YAML (indentation carries meaning);
  generate-once was rejected because hubs would drift from the templates with no way to see or repair it. New
  `hub.json` keys for project JSON additions were rejected because the config would grow a key for every Claude Code
  setting and have to follow each change of that tool's settings format.

## More Information

- [design/hub-generator.md](../design/hub-generator.md): classification of every generated file, the lock format, the
  sync and adopt steps and their exit codes.
- [ADR 0010](0010-hub-json-config-contract.md): the `hub.json` contract the templates are rendered from.
