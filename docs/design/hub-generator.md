# Hub generator: init, sync, adopt, hooks and commands

## Purpose

How `hub init` writes a hub from the templates, how `hub sync` keeps it current without losing project edits, how a
hand-made hub is adopted, how hooks and the plugin are wired, which commands replace the hub scripts, and how the CLI
ships. Phase 1 implements it; the config is [project-config.md](project-config.md), the reasons are in the ADRs.

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

### Extension files

A project changes a managed file only through `hub.json` or a seeded sibling. Markdown: the managed `CLAUDE.md` imports
`@AGENTS.md` and `@AGENTS.project.md`, so project rules apply without a sync. Makefile: the managed `Makefile` includes
`mk/<module>.mk` per selected module and ends with `-include Makefile.project` (redefining a managed target is a
`makefile.override` finding). JSON: a seeded `*.project.json` sibling is deep-merged over the template (objects by key,
project wins on scalars, arrays concatenated then de-duplicated in order); the merged file is managed and hashed.

### hub.lock

JSON at the hub root, sorted keys, 2-space indent, final newline; SHA-256 of the bytes written (LF endings). Top level:
`lock_version` (1), `platform_version`, `schema_version`, `modules` (sorted ids) and `files`, keyed by path: a managed
file `{"ownership": "managed", "sha256": "<hex>", "executable": false}`, a managed link `{"ownership": "managed",
"symlink": "<target>"}`, a seeded file `{"ownership": "seeded"}` (no hash).

### hub init

`hub init <project> --repos org/a,org/b --tracker linear:TEAM [--dir PATH]` builds a schema-1 `hub.json`: each repo gets
`dir` = its name, `role` = `app`, checks `make check-fast` / `make check`; `platform.version` = the running CLI. Values
no flag gives (author, `branch_prefix`, `hub_repo`) come from `git config` and the `origin` remote, else exit 1 naming
the flag. `hub init --config PATH [--dir PATH]` validates and copies an existing `hub.json`. The target (default: the
current directory) must be empty except for `.git`, else exit 1 pointing to `hub sync --adopt`. Init writes every file
and `hub.lock`, runs no git command, and prints `created N files (M managed, K seeded)` and the next steps.

### hub sync

1. Validate `hub.json` of the current checkout (a worktree syncs itself); the installed CLI must equal
   `platform.version` and `hub.lock` must exist, else exit 1 naming the fix (the install command, `hub sync --adopt`).
2. Render the template set for the config and modules in memory, in sorted path order.
3. Drift is a managed lock entry whose file is missing or whose hash differs; a conflict is a rendered managed path on
   disk without a lock entry. On any: print a unified diff (disk vs rendered) per file, write nothing, exit 3.
4. Apply: write changed and new managed files; create seeded files new to the lock only if absent; delete managed files
   that left the template (step 3 proved them unedited); a rename is a delete plus a create. Existing seeded files are
   never touched, and a seeded file the project deleted (in the lock, not on disk) is never recreated.
5. Write through a temporary file and a rename, `hub.lock` last. Nothing to do: write nothing and print `up to date`.
6. Exit codes: 0 done or up to date; 1 error (config, version, I/O); 2 usage; 3 stopped on drift or conflict; 4 with
   `--check` (a dry run that prints the plan and writes nothing) when changes are pending.

### hub sync --adopt

Runs while `hub.lock` is absent or a rendered managed path is still outside it (else exit 1). Files identical to the
template become `managed`, existing seeded paths are recorded `seeded`, and missing seeded files are created, including
an empty `plugin/<project>/`. Differing files are listed (`<path>: +a -b lines`), left untouched and out of the lock;
exit 0 when none differ, else 3. It never commits or rewrites git history. The owner moves project content to extension
files and re-runs `--adopt`, or passes `--accept PATH` to take the template version (git keeps the old one).

### Plugin and .claude wiring

`plugin/hub-workflow/` is the managed base plugin, named the same in every hub; `plugin/<project>/` is seeded
(`.claude-plugin/plugin.json`, empty `agents/` and `skills/`, a guard extension stub). Cloud sessions do not install
plugins declared by the repo, so the template wires both at project level: `.claude/agents/` and `.claude/skills/` are
managed directories of per-entry links into both plugins (a new project entry is linked at the next sync; a name in both
plugins stops sync, exit 3), and `.claude/settings.json` carries the hooks block. The marketplace is optional. Loki
enables its plugin from its marketplace today; adoption moves it to this wiring, as `hub-workflow` plus `plugin/loki/`.

### Hooks

Managed stdlib scripts in `plugin/hub-workflow/hooks/`, run by the system `python3` (3.9 or newer). They read
`hub.json` through a shared defensive reader and fail open: a hook never errors the session. They never call the CLI,
except SessionStart, once per session: it calls `hub brief` with a short timeout and falls back to a stdlib mini brief
(`brain/now.md`, the latest journal entry, the pre-compact snapshot) when the CLI is missing, fails or times out.
Guard extension: the seeded `plugin/<project>/hooks/project_guard.py`, loaded by path after the base checks. Its
`check(event: dict, cfg: Config) -> Optional[Tuple[str, str]]` receives the PreToolUse payload and the parsed config,
and returns `None`, `("deny", reason)` or `("ask", reason)`; the strictest verdict wins. A missing file is skipped; an
import error or exception turns the call into `ask` with the error as reason. Proof: hook unit tests in agent-hub; the
`hooks.guard-extension` doctor rule imports the file and checks the signature.

### Commands

| Hub item(s) | Becomes | Note |
|---|---|---|
| `worktree.sh`, `make worktree`, `make worktree-remove` | `hub worktree <name> [--only REPO]`, `--remove <name>` | keeps the per-repo setup/teardown scripts |
| `brief.py`, `make brain-brief` | `hub brief` | SessionStart calls it (Hooks) |
| `agent_runner.py`, `make next`, `make run-issue` | `hub next`, `hub run <issue> --repo REPO [--live]` | through `TrackerClient` |
| `agent`, `make agent` | shim for `hub agent` | adds each repo dir and appends its `AGENTS.md` |
| `bench.py`, `make bench`, `make bench-validate` | `hub bench [--validate]`, module `bench` | cases stay in the brain |
| `agent_config_lint.py`, `features_check.py` | doctor rules ([hub-doctor.md](hub-doctor.md)) | skills run `hub doctor --only features.tracker` |
| `hubconfig.py` | dropped | the CLI reads `HubConfig` |
| `cloud-setup.sh` | stays a hub file, module `cloud` | installs the pinned CLI, so cannot depend on it |
| `mine_transcripts.py`, `recall_transcripts.py`, `retro_metrics.py`, `make mine`, `make retro` | stay hub files | AGH-5 R12: Phase 2 redesigns them |
| `make usage`, `make check`, `make help` | stay targets; `check` runs `hub doctor` and the hub's own tests | `usage` wraps an external cost tool until the Phase 2 cost view; hook tests move to agent-hub |
| `guard.py`, `hubhooks.py`, `hooks.json`, `post_edit.py`, `stop_gate.py`, `session_start.py`, `session_end.py`, `pre_compact.py` | stay hub files, managed | hooks exception, AGH-5 D9 ([ADR 0012](../adr/0012-cli-subsumes-hub-scripts.md)) |

A shim runs the `hub` command when it is on `PATH`, else prints the install command and exits 127. A script is deleted
in the release where its command lands, with the skills' text updated. Order: characterization tests for the untested
scripts and hooks first (brief, bench, retro metrics, config lint, cloud setup, post-edit, session start and end,
pre-compact), then `worktree`, `brief`, `doctor`, `agent`, `next`/`run`, `bench`.

### Distribution

Releases are semver tags `vX.Y.Z` on agent-hub `main`, made by the owner; no PyPI. `hub --version` prints the tag.
Install: `uv tool install git+https://github.com/jroquette/agent-hub@vX.Y.Z#subdirectory=packages/agent-hub`. The
`cloud` module's setup script reads `platform.version`, runs that install, then fetches the repos. If the installed CLI
differs from `platform.version`, `hub sync` exits 1 with the install command and `hub doctor` reports a
`platform.version` error. Upgrade: edit `platform.version`, install, `hub sync`.

### Acceptance

Every hub's `ci.yml` has a golden job: install the pinned CLI, `hub init --config hub.json --dir "$tmp"`, then compare
the managed entries of both locks and those files' bytes (brain content and seeded files excluded). agent-hub tests a
synthetic `demo` project with two repos: two inits are byte-identical, a no-op sync writes nothing, drift exits 3, adopt
lists differences, and the `hub.lock` snapshot is committed. Loki: write its `hub.json`, move its guard rules to
`guard.*` and `project_guard.py` ([project-config.md](project-config.md)) and its domain rules to `AGENTS.project.md`,
then adopt.

## Invariants

- No generator operation silently overwrites or deletes a project edit; seeded files are written once.
- The same config and platform version give the same bytes; a no-op sync writes nothing.
- Hooks work without the CLI; agent-hub holds no project-owned material (its tests use a synthetic project).

## Decisions

- [ADR 0009](../adr/0009-hub-sync-by-file-ownership.md): ownership, `hub.lock`; 3-way merge, marker blocks rejected.
- [ADR 0011](../adr/0011-templates-as-package-data.md): templates as package data, stdlib rendering, no new port.
- [ADR 0012](../adr/0012-cli-subsumes-hub-scripts.md): logic in the CLI, shims, the hooks exception, the in-hub plugin.
- [ADR 0013](../adr/0013-release-by-git-tags.md): semver tags, the pinned install, mismatch behavior.

## Open questions

- Timeout of the SessionStart `hub brief` call: a template constant, set with the `brief` command issue.
