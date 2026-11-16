# 0037. Learning decisions take an unpushed inbox note and the owner's edited body

- Status: proposed
- Date: 2026-10-16
- Deciders: José Henrique Roquette
- Partially supersedes: [ADR 0024](0024-learning-actions-from-the-app.md), for where the note is read from
  and what the accept commit writes (0024 is not edited)

## Context and Problem Statement

ADR 0024 has the `hub_git` adapter refuse a learning whose note is not on `origin/<default_branch>`. `/learn` writes
its note in the hub checkout's `brain/_inbox/` and nobody pushes it on its own, so most learnings the app lists could
never be accepted or rejected: the owner had to commit and push the note by hand first, which is the step the app
exists to remove. Separately, the adapter took only `git@github.com:` and `ssh://git@github.com/` as GitHub remotes,
so a hub whose `origin` uses an ssh host alias `github.com-<account>` (the usual way to keep two GitHub accounts on
one machine) was "not on GitHub" and its actions were off. Last, an agent's note is often almost right: the owner
wants to fix a sentence before accepting it, and 0024's `BrainChange` carries only the frontmatter to set, so the only
way was a second pull request after the merge.

## Considered Options

1. Keep 0024: the owner pushes every inbox note before deciding it.
2. Read the note from the hub checkout when `origin/<default_branch>` lacks it, and add it in the PR's branch.
3. Have the app commit and push the inbox note first, then open the PR (writes the user's checkout and default branch).
4. For edits: a separate "propose an edit" PR before the accept (two PRs per learning, the first to merge and pull
   before the second can open).
5. For edits: the edited body travels in the accept request and the accept commit writes it.

## Decision Outcome

Options 2 and 5.

- When the note is not on `origin/<default_branch>`, the adapter reads it from the hub checkout at
  `brain/<note>`: only read, through `lstat` (never through a link), a regular file of at most 256 KiB and UTF-8, the
  same rules as on `origin`. The PR's single commit then adds the note at its destination (mode `100644`) instead of
  moving it. The checkout's tree, index, refs and worktree list stay untouched (the tests compare them).
- A note in neither place is a 409 `change_request_conflict`, "Note not on origin/<default> nor in the hub checkout".
- An ssh remote whose host is `github.com` followed by `-<account>` parts (`git@github.com-work:owner/hub.git`,
  `ssh://git@github.com-work/owner/hub.git`) names GitHub; https keeps only `github.com`, and look-alike hosts
  (`github.com.evil.example`) stay refused.
- `POST /learnings/{id}/accept` takes an optional `note_body` (1 character to 256 KiB): the note's text after its
  frontmatter as the owner edited it. Core refuses a blank one or one past 256 KiB (UTF-8) with a 409
  `learning_conflict`; `BrainChange` gains `note_body`, and the adapter's single commit replaces the text after the
  frontmatter (kept byte for byte) before setting `status` and `last_verified`, so the move and the edit are one
  commit. The PR body says the note was edited in agent-hub and quotes the edited body's first paragraph (redacted
  with `r1`, 200 characters). Title and labels are not editable; reject takes no edit.
- The web app keeps the edit as a draft in this browser (`ah.learning.draft.<id>`, the body and the body it started
  from), never in the database: the "Metadata only" departure holds. A draft whose starting body differs from the
  hub's note shows that the note changed in the hub.

### Consequences

- Good: a learning `/learn` proposed can be decided at once, still through a PR the owner reviews and merges.
- Good: two-account machines get learning actions.
- Good: a fix to a note is part of the accept PR the owner reviews; nothing else writes the hub.
- Bad: a draft lives in one browser; another browser or machine does not see it.
- Bad: the PR can carry a note the default branch never had, so its review is the first time the note is seen in git.

## More Information

[ADR 0024](0024-learning-actions-from-the-app.md), [API.md](../API.md) "Learning decisions", AGH-272.
