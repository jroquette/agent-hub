# Learnings

**Phase:** P2 as built (AGH-201 moved accept and reject into P2; snooze stays P3) · **Route:** `/knowledge/learnings`,
`/knowledge/learnings/:learningId`, query `?status=&learning=` · **Answers:** "Which of these can go into the brain, and
is each one right before I accept it?"

There was no screen spec for Learnings: it was defined by `01-navigation.md`, `02-data-and-api.md` (Learning, as built
AGH-201), `22-first-run-and-errors.md`, `30-flows.md` Flow 4, `31-responsive.md` and
[ADR 0024](../../../adr/0024-learning-actions-from-the-app.md). This spec records the screen as the owner validated it
in the playground (AGH-272); the README's Departures still win over it.

## Purpose and primary user

The hub owner triages what agents proposed with `/learn`. The screen shows at a glance which proposals can be
decided here, lets the owner check each one, and ends an accept or a reject in a hub pull request he merges
(ADR 0024). The one action that matters most: **Accept** a learning that is ready.

## Layout (1440 px)

A two-column body under the Knowledge header: the queue (a `DataTable`, one row per learning) on the left, the
selected learning's detail on the right. The Status `SegmentedControl` (Proposed, Accepted, Rejected) sits in the
header.

- **Queue.** Proposals that can be decided first, oldest first, then the blocked ones (oldest first). The column
  header reads "Learnings · {n} {status}"; the strip above the table reads "{r} ready · {b} blocked · oldest first"
  when some proposals are blocked. A row shows the title (without an agent's "Proposal:" prefix, wrapped to two
  lines, the whole title on hover), the summary (one line), a `blocked` `StatusBadge` naming why when the proposal
  cannot be decided here, and its state, provenance, external label and project.
- **Detail.** Title, state badge, provenance (from the event, else the note's frontmatter), "proposed {age} ago by
  {agent}" (the exact time on hover); a **Frontmatter** section with `FrontmatterChips` (type, repos, last verified)
  when the note has any; the **Note** section; Target, Source, Pull request and Decision as before; the action bar.
  A proposal that cannot be decided shows, under the disabled buttons, a warning `Banner` "Cannot be decided here."
  with the reason. A note missing from the hub checkout says that the agent recorded that path, that it was likely
  written in another worktree and never pushed, and that pulling the hub brings it in.

## Acceptance criteria

| Id | Given / when / then | Test |
|---|---|---|
| AC-272.1 | Given proposals some of which cannot be decided here, when the queue loads, then the decidable ones come first and the blocked ones after them, each group oldest first, each blocked row names why, and the strip reads "{r} ready · {b} blocked · oldest first" | `index.test.tsx` "lists decidable proposals before blocked ones and says why each is blocked" |
| AC-272.2 | Given a title starting "Proposal:", when it is shown in the queue or the detail, then the prefix is left out | same test |
| AC-272.3 | Given a long title, when its row renders, then it wraps to two lines without widening the table and the whole title is its tooltip | `index.test.tsx` "wraps a long title and keeps it whole on hover" |
| AC-272.4 | Given a status other than Proposed, when the owner picks it, then the URL carries `?status=` and Back returns to the previous status; opening that URL shows that status | `index.test.tsx` "keeps the status in the URL" |
| AC-272.5 | Given a note with frontmatter, when the learning is open, then its type, repos and last verified show as chips and its provenance shows even when the event has none | `LearningDetail.test.tsx` "shows the note's type, repos and provenance from its frontmatter" |
| AC-272.6 | Given a proposal whose note is not in the hub checkout, when it is open, then the detail explains where the note was recorded and why it is missing, and a warning banner says it cannot be decided here | `LearningDetail.test.tsx` "explains a note missing from the checkout and blocks the decision" |
