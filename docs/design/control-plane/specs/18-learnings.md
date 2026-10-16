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
- **Edit before accepting** ([ADR 0037](../../../adr/0037-learning-decisions-unpushed-notes-and-edits.md)). On a
  proposal that can be decided and whose note is readable, "Edit note" (`file-pen`) opens, in place in the Note
  section, a Write / Preview `SegmentedControl`, a monospace textarea of the body after the frontmatter (labelled
  "Note body") and "Done editing". The edit is a draft kept in this browser per learning; the Note section then shows
  the edited version, "Edited here. The accept pull request writes this version of {path}.", "Edit again" and
  "Discard edits" (an inline confirm "Discard your edits?" with "Discard edits" / "Keep"). A draft that started from
  a body the hub no longer has shows a warning banner "The note changed in the hub since you edited it." Done
  editing with nothing changed drops the draft. The accept dialog adds "Writes the note as you edited it, in the
  same commit", and the accept sends `note_body`; a successful accept drops the draft. Title and labels are not
  editable (the design's title and label editing is not built).
- **Review with Claude.** A **Review** section on a proposal that can be decided and has its note: "Review with
  Claude" starts a hub-web session in the project's hub folder (the reason shows beside the disabled button when
  this machine cannot drive Claude or the hub has no folder). Its first message holds the note to `/learn`'s bar
  (non-obvious, verified, not a duplicate, well written), asks for a brain target among the learning's
  `target_choices`, and lets it write only `review.json` (verdict `ready` | `needs_changes` | `not_for_brain`, a
  summary, named checks pass / fail / could not tell, a target) and, when the note should change, `note.md` (the
  revised body) in a draft folder; it never edits, accepts, commits or pushes. The section follows the session
  ("Claude is checking…", waiting on a permission, ended without a verdict, a verdict it cannot read) and shows the
  verdict as a `StatusBadge` ("Ready for the brain", "Needs changes", "Not for the brain") marked "Claude's
  recommendation · you decide", each check with an icon and a word, "Use Claude's revision" (it becomes the edit
  draft) and "Use target brain/{target}" (it fills Target), "Open the conversation" and "Review again". The link
  between a learning and its review session is kept in this browser.
- **Discuss.** The learning and a Brain note register a Discuss target with one-click starters (the Discuss panel's
  "Start with" group): a proposal offers "Is this worth keeping?", "Improve the note", "Duplicate or overlap?" and
  opens Discuss on arrival; an accepted note offers "Is this still true?", "Improve the note", "Duplicate or
  overlap?". The brief names where the note is, the `/learn` criteria and, for a missing note, that its title is
  all there is.

## Acceptance criteria

| Id | Given / when / then | Test |
|---|---|---|
| AC-272.1 | Given proposals some of which cannot be decided here, when the queue loads, then the decidable ones come first and the blocked ones after them, each group oldest first, each blocked row names why, and the strip reads "{r} ready · {b} blocked · oldest first" | `index.test.tsx` "lists decidable proposals before blocked ones and says why each is blocked" |
| AC-272.2 | Given a title starting "Proposal:", when it is shown in the queue or the detail, then the prefix is left out | same test |
| AC-272.3 | Given a long title, when its row renders, then it wraps to two lines without widening the table and the whole title is its tooltip | `index.test.tsx` "wraps a long title and keeps it whole on hover" |
| AC-272.4 | Given a status other than Proposed, when the owner picks it, then the URL carries `?status=` and Back returns to the previous status; opening that URL shows that status | `index.test.tsx` "keeps the status in the URL" |
| AC-272.5 | Given a note with frontmatter, when the learning is open, then its type, repos and last verified show as chips and its provenance shows even when the event has none | `LearningDetail.test.tsx` "shows the note's type, repos and provenance from its frontmatter" |
| AC-272.6 | Given a proposal whose note is not in the hub checkout, when it is open, then the detail explains where the note was recorded and why it is missing, and a warning banner says it cannot be decided here | `LearningDetail.test.tsx` "explains a note missing from the checkout and blocks the decision" |
| AC-272.7 | Given an accept with an edited body, when the hub PR is opened, then its one commit moves the note, keeps the frontmatter, writes the edited body and sets `status: accepted`, and the PR body says the note was edited and quotes the edited first paragraph | `test_decide_learning.py` (edited body tests), `brain_change_requests_contract.py` "writes edited body with frontmatter when accepted with edit", `test_frontmatter.py` `TestWithBody` |
| AC-272.8 | Given an edited body that is blank or over 256 KiB, when it is accepted, then the API answers 409 (422 for an empty one) and nothing is pushed | `test_decide_learning.py`, `routes/test_learnings.py` |
| AC-272.9 | Given a learning that can be decided, when the owner edits its note and accepts, then the request carries `note_body`, the dialog says the edit is written in the same commit, and the draft is dropped | `LearningDetail.test.tsx` "accepts the edited body in the same pull request" |
| AC-272.10 | Given an edited note, when the page reloads, then the edit is still shown as edited, and Discard edits asks before dropping it | `LearningDetail.test.tsx` "keeps the edit across a reload and discards it after a confirm" |
| AC-272.11 | Given a draft started from a body the hub no longer has, when the learning opens, then a warning says the note changed in the hub | `LearningDetail.test.tsx` "warns when the note changed in the hub since the edit started" |
| AC-272.12 | Given a learning that cannot be decided, when it is open, then no edit is offered | `LearningDetail.test.tsx` "offers no edit when the learning cannot be decided" |
| AC-272.13 | Given a note only in the hub checkout, when it is accepted, then the PR adds it from the checkout, which stays untouched; a link there is refused | `test_brain_change_requests.py` "adds note from checkout when never pushed", "refuses checkout note when it is a link" |
| AC-272.14 | Given an `origin` through an ssh alias `github.com-<account>`, when availability is checked, then it is GitHub; look-alike hosts stay refused | `test_github_remote.py` |
| AC-272.15 | Given a proposal that can be decided, when the owner clicks Review with Claude, then a session starts in the hub folder with the review prompt (the note, the `/learn` bar, the draft folder, that the owner decides) | `ReviewPanel.test.tsx` "starts a review session in the hub folder with the review prompt", `review.test.ts` "names the note, the bar, the draft folder and that the owner decides" |
| AC-272.16 | Given the session wrote its verdict and revision, when the learning is open, then the verdict, checks, revision and target show, and Use Claude's revision / Use target fill the edit draft and Target | `ReviewPanel.test.tsx` "shows Claude's verdict and hands its revision and target to the learning", `review.test.ts` (parse, writes, waiting and malformed) |
| AC-272.17 | Given this machine cannot drive Claude, when the Review section shows, then the button is disabled and says why | `ReviewPanel.test.tsx` "says why a review cannot start on this machine" |
| AC-272.18 | Given a learning or a Brain note, when Discuss opens, then it offers its starters and one click starts the conversation with that message; a target without starters offers none | `discussLearning.test.ts`, `DiscussPanel.test.tsx` "starts the conversation with a starter's message in one click", "offers no starters when the target has none", `LearningDetail.test.tsx` "offers to talk with Claude about the learning" |
