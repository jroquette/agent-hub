# Learnings

**Phase:** P2 as built (AGH-201 moved accept and reject into P2; snooze stays P3) · **Route:** `/knowledge/learnings`,
`/knowledge/learnings/:learningId`, query `?status=&learning=&q=&project=&readiness=&claude=&provenance=` · **Answers:** "Which of these can go into the brain, and
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
  cannot be decided here, and its state, provenance, external label and project. A proposal **resolved elsewhere**
  (its inbox note is gone from a hub checkout that reads fine: someone triaged it by hand) is not a pending
  decision: it is hidden from All, Ready to decide and Blocked, and its row reads "Resolved outside the app: the note
  is no longer in the inbox" with a "Resolved elsewhere" (`ended`) state badge instead of a `blocked` one.
- **Detail.** Title, state badge, provenance (from the event, else the note's frontmatter), "proposed {age} ago by
  {agent}" (the exact time on hover); a **Frontmatter** section with `FrontmatterChips` (type, repos, last verified)
  when the note has any; the **Note** section; **Review**; **Project**; the **Trail** (AGH-393, below), which
  replaces the Source, In the brain, Pull request and Decision rows; **Target in brain/** (decidable proposals only,
  next to the action bar); the action bar.
  A proposal that cannot be decided shows, under the disabled buttons, a warning `Banner` "Cannot be decided here."
  with the reason. A proposal resolved elsewhere instead shows, under the disabled buttons (their tooltip the same
  reason), an info `Banner` "Nothing to decide here." with "Resolved outside the app: the note is no longer in the
  inbox"; its Note section names the inbox path, says nothing is recorded as accepted or rejected, and that a note
  written only in another worktree comes back once pushed and pulled. A note missing from the hub checkout says that the agent recorded that path, that it was likely
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
- **Trail** (AGH-393). One `Section` labelled "Trail" holds a vertical `ProvenanceLineage`, an `ol` named "Trail
  from session to note": one step per `li`, each starting with its visible name, a decorative 16 px icon and a 1 px
  connector; no node is dashed or coloured, so what a step waits for is said in words. Nothing after the note is
  claimed (Q16). The trail renders from the learning already loaded; no new request.

  | Step | Content | Link |
  |---|---|---|
  | **Session** (`square-terminal`) | "Session <short id>" (the full id in a tooltip); none: "No source session recorded." | `/sessions/<source_session_id>` |
  | **Proposal** (`lightbulb`) | "Open at that moment" (no event id: "Open the session timeline"), then the inbox path as text, `brain/` once; no session and no path: "No proposal event recorded." | `/sessions/<id>?event=<source_event_id>` (the default `?tab=timeline` omitted, AM-1), else `/sessions/<id>` |
  | **Decision** (`split`) | proposed: "Not decided yet"; with a `pr_url`: "Accepted <time> by <person>" (or "Rejected …"), the app's absolute time format; without one: "Accepted outside the app" (or "Rejected outside the app"), with a muted "<time> by <person>" line under it when recorded (the time alone, or "by <person>" alone, when only one is), without the verb again; a rejection's reason under it; then `git-pull-request` "Pull request #<n> in <owner>/<repo>" (the URL itself when it is not a GitHub pull request), through `safeHref`, a new tab ("(opens in a new tab)" for assistive tech) | the PR |
  | **Note** (`file-text`, accepted only) | `brain/<rest>` once (D-brain-path: one leading `brain/` removed from `brain_path`), then "In the brain"; `accepted_pr_open`: the path as text, then "In the brain once the pull request is merged and pulled"; no path: "No note path recorded."; a path the note route refuses (AM-8) is text whatever the state, its muted line ending "· not opened here" ("In the brain · not opened here"), with the Brain's knowledge-row tooltip, "The app does not open notes at this path (not a .md file, a hidden name, under auto/, too long or deep, or with an empty part or characters the app does not serve)" (spec 19) | `/projects/<project>/brain/<rest>` when `state` is `in_brain` and the note route serves the path |

  A rejected or proposed learning has no Note step. Right after an accept or a reject on this page, the Decision step
  reads "Accepted just now · pull request opened" (or "Rejected just now · pull request opened") with its link, only
  while the learning has no `decided_at`; once the refetched learning records the decision, the step reads as above,
  "Accepted <time> by <person>" in the shared time format. After an accept the Note step shows the path the typed
  target gives, as text, with the "once merged" line, until the refetched learning says more.
- **Discuss.** The learning and a Brain note register a Discuss target with one-click starters (the Discuss panel's
  "Start with" group): a proposal offers "Is this worth keeping?", "Improve the note", "Duplicate or overlap?" and
  opens Discuss on arrival; an accepted note offers "Is this still true?", "Improve the note", "Duplicate or
  overlap?". The brief names where the note is, the `/learn` criteria and, for a missing note, that its title is
  all there is.

- **Filters** (above the queue, in the URL, mirroring the Skills catalog): a search over title, summary and project
  (200 characters); quick views **All · {n}**, **Ready to decide · {n}**, **Blocked · {n}** and, when there is any,
  **Resolved elsewhere · {n}** (Proposed only; All is ready plus blocked). The quick-view counts, and the Learnings
  tab's count, are decisions, not rows: proposals of the same inbox note (one per session) count once; compact
  `FacetMenu`s "Project" (one project; shown when the queue spans several), "Claude" (its recommendation) and
  "Source" (provenance), each listing its options with how many learnings each keeps given the other filters; "Clear
  all"; an empty result says nothing matches. A menu closes on Escape or a click outside it. Unknown values in a
  hand-written URL are dropped.
- **Triage with Claude** (Proposed, one project): "Triage with Claude · {n}" starts one hub-web session in the
  project's hub folder over up to 15 decidable proposals with a note and no verdict yet, each reviewed into its own
  draft folder exactly as a single review (above). A queue spanning several projects asks to pick one; a machine
  that cannot drive Claude says why. A **Triage progress** strip shows the run live ("Live", "Needs you", "Done" or
  "Stopped"), the learning Claude is on now, how many are done and queued, and links the conversation ("Answer in the
  conversation" when it waits on you); it can be dismissed when finished. Each row carries Claude's recommendation
  ("Goes in", "Needs changes", "Leave out", "Reviewing now", "Queued", "Needs you", "No verdict"), and the detail
  opens with it at the top ("Claude's recommendation · you decide", or what Claude is doing with it now). A
  finished run gives no verdict to the learnings it never reached.
- **Triage marks** (AGH-687, validated in the playground snapshot `20261106T092037Z`). On a proposal that can be
  decided, the accept and reject dialogs add "Mark to accept" / "Mark to reject" beside "Open pull request" ("Deciding
  several? Mark this one instead: every marked learning goes into one triage pull request you open from the list.").
  A mark is kept in this browser, never sent until asked. The detail then shows "Marked to accept" (to its target,
  "with your edit" when edited) or "Marked to reject" (its reason), "It goes into the triage pull request with the
  other marked learnings." and Unmark; the dialog opens again to change it. The queue row shows a "Marked: accept" or
  "Marked: reject" badge, and after a mark the queue selects the next learning down that can be decided and is not
  marked (it stays put when there is none). Accepting or rejecting a marked learning on its own drops its mark.
  - On Proposed only, a bar "Marked learnings" above the queue reads "{n} marked" and "{a} accept · {r} reject", with
    Clear and "Review and open PR".
  - "Review and open PR" opens the dialog "Open the triage pull request": the marks by project (alphabetical), each
    with its counts, its learnings (each opens its detail; Unmark), and its own "Open pull request" ("Opening pull
    request…" while it runs; disabled over 50, "At most 50 per pull request"). One project's pull request is
    `POST /api/v1/learnings/decisions` ([API.md](../../../API.md#learning-decisions)): opened, its marks clear and
    the dialog says "Pull request opened for {project} · {n} learnings" with its link; refused, the marks stay and an
    alert says "Could not open the pull request." with the reason and "Nothing was pushed; fix or unmark that
    learning and try again." Tab stays in the dialog; Escape and Close close it, except while a pull request is being
    opened.

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
| AC-272.19 | Given learnings of several projects, provenances and verdicts, when the owner searches, picks a quick view or a facet, then the queue keeps only matching rows, each option shows its count with the other filters applied, the choice is in the URL (other parameters kept, unknown values dropped) and Clear all resets it | `filters.test.ts`, `index.test.tsx` "narrows the queue to one project and keeps the choice in the URL", "says nothing matches when the search finds no learning" |
| AC-272.20 | Given an open facet menu, when the owner presses Escape or clicks outside, then it closes | `index.test.tsx` "closes a filter menu on Escape and on a click outside it", `data.test.tsx` "says what a facet menu keeps, lists options with counts and clears them" |
| AC-272.21 | Given one project with decidable unreviewed proposals, when the owner clicks Triage with Claude, then one session starts in the hub folder over at most 15 of them, each linked to its own draft folder | `triage.test.tsx` "starts one session over the decidable learnings and links each to its folder" |
| AC-272.22 | Given a queue over several projects, when triage is offered, then it asks for one project | `triage.test.tsx` "asks for one project when the queue spans several" |
| AC-272.23 | Given a running triage, when the queue shows, then each row carries Claude's verdict or where the review stands (current, queued, needs you), the Claude facet filters by it, and a finished run gives no verdict to learnings it never reviewed | `triage.test.tsx` "shows Claude's verdict on each row and filters by it", "marks the learnings behind the current one as queued and says when Claude needs you", "gives no verdict to the learnings a finished session never reviewed"; `filters.test.ts` "keeps the learnings Claude recommends when the Claude facet is picked" |
| AC-272.24 | Given a proposal resolved elsewhere (its note gone from a readable hub checkout) and two proposals of the same note, when the Proposed queue loads, then they are hidden from All, Ready to decide and Blocked, "Resolved elsewhere · 1" lists both rows, each reading "Resolved outside the app: the note is no longer in the inbox" with a "Resolved elsewhere" badge and no `blocked` badge | `index.test.tsx` "hides what was resolved outside the app and counts it once in its own view"; `filters.test.ts` "counts proposals of the same note once" |
| AC-272.25 | Given a proposal resolved elsewhere, when its detail opens, then Accept and Reject are disabled with that reason as tooltip, an info banner says "Nothing to decide here.", the Note section names the inbox path, the server refuses a decision with 409 and no event is stored; axe finds no serious or critical violation | `index.test.tsx` "disables accept and reject on a learning resolved outside the app" and "has no serious a11y violations in the resolved view (a11y)"; `test_decide_learning.py` "test_refuses_and_stores_nothing_when_note_resolved_elsewhere" |
| AC-272.26 | Given a proposed learning whose inbox note is absent from a hub checkout whose `brain/` reads, when the learnings or the learning are read, then its `state` is `resolved_elsewhere` (derived on read, never stored, no decision event), with no `summary`, no `note_unavailable` and the reason as `actions_unavailable`; a note that exists but cannot be read, or a `brain/` that cannot be read, keeps `proposed` and its `note_unavailable`; the global stream's `learnings_proposed` counts one per inbox note | `test_read_learnings.py` "test_resolves_elsewhere_when_note_gone_from_readable_checkout", "test_stays_proposed_when_note_present_in_readable_checkout", "test_keeps_note_unavailable_when_note_unreadable_or_checkout_unreadable", "test_resolves_elsewhere_once_per_checkout_when_many_notes_gone"; `test_event_read_models.py` "test_counts_one_proposed_learning_per_note_when_proposed_twice"; `routes/test_learnings.py` "test_serializes_resolved_elsewhere_when_note_left_inbox"; integration `test_learnings.py` "test_resolves_elsewhere_when_note_gone_from_checkout" |
| AC-393.14 | Given a learning with `source_session_id` `s1`, `source_event_id` `e1`, a pull request, accepted and in the brain at `brain/learnings/web-gates.md`, when the detail renders, then the trail shows Session, Proposal, Decision and Note in order, linking to `/sessions/s1`, the session at event `e1`, the PR (new tab) and the note, the path reading `brain/` once (also with `brain_path` `learnings/web-gates.md`); `accepted_pr_open` → the Note step is text with the "once merged" sentence; no `pr_url` → "Accepted outside the app"; no session → "No source session recorded."; a rejected learning has no Note step; axe finds no serious or critical violation | `LearningDetail.test.tsx` "trail: …" and "trail has no serious a11y violations (a11y)"; `status.test.tsx` "ProvenanceLineage …" |
| AC-687.3.1 | Given a proposal that can be decided, when the owner marks it to accept (with an edited target or body) or to reject (with a reason) in the dialog, then no pull request opens, the mark is kept in this browser and shown on the detail with Unmark, and the dialog opens again to change it | `LearningDetail.test.tsx` "marks an accept to the edited target without opening a pull request", "marks a reject with its reason and offers it again to change", "unmarks a marked learning" |
| AC-687.3.2 | Given a marked learning, when it is accepted or rejected on its own, then its mark is dropped | `LearningDetail.test.tsx` "drops the mark when the marked learning is decided on its own" |
| AC-687.3.3 | Given a mark, when it is made, then the queue row is badged and the next decidable unmarked learning is selected, or the selection stays when none follows; the bar shows on Proposed only | `index.test.tsx` "LearningsScreen triage marks" |
| AC-687.3.4 | Given marks, when the owner opens the dialog and a project's pull request, then one `POST /learnings/decisions` carries that project's marks (an accept's edited body included), the marks clear and the PR is linked; refused, the marks stay and the conflict is named; marks group by project alphabetically, over 50 are refused; Tab stays inside, Escape closes | `TriageBatch.test.tsx` |
| AC-687.3.5 | Given 1 to 50 decisions of one project, when they are sent, then one PR with one commit on `<prefix>learning-triage-<stamp>` applies them all and one event per learning names it; any refused decision (already decided, twice, two projects, one destination, read-only hub, a destination taken, the branch on `origin`) refuses the batch, nothing pushed or stored; a foreign or missing Origin is 403 and a body that is not JSON 415 | `test_decide_learning.py` (`…_when_batched`, `test_refuses_batch_…`), `test_brain_change_requests.py` (core and hub_git), `brain_change_requests_contract.py`, `routes/test_learnings.py`, `test_learning_actions.py`, `test_local_security.py` |
