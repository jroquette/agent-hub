# Hub sync: hub.lock, hub sync, --check and --adopt

## Purpose

Phase 1 contract for `hub.lock`, `hub sync [--check]`, the one write path `hub init` shares, the `*.project.json`
merge and the project-entry links; `hub sync --adopt`: [hub-adopt.md](hub-adopt.md). What is rendered and who owns it,
`hub init`, hooks, commands: [hub-generator.md](hub-generator.md). Config: [project-config.md](project-config.md).

## Contract

### hub.lock

`hub.lock` (JSON, in the one JSON form): `lock_version` (1), `platform_version`, `schema_version`, `modules` (sorted)
and `files` by path: a managed file (SHA-256 of the LF bytes written, executable bit), a managed link (relative
target) or seeded (no hash). "Equal": same bytes and executable bit, or same link target. It never lists itself or
`.git`, and `hub.json` is always recorded seeded: it is the project's, never compared, written or deleted. The lock is
a function of the render and the config only (`build_hub_lock`), written by `init` and `sync`, last.

### hub sync

1. **Root:** the real path of the cwd, taken once; no `--dir`, no walk-up (a worktree syncs itself).
2. **Load**, each step exiting 1 before anything after it is read: `hub.json` (none: the reader's `cannot read` line,
   then `hub.json: run hub sync in the hub folder`); running CLI = `platform.version` (else only the pinned `uvx`
   command), `schema_version`, the model (`hub.json: <json path>: <message>`); then `hub.lock`, read once and never
   through a link. Absent: `hub.lock: not found; run hub sync --adopt to join this hub to the lock`. A link, folder,
   FIFO or other non-regular file is never opened: `hub.lock: not a regular file`. Malformed: one line per problem,
   `hub.lock: <json path>: <message>` (JSON errors worded as for `hub.json`; the model's messages without class names;
   `lock_version` other than 1; a `hub.json` entry that is not seeded: `must be seeded: hub.json is the project's`; a
   key or string holding a lone surrogate: `not UTF-8 text: holds a lone surrogate`, reported alone). Both end with
   `hub.lock: restore it from git, or run hub sync --adopt`.
3. **Read** after the render, only what is planned: every rendered path and every lock path but `hub.json` and
   `hub.lock`, each ancestor looked at without following it and the descent stopped at the first that is not a folder;
   content only for the files compared (rendered managed, managed file entries); the listing of each folder holding a
   planned path (the root too), for leftovers; and of `plugin/<project>/{agents,skills}`, each name it links looked at in
   `.claude/<folder>/`, never listed. Unknown entries (run output, FIFOs, unreadable folders, extra `.claude/skills/`
   entries) are never read or touched. An I/O error exits 1 naming the path.
4. **Plan** in memory (core `plan_sync`), each path in this order: (a) an ancestor that is a link or not a folder:
   conflict; (b) a link on disk resolving outside the hub: conflict; (c) equal to the render: clean, recorded, whatever
   the lock says (so a file an interrupted sync wrote is never a conflict); (d) the type rule; (e) ownership. (a) and
   (b) apply to the paths sync writes, deletes or compares; a seeded path with a lock entry is never looked at.
   - **Rendered managed.** Managed entry: absent → write, `restored`; disk equal to the entry → write, `updated`;
     else conflict. No entry or a seeded one: absent → write, `created` (never `restored`); present → conflict.
   - **Rendered seeded.** No entry: absent → write, `created`; a regular file → recorded; a link, folder or other →
     conflict. Seeded entry: nothing, whatever is on disk (deleted stays deleted). Managed entry (managed → seeded):
     the file, or its absence, stays; recorded seeded.
   - **In the lock, not rendered.** Seeded → entry dropped. Managed: gone → dropped; equal to the entry → deleted,
     `deleted`; else conflict. A rename is a delete plus a create.
   - **Type.** A file or folder where a link is rendered, or the reverse, is a conflict even when equal to its entry
     (delete it and re-run); so is a rendered path whose ancestor is a file, even one planned for deletion.
   - **Lock.** The new lock is always `build_hub_lock` of the render, written when its bytes differ from the bytes read:
     a header change, a dropped entry, a missing `hub.json` entry or a reformatted lock rewrite only `hub.lock`.
   - **Leftovers:** a file or link named `.<name>.hub-tmp-<8 hex>` in a listed folder, never a planned path.

### Output and exit codes

- **Changes** (stdout): one line per changed path, sorted by path, files and links alike: `created P`, `restored P`,
  `updated P`, `deleted P`; then `removed N leftover temporary files`; then `updated hub.lock` last whenever the lock is
  written (a lock-only change prints only that). Nothing pending (no file action, lock bytes identical): exactly
  `up to date`, and the adapter is not called.
- **`--check`** writes nothing and prints the same lines with `would ` before the verb (`would create P`,
  `would remove N leftover temporary files`, `would update hub.lock`): exit 4 when anything is pending, creations and
  leftovers included; else `up to date`, exit 0.
- **Conflicts** win, with or without `--check`: stdout empty; on stderr each conflicted path in path order, then the
  way out `move the change to an extension file (hub.json, a *.project.* file, Makefile.project), restore or delete
  the file, then re-run hub sync`; nothing written; exit 3. A text file gives a unified diff of disk against render,
  labels `--- P (on disk)` and `+++ P (render)`, 3 lines of context, at most 200 lines per path (labels, `@@` headers
  and `\ No newline at end of file` counted), then `… N more lines`. Lines split on `\n` only, so a `\r` shows; a line
  holding an unprintable character (a tab aside) is shown as a JSON string. Not UTF-8 or holding a NUL:
  `P: binary content differs (on disk sha256 <12 hex>, render <12 hex>)`. Other causes, one line `P: <cause>`:
  `executable bit differs (on disk +x, render -x)`, `link target differs (on disk -> X, render -> Y)`,
  `differs from its hub.lock entry and is no longer rendered` (bytes, bit or target), `symlinked ancestor A`,
  `a file where a folder belongs: A`, `resolves outside the hub`, or `init`'s type wording (`a link where a file
  belongs`, `not a regular file`, …). A name clash: below.
- **Exits:** 0 done or up to date; 1 error (config, lock, extension inputs, I/O; one escaped line each, stderr); 2
  usage; 3 conflict; 4 `--check` with changes pending.

### Apply

The writer opens the root once per apply, checked against its real path by device and inode, after checking every path
it is given (plain, relative) and before touching any. Order: leftovers, deletes, missing folders (parents first),
files, links (each in path order), `hub.lock` last. Each path is written through `.<name>.hub-tmp-<8 random hex>` in its
folder (`O_CREAT|O_EXCL|O_NOFOLLOW`, 0o600; a link: `os.symlink`), given its final mode, then `os.replace`d; on an error
the adapter removes its own temp entry. A delete unlinks a regular file or a link, never a folder, never recursively;
another type is an error; a gone entry is fine, a gone parent is an error. Folders emptied by a delete stay. `init` uses
the same writer (leftovers: the whole tree but `.git`). Reader and writer descend by `O_DIRECTORY|O_NOFOLLOW`
descriptors, so neither follows a symlinked ancestor of a path it touches, nor opens a non-regular file; a link
resolving outside the hub is refused (accepted risk: both resolve it by path, so a folder swapped meanwhile can escape;
the writer's root check narrows that). Found only by the writer (a race), a symlinked ancestor or an I/O error exits 1
naming the path and cause. An interrupted sync leaves the old `hub.lock`; the next run ends where a clean one would.

### --adopt

`hub sync --adopt [--accept PATH]…` joins a hand-made hub to the lock: [hub-adopt.md](hub-adopt.md).

### Project JSON and project entries

A seeded built `X.project.json` pairs with a managed built `X.json` (`.claude/settings.project.json`; module
`marketplace`: `.claude-plugin/marketplace.project.json`); `sync` and `init` read a present sibling and deep-merge it
into `X.json` (absent or deleted: the template's). Objects merge by key, the project wins on scalars, arrays are the
template's items then the project's, a repeat dropped keeping the first (equal: the same `dump_json` bytes, so `true` ≠
`1`, `1` ≠ `1.0`); a rerun gives the same bytes. The merge only adds. A bad sibling exits 1, nothing written, with one
line `P: <key path>: <message>` (`permissions.allow`, `hooks[0]`, `$` the root): a refused key first, else the first
problem in the sibling's key order. At `$`: the parser's words (not UTF-8, a BOM, bad JSON, over 4300 digits, nested too
deeply) and, strictly, `not valid JSON here: ` then `the key "<k>" appears more than once`, `NaN|Infinity|-Infinity is
not a JSON number`, `a number is too large for this reader` or `a string holds a lone surrogate escape` (a key too).
Refused by presence in `.claude/settings.project.json`: `disableAllHooks` and `permissions.defaultMode`, `refused: a
project cannot set this key (it weakens the harness)`. Refused in the marketplace sibling: `name`, `owner` (`refused:
the managed marketplace.json owns this key`), a plugin named `hub-workflow` or `<project>` (`… entry`), a repeated
plugin name, an entry not an object with a string `name`; its other keys are the project's. An object or array against
another type, the root included: `<an object|an array|a string|a boolean|a number|null> where the template has <…>`. A
`null` at any depth, in new keys and items too: `null is refused: the merge never deletes a key`. A link, folder or
other non-regular sibling: `P: not a regular file`.

`sync` links each regular file in `plugin/<project>/agents` and each real folder in `skills`, whatever it holds:
`.claude/<folder>/<name>` → `../../plugin/<project>/<folder>/<name>`, managed and locked like a base link. Names
starting with `.`, links, other types and nested paths are left alone; a file already at a link path is a conflict,
never replaced. A name the lock cannot hold exits 1 (nothing written): `plugin/<project>/<folder>/<name>: cannot be
linked: <reason>`, first of `not UTF-8`, `holds a backslash`, `not printable`. Names equal after NFC and `casefold()`
are one (one entry on APFS); a clash is a conflict, exit 3, the base link kept: `.claude/<folder>/<name>: in both
plugins (<base entry> and plugin/<project>/<folder>/<name>)`, or at each of two project names `named twice in
plugin/<project>, ignoring case and Unicode form (<other> and <own>)`. A case-only rename deletes and creates the link
on Linux; on APFS it finds the old link: `link target differs`, exit 3, until that link is deleted. `init` merges a kept
sibling but links no entry: an unlinkable name exits 1, others are unknown (`hub sync --adopt`).

## Invariants

- Sync plans every path before its first write; a load error or a conflict writes, creates and deletes nothing.
- It deletes only a managed path equal to its entry and leftovers in listed folders; it never writes `hub.json`, never
  removes a folder, and never reads or touches a path neither rendered nor in the lock, bar listing project entries.
- Same `hub.json`, release and extension inputs, same tree and `hub.lock` bytes; after any successful sync the lock is
  `build_hub_lock` of the render, and a second sync prints `up to date` and writes nothing, not even `hub.lock`.
- The planner is pure core code; reads and writes go through the generator's adapter from the held root.

## Decisions

- [ADR 0009](../adr/0009-hub-sync-by-file-ownership.md): ownership, lock, sync, adopt; no 3-way merge or marker blocks.
- [ADR 0011](../adr/0011-templates-as-package-data.md): the planner in core, the file adapter in the generator, no port.
- [ADR 0013](../adr/0013-release-by-git-tags.md): a CLI other than the pin refuses sync and prints the pinned command.

## Open questions

- Harness-weakening keys beyond ADR 0009's two (`disableAllHooks`, `permissions.defaultMode`): a new ADR if wanted.
