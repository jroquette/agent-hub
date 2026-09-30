# Hub generator: init, sync, adopt, hooks and commands

## Purpose

Phase 1 contract for `hub init`, `hub sync`, `--adopt`, hooks, plugin wiring, the commands that replace the hub
scripts, and how the CLI ships. Config: [project-config.md](project-config.md); full rules and reasons: the ADRs.

## Contract

### Classification and rendering

Kind: `generic` (same for every project), `module` (only when selected in `modules`) or `project-owned`. Ownership:
`managed` (sync rewrites it), `seeded` (written once when absent, then never touched) or `not generated`.

| Entry in a generated hub | Kind | Ownership |
|---|---|---|
| `hub.json` (`hub.lock` is tool state: written by init and sync, not listed in itself) | project-owned | seeded |
| `hub.schema.json`, `AGENTS.md` and `CLAUDE.md` (base rules), `Makefile`, `agent` launcher (shim), `.pre-commit-config.yaml`, `.github/workflows/ci.yml` | generic | managed |
| `AGENTS.project.md` (project rules, created empty); `Makefile.project`; `README.md`; `.gitignore` (base entries) | project-owned (`README.md`, `.gitignore` generic) | seeded |
| `.claude/settings.json` (merged with a seeded `.claude/settings.project.json`; it runs the base hooks, so a hub never enables `hub-workflow`: Claude Code drops only identical duplicate hook commands), `.claude/agents/` and `.claude/skills/` (one link per entry of both plugins, since cloud sessions do not install repo-declared plugins; not dotfiles such as `.gitkeep`; a new project entry is linked at the next sync) | generic (+ project-owned) | managed (+ seeded) |
| `plugin/hub-workflow/**` (base agents, skills, hooks; same name in every hub; on adoption, Loki's `loki-workflow` becomes it plus `plugin/loki/`) | generic | managed |
| `plugin/<project>/**` (project agents, skills, guard extension; empty folders hold a `.gitkeep`) | project-owned | seeded |
| Brain skeleton: `brain/index.md`, `brain/now.md`, `brain/decisions/index.md`, folder `.gitkeep`s, journal template | generic | seeded |
| `scripts/` transcript mining, recall and retro metrics | generic | managed (until Phase 2) |
| `scripts/cloud-setup.sh`, `scripts/contract-sync.sh`, `mk/<module>.mk`, `.claude-plugin/marketplace.json` (merged with a seeded `marketplace.project.json`) | module: `cloud`, `contract-sync`, the selecting module, `marketplace` | managed (+ seeded) |
| Worktree, brief, runner, benchmark, config-lint and feature-check scripts | generic (`bench`: module) | not generated: `hub` commands |
| Brain content, bench cases, hub `tests/`, `workflows/` (Phase 4), run output (`.agent-runs/`), domain rules (for Loki: red-chain, Decimal, paper/testnet, kept in `AGENTS.project.md`) | project-owned | not generated |

Output depends only on `hub.json` (values validated or quoted: [project-config.md](project-config.md)), the platform
version and the seeded extension inputs (`*.project.json`, `AGENTS.project.md`, entries under `plugin/<project>/`); text
templates use `@@` placeholders, always substituted. A project changes a managed file only via `hub.json` or a seeded
sibling: `CLAUDE.md` imports `@AGENTS.md` and `@AGENTS.project.md`; the `Makefile` includes `mk/<module>.mk` per
selected module, then `-include Makefile.project`; a `*.project.json` is deep-merged at the next sync (strict: bad input
or a harness-weakening key exits 1). Every JSON the generator builds or merges (settings, manifests, merged
`*.project.json`, `hub.lock`) has one form: sorted keys, 2-space indent, UTF-8, final newline.

### hub.lock and hub sync

`hub.lock` (JSON): `lock_version` (1), `platform_version`, `schema_version`, `modules` (sorted) and `files` by path: a
managed file (SHA-256 of the LF bytes written, executable bit), a managed link (relative target) or seeded (no hash).
"Equal": same bytes and executable bit, or same link target.

1. Load this checkout's `hub.json` (a worktree syncs itself), checking in order: running CLI = `platform.version`,
   `schema_version`, the model; `hub.lock` exists. Else exit 1 naming the fix (the pinned `uvx` command, `--adopt`).
2. Plan in memory, sorted, only paths rendered or in the lock (others, extra `.claude/skills/` entries too, are never
   touched). Equal to the render: clean, recorded. Managed in the lock: equal to its entry → rewrite; missing → write,
   `restored <path>`; no longer rendered → delete if equal (a rename is a delete plus a create). Rendered managed, no
   entry, absent: write, `created <path>`. Seeded, no entry: created if absent, else recorded; in the lock: never
   touched, even if deleted. Managed to seeded: the file (or its absence) stays. Conflict: a managed file differing from
   entry and render; a rendered managed path on disk with no managed entry; a file or directory where a link belongs, or
   the reverse; a name in both plugins; a symlinked ancestor. Print a diff or cause per path, write nothing, exit 3. Way
   out: move the change to an extension file, restore or delete the file, re-run.
3. Write each path through `.<name>.hub-tmp-<8 random hex>` in its folder (`O_CREAT|O_EXCL|O_NOFOLLOW`, 0o600; a link:
   `os.symlink`), give it its final mode, `os.replace` it; `hub.lock` last. On an error the adapter removes its own temp
   entry. A file or link (not a folder) of that shape is a leftover, never unknown or locked, removed after the plan
   passes, before any write (init: the whole tree but `.git`; sync: planned folders). Nothing to do: `up to date`. The
   writer opens the root once per apply, checked against its real path by device and inode. Reader and writer descend by
   `O_DIRECTORY|O_NOFOLLOW` descriptors, so neither follows a symlinked ancestor of a path it touches, nor opens a
   non-regular file; a link resolving outside the hub is refused (accepted risk: both resolve that by path, so a folder
   swapped meanwhile can escape it; the writer's root check narrows that window). Exits: 0 done; 1 error (config, merge,
   version, I/O); 2 usage; 3 conflict; 4 `--check` (writes nothing): changes pending, creations included.

`--adopt` joins a hand-made hub; re-runnable, needs no `hub.lock`, never commits. Lock paths follow sync; others, in the
same run: equal → recorded managed; missing managed → written; seeded → recorded, created when absent (an empty
`plugin/<project>/` too); a differing file → listed (`<path>: +a -b lines`), untouched, out of the lock; a directory
link where a directory of per-entry links is rendered (e.g. `.claude/skills`) → listed as a migration. The partial
`hub.lock` is saved, then exit 3 if anything is listed, else 0. `--accept PATH` (repeatable) takes the template version
of a listed difference or migration (the directory link becomes a real directory of links), overwriting the working
file; other conflicts are listed and refused, like a path not listed this run (exit 2).

### hub init

`hub init <project> --repos org/a,org/b --tracker linear:TEAM --branch-prefix P [--dir PATH]` writes a schema-1
`hub.json` without defaults: repo `dir` = name, `github` = `org/name`, `role` = `app`, checks `make check-fast` / `make
check`, `platform.version` = the running CLI. Git is read (never written) for a missing value only, in the target (else
the cwd): `--author-name`/`--author-email` from `git config --get user.name`/`user.email`, `--hub-repo` from a GitHub
`remote.origin.url`, never printed, read only if the target is its work tree's top and none of `GIT_DIR`,
`GIT_WORK_TREE`, `GIT_COMMON_DIR` is set. `--branch-prefix` has no default. A missing or rejected value exits 1 naming
its flag and why (no value, `git not found`, `git timed out`, `git could not run`). `--config PATH` checks the pin (else
the pinned `uvx` command), schema and model, and copies it byte for byte; selected modules exit 1 until module templates
ship. `--dir` (default: the cwd) is created after every check. The target may hold only `.git`, seeded files (kept),
paths equal to their render and leftovers: a `hub.lock` exits 1 pointing to `hub sync`; a differing managed path, an
unknown entry or a `hub.json` other than this run's to `hub sync --adopt`; any other problem names its cause. Output:
`created N files (M managed, K seeded) and L links in <root>`; if any, `kept X files already there (Y seeded, Z equal to
the render)` (`and L links`) and `removed X leftover temporary files`; next steps. Exits: 0 done, 1 error, 2 usage.

### Hooks and plugin wiring

Managed stdlib scripts in `plugin/hub-workflow/hooks/`, run by the system `python3` (3.9 or newer), read `hub.json`
through `stdlib_reader.py` beside them and fail open: on a crash the guard asks, other hooks print one `skipped` line,
the stop gate does not block if it cannot save its block counter. `hub.json` is the one `$HUB_CONFIG` names (hub: its
folder), else the hook root's (the hub or hub worktree holding the hook files; a worktree reads its own `hub.json`, but
the hub is its main checkout and the workspace that checkout's parent), else (plugin cache) the first found walking up
from the start, a sibling hub only if the start is in it or a repo it lists. That file gives every value (repos and the
`check_fast` the stop gate runs, the `platform.version` SessionStart fetches, default branch, branch prefix, hub,
workspace), except that `$HUB_CONFIG`'s `ask_before_edit`, `deny_paths` and `deny_hosts` are added to the hook root's,
never replace them; the extension, `@hub/` anchors and guard-file asks stay pinned to the hook root. Only SessionStart
calls the CLI: one pinned `uvx … hub brief` (10 s timeout), else a mini brief naming the cause. Guard extension: the
seeded `plugin/<project>/hooks/project_guard.py` of the hook root (never from `CLAUDE_PROJECT_DIR`, the cwd or tool
input). Unless the base verdict is `deny` (final), it runs in a child `python3` in its own session (3 s, then killed
with its process group) and only tightens: `check(event, cfg)` returns `None`, `("deny", reason)` or `("ask", reason)`,
and the child, given the event JSON on stdin, prints it as one JSON value, `null` or `{"verdict": "deny"|"ask",
"reason": "..."}`; anything else (other verdict or type, non-zero exit, unparseable or extra output, timeout, a file
resolving outside the hub) gives `ask` with the cause; no file: skipped. The base guard asks before edits to
`plugin/hub-workflow/hooks/`, `plugin/<project>/hooks/`, `.claude/settings*.json`, `hub.lock` and `hub.json`. It is a
guardrail against mistakes, not a sandbox: it matches tool input and Bash text by pattern, so a determined agent can get
round it. The real limits are OS permissions and Claude Code's permission rules; the extension's trust boundary is the
ask on edits of the hooks folders. Proof: integration tests.

### Commands

| Hub item(s) | Becomes | Note |
|---|---|---|
| `worktree.sh`, `make worktree`, `make worktree-remove` | `hub worktree <name> [--only REPO]`, `--remove <name>` | keeps the per-repo setup/teardown scripts |
| `brief.py`, `make brain-brief` | `hub brief` | SessionStart calls it (Hooks) |
| `agent_runner.py`, `make next`, `make run-issue` | `hub next`, `hub run <issue> --repo REPO [--live]` | through `TrackerClient` |
| `agent`, `make agent` | shim for `hub agent` | adds each repo dir and appends its `AGENTS.md` |
| `bench.py`, `make bench`, `make bench-validate` | `hub bench [--validate]`, module `bench` | cases stay in the brain |
| `agent_config_lint.py`, `features_check.py`; `hubconfig.py` | doctor rules ([hub-doctor.md](hub-doctor.md)); `hubconfig.py` dropped (the CLI reads `HubConfig`) | skills run `hub doctor --only features.tracker` |
| `cloud-setup.sh` | stays a hub file, module `cloud` | bootstraps access and the uv cache, so it cannot need the CLI |
| `mine_transcripts.py`, `recall_transcripts.py`, `retro_metrics.py`, `make mine`, `make retro`; `guard.py`, `hubhooks.py`, `hooks.json`, `post_edit.py`, `stop_gate.py`, `session_start.py`, `session_end.py`, `pre_compact.py` | stay hub files, managed | scripts: AGH-5 R12, Phase 2 redesigns them; hooks: the hooks exception, AGH-5 D9 ([ADR 0012](../adr/0012-cli-subsumes-hub-scripts.md)) |
| `make usage`, `make check`, `make help` | stay targets; `check` runs `hub doctor` and the hub's own tests | `usage` wraps an external cost tool until the Phase 2 cost view; hook tests move to agent-hub |

A shim reads `platform.version` from `hub.json` at run time (stdlib `python3` one-liner). No uv: install hint, exit 127.
A resolve step, `uvx --from <pinned source> hub --version`, fails: names the missing access, exit 1. Then the real call;
its exit code passes through. A script is deleted when its command lands, after characterization tests of the untested
(brief, bench, retro, lint, cloud setup). Order: `worktree`, `brief`, `doctor`, `agent`, `next`/`run`, `bench`.

### Distribution

Releases are semver tags `vX.Y.Z` on agent-hub `main`, made by the owner and checked against the meta-package version by
CI; no PyPI. A shim runs the pinned release with no install (uv caches each version):
`uvx --from git+https://github.com/jroquette/agent-hub@v<platform.version>#subdirectory=packages/agent-hub hub …`.
`hub init` takes the same source via `uvx` or `uv tool install`. Private access: a read-only secret in hub CI; the repo
attached or `GH_TOKEN` in other projects' cloud sessions (the `cloud` setup checks access, warms the cache). Credentials
go through a git credential helper or `GIT_CONFIG_*` `insteadOf`, never the URL, `hub.json` or `hub.lock`. A direct
`hub` other than `platform.version`: `hub sync` exits 1, `hub doctor` errors. Upgrade: edit `platform.version`, sync.

### Acceptance

Each hub's `ci.yml` has a golden job: copy `hub.json` and the seeded inputs to `$tmp`, run the pinned `hub init
--config hub.json --dir "$tmp"`, compare managed lock entries and bytes. agent-hub tests a synthetic `demo`: identical
inits, no-op and rerun syncs, an edit exits 3, adopt lists differences, a `hub.lock` snapshot. Loki: write `hub.json`,
move guard rules to `guard.*`/`project_guard.py` and domain rules to `AGENTS.project.md`, adopt.

## Invariants

- No operation silently overwrites or deletes a project edit or an unknown path; seeded files are written once; same
  inputs, same bytes; re-runs are safe; hooks need no CLI; agent-hub holds no project-owned material.

## Decisions

- [ADR 0009](../adr/0009-hub-sync-by-file-ownership.md): ownership, lock, sync, adopt; no 3-way merge or marker blocks.
- [ADR 0011](../adr/0011-templates-as-package-data.md): templates as package data, the `@@` renderer, no new port.
- [ADR 0012](../adr/0012-cli-subsumes-hub-scripts.md): logic in the CLI, shims, the hooks exception, the in-hub plugin.
- [ADR 0013](../adr/0013-release-by-git-tags.md): semver tags, the per-hub pinned run, credentials, mismatch.

## Open questions

- None.
