# 0009. Hub sync by per-file ownership

- Status: accepted
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
  managed file, its path, the SHA-256 hash of the bytes written and the executable bit (for a link, its relative
  target). Seeded files are listed without a hash. It also records the schema version and the selected modules.
  Entries have a fixed shape: a managed file `{"ownership": "managed", "sha256": "<hex>", "executable": false}`, a
  managed link `{"ownership": "managed", "symlink": "<relative target>"}`, a seeded path `{"ownership": "seeded"}`.
- The generated output is a function of three inputs only: `hub.json`, the platform version, and the seeded extension
  inputs (`*.project.json` files, `AGENTS.project.md`, and the entries present under `plugin/<project>/`).
- Sync loads and checks its inputs first, in this order: the running CLI against the pin
  ([ADR 0013](0013-release-by-git-tags.md)), then the config's schema version and the whole config
  ([ADR 0010](0010-hub-json-config-contract.md)), then the presence of `hub.lock` (only adopt, below, runs without
  it). Any failure writes nothing and exits 1 naming the fix; the pin comes first because a CLI of another release may
  not understand the config at all, and its fix (run the pinned release) also settles a schema version mismatch.
- Sync plans every path before writing anything. It plans only paths that are rendered or recorded in the lock; any
  other path is unknown and is never written, moved or deleted. A managed directory such as `.claude/skills/`
  owns only the entries the lock lists; anything else inside it is unknown too. "Equal" compares the bytes and the
  executable bit of a file, and the target of a link, stored relative to the link. Per path, in sorted order:
  - Rendered and equal on disk: clean whatever the lock says; sync only records it. This makes an interrupted run,
    and a re-run of `init`, `sync` or `adopt`, safe.
  - Managed and recorded as managed: when it equals its lock entry, it is rewritten with the new render. Missing from
    disk, it is written again and reported as `restored <path>`: the templates own it, and nothing of the project is
    lost. `restored` is only for a path recorded in the lock.
  - Managed, rendered, with no lock entry and absent from disk (a new template file, or a module just selected): it is
    created and reported as `created <path>`.
  - Managed and no longer rendered: deleted when it equals its lock entry, its entry dropped when it is already gone,
    a conflict otherwise. A rename is a delete plus a create.
  - Managed to seeded: the file stays as it is, and only its lock entry changes. If the file is missing, it
    is recorded as seeded and not created.
  - Seeded and absent from the lock: created only when absent on disk; a file already there is recorded as seeded
    and left alone. Seeded and in the lock: never touched, even when deleted; dropped from the lock when no longer
    rendered. An empty seeded directory is a seeded `.gitkeep`, since git does not track directories.
  - Conflicts: a managed file that differs from both its lock entry and the render (an edit); a rendered managed path
    on disk without a managed lock entry (including seeded to managed); a real file or directory where a link is
    rendered, or the reverse (never removed, and never recursively); a path with a symlinked ancestor (below); and one
    agent or skill name present in both plugins. Sync prints a diff (or the cause) per path, writes nothing and exits
    3. The way out is to move the change into an extension file, then restore the file from git or delete it (git
    keeps its history), and re-run; plain sync has no flag that overwrites an edit.
  - The lock header (`platform_version`, `schema_version`, `modules`) is part of the plan: when it differs, sync
    rewrites the lock even if no file changes. With nothing to change, sync writes nothing and prints `up to date`.
  - `--check` plans and writes nothing: it exits 3 when a conflict exists and 4 when only changes are pending; a path
    to create counts as pending.
- The file adapter never follows a symlinked parent. Before it writes, deletes or compares a path, it `lstat`s every
  ancestor between the hub root and that path; a symlinked ancestor makes the path a conflict (or, for adopt, the
  migration below), so a link planted in the hub can never redirect a write or a delete outside the files it names.
  It also refuses any link, managed or found on disk, whose target resolves outside the hub.
- A project customizes a managed file only through `hub.json` or a seeded sibling extension file:
  - Markdown: `X.md` is paired with an optional seeded `X.project.md`; the managed `CLAUDE.md` imports both
    `AGENTS.md` and `AGENTS.project.md`, so project rules take effect without a sync and the lock stays stable.
  - Makefile: the managed `Makefile` ends by including a seeded `Makefile.project` if it exists, also without a sync.
  - JSON: a seeded `*.project.json` sibling (for example `.claude/settings.project.json`) is deep-merged over the
    template output; the merged file is managed and hashed like any other, so a change to the sibling takes effect at
    the next sync. The same holds for the links to a new entry under `plugin/<project>/`. The merge is strict:
    objects merge by key and the project wins on scalars; arrays are concatenated, template first, then de-duplicated
    by deep equality, keeping the first occurrence. A malformed sibling, a type mismatch (a project scalar where the
    template has an object or array, or the reverse) and a `null` value (the merge never deletes a template key) each
    make sync exit 1 naming the file and key path. Keys that weaken the harness are refused the same way: in
    `.claude/settings.project.json`, `disableAllHooks` and `permissions.defaultMode`; base hooks cannot be removed at
    all, because the merge only adds. `hub doctor` checks the same keys (rule `settings.weakening`).
  - `.gitignore` is seeded, written with the base entries at `hub init`: projects add to it freely, and a new base
    entry reaches existing hubs as a documented manual edit.
- An existing hand-made hub joins this model through `hub sync --adopt`, which can be re-run and needs no `hub.lock`
  (it writes one). Paths already in the lock follow the sync rules above. For a path not in the lock, adopt acts in
  the same run: a file equal to the render is recorded as managed; a missing managed file is written; a seeded path is
  recorded as seeded and created when absent (an empty `plugin/<project>/` included); a differing file is listed with
  its line counts, left untouched and kept out of the lock. The partial `hub.lock` is saved even when adopt then exits
  3 because something is listed, so the next run starts from what is already settled; with nothing listed it exits 0,
  and on a fully adopted hub with nothing to do it is a no-op that prints `up to date`.
- A directory symlink where a managed directory of per-entry links is rendered (a hand-made hub whose `.claude/skills`
  or `.claude/agents` points into its plugin folder) is listed as a migration, not a conflict: without `--accept` it is
  a listed difference (exit 3); `--accept .claude/skills` (and the same for agents) removes the directory link itself,
  never the contents of its target, and writes a real directory holding one link per entry of both plugins.
- `--accept PATH`, repeatable, takes the template version of a path that this run lists as different or as a
  migration; it overwrites the working file, so only what was committed survives in git. Other conflict kinds (a file
  or directory where a link belongs or the reverse, other symlinked ancestors, a name in both plugins) are listed as
  conflicts and `--accept` refuses them, as it refuses any path this run does not list (usage error, exit 2). Until
  every rendered managed path is in the lock, plain `hub sync` stops on the rest as conflicts. Adopt never commits,
  and git history is never rewritten.

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
  and that an agent cannot resolve reliably; marker blocks were rejected because a hand edit can break the markers
  and because they are useless for JSON (no comment syntax) and fragile in YAML (indentation carries meaning);
  generate-once was rejected because hubs would drift from the templates with no way to see or repair it. New
  `hub.json` keys for project JSON additions were rejected because the config would grow a key for every Claude Code
  setting and have to follow each change of that tool's settings format.

## More Information

- [design/hub-generator.md](../design/hub-generator.md): classification of every generated file, the lock format, the
  sync and adopt steps and their exit codes.
- [ADR 0010](0010-hub-json-config-contract.md): the `hub.json` contract the templates are rendered from.
