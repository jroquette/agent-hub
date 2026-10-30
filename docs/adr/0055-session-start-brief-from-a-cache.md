# 0055. SessionStart brief from a cache, refreshed in the background

- Status: proposed (accepted at merge)
- Date: 2026-10-30
- Deciders: José Henrique Roquette
- Partially supersedes: [ADR 0012](0012-cli-subsumes-hub-scripts.md), only its SessionStart clause (the hook "calls
  the pinned `hub brief` ... with a short timeout"); the rest of ADR 0012 stands, SessionStart included as the only
  hook that calls the CLI. ADR 0012 is not edited.

## Context and Problem Statement

[ADR 0012](0012-cli-subsumes-hub-scripts.md) lets one hook call the CLI: SessionStart "calls the pinned `hub brief`
the same way the shims do, with a short timeout, and falls back to a small stdlib brief". That call holds every
session start: 6.1 s, p95 10 s in the v0.27.0 audit, and `POST /api/v1/agent-sessions` takes 9.1 s.
[ADR 0053](0053-interactive-path-latency-budgets.md) sets 1500 ms for "a session ready, Claude aside" and allows no
network call with no cache on an interactive path.

How does a session get the brief without waiting for the CLI, and how does the brief stay fresh?

Decision drivers:

- The hook never waits on the network or on `uvx` (ADR 0053).
- The hook keeps the ADR 0012 rules for hooks: stdlib Python 3.9, fail open, never break a session.
- Plain `hub brief` stays read-only, as documented and tested.
- `git status` in the hub stays clean, with no edit to existing hubs' seeded `.gitignore`.
- SessionEnd keeps its 80 ms budget.

## Considered Options

Where the cache lives:

- **`.hub-cache/brief.json` in the hub, in a folder with its own `.gitignore` (`*`)**, like `.hub-uv/`. No edit to
  existing hubs, and kept apart from memory.
- `brain/auto/workspace/brief-cache.md`: already ignored, but mixes a cache with personal memory that agents read.
- `.agent-runs/brief.json`: already ignored, but that folder is for runs.

How old a cached brief may be when shown:

- **12 h.** One brief covers a working day.
- 1 h: fresher, but more sessions start with the mini brief.
- 24 h: fewer mini briefs, but older briefs across a day.

Who writes and refreshes the cache:

- **`hub brief --write-cache` writes it; only SessionStart starts the refresh, in the background.** Plain `hub brief`
  stays read-only, and no new hook calls the CLI.
- `hub brief` always writes the cache: simpler, but changes the tested "writes nothing" rule.
- SessionEnd also starts the refresh: the next session after a long one gets a newer brief, but a second hook calls
  the CLI, against ADR 0012, and no criterion needs it.

## Decision Outcome

Chosen options: **`.hub-cache/brief.json`, shown up to 12 h old, written by `hub brief --write-cache` and refreshed
in the background by SessionStart only**, because the session start becomes a stdlib file read, the network leaves
the path a person waits on, and the plain command and the other hooks keep their rules.

- **SessionStart never waits for the CLI.** It injects `<hub>/.hub-cache/brief.json` when the cache is under 12 h
  old, headed with its age (for example `brief from 3 min ago`). Otherwise it injects the stdlib mini brief, which
  names the cause: no cache, a stale cache, an unreadable cache, or the last refresh's failure.
- **Checks first.** The checks that need no cache come first and do not change: no version, a bad repository or no
  uv give the mini brief, write nothing and start no refresh.
- **When to refresh.** The hook starts one refresh only when the cache is missing, unreadable or at least 5 min old.
  SessionStart fires for `startup`, `resume`, `clear` and `compact`, for every `hub web` session and every
  `claude -p` in the hub, so the 5 min floor stops back-to-back refreshes.
- **How the refresh runs.** Before anything else in `.hub-cache/`, the hook writes the folder's `.gitignore` (`*`),
  so `git status` stays clean. The refresh is the same hook file in a refresh mode, in its own session, holding none
  of the hook's stdio, so it outlives the hook and the hook's process-group kill. It runs the pinned
  `hub brief --write-cache`: one `uvx` call at the lock commit ([ADR 0054](0054-pin-the-platform-release-by-commit.md)),
  or the tag path as today for a lock without a commit. It has a 60 s limit, then its process group is killed.
- **One at a time.** A non-blocking `flock` on `.hub-cache/refresh.lock` allows one refresh per hub at a time.
- **A failed refresh** writes `.hub-cache/refresh.json` (time and cause), which the next mini brief names.
- **Who writes the cache.** Only `hub brief --write-cache`; plain `hub brief` stays read-only. The CLI creates
  `.hub-cache/` with its own `.gitignore` (`*`) when missing, refuses a folder that is a link, and replaces the file
  atomically.
- **Still one CLI hook.** SessionStart is still the only hook that calls the CLI (ADR 0012); SessionEnd does not
  refresh.
- **The cache is untrusted.** The hook reads only a regular file of at most 64 KiB, checks its fields, cuts the brief
  at 8000 characters, and fails open to the mini brief.

### What this supersedes

- [ADR 0012](0012-cli-subsumes-hub-scripts.md), in part: the SessionStart hook no longer calls `hub brief` in the
  foreground with a short timeout. It reads a cache and starts the call in the background. The rest of ADR 0012
  stands: hooks stay stdlib scripts that fail open, and SessionStart is the only hook that calls the CLI.
- ADR 0012 stays unedited, as accepted ADRs are never edited.

### Consequences

- Good: a session start is a stdlib file read (about 100 ms); the network leaves the foreground path.
- Good: plain `hub brief` and SessionEnd keep their rules and budgets.
- Bad: the brief, its git lines (branch, dirty state) included, can be up to 12 h old. Its age heads it, so the reader
  knows.
- Bad: the first session after a clone, or after a cache older than 12 h, gets the mini brief.
- Bad: a background process outlives the hook. Its 60 s limit and the lock bound it.

## More Information

- [ADR 0053](0053-interactive-path-latency-budgets.md): the `session_start` budget and the no-network rule.
- [ADR 0054](0054-pin-the-platform-release-by-commit.md): the lock commit the refresh runs.
- [SPEC](../SPEC.md): the session brief.
