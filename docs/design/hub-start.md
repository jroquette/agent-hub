# Hub start: from a tracker issue to its worktrees and a session

## Purpose

A developer starting work on an issue needs its worktrees in the repos it touches, the issue moved to the team's
started state and a Claude Code session launched from the hub with those worktrees attached. `./hub start ISSUE` does
all three in one command, and resumes the task when its worktrees already exist. Its contract: options, order, task
name, launch, output, exit codes (AGH-62).

## Contract

### Command

- `hub start ISSUE [--repo DIR]… [--no-agent]`, run as `./hub start` from the hub. `ISSUE` is `<TEAM>-<n>` in upper
  case (`DEM-7`) for a team of `hub.json`. `--repo` (repeatable) names a repo `dir` of `hub.json` to work in; without
  it, every repo is touched. Touched repos follow `hub.json` order, whatever the flags' order. `--no-agent` stops
  before the session and prints how to launch it.
- Root: `AGENT_HUB_ROOT` when `./hub` exports it, else the cwd; no `hub.json` there exits 2. Run from a worktree of
  the hub repo (its `.git` a file), the hub's main checkout is the hub: its `hub.json`, its workspace, the session's
  cwd. Finding it needs git: no git, or git cannot run, exits 1.
- Usage errors exit 2 before any tracker call or git call in a repo: an issue not shaped `<TEAM>-<n>` for a configured
  team (the message names the shape, and the teams when there are several), a `--repo` that is not a `dir` (all
  unknown ones named, with the valid list), a malformed `hub.local.json` or no branch prefix
  ([developer-identity.md](developer-identity.md)).
- Preconditions exit 1 before any request: without `--no-agent`, `claude` must be on `PATH`; transport `api` needs
  `LINEAR_API_KEY`. Then one stderr line names the transport, as in `hub next` and `hub run`.

### Order (D-order)

1. Read the issue once (`TrackerClient.get_issue`).
2. List the task folders of every hub repo, touched or not, and decide the task name (D-resume, below).
3. Check the touched repos' branches for that name before any create (`hub worktree`'s checks: a branch checked out
   in another worktree, an existing worktree on another branch, a task folder that is not a worktree).
4. Create each touched repo's missing worktree with `hub worktree`'s steps: a fresh fetch, `git worktree add` from
   `origin/<repos[].default_branch>` on the branch `conventions` gives, then the repo's setup script
   ([worktree-environment.md](worktree-environment.md)). An existing one prints `exists` and is kept.
5. Move the issue to `tracker.states.started` (default `In Progress`). This is the last write, so no failure leaves
   the issue started without its worktrees.
6. Launch (below).

### Task name (D-resume)

- A folder under `<repo>/.claude/worktrees/` belongs to the issue when it is the issue id in lower case, or that id
  followed by `-` (`dem-7`, `dem-7-x` for `DEM-7`; not `dem-70-x`).
- No such folder in any hub repo: a fresh start, named `<issue lower>-<title slug>`. The slug is the title with only
  `A`-`Z` lowercased and each run of other characters outside `[a-z0-9]` turned into one `-` (non-ASCII letters drop:
  `Café` gives `caf`), trimmed of `-`, at most 40 characters cut at a word end (the first 40 when the first word is
  longer). An empty slug leaves the lowercase id alone.
- One name found, in one or more repos: a resume; the name is kept and only the touched repos get a worktree. A name
  read from disk must be a valid task name, `<issue lower>[-<desc>]` with `<desc>` in `[a-z0-9._-]`, else exit 1
  naming it. Two names in one repo, or different names across repos, exit 1 listing every match, before any fetch.
- A fresh start moves the issue unconditionally; a resume moves it only while its state type is unstarted (triage,
  backlog, unstarted: `move_state(..., only_if_unstarted=True)`), so an issue already started, in review or closed is
  left as it is and the summary says `<state> (already started, not moved)`.

### Launch

- Stdout holds the `created`/`exists` lines and setup script output, then a blank line and the summary: `task     :`
  (name and branch; one `branch   :` line per repo when branches differ), `repos    :`, one `worktree :` per touched
  repo, `state    :`, and a `remove   :` line per created worktree (below).
- The session: `claude` exec'd (`os.execvp`) from the hub's main checkout, with `--add-dir` for each touched repo's
  worktree, the per-task context file `brain/auto/agent-context-<issue lower>.md` (each worktree's `AGENTS.md` under a
  header naming it, written through a temporary file) as `--append-system-prompt-file`, the `--settings` that keep
  auto memory in `brain/auto/workspace/` ([memory-layers.md](memory-layers.md)), and the issue as the first prompt.
  `hub agent` shares this launch (`claude_launch.py`); the context file is per task so two tasks never overwrite it.
- The first prompt names the issue and the task, says the worktrees are attached and every change goes there, holds
  the issue in `hub run`'s fenced block of untrusted data (`issue_block`, bounded to one argument), and ends handing
  control back to the hub's workflow (plan before code, ask before acting beyond the task).
- `--no-agent`: the summary ends with `next     : ./hub start <ISSUE> [--repo DIR]…`, the same `--repo`s, which
  resumes the task and launches its session. Exit 0.
- Lines are built from the `ISSUE` argument, not the tracker's answer; the tracker's state text is escaped.

### Failures

A failure after the usage checks prints `hub start: <reason>` on stderr, then one `created  : <path>` per worktree
this run created and the lines that remove them, and exits 1. The worktrees are kept. A remove line is
`./hub worktree --remove <name>` when every hub repo was created, else one `./hub worktree --remove <name> --only
<repo>` per created repo. A setup script that fails after `git worktree add` counts as created. A launch failure
(context file not written, `claude` cannot start, hub not entered) also prints `state    : <ISSUE> was moved to
<started>; ./hub start … resumes the task` when this run moved it. An unknown issue, or a started state the team
lacks, writes nothing to the tracker.

### Environment

Setup scripts and git get the caller's environment minus `LINEAR_API_KEY` (the scripts are the repo's) and git's
location variables (`GIT_DIR`, …); GitHub tokens are kept, as in `hub worktree`. The session gets the caller's whole
environment plus `CLAUDE_CODE_ADDITIONAL_DIRECTORIES_CLAUDE_MD=1`, so each attached worktree's `CLAUDE.md` loads.

### Gitignore

The seeded `.gitignore` lists `brain/auto/agent-context-*.md`. A hub generated before it must add that line by hand:
seeded files are never rewritten by `hub sync`.

## Invariants

- The issue is read once (`get_issue`) and moved at most once, last; no issue is moved before its worktrees exist.
- No worktree is removed, and no branch deleted; a rerun after a failure resumes under the same name.
- The same issue title and worktrees on disk give the same task name and branches on every machine.
- No text from the tracker or from disk reaches a line, a branch or the prompt unescaped or unvalidated.

## Decisions

- AGH-62's spec: the order with the move last (D-order), resume from any repo's worktree with a move only from an
  unstarted state (D-resume), exec from the hub's main checkout with a per-task context file (D-launch).
- [ADR 0014](../adr/0014-tracker-port-linear-graphql.md), [ADR 0015](../adr/0015-linear-mcp-tracker-transport.md):
  the tracker port and its two transports; `hub start` uses the adapter `tracker.transport` picks.
- [ADR 0016](../adr/0016-per-developer-identity.md): the branch prefix comes from `hub.local.json`, `hub.json`, git.
- [ADR 0002](../adr/0002-lean-hexagonal-architecture.md), [ADR 0008](../adr/0008-cli-as-composition-root.md): the
  use case `start_task` and its ports `TaskWorktrees` and `SessionLauncher` are core; git, the prints and the exec
  are `cli` (`GitTaskWorktrees`, `ClaudeSession`, `PrintedSession`).

## Open questions

- `tracker.states.review` is read by nothing yet: the review step (AGH-63) decides who moves an issue there.
- An existing hub gets `brain/auto/agent-context-*.md` in its `.gitignore` only by hand; nothing reports it missing.
