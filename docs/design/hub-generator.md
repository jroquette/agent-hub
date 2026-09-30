# Hub generator: init, hooks, plugin wiring and commands

## Purpose

Phase 1 contract for what a hub holds and who owns it, `hub init`, hooks, plugin wiring, the commands that replace
the hub scripts, and how the CLI ships. `hub.lock`, `hub sync`, `--adopt` and the write path:
[hub-sync.md](hub-sync.md). Config: [project-config.md](project-config.md); full rules and reasons: the ADRs.

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
selected module, then `-include Makefile.project`; a `*.project.json` is deep-merged at the next sync
([hub-sync.md](hub-sync.md)). Every JSON the generator builds or merges (settings, manifests, merged
`*.project.json`, `hub.lock`) has one form: sorted keys, 2-space indent, UTF-8, final newline.

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
unknown entry or a `hub.json` other than this run's to `hub sync --adopt`; any other problem names its cause. It writes
through the sync writer ([hub-sync.md](hub-sync.md), Apply), `hub.lock` last. Output:
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

Releases are semver tags `vX.Y.Z` on agent-hub `main`, made by the owner and checked by `release.yml` against the
meta-package version, which `agent-hub-cli` shares in lockstep (`make lockstep`); no PyPI. A shim runs the pinned
release with no install (uv caches each version):
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
