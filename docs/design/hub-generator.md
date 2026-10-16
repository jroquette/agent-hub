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
| `hub.schema.json`, `AGENTS.md` and `CLAUDE.md` (base rules; Brain rules route each learning: [memory-layers.md](memory-layers.md)), `Makefile`, `hub` shim, `agent` launcher, `.pre-commit-config.yaml`, `.github/workflows/ci.yml` | generic | managed |
| `AGENTS.project.md` (project rules, created empty); `Makefile.project`; `README.md` (with a "Join this hub" section: requirements, access, `./hub setup`, known traps, and cloud steps with module `cloud`); `docs/app-repo-AGENTS.md` (starter for each repo's root `AGENTS.md`); `.gitignore` (base entries, `hub.local.json`, the launch context files `brain/auto/agent-context*.md` and personal memory `brain/auto/workspace/*` among them) | project-owned (`README.md`, `docs/app-repo-AGENTS.md`, `.gitignore` generic) | seeded |
| `.claude/settings.json` (merged with a seeded `.claude/settings.project.json`, which can add sandbox hosts and override the sandbox's scalars, `enabled` included: only managed or CLI settings can enforce the sandbox; it holds the base denies (push denies per protected branch; no `terraform`/`aws` denies when `guard.infra` is set) and sandbox and runs the base hooks, so a hub never enables `hub-workflow`: Claude Code drops only identical duplicate hook commands), `.claude/agents/` and `.claude/skills/` (one link per entry of both plugins, since cloud sessions do not install repo-declared plugins; not dotfiles such as `.gitkeep`; a new project entry is linked at the next sync) | generic (+ project-owned) | managed (+ seeded) |
| `plugin/hub-workflow/**` (base agents `architect`, `evaluator`, `planner`, `quality-reviewer`, `requirements-analyst`, `researcher`, `spec-reviewer`, `ux-designer`; `quality-reviewer`, `researcher` and `spec-reviewer` say `mutates_checkout: false`; skills `adr`, `create-plan`, `deliver`, `feature`, `fix`, `handoff`, `incident`, `kickoff`, `learn` (`/learn personal` writes `brain/auto/workspace/`), `onboard`, `overengineering-review` (with `references/patterns.md`), `recall`, `refactor`, `release`, `research`, `retro`, `review`, `triage`, `upgrade`, `ux-review` (with `references/checklist.md`); hooks; `schemas/review.v1.json` and `schemas/eval.v1.json`, the agent output schemas, core package data copied verbatim; same name in every hub; on adoption, Loki's `loki-workflow` becomes it plus `plugin/loki/`) | generic | managed |
| `plugin/<project>/**` (project agents, skills, guard extension; empty folders hold a `.gitkeep`) | project-owned | seeded |
| Brain skeleton: `brain/index.md`, `brain/now.md`, `brain/decisions/index.md`, folder `.gitkeep`s (`brain/auto/workspace/` too), journal template | generic | seeded |
| `scripts/` transcript mining, recall and retro metrics | generic | managed (until Phase 2) |
| `scripts/cloud-setup.sh`, `scripts/contract-sync.sh`, `mk/<module>.mk`, `.claude-plugin/marketplace.json` (merged with a seeded `.claude-plugin/marketplace.project.json`) | module: `cloud`, `contract-sync`, the selecting module, `marketplace` | managed (+ seeded) |
| Worktree, brief, runner, benchmark, config-lint and feature-check scripts | generic (`bench`: module) | not generated: `hub` commands |
| `workflows/<pack>/**`: the built-in packs (`issue-to-pr`: `issue-to-pr.yaml`, `prompts/`, `fixtures/`; `sdlc`: `deliver.yaml`, `review.yaml`, `prompts/`, `scripts/`, `fixtures/`), core package data copied byte for byte. A pack is seeded as a unit: only when `hub.lock` holds none of its paths and its folder holds nothing but the render's own folders and bytes (an interrupted seed is completed); else no file of it is written, so a release that adds a fixture never adds it to a hub's own pack. The hub's copy is the one discovery and `hub run` read ([workflow-schema.md](workflow-schema.md)); to follow the built-in again, delete `workflows/<pack>/`: sync neither re-seeds it nor reports drift for seeded files | generic | seeded |
| Brain content, bench cases, hub `tests/`, other `workflows/` packs, run output (`.agent-runs/`), domain rules (for Loki: red-chain, Decimal, paper/testnet, kept in `AGENTS.project.md`) | project-owned | not generated |

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
the stop gate does not block if it cannot save its counter. `hub.json` is the one `$HUB_CONFIG` names (hub: its folder),
else the hook root's (the hub or hub worktree holding the hook files; a worktree reads its own `hub.json`, but the hub
is its main checkout and the workspace that checkout's parent), else (plugin cache) the first found walking up from the
start, a sibling hub only if the start is in it or a repo it lists. That file gives every value (repos, the stop gate's
`check_fast`, SessionStart's `platform.version`, default branch, branch prefix, hub, workspace), except that
`$HUB_CONFIG`'s `ask_before_edit`, `deny_paths`, `deny_hosts` and `secret_env_files` are added to the hook root's, never
replace them, and `readable_env_files` is the hook root's only; for
`guard.infra`, the mode and `allow` are the hook root's only and `$HUB_CONFIG`'s `prod_markers` and unusable-value
problem are added (in the plugin cache, the found file's `guard.infra` as is); the extension, `@hub/` anchors and
guard-file asks stay pinned to the hook root. Only SessionStart calls the CLI, from the hub with `AGENT_HUB_ROOT` set:
the shim's resolve step (`uvx … hub --version`), then `uvx … hub brief`, both within one 10 s deadline; else a mini
brief naming the cause (`no version`, `no uv`, `resolve failed`, `failed (exit N)`, `(no output)` or `(cannot start)`,
`timed out`). Guard extension: the seeded `plugin/<project>/hooks/project_guard.py` of the hook root (never from
`CLAUDE_PROJECT_DIR`, the cwd or tool input). Unless the base verdict is `deny` (final), it runs in a child `python3` in
its own session (3 s, then killed with its process group) and only tightens: `check(event, cfg)` returns `None`,
`("deny", reason)` or `("ask", reason)`, and the child, given the event JSON on stdin, prints it as one JSON value,
`null` or `{"verdict": "deny"|"ask", "reason": "..."}`; anything else (other verdict or type, non-zero exit, unparseable
or extra output, timeout, a file resolving outside the hub) gives `ask` with the cause; no file: skipped. The base guard
asks before edits to `plugin/hub-workflow/hooks/`, `plugin/<project>/hooks/`, `.claude/settings*.json`, `hub.lock`,
`hub.json` and the `hub`/`agent` launchers (Bash asks only when it writes one). It is a guardrail against mistakes, not
a sandbox: it matches tool input and Bash text by pattern, so a determined agent can get round it. The real limits are
OS permissions and Claude Code's permission rules; the extension's trust boundary is the ask on hooks folder edits. The
settings' denies and sandbox are defense in depth (sandboxed Bash runs without a prompt; excluded commands take the
normal permission flow). The sandbox keeps writes in the workspace and `$TMPDIR` and the network to the HTTP(S)
allowlist; SSH never passes it. So the hub's own network commands are `excludedCommands` (AGH-134,
`WORKFLOW_EXCLUDED_COMMANDS`): `gh`, git's `push`/`fetch`/`pull`/`clone`/`ls-remote`, and `hub worktree` by its three
spellings (`./hub worktree *`, `hub worktree *`, `make worktree *`, plus `make worktree-remove *`), since its own
`git fetch` never matches; never `make *` or `./hub *`, which would let any Makefile target out. Claude Code matches an
entry against the literal Bash text, so only a call that is exactly the command escapes (no `cd … &&`, `;`, pipe,
redirect or `git -C`). `hub worktree --no-fetch` is the escape hatch after a bare `git fetch`. The `hub` shim moves
uv's cache and tool folders to `<hub>/.hub-uv/` (which ignores itself) only when they cannot be written, and then sets
`UV_PYTHON_DOWNLOADS=never`; settings `env` cannot do it (no expansion, a committed file cannot name a per-machine
path, and it would change every repo's uv), and `sandbox.filesystem.allowWrite` on `~/.cache/uv` or
`~/.local/share/uv` would let a sandboxed agent plant code that later runs unsandboxed (uv tools on `PATH`).
`hub doctor`'s `sandbox.workflow` checks the exclusions. The stop gate checks the checkouts holding cwd or a file the session or its subagents edited,
changed since the transcript's first timestamp (else its birth time, else 12 h ago); in one 160 s budget each run gets
`repos[].check_fast_timeout` (default 150 s), then its group is killed; a cut run says `not run`.
The event sensor `event_sensor.py` (AGH-200) is registered beside them on eleven events (SessionStart,
UserPromptSubmit, PreToolUse, PostToolUse and PostToolUseFailure with matcher `*`, Notification, Stop, SubagentStart,
SubagentStop, PreCompact, SessionEnd; timeout 5 s): it reads the input (at most 16 MiB), reduces each body to its size
(the prompt to `prompt_chars` and `prompt_slash_command`; a Write's `content` and an Edit's or MultiEdit edit's
`old_string`/`new_string` to `<key>_lines`, a Write under `brain/_inbox/` keeping its first heading as
`content_heading`; `tool_response` to `tool_response_bytes`), replaces each string still over 64 KiB with
`{"_omitted_bytes": n}`, wraps it in the v1 envelope `{v, project, repo, run, step, attempt, sent_at, hook}`
(project from `hub.json`, repo from the cwd's checkout or worktree, run/step/attempt from `AGENT_HUB_RUN_ID`,
`AGENT_HUB_STEP`, `AGENT_HUB_ATTEMPT`, each null when out of bounds) and POSTs it to `/api/v1/events/hooks` of
`AGENT_HUB_WEB_URL` (default `http://127.0.0.1:7420`; only plain `http` to `127.0.0.1`, `[::1]` or `localhost`, any other
URL turns it off without opening a socket) within 0.5 s. An envelope over 1 MiB, an input that is not a JSON object or
no hub found sends nothing; it never prints and always exits 0. After deciding, and after printing its decision, the
guard sends a deny or an ask (`decision: {by: guard, kind, rule}`, `rule` a stable id read from the reason, e.g.
`push_protected_branch`, `ask_before_edit`) and the Stop gate a block (`{by: stop_gate, kind: block, command,
exit_code}`) through the sensor's `send_decision`, bounded the same way; their output and exit codes do not change
(characterization goldens `golden/guard`, `golden/stop_gate`). Proof: integration tests.
The read-only gate `readonly_gate.py` (AGH-141) is a second group on SubagentStart (timeout 10 s) and SubagentStop
(30 s), after the sensor's. It acts only for a declared agent: the first definition whose frontmatter `name` is the bare
`agent_type` (split at its last `:`), looked up in the hook root's `.claude/agents/`, then `plugin/<project>/agents/`,
then the base plugin's own `agents/` (prefix `hub-workflow:`: the last only; the project's name: the second only; any
other prefix: none; `<name>.md` first, then the folder's other `*.md`), says `mutates_checkout: false` (unquoted, any
case). The base `researcher`, `spec-reviewer` and `quality-reviewer` do; app repos' and `~/.claude/agents/` are not
searched; any other agent gets no state and no output. Watched checkouts: each repo of `hub.json` with a plain folder
name, then the hub, then their task worktrees (a folder holding `.git` under `<checkout>/.claude/worktrees/`, newest
first), each a checkout of its own labelled `<dir>/.claude/worktrees/<name>`; a worktree that is a link, or a
`.claude/worktrees/` reached through one, is not watched (a main checkout's folder may be a link). At the start the gate
saves in `$TMPDIR/hub-readonly-<session>-<agent>.json` each checkout's HEAD, branch and `git status --porcelain=v2`
entries (status, modes, index blobs and the file's sha256, so staging alone is a change; a link's target text is hashed,
never followed), the main transcript's size and the listing of the session's `subagents/` folder; a resumed agent keeps
its first state while it is under 12 h old. The hub's `brain/` (also in a hub worktree), gitignored files,
`.claude/worktrees/` seen from the main checkout and `$TMPDIR` never count; submodule content is not checked. At the
stop the same checkouts are snapshotted again: a changed entry, a HEAD or branch move and a new task worktree
(`<dir>/.claude/worktrees/<name>/ (new worktree)`, its files not read) are changes; a removed worktree or checkout is a
note. Attribution reads the agent's transcript (`agent_transcript_path`, else
`<main transcript minus .jsonl>/subagents/agent-<id>.jsonl`): the real paths its Write, Edit, MultiEdit and NotebookEdit
named, and its Bash commands. A change at one of those paths is blocked. Any other change is blocked only when no
overlap signal is present, each named in the report: another fresh gate state of the session
(`another read-only agent running`), a tool call other than Agent or Task, or any tool result, in the main transcript
after its size at the start (`main session tool call`, `main session tool result`; sidechain lines skipped), another
subagent transcript created or changed (`another subagent ran`) or left ending in a call with no result
(`another subagent running`), or any of these inputs unreadable or cut. With a signal, or without a readable agent
transcript, the change is reported in a `systemMessage`: every doubtful case reports, never blocks. A block
(`decision: block`) lists the paths (at most 40), asks the agent to revert them or explain each in its final report, and
names its last 10 Bash commands (one line each, cut at 160 characters). The gate writes the agent's `.blocks` counter
before blocking, so an agent is held once: on its next stop, or when `stop_hook_active` is true, whatever is still
changed is reported as "left changed"; a counter that cannot be written means no block. Each outcome present (`block`,
`report`, `left_changed`) appends one line `{ts, session_id, agent_id, agent_type, outcome, paths}` (labels only, at
most 200; never file content or command text) to `$TMPDIR/hub-readonly-<session>.jsonl`. It imports no network module
and sends nothing; the decisions will reach the control plane with AGH-159. Fail-open: no hub, an undeclared agent or an
unreadable event prints nothing; a declared agent that cannot be checked gets
`[hub readonly-gate] not checked (<cause>)` (`no start snapshot`, `start snapshot unreadable`, `state not saved`,
`agent transcript unreadable`, `<label>: git failed`, `budget`, `caps` or `removed`, `<label>/<path>: too large`, …) and
is never blocked for it; a crash prints one `skipped` line. Bounds: a 5 s budget at the start and 15 s at the stop (one
`git` call at most 4 s, its process group killed after; at most 5 s of it reading the agent transcript), 24 checkouts
per event, 256 worktree names per folder, 4 MiB and 2,000 status entries per checkout, 8 MiB hashed per file and 128 MiB
per event, 1 MiB of stdin, 16 MiB of agent transcript, 8 MiB of main-transcript window, 1 MiB per line, 256 agent files
per folder and 16 KiB of frontmatter, 256 subagent transcripts and 256 other states looked at, the last 64 KiB of each
unchanged subagent transcript, a 16 MiB state, 12 h before a state or a silent subagent transcript is stale. Not seen,
so a change it makes can be blamed on the agent (one block, which the agent answers by saying so): another Claude
session or the user editing the same checkout, and a main-session background Bash started before the agent. A state left
by a subagent that never got SubagentStop, or a subagent killed mid-call, makes later read-only agents of the session
report instead of block for up to 12 h. Proof: integration tests, characterization goldens `golden/readonly_gate`.

### Commands

| Hub item(s) | Becomes | Note |
|---|---|---|
| `worktree.sh`, `make worktree`, `make worktree-remove` | `./hub worktree <name> [--only REPO] [--remove]` | keeps the per-repo setup/teardown scripts |
| — | `./hub start ISSUE [--repo DIR]… [--no-agent]` | issue to worktrees, started state and a session ([hub-start.md](hub-start.md)) |
| — | `./hub setup [--yes]` | onboards a machine ([hub-setup.md](hub-setup.md)) |
| `brief.py`, `make brain-brief` | `./hub brief [--no-network]` | SessionStart calls it (Hooks) |
| `agent_runner.py`, `make next`, `make run-issue` | `hub next`, `hub run <issue> --repo REPO [--live] [--budget USD] [--from implement\|verify]` | through `TrackerClient`; `run-issue` passes `BUDGET` and `FROM`, each checked as a name |
| `agent`, `make agent` | `./agent`: `exec ./hub agent "$@"` | `--add-dir` per repo dir; the repos' `AGENTS.md` in `brain/auto/agent-context.md` (rewritten per launch, gitignored); auto memory in `brain/auto/workspace/` (personal, gitignored); then `exec claude` |
| `bench.py`, `make bench`, `make bench-validate` | `hub bench [--validate] [options]`, module `bench` | cases stay in the brain: `brain/workflow/bench/tasks.json` (absent or `[]`: nothing to do; bounds: the `bench.tasks` row of [hub-doctor.md](hub-doctor.md)); without `bench` selected, exit 2 `module bench is not selected`. `--validate` (no run option) grades each case not excluded at its merge's parent (must fail) and at its merge (must pass), never runs `claude`. A run (`--runs` 3, `--arms with,without`, `--cases` all, `--budget` 15, `--per-run` 2, `--parallel` 3, `--label` `bench-%Y%m%d-%H%M`, `--trace`; `BENCH_EFFORT` low/medium/high) lays `origin/main`'s agent config over each case's merge parent in a detached worktree under `<ws>/_bench/wt` (`<ws>`: the folder of the hub's main checkout), runs one `claude -p` per job (the `with` arm enables `hub-workflow@<project>`), then grades it; a wave starts only while it fits the budget (else `STOP:`), and a failed session without a cost counts at `--per-run`. Records go to `<ws>/_bench/results/<label>.jsonl` (traces in `results/traces/`, files 0600), then the summary. Children run without `LINEAR_API_KEY`, `GH_TOKEN`, `GITHUB_TOKEN`; sessions use `--setting-sources user`, so the user's own hooks and plugins load in both arms (AGH-77 checks whether project instruction files are read). `<ws>/_bench/bench.lock` allows one bench per workspace; a left-behind lock exits 1 for the user to delete. Each job's `git worktree add` and its removal (`remove`, `prune`) run under one in-process lock, one at a time (AGH-120). Exits: 0 done, 1 bad cases, wrong grade, failed step or lock, 2 usage |
| `agent_config_lint.py`, `features_check.py`; `hubconfig.py` | doctor rules ([hub-doctor.md](hub-doctor.md)); `hubconfig.py` dropped (the CLI reads `HubConfig`) | skills run `hub doctor --only features.tracker` |
| `cloud-setup.sh` | stays a hub file, module `cloud` | sets the git identity from `hub.json`'s author (global and repo-local), else from `HUB_AUTHOR_NAME`/`HUB_AUTHOR_EMAIL` repo-local only, else a WARN ([developer-identity.md](developer-identity.md)); checks access to the pinned tag, warms the uv cache, then fetches the repos; no access: exit 1 naming it; it cannot need the CLI |
| `mine_transcripts.py`, `recall_transcripts.py`, `retro_metrics.py`, `make mine`, `make retro`; `guard.py`, `hubhooks.py`, `hooks.json`, `post_edit.py`, `stop_gate.py`, `session_start.py`, `session_end.py`, `pre_compact.py`, `event_sensor.py`, `readonly_gate.py` | stay hub files, managed | scripts: AGH-5 R12, Phase 2 redesigns them; hooks: the hooks exception, AGH-5 D9 ([ADR 0012](../adr/0012-cli-subsumes-hub-scripts.md)) |
| `make usage`, `make check`, `make help` | stay targets; `check` runs `hub doctor`, `hub workflow test` (the packs' fixtures) and the hub's own tests | `usage` wraps an external cost tool until the Phase 2 cost view; hook tests move to agent-hub |

Every caller (Makefile `HUB`: `$(CURDIR)/hub` single-quoted; pre-commit `./hub doctor`; skills; `./agent`) goes through
the managed POSIX `sh` shim `./hub`, run by its real path (a symlink elsewhere reads the link's folder): it reads
`platform.version` and `platform.repository` from its own folder's `hub.json` at run time (stdlib `python3`; no
`python3` or no uv: exit 127; a bad pin or repository, never echoed: exit 1), runs the resolve step `uvx --from <pinned
source> hub --version` (fails: exit 1 naming the source and the missing access, no real call), then `exec`s the real
call, which keeps the caller's cwd, gets `AGENT_HUB_ROOT` = the shim's folder, and passes its exit code through. Windows
is not supported. A script is deleted when its command lands, after characterization tests (brief, bench, retro, lint,
cloud setup). Order: `worktree`, `brief`, `doctor`, `agent`, `next`/`run`, `bench`, `setup`, `start`.

### Distribution

Releases are annotated semver tags `vX.Y.Z` (`git tag -a`) on agent-hub `main`, made by the owner; `release.yml` checks
their form, that they are annotated and on `main`, and the meta-package version `agent-hub-cli` shares in lockstep
(`make lockstep`); no PyPI. A shim runs the pinned release with no install (`hub init` takes the same source):
`uvx --from <platform.repository>@v<platform.version>#subdirectory=packages/agent-hub hub …`, the repository read from
`hub.json` at run time (default `git+https://github.com/jroquette/agent-hub`, public: no credential). A private mirror
([project-config.md](project-config.md)) reads through `AGENT_HUB_READ_TOKEN` in hub CI, or the repo attached or
`GH_TOKEN` in cloud sessions (`cloud` setup checks access), on `https://github.com/` only, via a credential helper or
`GIT_CONFIG_*` `insteadOf`, never the URL, `hub.json` or `hub.lock`. A direct `hub` other than `platform.version`: `hub
sync` exits 1, `hub doctor` errors. Upgrade: edit `platform.version`, sync.

### Acceptance

Each hub's `ci.yml` has a golden step: the pinned `hub sync --check`, before `make check`, must exit 0 (steps, exits, CI
credential: [hub-adopt.md](hub-adopt.md)). agent-hub tests a synthetic `demo`: identical inits, no-op and rerun syncs,
an edit exits 3, adopt lists differences, a `hub.lock` snapshot. Loki: write `hub.json`, move guard rules to
`guard.*`/`project_guard.py` and domain rules to `AGENTS.project.md`, adopt.

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
