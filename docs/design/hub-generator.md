# Hub generator: init, sync, adopt, hooks and commands

## Purpose

Phase 1 contract for `hub init`, `hub sync` and `--adopt`, the hooks and plugin wiring, the commands that replace the
hub scripts, and how the CLI ships. The config is [project-config.md](project-config.md); the reasons are in the ADRs.

## Contract

### Classification

Kind: `generic` (same for every project), `module` (only when selected in `modules`) or `project-owned`. Ownership:
`managed` (sync rewrites it), `seeded` (written once when absent, then never touched) or `not generated`.

| Entry in a generated hub | Kind | Ownership |
|---|---|---|
| `hub.json` (`hub.lock` is tool state: written by init and sync, not listed in itself) | project-owned | seeded |
| `hub.schema.json`, `AGENTS.md` and `CLAUDE.md` (base rules), `Makefile`, `agent` launcher (shim), `.gitignore`, `.pre-commit-config.yaml`, `.github/workflows/ci.yml` | generic | managed |
| `AGENTS.project.md` (project rules, created empty); `Makefile.project`; `README.md` | project-owned (`README.md` generic) | seeded |
| `.claude/settings.json` (merged with a seeded `.claude/settings.project.json`), `.claude/agents/` and `.claude/skills/` (links into the plugins) | generic (+ project-owned) | managed (+ seeded) |
| `plugin/hub-workflow/**` (base agents, skills, hooks) | generic | managed |
| `plugin/<project>/**` (project agents, skills, guard extension) | project-owned | seeded |
| Brain skeleton: `brain/index.md`, `brain/now.md`, `brain/decisions/index.md`, folder `.gitkeep`s, journal template | generic | seeded |
| `scripts/` transcript mining, recall and retro metrics | generic | managed (until Phase 2) |
| `scripts/cloud-setup.sh`, `scripts/contract-sync.sh`, `mk/<module>.mk`, `.claude-plugin/marketplace.json` (merged with a seeded `marketplace.project.json`) | module: `cloud`, `contract-sync`, the selecting module, `marketplace` | managed (+ seeded) |
| Worktree, brief, runner, benchmark, config-lint and feature-check scripts | generic (`bench`: module) | not generated: `hub` commands |
| Brain content, bench cases, hub `tests/`, `workflows/` (Phase 4), run output (`.agent-runs/`), domain rules (for Loki: red-chain, Decimal, paper/testnet, kept in `AGENTS.project.md`) | project-owned | not generated |

### Rendering and extension files

Output depends only on `hub.json`, the platform version and the seeded extension inputs (`*.project.json`,
`AGENTS.project.md`, entries under `plugin/<project>/`). Text templates use a `string.Template` subclass with the `@@`
delimiter and always `substitute`; a test asserts no `@@` survives. A project changes a managed file only via `hub.json`
or a seeded sibling. Effective at once: the managed `CLAUDE.md` imports `@AGENTS.md` and `@AGENTS.project.md`; the
managed `Makefile` includes `mk/<module>.mk` per selected module and ends with `-include Makefile.project` (redefining a
managed target is a `makefile.override` finding). Effective at the next sync: a seeded `*.project.json` sibling is
deep-merged over the template (objects by key, project wins on scalars, arrays concatenated then de-duplicated).

### hub.lock

JSON at the hub root, sorted keys, 2-space indent, final newline; SHA-256 of the bytes written (LF endings). Top level:
`lock_version` (1), `platform_version`, `schema_version`, `modules` (sorted ids) and `files`, keyed by path: a managed
file `{"ownership": "managed", "sha256": "<hex>", "executable": false}`, a managed link `{"ownership": "managed",
"symlink": "<target>"}`, a seeded file `{"ownership": "seeded"}` (no hash).

### hub init

`hub init <project> --repos org/a,org/b --tracker linear:TEAM [--dir PATH]` writes a schema-1 `hub.json` (repo `dir` =
name, `role` = `app`, checks `make check-fast` / `make check`, `platform.version` = the running CLI; author,
`branch_prefix` and `hub_repo` from `git config` and `origin`, else exit 1 naming the flag). `--config PATH` validates
and copies a `hub.json` instead. The target may hold only `.git`, seeded files (kept) and files equal to their
render, else exit 1 pointing to `--adopt`. Init writes the rest and `hub.lock`, runs no git command, and prints
`created N files (M managed, K seeded)`.

### hub sync

1. Validate `hub.json` of the current checkout (a worktree syncs itself); the running CLI must equal `platform.version`
   and `hub.lock` must exist, else exit 1 naming the fix (the pinned shim, `hub sync --adopt`).
2. Render in memory in sorted path order; classify each path ([ADR 0009](../adr/0009-hub-sync-by-file-ownership.md)):
   - bytes equal to the render: clean, whatever the lock says; only the lock entry is recorded;
   - managed and equal to its lock hash, or missing: write the render; seeded and absent from the lock: create it;
   - managed and left the template: delete it if equal to its lock hash; a rename is a delete plus a create;
   - managed to seeded: keep the file, change the entry; a seeded file in the lock but gone from disk: never recreate;
   - conflict: a managed file differing from both its lock hash and the render, or a rendered managed path on disk
     without a managed lock entry (including seeded to managed): print a diff per file, write nothing, exit 3. Way out:
     move the change to an extension file, restore or delete the file (git keeps it), re-run; no flag overwrites it.
3. Write via a temporary file and a rename, `hub.lock` last; nothing to do: write nothing, print `up to date`. Exits:
   0 done; 1 error (config, version, I/O); 2 usage; 3 conflict; 4 `--check` dry run with changes pending.

### hub sync --adopt

Re-runnable; never commits or rewrites git history. Files equal to the render become `managed`, seeded paths are
recorded `seeded`, and missing seeded files are created, including an empty `plugin/<project>/`. Differing files are
listed (`<path>: +a -b lines`), left untouched and out of the lock (exit 3; 0 when none differ); `--accept PATH` takes
the template version of one. Plain `hub sync` exits 3 while an adopted-but-different managed path remains.

### Plugin and .claude wiring

`plugin/hub-workflow/` is the managed base plugin, named the same in every hub; `plugin/<project>/` is seeded
(`.claude-plugin/plugin.json`, empty `agents/` and `skills/`, a guard extension stub). Cloud sessions do not install
repo-declared plugins, so `.claude/agents/` and `.claude/skills/` are managed directories of one link per entry of both
plugins (a new project entry is linked at the next sync; a name in both is a conflict), and `.claude/settings.json`
carries the hooks block. The marketplace is optional; on adoption Loki drops its installed plugin for this wiring.

### Hooks

Managed stdlib scripts in `plugin/hub-workflow/hooks/`, run by the system `python3` (3.9 or newer), that read
`hub.json` through a shared defensive reader and fail open: a hook never errors the session. They never call the CLI,
except SessionStart, once per session: it runs the pinned `hub brief` like a shim, with a short timeout, and falls back
to a stdlib mini brief (`brain/now.md`, the latest journal entry, the pre-compact snapshot) on any failure or timeout.
Guard extension: the seeded `plugin/<project>/hooks/project_guard.py`, resolved from the hub root (the hook's location
or `CLAUDE_PROJECT_DIR`, never the current directory or tool input), run after the base checks with a time bound. Its
`check(event: dict, cfg: Config) -> Optional[Tuple[str, str]]` receives the PreToolUse payload and parsed config and
returns `None`, `("deny", reason)` or `("ask", reason)`; the strictest wins. Missing file: skipped; timeout, import
error or exception: `ask` with the cause. The base guard asks before edits to the extension, the hooks directory,
`.claude/settings*.json`, `hub.lock` and `hub.json`. Proof: hook unit tests.

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
| `mine_transcripts.py`, `recall_transcripts.py`, `retro_metrics.py`, `make mine`, `make retro` | stay hub files | AGH-5 R12: Phase 2 redesigns them |
| `make usage`, `make check`, `make help` | stay targets; `check` runs `hub doctor` and the hub's own tests | `usage` wraps an external cost tool until the Phase 2 cost view; hook tests move to agent-hub |
| `guard.py`, `hubhooks.py`, `hooks.json`, `post_edit.py`, `stop_gate.py`, `session_start.py`, `session_end.py`, `pre_compact.py` | stay hub files, managed | hooks exception, AGH-5 D9 ([ADR 0012](../adr/0012-cli-subsumes-hub-scripts.md)) |

A shim runs the pinned release; without uv it says how to install uv and exits 127. A script is deleted in the release
where its command lands, after characterization tests for the untested ones (brief, bench, retro, lint, cloud setup,
four hooks). Order: `worktree`, `brief`, `doctor`, `agent`, `next`/`run`, `bench`.

### Distribution

Releases are semver tags `vX.Y.Z` on agent-hub `main`, made by the owner and checked against the meta-package version
by CI; no PyPI. Shims run `uvx --from SRC hub …`, SRC being the pinned source (uv caches each version, no install):
`git+https://github.com/jroquette/agent-hub@v<platform.version>#subdirectory=packages/agent-hub`. For `hub init`:
`uv tool install git+https://github.com/jroquette/agent-hub@vX.Y.Z#subdirectory=packages/agent-hub`, or `uvx` alike.
Private access: a read-only secret in hub CI; the repo attached or `GH_TOKEN` in other projects' cloud sessions, where
the `cloud` module's setup script checks access and warms the cache. A direct `hub` whose version differs from
`platform.version` makes `hub sync` exit 1 and `hub doctor` report an error. Upgrade: edit `platform.version`, sync.

### Acceptance

Each hub's `ci.yml` has a golden job: copy `hub.json` and the seeded extension inputs to `$tmp`, run the pinned
`hub init --config hub.json --dir "$tmp"`, compare the managed lock entries and bytes (brain content and seeded files
excluded). agent-hub tests a synthetic `demo` project: two inits are byte-identical, a no-op or interrupted-then-rerun
sync is clean, an edit exits 3, adopt lists differences, the `hub.lock` snapshot is committed. Loki: write `hub.json`,
move guard rules to `guard.*` and `project_guard.py`, domain rules to `AGENTS.project.md`, then adopt.

## Invariants

- No operation silently overwrites or deletes a project edit; seeded files are written once; same inputs, same bytes.
- A no-op sync writes nothing; any init, sync or adopt can be re-run; hooks work without the CLI; agent-hub holds no
  project-owned material.

## Decisions

- [ADR 0009](../adr/0009-hub-sync-by-file-ownership.md): ownership, lock, sync; 3-way merge, marker blocks rejected.
- [ADR 0011](../adr/0011-templates-as-package-data.md): templates as package data, the `@@` renderer, no new port.
- [ADR 0012](../adr/0012-cli-subsumes-hub-scripts.md): logic in the CLI, shims, the hooks exception, the in-hub plugin.
- [ADR 0013](../adr/0013-release-by-git-tags.md): semver tags, the per-hub pinned run, credentials, mismatch.

## Open questions

- Timeout of the SessionStart `hub brief` call and of the guard extension: template constants, set in their issues.
