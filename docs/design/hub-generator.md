# Hub generator: init, hooks, plugin wiring and commands

## Purpose

Phase 1 contract for what a hub holds and who owns it, `hub init`, hooks, plugin wiring, the commands that replace
the hub scripts, and how the CLI ships. `hub.lock`, `hub sync`, the write path: [hub-sync.md](hub-sync.md); `--adopt`:
[hub-adopt.md](hub-adopt.md). Config: [project-config.md](project-config.md); full rules and reasons: the ADRs.

## Contract

### Classification and rendering

Kind: `generic` (same for every project), `module` (only when selected in `modules`) or `project-owned`. Ownership:
`managed` (sync rewrites it), `seeded` (written once when absent, then never touched) or `not generated`.

| Entry in a generated hub | Kind | Ownership |
|---|---|---|
| `hub.json` (`hub.lock` is tool state: written by init and sync, not listed in itself) | project-owned | seeded |
| `hub.schema.json`, `AGENTS.md` and `CLAUDE.md` (base rules), `Makefile`, `hub` shim, `agent` launcher, `.pre-commit-config.yaml`, `.github/workflows/ci.yml` | generic | managed |
| `AGENTS.project.md` (project rules, created empty); `Makefile.project`; `README.md`; `docs/app-repo-AGENTS.md` (starter for each repo's root `AGENTS.md`); `.gitignore` (base entries, `hub.local.json` among them) | project-owned (`README.md`, `docs/app-repo-AGENTS.md`, `.gitignore` generic) | seeded |
| `.claude/settings.json` (merged with a seeded `.claude/settings.project.json`, which can add sandbox hosts and override the sandbox's scalars, `enabled` included: only managed or CLI settings can enforce the sandbox; it holds the base denies (push denies per protected branch) and sandbox and runs the base hooks, so a hub never enables `hub-workflow`: Claude Code drops only identical duplicate hook commands), `.claude/agents/` and `.claude/skills/` (one link per entry of both plugins, since cloud sessions do not install repo-declared plugins; not dotfiles such as `.gitkeep`; a new project entry is linked at the next sync) | generic (+ project-owned) | managed (+ seeded) |
| `plugin/hub-workflow/**` (base agents, skills, hooks; same name in every hub; on adoption, Loki's `loki-workflow` becomes it plus `plugin/loki/`) | generic | managed |
| `plugin/<project>/**` (project agents, skills, guard extension; empty folders hold a `.gitkeep`) | project-owned | seeded |
| Brain skeleton: `brain/index.md`, `brain/now.md`, `brain/decisions/index.md`, folder `.gitkeep`s, journal template | generic | seeded |
| `scripts/` transcript mining, recall and retro metrics | generic | managed (until Phase 2) |
| `scripts/cloud-setup.sh`, `scripts/contract-sync.sh`, `mk/<module>.mk`, `.claude-plugin/marketplace.json` (merged with a seeded `.claude-plugin/marketplace.project.json`) | module: `cloud`, `contract-sync`, the selecting module, `marketplace` | managed (+ seeded) |
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
the pinned `uvx` command), schema and model, and copies it byte for byte (a team's may leave the identity out). `--dir` (default: the cwd) is created after every check. The target may hold only `.git`, seeded files (kept),
paths equal to their render and leftovers: a `hub.lock` exits 1 pointing to `hub sync`; a differing managed path, an
unknown entry or a `hub.json` other than this run's to `hub sync --adopt`; any other problem names its cause. It writes
through the sync writer ([hub-sync.md](hub-sync.md), Apply), `hub.lock` last. Output:
`created N files (M managed, K seeded) and L links in <root>`; if any, `kept X files already there (Y seeded, Z equal to
the render)` (`and L links`) and `removed X leftover temporary files`; next steps. Exits: 0 done, 1 error, 2 usage.

### Modules

A selected module renders its files (rows above) and `mk/<id>.mk`, whose `.PHONY` targets `make help` lists: `bench`
(`$(ARGS)` passed raw), `bench-validate`, `cloud-setup`, `contract-sync`, `marketplace-validate`. `contract-sync.sh` runs
`make contract-export` in `../<source>`, then `make contract-import` in `../<target>` (no contract format). The managed
marketplace holds `name`, `owner` and the plugins `hub-workflow` and `<project>`; the sibling's plugins follow in their
order ([hub-sync.md](hub-sync.md)). `AGENTS.md` names the selected modules' files only, so it changes with `modules`.

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
calls the CLI, from the hub with `AGENT_HUB_ROOT` set: the shim's resolve step (`uvx … hub --version`), then
`uvx … hub brief`, both within one 10 s deadline; else a mini brief naming the cause (`no version`, `no uv`,
`resolve failed`, `failed (exit N)`, `failed (no output)`, `failed (cannot start)`, `timed out`). Guard extension: the
seeded `plugin/<project>/hooks/project_guard.py` of the hook root (never from `CLAUDE_PROJECT_DIR`, the cwd or tool
input). Unless the base verdict is `deny` (final), it runs in a child `python3` in its own session (3 s, then killed
with its process group) and only tightens: `check(event, cfg)` returns `None`, `("deny", reason)` or `("ask", reason)`,
and the child, given the event JSON on stdin, prints it as one JSON value, `null` or `{"verdict": "deny"|"ask",
"reason": "..."}`; anything else (other verdict or type, non-zero exit, unparseable or extra output, timeout, a file
resolving outside the hub) gives `ask` with the cause; no file: skipped. The base guard asks before edits to
`plugin/hub-workflow/hooks/`, `plugin/<project>/hooks/`, `.claude/settings*.json`, `hub.lock` and `hub.json`. It is a
guardrail against mistakes, not a sandbox: it matches tool input and Bash text by pattern, so a determined agent can get
round it. The real limits are OS permissions and Claude Code's permission rules; the extension's trust boundary is the
ask on edits of the hooks folders. The settings' denies and sandbox are defense in depth: sandboxed Bash runs without a
prompt (`autoAllowBashIfSandboxed` defaults to true), and the sandbox's excluded commands run unsandboxed through the
normal permission flow. The stop gate checks the checkouts holding cwd or a file the session or its subagents edited,
changed since the transcript's first timestamp; in one 160 s budget each run gets `repos[].check_fast_timeout` (default
150 s), then its process group is killed; a skipped or cut run prints `not run`, never blocks. Proof: integration tests.

### Commands

| Hub item(s) | Becomes | Note |
|---|---|---|
| `worktree.sh`, `make worktree`, `make worktree-remove` | `./hub worktree <name> [--only REPO]`, `--remove <name>` | keeps the per-repo setup/teardown scripts |
| `brief.py`, `make brain-brief` | `./hub brief [--no-network]` | SessionStart calls it (Hooks) |
| `agent_runner.py`, `make next`, `make run-issue` | `hub next`, `hub run <issue> --repo REPO [--live] [--budget USD] [--from implement\|verify]` | through `TrackerClient`; `run-issue` passes `BUDGET` and `FROM`, each checked as a name |
| `agent`, `make agent` | `./agent`: `exec ./hub agent "$@"` | `--add-dir` per repo dir; the repos' `AGENTS.md` in `brain/auto/agent-context.md` (rewritten per launch, gitignored); then `exec claude` |
| `bench.py`, `make bench`, `make bench-validate` | `hub bench [--validate] [options]`, module `bench` | cases stay in the brain: `brain/workflow/bench/tasks.json` (absent or `[]`: nothing to do; bounds: the `bench.tasks` row of [hub-doctor.md](hub-doctor.md)); without `bench` selected, exit 2 `module bench is not selected`. `--validate` (no run option) grades each case not excluded at its merge's parent (must fail) and at its merge (must pass), never runs `claude`. A run (`--runs` 3, `--arms with,without`, `--cases` all, `--budget` 15, `--per-run` 2, `--parallel` 3, `--label` `bench-%Y%m%d-%H%M`, `--trace`; `BENCH_EFFORT` low/medium/high) lays `origin/main`'s agent config over each case's merge parent in a detached worktree under `<ws>/_bench/wt` (`<ws>`: the folder of the hub's main checkout), runs one `claude -p` per job (the `with` arm enables `hub-workflow@<project>`), then grades it; a wave starts only while it fits the budget (else `STOP:`), and a failed session without a cost counts at `--per-run`. Records go to `<ws>/_bench/results/<label>.jsonl` (traces in `results/traces/`, files 0600), then the summary. Children run without `LINEAR_API_KEY`, `GH_TOKEN`, `GITHUB_TOKEN`; sessions use `--setting-sources user`, so the user's own hooks and plugins load in both arms (AGH-77 checks whether project instruction files are read). `<ws>/_bench/bench.lock` allows one bench per workspace; a left-behind lock exits 1 for the user to delete. Exits: 0 done, 1 bad cases, wrong grade, failed step or lock, 2 usage |
| `agent_config_lint.py`, `features_check.py`; `hubconfig.py` | doctor rules ([hub-doctor.md](hub-doctor.md)); `hubconfig.py` dropped (the CLI reads `HubConfig`) | skills run `hub doctor --only features.tracker` |
| `cloud-setup.sh` | stays a hub file, module `cloud` | sets the git identity from `hub.json`'s author (global and repo-local), else from `HUB_AUTHOR_NAME`/`HUB_AUTHOR_EMAIL` repo-local only, else a WARN ([developer-identity.md](developer-identity.md)); checks access to the pinned tag, warms the uv cache, then fetches the repos; no access: exit 1 naming it; it cannot need the CLI |
| `mine_transcripts.py`, `recall_transcripts.py`, `retro_metrics.py`, `make mine`, `make retro`; `guard.py`, `hubhooks.py`, `hooks.json`, `post_edit.py`, `stop_gate.py`, `session_start.py`, `session_end.py`, `pre_compact.py` | stay hub files, managed | scripts: AGH-5 R12, Phase 2 redesigns them; hooks: the hooks exception, AGH-5 D9 ([ADR 0012](../adr/0012-cli-subsumes-hub-scripts.md)) |
| `make usage`, `make check`, `make help` | stay targets; `check` runs `hub doctor` and the hub's own tests | `usage` wraps an external cost tool until the Phase 2 cost view; hook tests move to agent-hub |

Every caller (Makefile `HUB`: `$(CURDIR)/hub` single-quoted; pre-commit `./hub doctor`; skills; `./agent`) goes through
the managed POSIX `sh` shim `./hub`, run by its real path (a symlink elsewhere reads the link's folder): it reads
`platform.version` and `platform.repository` from its own folder's `hub.json` at run time (stdlib `python3`; no
`python3` or no uv: exit 127; a bad pin or repository, never echoed: exit 1), runs the resolve step `uvx --from <pinned
source> hub --version` (fails: exit 1 naming the source and the missing access, no real call), then `exec`s the real
call, which keeps the caller's cwd, gets `AGENT_HUB_ROOT` = the shim's folder, and passes its exit code through. Windows
is not supported. A script is deleted when its command lands, after characterization tests of the untested (brief,
bench, retro, lint, cloud setup). Order: `worktree`, `brief`, `doctor`, `agent`, `next`/`run`, `bench`.

### Distribution

Releases are semver tags `vX.Y.Z` on agent-hub `main`, made by the owner and checked by `release.yml` against the
meta-package version, which `agent-hub-cli` shares in lockstep (`make lockstep`); no PyPI. A shim runs the pinned
release with no install (uv caches each version):
`uvx --from <platform.repository>@v<platform.version>#subdirectory=packages/agent-hub hub …`, the repository read from
`hub.json` at run time (default `git+https://github.com/jroquette/agent-hub`; [project-config.md](project-config.md)).
`hub init` takes the same source via `uvx` or `uv tool install`. Private access: the read-only secret
`AGENT_HUB_READ_TOKEN` in hub CI; the repo attached or `GH_TOKEN` in other projects' cloud sessions (the `cloud` setup
checks access, warms the cache). Both answer for `https://github.com/` only: CI maps no token for another host, and the
`GH_TOKEN` helper serves `github.com` alone. Credentials go through a git credential helper or `GIT_CONFIG_*`
`insteadOf`, never the URL, `hub.json` or `hub.lock`. A direct `hub` other than `platform.version`: `hub sync` exits 1,
`hub doctor` errors. Upgrade: edit `platform.version`, sync.

### Acceptance

Each hub's `ci.yml` has a golden step: the pinned `hub sync --check`, before `make check`, must exit 0 (the managed
files are the release's render; steps, exits and the CI credential: [hub-adopt.md](hub-adopt.md)). agent-hub tests a
synthetic `demo`: identical inits, no-op and rerun syncs, an edit exits 3, adopt lists differences, a `hub.lock`
snapshot. Loki: write `hub.json`, move guard rules to `guard.*`/`project_guard.py` and domain rules to
`AGENTS.project.md`, adopt.

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
