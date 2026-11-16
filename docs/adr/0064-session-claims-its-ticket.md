# 0064. A session claims its ticket before any edit

- Status: proposed
- Date: 2026-11-11
- Deciders: José Henrique Roquette (spec decision D4 and plan amendments AM-3 and AM-4 of AGH-805, 2026-11-11)
- Supersedes: nothing. The tracker ports keep their scope: `TrackerReader` still reads issue summaries only, never
  comments.

## Context and Problem Statement

Several sessions have worked on the same ticket at once: four "Milestone 2" sessions started within 2 minutes. Each
one spends quota, and their branches and pull requests collide. Nothing tells a session that another one already
works on its ticket. hub web has its own session store, but cloud and local CLI sessions do not write to it.

How does a session tell other sessions that it works on a ticket, and how does a second session know whether the
first is still alive, in the cloud and on a developer's machine?

Decision drivers:

- Visible to every session that can read the tracker, wherever it runs.
- Auditable: every claim, takeover and release leaves a trace a person can read.
- A dead session never blocks a ticket for long. A session that waits on the owner (for a merge, an answer) is not
  dead.
- No new service, no tracker port change, no sign of an agent in the tracker (authorship rule).

## Considered Options

1. **A tracker comment as the shared record, plus a liveness check by place.** In the cloud, the session's status.
   Locally, a claim file under `.agent-runs/claims/` with the Claude Code process id, kept by `hub claim`.
2. The tracker's assignee or state as the lock.
3. A lock file committed to the hub repo (a branch or a file per ticket).
4. hub web's session store as the registry.
5. No claim; a person checks before starting.

## Decision Outcome

Chosen option: **1, a tracker comment plus a liveness check by place.** The tracker is the one store every session
already reads and writes. The liveness check uses what each place can see.

- **Claim.** Before any edit, a session that starts work on a ticket (`/implement`, `/change` (named `/fix` until
  AGH-479), `/refactor`, `/upgrade`, `/feature` on an issue, `/deliver`, `/release`) reads the ticket's comments with
  its own tracker tools. It takes the newest comment that starts with `In progress in session`, `Took over from
  session` or `Released by session`.
  - None, or a release: it claims the ticket. Locally it first runs `hub claim take <ticket> --session <id>`, which
    writes `.agent-runs/claims/<ticket>.json` (session id, Claude Code process id and start time, hub path, claim
    time, last activity). Then it posts `In progress in session <id>: <link>`. The link is the cloud session's link,
    or `local, <hub path>, pid <pid>`.
  - Where the session can set its own title, the title starts with the ticket id. The session id comes from the
    session brief's `Session id:` line.
- **Liveness.** A claim held by another session is stale when that session has ended:
  - Cloud: the session is archived, or completed or failed, or it has been idle for more than 24 hours while not
    waiting on the owner (not `blocked`, not `review_ready`).
  - Local: the recorded Claude Code process is not running, or the pid now belongs to a process with another start
    time. With no recorded pid, the claim is stale once its last activity is more than 24 hours old.
  - A claim the session cannot check (another machine, no status tool) counts as live.
- **Live claim.** The second session stops before any edit, names the first (id and link), and goes on only if the
  owner says so in their own words in that session.
- **Stale claim.** The new session takes over without asking and posts `Took over from session <old id>: <why>.`
- **Release.** When the ticket moves to Done (`/deliver` step 7) or is handed off (`/handoff`), the session runs
  `hub claim release` and posts `Released by session <id>.` A released claim never stops a new session.
- `hub claim` runs outside the sandbox, because the process check needs the host's process table. It is not
  pre-allowed, because it writes a file, so it asks.

### Consequences

- Good: a second session stops with a name to look up, instead of duplicating the work.
- Good: every claim, takeover and release is a comment the owner can read; the digest (AGH-811) can read them too.
- Good: a session waiting on the owner's merge keeps its claim, however long the owner takes.
- Good: no tracker port change and no new service.
- Bad: the check depends on the session's tools: tracker comments, and in the cloud a session-status tool. Where
  either is missing, the claim counts as live and the owner decides.
- Bad: a local claim is visible only to sessions on the same machine, and a cloud claim only to sessions of the same
  account. Across them, the claim counts as live.
- Bad: two permission prompts per ticket locally (take and release).
- Bad: two more sandbox exclusions (`./hub claim *`, `hub claim *`).

### Why not the others

- 2: the assignee is a person (the owner). Moving it to mark a session would hide who owns the work, and a state
  carries no session id or liveness.
- 3: a commit per claim adds noise and a pull request to the hub, and a dead session's lock stays until a person
  removes it.
- 4: it needs `hub web` running, and cloud and CLI sessions do not write there.
- 5: it is the situation today.

## More Information

- AGH-805 spec: D4, AC-12 to AC-15. Plan amendments AM-3 (staleness by session status or process, not by idle time
  alone) and AM-4 (the title only where the session can set it).
- Related: [ADR 0063](0063-session-follows-its-own-pr.md) (the session follows its own pull request; a takeover
  session waits until the first releases the pull request's event subscription),
  [ADR 0030](0030-run-outcomes-in-the-tracker.md) (run outcomes in the tracker),
  [ADR 0059](0059-auto-mode-offered-in-every-app.md) (the one-day wait for an answer).
