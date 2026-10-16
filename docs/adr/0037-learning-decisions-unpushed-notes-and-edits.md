# 0037. Learning decisions take an unpushed inbox note

- Status: proposed
- Date: 2026-10-16
- Deciders: José Henrique Roquette
- Partially supersedes: [ADR 0024](0024-learning-actions-from-the-app.md), for where the note is read from
  only (0024 is not edited)

## Context and Problem Statement

ADR 0024 has the `hub_git` adapter refuse a learning whose note is not on `origin/<default_branch>`. `/learn` writes
its note in the hub checkout's `brain/_inbox/` and nobody pushes it on its own, so most learnings the app lists could
never be accepted or rejected: the owner had to commit and push the note by hand first, which is the step the app
exists to remove. Separately, the adapter took only `git@github.com:` and `ssh://git@github.com/` as GitHub remotes,
so a hub whose `origin` uses an ssh host alias `github.com-<account>` (the usual way to keep two GitHub accounts on
one machine) was "not on GitHub" and its actions were off.

## Considered Options

1. Keep 0024: the owner pushes every inbox note before deciding it.
2. Read the note from the hub checkout when `origin/<default_branch>` lacks it, and add it in the PR's branch.
3. Have the app commit and push the inbox note first, then open the PR (writes the user's checkout and default branch).

## Decision Outcome

Option 2.

- When the note is not on `origin/<default_branch>`, the adapter reads it from the hub checkout at
  `brain/<note>`: only read, through `lstat` (never through a link), a regular file of at most 256 KiB and UTF-8, the
  same rules as on `origin`. The PR's single commit then adds the note at its destination (mode `100644`) instead of
  moving it. The checkout's tree, index, refs and worktree list stay untouched (the tests compare them).
- A note in neither place is a 409 `change_request_conflict`, "Note not on origin/<default> nor in the hub checkout".
- An ssh remote whose host is `github.com` followed by `-<account>` parts (`git@github.com-work:owner/hub.git`,
  `ssh://git@github.com-work/owner/hub.git`) names GitHub; https keeps only `github.com`, and look-alike hosts
  (`github.com.evil.example`) stay refused.

### Consequences

- Good: a learning `/learn` proposed can be decided at once, still through a PR the owner reviews and merges.
- Good: two-account machines get learning actions.
- Bad: the PR can carry a note the default branch never had, so its review is the first time the note is seen in git.

## More Information

[ADR 0024](0024-learning-actions-from-the-app.md), [API.md](../API.md) "Learning decisions", AGH-272.
