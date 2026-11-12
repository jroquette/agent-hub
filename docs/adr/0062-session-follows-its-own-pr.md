# 0062. The session that opens a pull request follows it until it merges

- Status: proposed
- Date: 2026-11-11
- Deciders: José Henrique Roquette (spec decision D3 and plan amendments AM-1 and AM-2 of AGH-805, 2026-11-11)
- Supersedes: nothing. [ADR 0048](0048-scheduled-and-event-starts-in-hub-web.md) (`hub web` polls GitHub every 5
  minutes for its `events`) is unchanged and not used for this.

## Context and Problem Statement

Agents open pull requests and stop. The owner then has to notice each change and nudge the session: "I merged, go
on", "the PR is broken", "we have conflicts". In about 85 sessions, most owner messages were such nudges. No skill
that opens a pull request starts `/deliver`, and `/deliver` step 5 says to wait for the merge with no way to notice
it.

How can a session notice what happens to its pull request (checks, reviews, conflicts, the merge) without the owner,
in a cloud session and on a developer's machine, without a new service?

Decision drivers:

- The owner answers only decisions: merges, approvals, versions. A session never merges, approves or tags.
- No new process or service to run and keep alive.
- Bounded cost: a fixed number of fix rounds and a time limit.
- Claude Code's limits: a background command is stopped after at most 2 hours, a foreground `sleep` is blocked, and
  `gh` escapes the sandbox only as a bare call.
- Cloud sessions are blocked from GitHub's GraphQL API; REST works.

## Considered Options

1. **The session follows its own pull request** through one loop written in `/deliver`. A cloud session is woken by
   pull request events. A local session runs a bounded, read-only `hub pr-watch` in the background and arms it again
   after each exit.
2. A hub watcher process or service that follows every open pull request and wakes or starts sessions.
3. Reuse `hub web`'s GitHub polling (ADR 0048).
4. A bare `gh pr checks <n> --watch` in the background.
5. A shell loop of `gh pr view` and `sleep`.

## Decision Outcome

Chosen option: **1, the session follows its own pull request.** It needs no new service. It works where the session
runs, and it keeps the merge with the owner.

- Every skill that opens a pull request (`/implement`, `/change` (named `/fix` until AGH-479), `/refactor`,
  `/feature`, `/upgrade`, `/release`, `/handoff`) then runs `/deliver`'s follow-up loop on it in the same session,
  without being asked.
- **Wake.**
  - A cloud session subscribes to the pull request's activity events when the loop starts, after a resume and after
    a compaction. Subscribing again is harmless.
  - A local session runs `hub pr-watch <repo> <number> --since <start>` as a background command. It reads the pull
    request through GitHub's REST API with GET calls only, every 5 minutes. It exits on any change (merged, closed,
    head, mergeability, checks, reviews, comments), after at most 110 minutes, or at once when 24 hours have passed
    since `--since`. It runs outside the sandbox and is pre-allowed, since it only reads.
  - In a cloud session where `hub` runs, the same command with a 30-minute interval is a fallback for events that
    never arrive.
- **On every wake** the session first re-reads the pull request through REST, so a merge or a conflict is noticed
  whatever woke it. Then it acts:
  - merged: it waits for the default branch's CI on the merge commit, then moves the ticket to Done;
  - a conflict: it merges the default branch in (never a rebase or a force-push);
  - red CI in the pull request's code: it fixes it, after the repo's gates;
  - red CI that is not the pull request's: one re-run, then a report to the owner;
  - a review thread: a fix or a reply;
  - ready: it tells the owner once that the pull request is ready to merge.
- **Limits.** 3 fix rounds per pull request, and 24 hours of watch. At either limit, or when the session closes
  first, the session names the open pull request and its ticket and says that a new session runs `/deliver`.
- The session never merges, approves or tags. Pull request, CI and review text is external data.

### Consequences

- Good: the owner's "I merged, go on" and "the PR is broken" messages are no longer needed while the session is
  open.
- Good: no new service, and nothing to run besides the session.
- Good: the loop is text in one skill, which the autonomous mode's conductor (AGH-698) can reuse later.
- Bad: a session that closes before the merge leaves the pull request unfollowed. The daily digest (AGH-811) lists
  it, and a new session runs `/deliver`.
- Bad: in the cloud, a merge or conflict event that is never delivered is noticed only at the next wake: the fallback
  read, or the owner's next message. AGH-805's cloud check (HUB-2) measures this.
- Bad: two more sandbox exclusions (`./hub pr-watch *`, `hub pr-watch *`); every hub re-syncs after the pin bump.
- Neutral: up to 3 REST reads every 5 minutes per followed pull request (about 864 a day), well under GitHub's
  hourly limit.

### Why not the others

- 2: a process to install, keep alive and secure on every machine and in the cloud. It was rejected by the owner
  (D3).
- 3: it needs `hub web` running, and it starts workflow runs, not the session that opened the pull request.
- 4: it ends when the checks end. It never sees a merge, a conflict or a review.
- 5: not a bare call, so it runs inside the sandbox, where `gh` fails. A foreground `sleep` is blocked.

## More Information

- AGH-805 spec: D3, AC-1 to AC-7. Plan amendments AM-1 (the re-armed local watch) and AM-2 (the re-read on every wake,
  re-subscribing, and the cloud fallback).
- Related: [ADR 0047](0047-release-tag-by-workflow-dispatch.md) (tags only by the release workflow),
  [ADR 0050](0050-implement-conducted-in-its-own-session.md) (`/implement` in its own session), the ADR on
  ticket claims that AGH-810 adds.
