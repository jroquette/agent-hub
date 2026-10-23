# Features

**Phase:** P2 (read-only) · **Routes:** `/features`, `/features/new` (AGH-420, Screen 3), `/features/{project}/{slug}` (params `doc=spec|plan|research|eval|issues` (as built: `tickets`, see Departures), `ac=AC-48.21`, `phase=`; as built also `eval=`, `tickets=table`, `ticket=<id>` and `step=<step>`, see Departures (AGH-326, AGH-330)) · **Answers:** "Where is each feature on the golden path, and is it really done?"

This section holds three screens: the **Features list**, **Feature detail** and **New feature** (AGH-420). A feature is a folder `brain/features/<slug>/` in the hub with `spec.md`, `research.md`, `plan.md`, `features.json`, `issues.md` and `eval.md`. The app only reads these files; editing a feature record stays a human act in a hub PR (principle 2).

## Departures (AGH-136, ticket planning)

Built with the changes below; where this file says otherwise, this list wins (records:
[feature-records.md](../../feature-records.md); route: [API.md](../../../API.md) "Feature tickets";
[ADR 0025](../../../adr/0025-reading-the-tracker-from-the-app.md)). For Linear, it replaces the control-plane
README's "Sources not connected": Linear is read for a feature's tickets; GitHub stays not connected.

- **Records.** A feature folder adds `evals/<delivery>.md` (one per evaluation, never overwritten; `eval.md` is read
  as the delivery `legacy`) and `reviews/<ticket>.md`. Tickets come from `features.json` (`tickets` and `linear`),
  not from `issues.md`, which only marks the plan as written.
- **Tabs.** Spec, Research, Plan, Eval, Criteria and Tickets (order replaced by AC-425.6; `?doc=spec|research|plan|eval|acs|tickets`; the old
  `?doc=issues` opens Tickets). Eval lists every delivery with its verdict, tickets, ACs, PRs and commit. Tickets
  loads `GET /features/{project}/{slug}/tickets` only while it is open.
- **Tickets tab.** Columns Ticket, Title, Status (badge with text, never color alone), Assignee, Blocked by (links,
  each edge tagged plan, Linear or both), ACs (links to Criteria `?ac=`) and Readiness ("Can start now", "Waiting on
  …", "Can start on …'s branch", "Done", "Canceled", "Waiting: cycle", "Unknown"). The assignee is shown: the owner asked for it (D1), a departure from
  "No assignee column" below. No linked run or PR column (GitHub and runs are not joined). A Linear link opens in a
  new tab, only for a `https://linear.app/` url. Below the table, the planning view: Can start now, Parallel groups
  (numbered layers), Recommended order, Critical path, and a banner for cycles and blockers outside the feature.
- **Notice.** With the plan as source, or a stale Linear snapshot, a notice says why (e.g. "From the plan
  (features.json); Linear is not connected for hub web, so status may be stale. Set LINEAR_API_KEY where hub web
  runs.") with its `as_of` and a Refresh button, which refetches the route (the 60 s cache still applies). A failed
  read shows its `tracker_problem` title.
- **Golden path stepper.** The steps come from the server (`golden_path`), not from the furthest file: done only when
  the whole feature satisfies the step (Tickets: every ticket created; Implement: every ticket Done and every AC
  passing; Review: every ticket Done in Linear or with an approved review record; Evaluate: every AC's latest eval a
  SHIP; Shipped: every ticket Done). States add `partial` ("partial: covers 3 of 36 ACs") and `unknown` ("Linear not
  connected"), each shown with text and its reason; `blocked` names the earlier step that does not hold, not a failed
  run. No step names an approver, a date range, sessions or a PR; "GitHub not connected" no longer appears. The
  Features list draws the same steps in its phase bar, and its `phase` equals the detail's.

## Departures (AGH-269, acceptance criteria, evals and records)

Built after the owner validated these in the playground; where this file says otherwise, this list wins.

**Eval tab**

- **AC-269.1** Given a project whose hub folder this machine can drive, when the owner picks a scope (Whole feature,
  or one of the feature's tickets) and presses "Evaluate <scope>", then a session starts in the hub folder in
  `acceptEdits` mode, asking the hub-workflow evaluator for that scope only, to write the next free
  `evals/<delivery>.md` and never to edit an existing eval, merge, push or change tickets.
- **AC-269.2** Given a run started from the tab, when the tab shows, then a strip gives its status as icon and label
  in a polite live region (Evaluating, Waiting for you, Finished, Finished without a new eval, Ended, Failed), its
  scope, its start time as relative time (absolute on hover) and an "Open chat" link; while it runs, Evaluate is off
  with "An evaluation is already running. Open its chat to follow it." and the scope control is disabled. The run is
  kept in the browser per feature.
- **AC-269.3** Given a run waiting for the owner's answer, then its action is the primary "Answer in chat" with the
  hand icon and the note "Claude asks before running a command. Answer in the chat."
- **AC-269.4** Given `?doc=eval&eval=<delivery>`, then that eval is read in place below the list (verdict, tickets,
  ACs, date, commit as `IdChip`, path as `PathText`, "Discuss this eval", "Open in Brain"); a row press selects
  another and keeps it in `?eval=` (replace). Without `?eval=`, the newest eval by `evaluated_at` is selected, else
  the last by name. The Discuss panel's target follows the selected eval.
- **AC-269.5** Given a run that went idle, then it reads "Finished" with a "Show <delivery>" button for each eval it
  wrote, or "Finished without a new eval" (not done) with a note to open the chat when it wrote none; a run no longer
  in flight can be cleared ("Clear this run"); a run whose session was deleted is forgotten.
- **AC-269.6** Given the machine cannot drive Claude or the project has no hub folder, then Evaluate is off with the
  reason in its tooltip and accessible name, and the capability problem shows as a warning banner.
- **AC-269.7** `SegmentedControl` takes `disabled`: every segment is off for pointer, keyboard and screen readers,
  and the value still shows.
- **AC-269.8** Given no eval yet, then the empty state says "No evals yet." and points to Evaluate.

**Acceptance criteria tab** (replaces "AC table" below where they differ)

- **AC-269.9** The tab reads "Acceptance criteria" with the `list-checks` icon and the count (`?doc=acs` unchanged).
- **AC-269.10** Each row shows: the status as icon and word ("Passes", "Owner step", "Not passing"); the criterion
  (id, repo chip, the whole description wrapped, Given/When/Then kept as text); the evidence in plain words, read
  from the evidence text ("4 tests passed" in `done`, "2 of 12 tests failed" in `failed`, "Command succeeded",
  "Superseded", "Recorded note", "No evidence yet"), with the commit (a GitHub link when the repo's `github` is
  known) and the date below it and a tooltip that explains each number; the documents citing it ("2 docs · 3×");
  and a labelled "Discuss" button (accessible name "Discuss AC-n with Claude", "In next message" while attached).
  A hint line under the filters says what Discuss does. The verification command leaves the row.
- **AC-269.11** An expanded row is a card in four labelled regions: *What must be true* (Given / When / Then on
  three lines); *How it was proven* (result in plain words and as recorded, commit, pull request, date, the
  `NAME=VALUE` settings it ran with, "Failed before" for a red-on-base clause, the eval records it names or the
  latest eval naming the AC as links to `?doc=eval&eval=`, an open owner check, and the recorded text, kept whole);
  *Check it yourself* (the command in a `CodeBlock` with "Copy command", or "Manual owner step:" with the steps);
  *Where it is cited* (each record of `brain/features/<slug>/` naming the id, in document order, with its first
  section, mention count and snippet, linking to the record tab, the eval, or the Brain note at the section).
  Facts read from the evidence text are marked derived; the recorded text is the source.
- **AC-269.12** Every criterion is listed at once: no fold, no "Show all".

**Record tabs: human summaries** (replaces "Rendered documents" below for Spec, Research and Plan)

- **AC-269.13** Given `brain/features/<slug>/summaries/<record>.md`, when a Spec, Research or Plan tab opens, then
  it shows that summary ("For humans", with when it was written and from which record); the "Agent markdown"
  segment shows the record itself as before, kept in `?view=agent`.
- **AC-269.14** A summary point linking to the record's section (`../plan.md#approach`) opens Agent markdown at that
  heading, in the same tab.
- **AC-269.15** Given the record's `sha256` (brain note route) differs from the summary's `source_sha256`, then a
  warning says the record changed after the summary was written, with "Ask Claude to update it" and "Read the full
  <record>.md".
- **AC-269.16** Given no summary yet, then the tab says so with "Ask Claude to write it" (opens Discuss, whose
  one-click starter "Write the human summary of <record>" asks for `/summarize <slug> <record>`) and "Read the full
  <record>.md". A Discuss target can carry such starters: one click sends the starter's message as the first one.
- **AC-269.17** `GET /projects/{project}/brain/note` returns `sha256`, the hex SHA-256 of the file's bytes.
- **AC-269.18** hub-workflow ships `/summarize` (records: [feature-records.md](../../feature-records.md)), and
  `/feature`, `/research` and `/create-plan` run it each time they write or amend a record.
## Departures (AGH-268, ticket flow)

Built with the changes below, validated by the owner in the playground; where this file or the AGH-136 list says
otherwise, this list wins. Each item is an acceptance criterion.

- **AC-268.1 In progress.** Given a ticket started in Linear (a `started` state such as In Progress or In Review),
  when the tickets are planned, then its readiness is `in_progress` ("In progress"): it wins over waiting on a
  blocker and is never listed in `can_start`.
- **AC-268.2 Flow.** Given the Tickets tab, when it opens, then it leads with a flow: the parallel groups as steps
  left to right, then the settled tickets; each card shows the ticket's Linear status, readiness, AC progress,
  review and whether it is on the critical path.
- **AC-268.3 Folded ACs.** Given a ticket with many ACs, when the table shows it, then its ACs fold into how many
  pass.
- **AC-268.4 Live.** Given the Tickets tab is open, then it rereads Linear every 30 s (the server still caches it for
  60 s) and the record every 15 s, and the source line says how long ago Linear was read.
- **AC-268.5 Implement counts work under way.** Given tickets in progress, when the golden path is built, then
  Implement's meta counts them ("0/3 tickets delivered · 2 in progress · 17/18 ACs") and a started ticket marks the
  step as started.
- **AC-268.6 Features list refresh.** Given the Features list is open, then it rereads the records every 30 s.
- **AC-268.7 Epics.** Given a ticket that is the parent of another row (the plan's optional `parent`, else Linear's
  parent issue), when the tickets are planned, then it is an epic: readiness `epic`, listed under `planning.epics`,
  never in a layer, on the critical path or in a blocker's place; the golden path counts it under Tickets only.
- **AC-268.8 Epic card.** Given an epic, when the Tickets tab opens, then an epic card heads the flow (its Linear
  status and link, a bar of its children done and in progress, their AC count), and the table lists the epic
  first, tagged, with its children under it.
- **AC-268.9 Plan parent.** Given a plan whose `parent` names no ticket of the plan or the ticket itself, when
  `hub doctor` runs, then it reports it; the planner writes `parent` on each child of an epic.
- **AC-268.10 Implement ends at review.** Given every ticket In Review or Done in Linear (or with an approved review
  record), when the golden path is built, then Implement is done; with tickets, a failing AC no longer holds
  Implement (Evaluate reports it) and is only counted in Implement's meta.
- **AC-268.11 Graph.** Given the ticket flow, then its steps share the width and an edge is drawn from each blocker
  to the ticket it holds back, the critical path, plan-only and started-early edges styled apart (the node
  measuring is the workflow graph's, as a shared hook).
- **AC-268.12 Cards.** Given a card of the flow, then it leads with the id, the Linear status (or "Not created") and
  the title's words; below a divider, a status line with the readiness only when it adds to the Linear status
  ("Can start now", "Waiting on X", "Can start on X's branch", "Started before X was done", "Reviewed · waiting for Done") and the newest
  session or Start, then the facts in two fixed rows: progress (AC meter, PR, Reviewed) and people and order
  (assignee, After X, Critical path). The legend folds beside the flow's title.
- **AC-268.13 Table.** Given the Tickets table, then ids stay on one line, an epic is tagged in its title and its
  children are marked with a branch.
- **AC-268.14 Done stays put.** Given a ticket that is done, when the flow is drawn, then it stays in its step, so the
  steps after it do not move.
- **AC-268.15 Opening tab.** Given a feature without `?doc=`, when it opens, then it opens where its work is: the
  record being written (Spec, Research, Plan), Tickets while it is built and reviewed, Criteria once it is evaluated
  or shipped.
- **AC-268.16 Steps open tabs.** Given the golden path, when a step is chosen, then the tab holding its evidence opens
  (Evaluate opens Eval).
- **AC-268.17 Header chips** (superseded by AC-425.5). Given the feature's tickets, then each header chip shows the id with its Linear status
  and the title on hover; the "PR —" placeholder is gone while GitHub is not connected.
- **AC-268.18 Sessions by issue.** Given `GET /sessions?issue=<id>` (any case), then it lists the sessions about that
  issue: the one their first prompt names (`/feature <id>`, a ticket's Start), else their branch or worktree, for
  the hub's tracker teams, else the issue their run names. A session started in the hub folder takes the hub
  checkout's branch, which can name another ticket, so the first prompt wins.
- **AC-268.19 Ticket sessions.** Given the Tickets table, then each ticket lists its sessions (asked by its issue), each
  linked to its detail (or its chat when driven), with its status (as the Sessions list shows it) and start time.
- **AC-268.20 No scope column.** Given the Tickets table, then the title shows its words without the
  conventional-commit prefix and there is no Scope column (it was empty for most tickets and told the owner nothing).
- **AC-268.21 Start a ticket.** Given a created ticket that can start now, then its card and row offer Start, which
  starts a Claude session in the hub folder that works that one ticket with `/feature` from its workspace step and
  opens its chat; disabled, with the reason, when this machine cannot drive Claude or the hub has no folder.
- **AC-268.22 Stacked start.** Given a created ticket whose only blocker not done is a ticket of this feature in
  review with an open pull request, then its readiness reads "Can start on X's branch" (in the table, with "X is in
  review, not merged" below) instead of "Waiting on X", and it offers the same Start (default, not primary), which
  first confirms the risk in a dialog, then starts a session that creates the worktree from X's pull request branch
  and opens a pull request stacked on it.
- **AC-521.2.1 Start runs /implement** (AGH-521, supersedes AC-268.21's skill). Given a created ticket free to start,
  then Start's session opens with `/implement <ticket>`, so the `implement` workflow writes the ticket's context brief
  and preflight and its Context and Preflight steps are recorded; the prompt never sends the session through
  `/feature`'s in-line steps. A stacked ticket (AC-268.22) keeps `/feature <ticket>` from step 6 (Implement), since the
  `implement` workflow cannot start a worktree from a blocker's branch.

---

## Departures (AGH-374, what needs you)

**Features list**

- **AC-374.1** Given features with a broken record, a NO-SHIP verdict or owner steps left, when the Features list
  opens, then there is no "Needs you" group: each sits in In progress with a warning on its row (the edge and line in
  the blocked tone for a broken record, failed for NO-SHIP, waiting for owner steps), and a feature with no warning
  has no tone.
- **AC-374.2** Given rows that need the owner in In progress, when the group is open, then its hint reads "What needs
  you first, then furthest along and most ACs passing" followed by how many of each kind ("1 session waits on you · 1
  your turn in a session · 1 wait on your steps · 1 no ship · 1 record cannot be read", only the kinds present), and
  the page summary starts with "N need you".
- **AC-374.3** Given a live session (not a subagent) whose issue (its label's, else the tile's, any case) is one of
  the feature's issues, or whose title names the feature's slug, when it waits on a permission or a question, then the
  feature's row reads "A session waits on you · <reason>" ("a permission prompt" when the session gives none); when
  its turn ended, the row reads "Your turn in a session · <last action>". A busy session, a subagent or a session on
  other work flags nothing, and a shipped feature is never flagged.
- **AC-374.4** Given several sessions waiting on the same feature, when the row is drawn, then a session waiting on a
  permission wins over one whose turn ended, then the most recent.
- **AC-374.5** Given rows that need the owner, when In progress is sorted, then they lead it in this order: a session
  waiting on you, your turn in a session, a broken record, NO-SHIP, owner steps; then the rest, furthest along and
  most ACs passing first.
- **AC-374.6** Given a row whose session waits on you, when the owner opens it, then the feature opens
  (`/features/<project>/<slug>`, no `?doc=`), not the session's chat.

**Sidebar**

- **AC-374.7** Given features that need the owner (a session waiting on you, a broken record, NO-SHIP, owner steps),
  when the sidebar is shown, then Features carries a badge with their count, named "Features, N need you", counted
  from the same features and live sessions the list reads; there is no count until the features are read, and the
  count still comes when the live sessions cannot be read.

## Departures (AGH-376, tickets, ACs and evals)

**Ticket pull requests (core and API)**

- **AC-376.1** Given a ticket's review record (`reviews/<ticket>.md`) whose `pr` is `<repo>#<n>` (the repo's `dir` or
  its GitHub name, any case) or a `https://github.com/<owner>/<repo>/pull/<n>` URL, when the feature's tickets are
  read, then the ticket's row carries `pr_url`, the GitHub URL resolved with the hub's repos (matched by the ticket's
  id, else its plan key); `#pending`, a repo the hub does not have and a malformed record give none, and a later
  record of the same ticket wins.

**Tickets tab**

- **AC-376.2** Given the Tickets table, when it shows a ticket's ACs, then every ticket shows the same AC meter as the
  flow card ("N/M ACs passing") whatever the number of ACs, with the AC ids folded under it, each with its status as
  icon and text (Passes, Owner step, Not passing).
- **AC-376.3** Given a ticket with a pull request, when the Tickets table is shown, then its last column, PR, links it
  as "PR #<n>", opening GitHub in a new tab ("PR #<n> of <ticket> (opens GitHub in a new tab)"); a URL that is not a
  GitHub pull request shows as plain text titled "Link not shown: only GitHub pull request links are opened"; a ticket
  without one shows "—" with the reason in its tooltip.
- **AC-376.4** Given a ticket with a pull request, when its flow card is drawn, then the card's progress row links "PR
  #<n>" the same way.
- **AC-376.5** Given the Tickets table, then there is no Scope column and the title shows its words without the
  conventional-commit prefix.
- **AC-376.6** Given a card of the flow, then it leads with the id, the Linear status (or "Not created") and the
  title's words; below, a status line with the readiness only when it adds to the Linear status ("Can start now",
  "Waiting on X", "Started before X was done", "Reviewed · waiting for Done"; nothing for a done ticket) and the
  newest session (named "Newest session: <status>, started <day>, <time>") or Start, then two fixed fact rows:
  progress (AC meter, PR, Reviewed) and people and order (assignee, After X, "Critical path").
- **AC-376.7** Given an AC id in the Tickets tab, when it is clicked, then the Criteria tab opens on that AC
  (`?doc=acs&ac=<id>`), even in a phase whose default tab is Tickets.
- **AC-376.8** Given an AC id in the Tickets table, when it is hovered or focused, then the shared Tooltip shows what
  must be true (the Then of a Given / When / Then, else the whole text, three lines at most), tied to the link with
  `aria-describedby` and with no `title`.
- **AC-376.9** Given the Criteria tab opened on an AC by `?ac=`, then keyboard focus moves to that AC row's toggle.

**Eval tab**

- **AC-376.10** Given a SHIP-WITH-OWNER-STEPS eval and a later owner SHIP sign-off, when the evals are listed, then
  that eval reads as SHIP with "owner steps signed off" (the tooltip says what the eval said and which sign-off
  settled it); an owner-steps eval after the sign-off, or with no sign-off at all, stays as it was; an undated eval
  counts as before the sign-off.
- **AC-376.11** Given evals of several scopes, when the Eval tab opens, then each group is headed by its ticket and
  the ticket's title and folds; only the selected eval's group (or a single scope) starts open; the evals read as
  "Eval N", the newest marked "latest", an older owner-steps one "replaced by Eval N"; each eval's ACs show as in the
  Tickets tab ("2/3 ACs passing"); the date shows with how long ago under it.
- **AC-376.12** Given the evals list, when the owner chooses Hide list, then the table folds and stays folded on this
  machine ("Show list" opens it).
- **AC-376.13** Given the latest eval of a scope is SHIP-WITH-OWNER-STEPS and no owner decision settled it, when the
  Eval tab shows it, then one "Waiting on you" callout under its ticket ("<ticket> Eval N passed with owner steps. Did
  you do them?") offers Needs more work and Mark owner steps done, and stays in view when its group is folded;
  choosing one turns it into a short form with "Note (optional)" and Cancel; Cancel sends nothing.
- **AC-376.14** Given the callout's form, when the owner confirms, then `POST .../owner-signoff` gets `{delivery,
  decision: "done" | "more_work", note}` and the written eval is selected; the API writes an owner SHIP (done) or
  NO-SHIP (more work) eval over that eval's waiting ACs with the note under "Owner's note", without needing the whole
  feature covered; it refuses an eval that is unknown, not SHIP-WITH-OWNER-STEPS or already settled, `more_work`
  without an eval, and answers 422 for an unknown decision or key; with no body it signs off every waiting AC as
  before. A `delivery` naming the acceptance eval follows two-level-flows A9 and A11 instead: it covers exactly what
  Acceptance waits on, with A9's refusals (a waiting AC whose latest eval is NO-SHIP, an undated or future-dated
  acceptance eval, evals left unread), except that `more_work` is not refused over ACs an agent's eval reopened, and
  either decision is refused, writing nothing, once an owner decision newer than the acceptance eval settled it.
- **AC-376.15** Given an owner decision after the latest owner-steps eval, then no callout asks again: more work reads
  "you found more work" on the eval and "Owner: more work" on the owner's row, a sign-off reads "Owner sign-off".
- **AC-376.16** Given evals waiting on owner steps, when the feature page opens, then its Waiting on you banner names
  them ("1 eval passed with owner steps: AGH-48 · Eval 1") and "Review owner steps" opens the first in Eval
  (`?doc=eval&eval=<delivery>`).
- **AC-376.17** Given a folded ticket in the eval table, then its row fills the table's columns with its latest eval
  (verdict, ACs, author, date), its evals fold under it, and the callout sits right under the ticket.

## Departures (AGH-381, stacked tickets)

**hub worktree (CLI)**

- **AC-381.1 Stacked worktree, every repo.** Given a stacked start, then the session's first prompt names one exact
  command, `./hub worktree <ticket id in lowercase> --stack-on <X's pull request URL>` (no `--only`, no `--base`):
  `hub worktree` reads the pull request with `gh` and creates the worktree of the pull request's repo (the `hub.json`
  repo whose `github` is the URL's `<owner>/<repo>`) from its head branch, and every other repo's from its default
  branch, so the blocker's repo starts on its branch even when this ticket's own work is in another repo. No step asks
  the agent to read the branch or choose the repo.
- **AC-381.2** Given `hub worktree <name> --base <branch>`, when it creates the worktrees, then each new worktree
  starts from `origin/<branch>` instead of the default branch and says so ("created <path> (<task branch> from
  origin/<branch>)"); `--base` with `--remove` exits 2 ("--base applies to creating worktrees, not to --remove"), and
  a branch name git refuses exits 2 naming it, before any repo is touched.
- **AC-381.8** Given `hub worktree <name> --stack-on <url>`, when the pull request is merged or closed, comes from a
  fork, or `gh` cannot read it, then it exits 1 with the reason; when the URL is not a GitHub pull request of a
  `hub.json` repo, `--only` leaves the pull request's repo out, or `--stack-on` comes with `--base` or `--remove`,
  then it exits 2; either way before any repo is touched. With `--only <the pull request's repo>` only that repo's
  worktree is created, from the pull request's branch.

**Tickets tab**

- **AC-381.3** Given a created ticket whose only blocker not done is a ticket of this feature already started (in
  progress) with a pull request, then it can start: it offers Start. Waiting on two tickets, or on a blocker without a
  pull request, it cannot.
- **AC-381.4** Given such a ticket, then its readiness reads "Can start on X's branch" instead of "Waiting on X": in
  the table with "<X id> is in review, not merged" below, on its flow card alone; the readiness help and the legend
  say "Can start on a blocker's branch: its only blocker is in review".
- **AC-381.5** Given such a ticket, then its Start is a default button (not primary) named "Start <id> on <X id>'s
  branch (<X id> is in review, not merged)"; clicking it first opens a "Start <id> on <X id>'s branch?" dialog saying
  "<X id> is in review and not merged: its code may still change."; "Start <id>" starts the session and opens its
  chat, Cancel starts nothing.
- **AC-381.6** Given a stacked start, then the session's prompt says its done blockers, "Its blocker <X id> is not
  merged yet: it is in review in <PR url>." and asks to open this ticket's pull request against X's branch.

**Sessions by issue (core)**

- **AC-381.7** Given a session whose first prompt names an issue of the hub's tracker teams (`/feature AGH-305`, a
  ticket's Start) and whose folder's branch names another ticket (a session started in the hub folder takes the hub
  checkout's branch), when it is labelled or listed by issue, then it is attributed to the issue its first prompt
  names; a prompt issue of another team, or none, leaves the branch's issue.

## Departures (AGH-326, ticket steps on the Tickets tab)

Each ticket has its own seven steps, Context, Preflight, Implement, Review, Eval, PR and Merged (records:
[feature-records.md](../../feature-records.md) "Ticket flow"; route: [API.md](../../../API.md) "Feature tickets",
`flow`). Where AGH-136, AGH-268 or AGH-376 above say otherwise, this list wins.

- **AC-1.11 Two views.** The Tickets tab shows one list in one of two views, toggled by a segmented control "Flow ·
  Table" (named "Show the tickets as") and kept in `?tickets=` (`table`; Flow, the default, is omitted), the URL
  replaced so the history keeps no toggle. This replaces AC-268.2's flow stacked above the table. Start appears once
  per view: on the card in Flow, in the Readiness column in Table.
- **AC-1.11 Step bars.** Each card (below its title) and each row (a Stage column after Title) shows the ticket's
  `StepBar` (shared, `components/StepBar.tsx`): one segment per ticket step in its state, labelled with the current
  step and its position, "Review · 4/7" (the Features list's format, AC-1.12, kept by spec amendment A13), then the
  current step's meta, or "Blocked", so its state is never told by color alone ("Review · 4/7 · Changes requested",
  "Eval · 5/7 · NO-SHIP"); every step's state and meta are in its tooltip and accessible name ("Ticket steps:
  Review. Context: not recorded; …"). The last step reads alone ("Merged", and "Shipped" on the Features list) only
  once it is done; otherwise it keeps its position ("Merged · 7/7"). An epic has no steps: its row shows "—", and
  its card stays as AC-268.8 says.
- **AC-1.11 Groups.** The flow's columns read "Group 1", "Group 2"… ("after group 1"); "Held back" and "Done" are
  unchanged.
- **Card title.** In Flow, each card, and the epic's card, holds its ticket's anchor (`#ticket-<ref>`), so a blocker
  named on a card leads to that card; the title is plain text (the table row it linked to is in the other view). The
  card's readiness line stays its one signal line (AC-376.6, AC-381.4): in S1 the flow carries no signal of its own
  (spec amendment A13).

## Departures (AGH-330, the ticket panel and one prompt per owner wait)

Designs: `two-level-flows/ux-new-ticket-panel.md` (Addendum 1) and `ux-change-waiting-prompts.md`, both approved;
spec amendment A15. Where the sections above say otherwise, this list wins.

**Ticket panel (two-level-flows AC-1.10)**

- **Panel.** `?ticket=<id>` (a tracker id or a plan key; written with replace) opens a non-modal panel beside the
  Tickets tab: an `aside` named "Ticket <id> · <title>" (the shared `SidePanel`), no scrim and no focus trap. Opening
  moves focus to its heading; Esc or its X ("Close ticket <id>") closes it and returns focus to the element that
  opened it, else to the same ticket in the view shown. It overlays at 1280 and docks at 1600 (`31-responsive.md`).
- **Content.** Its Linear link, status, assignee and readiness line; the seven steps as a vertical stepper (the
  shared `GoldenPathStepper`, `vertical`), one disclosure button per step ("Review, in progress, changes requested,
  show details"), the current step open (`?step=` keeps the open one); then its ACs, Blocked by and Blocks (each
  opens that ticket's panel in place) and its sessions. Every step says only what S1's records hold (Context and
  Preflight "Not recorded" before `/implement`; Review links its review record in Brain; Eval its latest eval in the
  Eval tab; PR its pull request; Merged "Done in Linear"). The panel reads the tickets route's row (spec A7).
- **No Start.** Start stays once per view, on the card or the row (owner decision 4, A15).
- **Signal.** Its one signal is a ticket eval waiting on owner steps: "Waiting on you: Eval N passed with owner steps"
  with "Settle them in the Eval tab", which closes the panel and opens that eval.
- **States.** An id that is no ticket of the feature reads "<id> is not a ticket of this feature." with Close panel;
  the feature's epic reads "<id> is this feature's epic: it has no steps of its own."
- **Openers.** The card title, and a table row's title, are links to `?doc=tickets&ticket=<id>` (this reverses
  AGH-326's "Card title": the title opens the panel; the epic's title stays plain text); a table row (the body is one tab stop: `j` / `k` and `↓` / `↑`
  move between tickets, epics skipped; `Enter`, `o` or a click opens it; links and buttons in the row keep their own
  action); a header chip (removed by AC-425.5), which opened the Tickets tab with that ticket's panel (tooltip "<id> · <title> · show its
  steps"; the Linear link moved into the panel, so AC-268.17's link is gone). The waiting banner opens it in S2 (A8).
- **Tab.** The panel belongs to the Tickets tab: another tab closes it and drops `ticket=` and `step=`.

**Tickets tab follow-ups (reviews/AGH-326.md)**

- **`v`** toggles Flow and Table while focus is in the Tickets tab and not in a text field (`?tickets=`, replaced);
  focus stays on the same ticket (card title and row), else goes to the toggle.
- **Names.** A card's and a row's accessible name carry its step line: "AGH-326 · <title> · Review · 4/7 · Changes
  requested". The StepBar stays out of the tab order; its per-step states are in the panel's step list.
- **Epic Stage.** The epic row's "—" is a focusable tooltip: "An epic has no steps of its own; each of its tickets has
  seven."
- **Columns.** At 1280 Assignee and Sessions hide; with the panel docked the table keeps Ticket, Title, Stage and
  Readiness (`31-responsive.md`).

**One prompt per owner wait (A15; replaces AC-376.13 and AC-376.16 for the acceptance eval)**

- **Acceptance prompt.** The decision buttons live only on the Eval tab, in a callout under the Whole feature group,
  whose state is the server's `acceptance_eval.owner_wait` (A9-A11): *sign off* ("Waiting on you · Acceptance: sign off
  3 ACs", Needs more work and Mark owner steps done, the request naming the acceptance eval); *reopened* ("Acceptance:
  2 ACs reopened · evaluate again", Needs more work only); *undated* ("Acceptance eval undated · evaluate again", no
  button; Evaluate whole feature is primary and asks for the acceptance eval's next re-run, `feature-r2` after
  `feature`, `feature-r3` after `feature-r2`); *future-dated* ("Sign-off possible after <date-time>", no button: the
  served `signable_after`, rounded up to the minute, written as the page writes every date-time, so the `t` toggle
  applies; the Acceptance step reads the same line on this page; the Features list still shows the server's UTC line, a known
  gap followed up in AGH-332); *no ACs listed* ("Waiting for you · Acceptance: sign off by hand · no ACs listed", names
  the hand-written `evals/owner-signoff.md`, no button). *Sign off* and *no ACs listed* are amber (`warning`, `hand`:
  both wait for the owner, A18, A19); the others are info. The client's own callout no
  longer shows for the acceptance eval; ticket eval callouts (AC-376.13, AC-376.14) are unchanged.
- **Banner.** The page has one "Waiting on you" banner, a signpost with one line per wait: "Acceptance: sign off 3
  ACs (Eval 2)" first (only in *sign off*), then "AGH-48: Eval 1 passed with owner steps" for each other eval waiting
  on owner steps, each line after the first a link to its eval; "Review owner steps" opens the first. The
  `OwnerSignOff` banner ("Mark owner steps done" above the tabs) is removed; the features.json "N owner steps left"
  banner shows only while the feature has no acceptance eval. Undated and future-dated never rank the feature as
  needing the owner (A12).
- **Acceptance step.** Its step, named "Open Eval N, the acceptance eval", opens `?doc=eval&eval=<acceptance
  delivery>`.
- **Signposts land on their eval.** The Acceptance step, the banner's button and lines, and the ticket panel's
  "Settle them in the Eval tab" open the Eval tab at their eval and move focus to its group's row.
- **Banner link names** are their visible lines ("AGH-48: Eval 1 passed with owner steps"), not "Open AGH-48 Eval 1
  in the Eval tab" as the design drafted: a link's name holds its visible label (WCAG 2.5.3).
- **Header verdict badge.** It shows the acceptance eval's verdict only (AC-1.6): the latest whole-feature eval's, none
  before one exists; a ticket eval never sets it.
- **Contrast (AC-1.14, A16).** The screens' axe tests run once, for structure and names (jsdom computes no colours);
  both themes' contrast is `tokens.test.ts`'s, on the token pairs the panel, the callouts and the banner use.

## Departures (AGH-405, plan change requests and the ticket flow's signals)

Two-level-flows S2 (AC-2.5, AC-2.8, AC-2.12, AC-2.14, AC-1.10's banner opener by A8; spec amendments A13, A16-A20).
Records: [feature-records.md](../../feature-records.md) "`tickets/<ticket>/` and `change-requests/`"; routes:
[API.md](../../../API.md) "Feature detail" (`change_requests`) and "Plan change requests". Where the sections above
say otherwise, this list wins.

- **One word for every owner wait (A18).** Each "Waiting on you" above reads "Waiting for you": the banner's title,
  the Acceptance prompt ("Waiting for you · Acceptance: sign off 3 ACs"), the Acceptance step (its state is the typed
  `waiting`, "Waiting for you", with the meta "Sign off 3 ACs"), the hand-written sign-off (A19: its step `waiting`,
  its banner line "Acceptance: sign off by hand · no ACs listed (Eval 2)", a link to its Eval callout with no button,
  the callout titled "Waiting for you · Acceptance: sign off by hand · no ACs listed"), the ticket eval callouts and
  the panel's signal. A wait is told by its typed state (the step's `waiting`, the list's `waiting_on_owner.kind`), never by
  its words.
- **States.** `waiting` reads "Waiting for you" with the `hand` icon and the `waiting` colour; `stale` reads "Re-run
  needed" with the `clock` icon and the `idle` colour (a StepBar segment filled `idle-soft`, edged `idle`). Their
  marks are checked at 3:1 in both themes by `tokens.test.ts` (`waiting` and `idle` on `surface` and
  `surface-overlay`, `idle` on `idle-soft`, A16).
- **Step signals.** A golden path step shows its `signal` under its state, in or out of focus, with the `hand` icon,
  and in its tooltip and description ("Plan: done · v2 · v3 waits for you"): Plan stays done while the next version
  waits (AC-2.8). Build's meta adds "· 1 paused for a plan change" (server).
- **Banner.** The "Waiting for you" banner lists the open plan change requests first, one line each ("Plan change
  request 2 from AGH-202: plan v2 → v3 · affects AGH-203"), then the eval waits. With a request, its button is
  "Review change request" (named "Review change request 2 from AGH-202"), on every tab: it opens the Tickets tab with
  the asking ticket's panel at its Preflight (`?doc=tickets&ticket=<ticket>&step=preflight`, replace), and Esc
  returns focus to it (AC-1.10). Each later request line opens its ticket's panel the same way.
- **Card and row signal (A13).** A ticket's flow `signal` joins its readiness line: the ticket's own plan change
  ("Waiting for you: plan change", `hand`), a hold ("Held: plan change pending", `circle-pause`) or a re-run ("Plan v3
  approved: re-run preflight", `clock`) takes the readiness line's place on the card and in the table's Readiness
  cell; local drift ("Local drift · 2 notes") is a muted line beside readiness, never a status (AC-2.5). Which one it
  is comes from the Preflight step's typed state, not the words. The step line keeps the current step's meta
  ("Preflight · 2/7 · Waiting for you").
- **Panel signal and header.** The panel shows the same signal under its readiness line (local drift stays in the
  Preflight step), then the eval wait's line if any. While the ticket's own request is open, its header carries the
  panel's one primary, "Review change request": it opens Preflight (`?step=preflight`, replace) and moves focus to
  the request's block.
- **Panel Preflight.** Read from `GET …/tickets/{ticket}` (A7): a skeleton while it loads, a compact `ProblemError`
  with "Try again" when it fails, and with no record the step's own meta (never "Not reached." for a `waiting` or
  `stale` step). It lists the change requests the ticket asks, then "Held by change request N from <ticket>: it waits
  until you answer it." for those that hold it (the request is a link to the asking ticket's panel at Preflight),
  then every run, newest first: "<date-time> · checked plan v2 against main at <commit> · local drift" (the commit an
  `IdChip`), its input ("after a discovery: …", "after a decline: …") and, for local drift, "Local drift · N notes"
  with each note (AC-2.5). An unknown plan version reads "—".
- **Before the decision (A20).** An open request is a region named "Plan change request N": its title "Plan change
  request N: plan v2 → v3" (a heading, the request's own headings one level below it) with how long it has waited ("waiting 2 h", from `opened_at`, also on the
  banner's line), problems if any, "Plan drift: it changes an AC, a contract or another ticket, so <ticket> is paused
  until you answer.", its evidence and proposal (the request's markdown, `Markdown` under a `ProvenanceBadge`
  "agent"), "What changes if you approve" ("Plan v2 becomes v3 (a new amendment).", "<ticket> runs preflight again on
  the new plan.", "AGH-203 runs preflight again before it goes on." or "AGH-203, AGH-204 run preflight again before
  they go on.", "Nothing is merged or pushed."), for a request longer than the 16 KiB read "The request goes on past
  what is shown: read the full request in Brain before deciding.", "Read the request in Brain", then its decision:
  - while its run waits at its gate (`approval_id`), the shared `GateDecision` of that gate (Approve, Decline); Decline
    asks for a "Note (required)" in its dialog and cannot be confirmed without one; the implement gate captures its
    response, so the note reaches the run (AC-2.7, AC-2.12);
  - when the server says the run is gone (`decidable_here`), the lost-run form (AC-2.14): "Its run is gone
    (abandoned, or its record lost): your decision is recorded in the hub, and the next /implement of <ticket> reads
    it.", a "Note (required to decline)" field, "Approve plan v3" (primary) and "Decline" (danger). Decline with an
    empty note sends nothing, says "Write a note to decline: the next preflight follows it." and moves focus to the
    note; then "Recording your decision…", "Decision recorded in the hub. The next /implement of <ticket> reads it."
    with the buttons off, or the gate's refusal box (`DecisionError`: the server's reason, "Nothing was recorded.");
  - else the run lives but its gate is not open, and no button: right after a decision through the gate, "Decision
    sent; the run records it and this shows it." (a status that takes focus until the run records it), otherwise
    "Its run is live and asks you at its gate; the decision shows here once the gate is open.".
  A decided request reads "Change request N approved by <person> · <date-time>[: <note>]"; after a decision taken
  here, through either path, focus moves to that line.
- **Announcing.** A request that arrives while the page is open is said once in a polite live region ("AGH-202 waits
  for you: plan change request 2."); those open at the first read are the banner's.
- **Start.** While a ticket's own plan change waits for the owner, the cards' and rows' Start is secondary: the
  banner's Review change request is the view's one primary.
- **No repeated state word.** A step meta that only repeats its state's word ("Waiting for you" on a `waiting`
  Preflight) is not said twice in the stepper, its description or the panel's step buttons; the step bar line keeps
  it ("Preflight · 2/7 · Waiting for you"), since the bar has no state word of its own.
- **Hand sign-off meta.** The Acceptance step of a hand-written sign-off reads `waiting` with the meta "Sign off by
  hand · no ACs listed" (was "Waiting on owner steps · no ACs listed"), the words its banner line and callout use.
- **Wording kept apart (UX Q4, Q5; departures).** The gate's own choice reads "Approve" (its label comes from the
  workflow's declared decision), the lost-run form's "Approve plan v3"; sessions keep "waits on you" (AC-374: a
  session waits on the person at the keyboard, not on an owner decision). In a build whose decision route is not
  wired (sessions off, `decidable_here` always false), a gone run's request still reads "Its run is live and asks
  you at its gate …": the API does not say why it is not decidable here; decide it by hand in the hub (write
  `change-requests/<n>.decision.md`) until hub web takes decisions there.
- **Request text cut.** A request read past its 16 KiB head shows "The request goes on past what is shown"; one of
  exactly 16 KiB reads as cut too, which only sends the owner to read it whole.
- **Departures from the approved designs.** The `ApprovalPanel` with its footer slot (ux-new-ticket-panel.md) is not
  reused: the request's block above holds its parts (title, wait, evidence and proposal, what changes, the decision),
  and the decision is `GateDecision` or the lost-run form, so `ApprovalPanel` keeps its Phase-2 footer unchanged. The
  request's "Requested by preflight in session …" line is left out: the request names its run, not a session. The
  mobile waiting line ("Answer it on a larger screen or in its session.") is not added: Feature detail below 768 px
  shows "This view needs a wider screen." (`31-responsive.md`). The banner's "Settle each one below." reads "Settle
  the eval waits below." on the Eval tab when a change request leads it.
- **Features list (AC-374.1, AC-374.2, AC-374.5, AC-374.7).** What needs the owner comes from `waiting_on_owner`, not
  the Acceptance step's words: a plan change request ("Plan change waits for you · from AGH-202"; two or more "2 plan
  changes wait for you · from AGH-202, AGH-203"; the row opens the first asking ticket's panel at its Preflight), the
  acceptance sign-off (the line AC-374 gives owner steps, opening Criteria) and a sign-off only the owner can write by
  hand (A17: "Sign off by hand · no ACs listed", opening the Eval tab; no decision button). In progress leads with: a
  session waiting on you, your turn, a broken record, NO-SHIP, a plan change, owner steps, a hand sign-off; the hint
  counts "1 plan change waits for you" and "1 sign-off by hand" too, each kind in the plural for several ("2 plan
  changes wait for you", "2 sessions wait on you"), and the sidebar badge counts them. A19: the hand sign-off's
  Acceptance step is `waiting` too ("Waiting for you"), with no decision button.
- **Panel Implement.** Each discovery of the preflight runs: "Discovery <date-time>: <text>. Preflight ran again."
  (AC-2.13); the step's meta ("Ticket plan written") when no round exists yet.

## Departures (AGH-422, the feature's own session)

Design: [20-chat.md](20-chat.md) (the Discuss panel). Where the sections above say otherwise, this list wins.

- **AC-422.1 The feature's session.** Given a feature whose spec (else research, else plan) a session `hub web`
  drives wrote, when its page opens, then its header names that session ("Session" and the session's name, a ghost
  button whose tooltip is "Talk with the session that wrote this feature's records: <name>") and a click opens the
  Discuss panel on that session; the panel's row 2 reads "Feature session · <name>", and its menu offers "New
  conversation" (the panel's own conversation for the record) and, from there, "Back to the feature session". The
  first session found wins (the oldest writer of the spec); no writer, no chip, and the panel works as before.

## Departures (AGH-425, feature detail and the Features list)

Built after the owner validated these in the playground (part of AGH-415); where the sections above say otherwise,
this list wins. Records and refusals: [feature-records.md](../../feature-records.md); route: [API.md](../../../API.md)
"Feature detail".

**Acceptance criteria tab**

- **AC-425.1 Mark a criterion as passing.** Given a criterion that does not pass in `features.json` and that the
  owner checked by hand, when its card offers "I checked it, mark as passing" and the owner confirms the short form
  ("Note (optional)", Cancel sends nothing), then `POST .../owner-signoff` gets `{acs: [<id>], decision: "done",
  note}`, the API writes an owner SHIP eval (`provenance: owner`) over that AC only, `features.json` and the other evals
  are kept, and the AC reads "Signed off" (passing, "You checked it by hand and signed it off") in its row, the AC
  bar and the counts, here and on the Features list; its card then says "You checked this by hand and signed it off;
  it counts as passing." with no button. A criterion that already passes offers nothing. Being an owner SHIP, the
  note also signs that AC off for the Acceptance step (it leaves the acceptance eval's `owner_wait`). A later agent
  eval of the AC decides again.
- **AC-425.2 Refusals stay.** Given a manual sign-off that main's sign-off rules refuse, then the API answers 409
  with its one-line reason and writes nothing, and the card's form shows it ("Could not mark <id> as passing"): an
  unknown or withdrawn AC, `acs` together with `delivery`, an AC whose latest eval is NO-SHIP ("fix or re-evaluate
  first"; the owner's by-hand check does not override an agent's NO-SHIP), a note that would not rank newer than an
  eval naming the AC (undated, or dated at or after now), and evals left unread. An empty `acs` is 422.

**Record tabs**

- **AC-425.3 Questions in plain words.** Given a record whose human summary is current and whose Open questions
  section names every question of the record (same ids), when the record's Approve bar shows, then the questions
  above it are the summary's, worded in plain words with their context and options; otherwise (no summary, out of
  date, or one missing) they are the record's own, so none goes unanswered. The questions link counts the same list.
  The `/summarize` skill repeats every open question of the record in that shape.
- **AC-425.4 Approved stays approved.** Given a record (spec, research or plan) whose frontmatter says `status:
  approved`, when its tab shows, then a status line reads "<Record> approved · last verified <date>." (the date when
  the frontmatter has `last_verified`) and neither the Approve bar nor its open questions show again.

**Header and tabs**

- **AC-425.5 No ticket chips.** Given a feature with tickets, when its page shows, then the header holds no ticket
  chips (the group "Tickets of this feature" is gone): the tickets and their Linear status are in the Tickets tab and
  its ticket flow, whose card titles and rows still open the ticket panel. This removes the header chip from the
  panel's openers (AGH-330 "Openers") and supersedes AC-268.17.
- **AC-425.6 Tab order.** Given the feature page, then the record tabs read Spec, Research, Plan, Acceptance criteria,
  Tickets, Eval: the order the workflow writes them (the planner writes the criteria and the ticket plan in
  `features.json` once the plan is approved; the eval comes last). This replaces the AGH-136 tab order.
- **AC-425.7 Fixed label.** Given a feature, named or not, when its page header or its Features list row shows, then
  its slug follows its name as a tag label ("Feature label <slug>", mono, tag icon; on hover: set when the feature was
  created, unique and never changes, a rename changes only its name), not a link on its own page; the chip that ties a
  session to its feature uses the same tag icon and hover text, plus "Open its panel."

## Departures (AGH-521, the playground's v0.23.0 work)

Built after the owner validated these in the playground (snapshot `20261023T210306Z`); where the sections above say
otherwise, this list wins.

**Features list (delivery 8)**

- **AC-521.8.1 Stage in words.** Given a feature row, then its Stage column shows the golden path step's name, a state
  dot and "step N of 8" instead of the segment bar; the columns read Tickets, Stage and Criteria met; the tips at the
  top of the card open downwards so the card never clips them.
- **AC-521.8.2 Criteria as "N of M".** Given the criteria bar on the Features list and on the feature page, then it
  says "3 of 13" in words, and its tip says what passes and what the owner checks by hand.
- **AC-521.8.3 What comes next.** Given a feature row, then the line under its name says what comes next in plain
  words ("Next: write the spec", "Building · 1 of 10 tickets merged", "Ready to ship after your manual checks")
  instead of the record's raw reasons; the group hint and the Linear notice are reworded to match.
- **AC-521.8.4 Label beside every title.** Given a feature row, named or not, then its label (AC-425.7) follows the
  title, so an unnamed feature shows its slug as both.
- **AC-521.8.5 Shipped features leave In progress.** Given a feature whose golden path waits on Linear's ticket states,
  when the Features list opens, then it reads that feature's tickets once (warming the Linear snapshot) and rereads
  the list, so a feature whose tickets are all done moves to Shipped.
- **AC-521.8.6 Working now.** Given a live main session matched to a feature and the collector connected, then the
  row's lead column shows the live dot, its line says "A session is working · <last action>", the row sorts right
  after the session warnings in In progress, and the summary line counts "N working now". Nothing shows while the
  collector is offline.

## Screen 1: Features list

**Route:** `/features` · **Answers:** "Which features are moving through the golden path, and how close is each to done?"

### Purpose and primary user

Owner / tech lead: see every feature's phase, how many acceptance criteria pass, and the evaluator's verdict. Auditor: find the record behind a shipped feature.

### Layout (1440 px)

```
+--------+-------------------------------------------------------------------------------------------------+
|Sidebar | TopBar: [All projects v]  [Search or jump to... Ctrl K]   (o Connected · last event 3 s ago)    |
+--------+-------------------------------------------------------------------------------------------------+
|        | Features                                                     [Phase: All v] [Verdict: All v]    |
|        | 4 features · 1 shipped · 2 in progress · 1 blocked                     [Repo: All v] [Size v]   |
|        +-------------------------------------------------------------------------------------------------+
|        | Feature                 Issues        Size           Golden path              ACs        Verdict |
|        |-------------------------------------------------------------------------------------------------|
|        | layered-memory          AGH-48 (+4)   architectural  ######## Shipped        [21/21 ...] SHIP-WITH-|
|        | agent-hub                                            08 Oct                  1 owner step OWNER-STEPS|
|        | order-book-reconnect    LOK-311       bounded        ######-- Review         [19/21 ===-] --      |
|        | loki-trader · tradeSentinel                          since 10 Oct                                  |
|        | tracker-team-cap        AGH-112       bounded        ####---- Implement      [4/9 ==---] --       |
|        | agent-hub                                            since 11 Oct                                  |
|        | guard-bypass            AGH-79        spike          ####---- Implement      [6/9 ===--] --       |
|        | agent-hub                             (run failed)   blocked since 10 Oct                         |
+--------+-------------------------------------------------------------------------------------------------+
```

Features without `eval.md` show "--" in Verdict.

### Components

| Component | Variant / notes |
|---|---|
| `AppShell`, `Sidebar` ("Features" selected), `TopBar`, `ProjectSwitcher`, `CollectorPill` | Standard |
| `DataTable` | Comfortable density (`row-comfortable` 40 px), two-line cells for name + project/repos |
| `IssueLink` | First issue + "(+4)" count popover listing the rest from `issues.md` |
| `StageChip` (size variant) | spike / bounded / architectural, neutral `idle-soft` ground |
| `StepBar` | 8 segments, one per feature step in its state; the step's name and position under it ("Build · 6/8", "Shipped" alone); see Departures (AGH-327) |
| `BudgetBar` (progress variant, reused for ACs) | Segments: passing (`done`), owner step (`waiting`, hatched), failing (`failed`), not yet verified (`gray-300`); label "19/21" |
| `StatusBadge` (verdict variant) | SHIP (`done`), SHIP-WITH-OWNER-STEPS (`waiting`), NO-SHIP (`failed`); "--" when no eval yet |
| `SegmentedControl` / filter menus | Step, Verdict, Repo, Size |
| `Skeleton`, `EmptyState`, `ProblemError`, `AsOfStamp` | States |

### Data mapping

| Element | Entity.field (brief §3) | API resource | Source · latency |
|---|---|---|---|
| Slug, project | Feature record folder `brain/features/<slug>/` | `GET /features?project=` → `items[].{slug, project}` | hub files · on file change (watcher) |
| Issues | `issues.md` (issue keys) + spec frontmatter | `items[].issues[]` | hub files; titles from linear · 60 s |
| Size | spec frontmatter `size` (spike/bounded/architectural) | `items[].size` | hub files |
| Repos | spec frontmatter `repos` | `items[].repos[]` | hub files |
| Golden path phase | derived: presence and status of spec, research, plan (approved), issues, run state, review, eval, merged PR | `items[].phase`, `items[].phase_since` | derived server-side from files + runs + github |
| ACs bar | `features.json` ACs: passes, owner-step flag | `items[].acs.{total, passing, owner_steps, failing, unverified}` | hub files |
| Verdict | `eval.md` verdict | `items[].verdict` (SHIP / SHIP-WITH-OWNER-STEPS / NO-SHIP / null) | hub files |
| Blocked marker | linked run FAILED | `items[].blocked_by.{run_id, stage}` | executor |

### Interactions

- Row click or Enter: Feature detail. Issue link: tracker. `j` / `k` row focus.
- Hover the AC bar: "20 passing by command · 1 owner step (AC-48.21) · 0 failing · 0 not verified".
- Hover the stepper: phase list with dates ("Plan approved 08 Oct 11:22 by José Henrique Roquette").
- Default sort: in-progress first by phase (furthest along first), then shipped by ship date desc.
- Filters in URL: `/features?phase=build,acceptance&verdict=none`.

### States

| State | What shows | Exact copy |
|---|---|---|
| Loading | 5 skeleton rows | (none) |
| Empty | `EmptyState` | "No feature records yet." / "Features appear when `/feature` writes `brain/features/<slug>/spec.md` in the hub. Start one in a Claude Code session in the hub: `/feature AGH-112`." |
| Empty after filters | Inline | "No features match these filters." [Clear filters] |
| Partial: malformed features.json | Row shows ACs "--" with `blocked` icon | Tooltip: "features.json could not be parsed (line 38: trailing comma). Fix it in a hub PR." |
| Partial: tracker down | Issue titles from cache | "Issue titles as of 08:55 (Linear not reachable)." |
| Error | `ProblemError` | e.g. "Could not load features" / "status 503 · The hub at ~/code/agent-hub-hub is not readable." [Retry] |
| Live | A file change in `brain/features/` refreshes the row (fade, `dur-base`) | (none) |
| Stale | `AsOfStamp` | "As of 14:02 · collector offline" |

### Departures (AGH-268, the list at a glance)

Validated by the owner in the playground; where Screen 1 says otherwise, this list wins.

- **AC-268.22 Who acts.** Given a feature held at Evaluate by owner steps only, then its row shows "Waiting for you"
  and the summary line counts it ("2 features · 1 waiting for you · 1 in progress · 0 shipped · furthest along
  first").
- **AC-268.23 Step position.** Given the golden path bar, then it names the phase with its position ("Implement · step
  5 of 8") and only the step's own progress (the ACs column counts the ACs); the bar takes focus for its tooltip.
- **AC-268.24 Column hints.** Given the table, then the Golden path, ACs and Verdict headers carry a hint (an info icon
  with a tooltip) instead of a footnote, and the columns have fixed widths.
- **AC-268.25 Issues.** Given a feature with several issues, then the first shows and "+N" opens all of them in a
  popover.
- **AC-268.26 Verdict scope.** Given a verdict while Acceptance is not done, then the Acceptance step's meta shows
  under the badge (the Evaluate step became Acceptance, AGH-325).
- **AC-268.27 Shipped last.** Given shipped features, then they sort after every feature in progress.
- **AC-268.28 Tooltips.** Given a tooltip in a table, then it wraps and opens downward where the table would cut it.

### Departures (AGH-327, feature steps on the list)

The golden path is the feature's own eight steps (AGH-325); where Screen 1 or the lists above say otherwise, this list
wins.

- **AC-1.12 Golden path column.** Given the list, then each row's `StepBar` (shared, `components/StepBar.tsx`) draws
  one segment per feature step, Spec, UX design, Research, Plan, Tickets, Build, Acceptance and Shipped, in its state
  (a step the server marks done after one that is not reads blocked), labelled "<Step> · n/8" ("Build · 6/8") and
  "Shipped" alone once shipped; its tooltip and accessible name ("Golden path: Build. Spec: done; …") give every
  step's state, meta and reason. The bar is not a tab stop: the row's accessible name reads its position and the
  current step's summary ("golden path at Build, step 6 of 8, Build: in progress · 1 of 3 merged"); the other steps
  are in the tooltip and the feature's detail. AC-268.23 reads with these steps ("Build · 6/8", not "Implement · step
  5 of 8"), and the row's line says only what the bar cannot (meta, reason, verdict), never the position again.
- **AC-1.12 Step filter.** The Step filter (`?phase=`) offers the eight feature steps. An old link's
  `?phase=implement` or `review` becomes `build`, and `evaluate` becomes `acceptance`, replacing the URL so the
  history holds the new one; an id that is not a step is dropped in the same replace. The list filters by the new
  steps from its first render.
- **AC-1.15 Groups** (spec amendment A12). The groups are In progress and Shipped: the Evaluated group is gone, and a
  feature the evaluator says ship for while its tickets are not read as done is listed in In progress (D-9), its line
  ending "evaluator says ship". What needs you stays inside In progress (AC-374.1): those rows lead it with a warning
  and the page summary starts with "N need you". A stored collapsed `evaluated` group is ignored and dropped on the
  next toggle.
- **AC-268.22 Who acts** reads at Acceptance: a feature whose Acceptance step waits on you ("Waiting on you: sign off
  N ACs") carries the owner-steps warning. One whose whole-feature eval lists no AC to sign off ("Waiting on owner
  steps · no ACs listed", spec amendment A10) has no warning: the list has nothing to open for it, and its line names
  the wait.

---

## Screen 2: Feature detail

**Route:** `/features/agent-hub/layered-memory` · **Breadcrumbs:** `agent-hub › Features › layered-memory` · **Answers:** "How did this feature get here, who approved each step, and does each acceptance criterion really pass?"

### Purpose and primary user

Auditor and owner reconstruct a feature end to end: the golden path with dates and approvers, the acceptance criteria with evidence and the exact command to re-verify, and the four documents rendered for reading. Developer copies a verification command to check an AC locally.

### Layout (1440 px), sample: layered-memory, AGH-48

```
+--------+-------------------------------------------------------------------------------------------------+
|Sidebar | agent-hub › Features › layered-memory                                                           |
|        +-------------------------------------------------------------------------------------------------+
|        | HEADER                                                                                          |
|        | Layered memory                       [SHIP-WITH-OWNER-STEPS]   architectural · agent-hub        |
|        | AGH-48 · AGH-49 · AGH-50 · AGH-51 · AGH-52    PR agent-hub #69 merged 08 Oct 17:40              |
|        | ACs [######################] 21/21 · 1 owner step       Run 01922b10 (reported) · $9.12          |
|        +-------------------------------------------------------------------------------------------------+
|        | GOLDEN PATH STEPPER                                                                             |
|        | (v)Spec   (v)Research (v)Plan     (v)Tickets (v)Implement (v)Review  (v)Evaluate (v)Shipped      |
|        | 06 Oct    07 Oct      approved    08 Oct     08 Oct      08 Oct     08 Oct      08 Oct          |
|        | analyst   researcher  08 Oct 11:22 planner   main        spec- +    evaluator   PR #69 merged   |
|        |                       by J. H.               3 sessions  quality    SHIP-WITH-  by J. H.        |
|        |                       Roquette               2 h 50 min  reviewers  OWNER-STEPS Roquette       |
|        +-------------------------------------------------------------------------------------------------+
|        | OWNER STEP CALLOUT (waiting-soft)                                                               |
|        | 1 owner step left: AC-48.21 Open a new session after merge and confirm the layered memory loads.|
|        | Recorded by hub-workflow:evaluator in session 5091b986 as passes:false (manual owner step).     |
|        +-------------------------------------------------------------------------------------------------+
|        | [Acceptance criteria 21] [Spec] [Research] [Plan] [Evaluation] [Issues 5]                      |
|        | Filter: [All | Passing 20 | Owner step 1 | Failing 0]       Repo [All v]   [Copy all commands]  |
|        | ID        Description                         Repo       Passes   Evidence        Verify      |
|        | AC-48.1   Given a hub with brain/auto/work... agent-hub  (v) yes  test run 08 Oct  uv run py..[c]|
|        | AC-48.2   Given a personal note, when the ... agent-hub  (v) yes  test run 08 Oct  uv run py..[c]|
|        | ...                                                                                             |
|        | AC-48.20  Given render output, when two PRs.. agent-hub  (v) yes  PR #69 CI       make check [c]|
|        | AC-48.21  Given the feature is merged, when.. agent-hub  (o) owner manual, owner   see eval.md   |
+--------+-------------------------------------------------------------------------------------------------+
```

When a document tab is selected (Spec, Research, Plan, Evaluation), the content area splits: rendered Markdown (max 760 px reading width) with a sticky TOC on the right (240 px) at 1440 px.

```
| [Acceptance criteria 21] [Spec] [Research] [Plan] [Evaluation] [Issues 5]                         |
| brain/features/layered-memory/eval.md · commit 4e1a9c2 · provenance agent  [Open in GitHub]      |
| type eval · status final · repos agent-hub · last verified 08 Oct            (FrontmatterChips)  |
| +--------------------------------------------------------------+  +---------------------------+  |
| | # Evaluation: layered memory                                 |  | ON THIS PAGE (sticky)      |  |
| | Verdict: SHIP-WITH-OWNER-STEPS                                |  | Verdict                    |  |
| | ## Summary                                                   |  | Summary                    |  |
| | 20 of 21 ACs pass by command on main at 4e1a9c2. AC-48.21 ... |  | > Acceptance criteria      |  |
| | ## Acceptance criteria                                       |  | Owner steps                |  |
| | (AcTable)                                                     |  | Risks                      |  |
| | ## Owner steps                                               |  | Follow-ups                 |  |
| | 1. After merge, open a new Claude Code session in the hub... |  |                            |  |
| +--------------------------------------------------------------+  +---------------------------+  |
```

### Components

| Component | Variant / notes |
|---|---|
| `Breadcrumbs` | Project › Features › slug |
| Header | `title` style name (from spec frontmatter `title`, else slug), verdict `StatusBadge`, size chip, repos, `IssueLink` list, PR link, AC bar, run `IdChip`, `Money` |
| `GoldenPathStepper` | Full variant: 8 steps, each with state (done / current / not reached / skipped / blocked), date, approver or agent, and a link to the evidence (session, approval, PR) |
| `Banner` (owner-step callout) | `waiting-soft` ground, `waiting` icon; only when owner steps remain |
| `Tabs` | Acceptance criteria (default), Spec, Research, Plan, Evaluation, Issues; counts in labels |
| `SegmentedControl` | AC filter: All / Passing / Owner step / Failing / Not verified (counts) |
| `DataTable` with `AcTable` columns | Sticky header, comfortable density, expandable rows |
| `CodeBlock` (inline variant) | Verification command, mono, copy button, middle-truncated with `PathText` rules |
| `Markdown` with `FrontmatterChips` | Rendered docs; Given/When/Then blocks styled as a three-row definition list |
| `ProvenanceBadge` | On each document: provenance (human / agent / agent-from-code / agent-from-external) |
| `DerivedLabel` | On the golden path phase ("Phase · derived from the record, runs and PRs") |
| `Popover` | Evidence details |
| `Skeleton`, `EmptyState`, `ProblemError`, `AsOfStamp`, `ExternalLabel` | States; ExternalLabel on any doc section sourced from outside (e.g. quoted web research) |

### Golden path stepper (detail)

As built (AGH-325, two-level-flows AC-1.1) the stepper draws the feature's eight steps, Spec, UX design, Research,
Plan, Tickets, Build, Acceptance and Shipped ([feature-records.md](../../feature-records.md) "Golden path"); each
ticket's seven steps, Context, Preflight, Implement, Review, Eval, PR and Merged, are on its step bar and in its
ticket panel (Departures AGH-326, AGH-330). The draft below, and the layout above, predate them.

Phases (fixed order): Spec → Research → Plan (approved) → Tickets → Implement → Review → Evaluate → Shipped.

| Phase | Done when (derivation) | Shows under the step | Sample (layered-memory) | Link |
|---|---|---|---|---|
| Spec | `spec.md` exists with ACs | date, author | 06 Oct · hub-workflow:requirements-analyst | session of the author |
| Research | `research.md` exists | date, author | 07 Oct · hub-workflow:researcher | session |
| Plan (approved) | `plan.md` exists and a plan gate.result = approved | date + time, approver, where | 08 Oct 11:22 · José Henrique Roquette · in the terminal | approval record `/approvals/{id}` |
| Tickets | `issues.md` lists issues that exist in the tracker | date, count | 08 Oct · 5 issues | Issues tab |
| Implement | a run or sessions with the issue reached Verifying | date range, sessions, duration | 08 Oct · 3 sessions · 2 h 50 min · main | run 01922b10 |
| Review | spec-reviewer and quality-reviewer sessions ended | date, agents | 08 Oct · spec-reviewer + quality-reviewer | sessions |
| Evaluate | `eval.md` with a verdict | date, verdict | 08 Oct · SHIP-WITH-OWNER-STEPS · hub-workflow:evaluator | session 5091b986 |
| Shipped | PR merged on the default branch | date, merged by | 08 Oct 17:40 · PR #69 · merged by José Henrique Roquette | GitHub PR |

Step states: done (`done` check), current (`live` ring, plus "since" date), not reached (outline, `text-subtle`), skipped (dashed outline, "skipped": e.g. Research skipped for a spike; tooltip "No research.md. Allowed for size spike."), blocked (`blocked` octagon: linked run FAILED, e.g. guard-bypass at Implement "blocked since 10 Oct · run 01923f1e failed at Verifying").

Approvers are people; agents are shown with their `plugin:name` id. "Plan (approved)" never shows an agent as approver (principle 2); if the gate.result was recorded without a person, the step reads "Plan written, approval not recorded" in `waiting` and the step is not counted as done.

### AC table (from features.json)

Columns:

| Column | Content | Notes |
|---|---|---|
| ID | `AC-48.1` mono-sm | Permalink `?ac=AC-48.1` |
| Description | Given/When/Then, truncated to 1 line (2 at 1920); full text in the expanded row | |
| Repo | repo dir | Hidden in single-repo features at < 1440 px |
| Passes | `(v) yes` (`done`), `(x) no` (`failed`), `(o) owner` (`waiting`, manual owner step), `--` not verified (`idle`) | Icon + word, never color alone |
| Evidence | short link text: "test run 08 Oct 16:58", "PR #69 CI", "eval.md §Owner steps" | Popover shows evidence text from features.json; links to the session event or CI run |
| Verify | verification command, copyable mono | "manual" commands render as text "see eval.md" with a link, not as a copy target |

Sample rows (synthetic; descriptions shortened here):

| ID | Description | Repo | Passes | Evidence | Verify |
|---|---|---|---|---|---|
| AC-48.1 | Given a hub with `brain/auto/workspace/`, when `hub sync` runs, then the folder is gitignored | agent-hub | yes | test run 08 Oct 16:58 | `uv run pytest packages/generator/tests/unit/test_gitignore.py -k workspace` |
| AC-48.2 | Given a personal note, when the session brief is built, then it is included only for its owner | agent-hub | yes | test run 08 Oct 16:58 | `uv run pytest packages/core/tests/unit/test_brief.py -k personal` |
| AC-48.3 | Given `hub doctor`, when `brain/auto/workspace/` is not ignored, then rule brain.memory warns | agent-hub | yes | test run 08 Oct 16:59 | `uv run pytest -k brain_memory_rule` |
| AC-48.7 | Given a team learning, when accepted, then it is written under `brain/learnings/` only | agent-hub | yes | test run 08 Oct 17:00 | `uv run pytest -k learning_target` |
| AC-48.20 | Given two PRs for one feature, when rendering, then the render impact is compared per merge | agent-hub | yes | PR #69 CI (check: test) | `make check` |
| AC-48.21 | Given the feature is merged, when the owner opens a new session in the hub, then the layered memory loads | agent-hub | owner | eval.md §Owner steps | manual (see eval.md) |

Expanded row: full Given/When/Then, evidence text, "Last verified by hub-workflow:evaluator in session 5091b986 on 08 Oct 17:02" (link to the `Read brain/features/layered-memory/features.json` event), and for AC-48.21 the recorded decision: "Decision · AC-48.21 stays passes:false (manual owner step)" with a link to that decision event in session 5091b986.

"Copy all commands" copies the non-manual verification commands, one per line, deduplicated, each prefixed with a comment `# AC-48.1`. A person can paste and run them in a worktree.

**Counting rule (design decision).** The header and list bar show "21/21 · 1 owner step": the numerator counts ACs that pass by command (20) plus ACs the evaluator classified as manual owner steps (1), because both are accounted for by the evaluation; the owner-step segment is hatched in `waiting` so it never reads as "passed". The tooltip always states the split: "20 passing by command · 1 owner step (AC-48.21, recorded passes:false)". A feature with a failing AC can never show a full bar. Alternative considered: show "20/21" and let the verdict explain; rejected because it makes a SHIP-WITH-OWNER-STEPS feature look identical to one with a failing AC at a glance.

### Rendered documents with sticky TOC

- Tabs Spec, Research, Plan, Evaluation render `spec.md`, `research.md`, `plan.md`, `eval.md` with `Markdown`. Frontmatter becomes `FrontmatterChips` (type, status, repos, last verified, provenance); last verified turns `waiting` when older than 60 days.
- Header line per document: path (mono), commit short hash, `ProvenanceBadge`, "Open in GitHub" (hub repo at that commit).
- Sticky TOC (240 px, right) from H2/H3; the current section is highlighted (`accent`, left bar) via scroll spy; click scrolls with focus moved to the heading. At < 1280 px the TOC becomes a "On this page" dropdown at the top.
- AC ids anywhere in a document become links to `?ac=` in the AC tab; issue keys become `IssueLink`s; file paths become `PathText`.
- Reading width capped at 760 px (`body` 14/20 at 1440; 15/24 reading variant is not introduced: one body size).
- Content quoted from outside (web sources in research.md marked by the researcher) shows `ExternalLabel` "External source" next to the quote.
- Issues tab: table from `issues.md` joined with the tracker: key, title, state, assignee is not shown (process, not people), linked run, PR.

### Data mapping

| Element | Entity.field (brief §3) | API resource | Source · latency |
|---|---|---|---|
| Name, size, repos | spec.md frontmatter | `GET /features/{project}/{slug}` → `title, size, repos` | hub files · watcher |
| Verdict | eval.md verdict | `verdict` | hub files |
| Issues list | issues.md + tracker | `issues[]` `{key, title, state, url, run_id, pr}` | hub files + linear 60 s + github 60 s |
| PR | linked PR | `pr.{repo, number, state, merged_at, merged_by}` | github · 60 s |
| AC bar counts | features.json | `acs.summary.{total, passing, owner_steps, failing, unverified}` | hub files |
| AC rows | features.json: id, description, repo, verification command, passes, evidence | `acs.items[]` `{id, description, repo, command, passes, owner_step, evidence}` | hub files |
| AC last verified | session that last read/updated features.json | `acs.items[].verified_in.{session_id, event_id, at}` | derived from events |
| Golden path steps | derived from files, approvals, runs, PRs | `golden_path[]` `{phase, state, at, actor: {kind: person|agent, name}, link}` | derived server-side |
| Plan approver | gate.result of the plan gate | `golden_path[phase=plan].actor` | hooks / app |
| Owner-step callout | features.json owner_step + eval.md Owner steps | `acs.items[owner_step=true]`, `owner_steps_text` | hub files |
| Document bodies | spec.md, research.md, plan.md, eval.md | `documents.{spec,research,plan,eval}.{path, commit, frontmatter, markdown, toc[]}` | hub files |
| Linked run and cost | WorkflowRun | `runs[]` `{id, state, cost_usd}` | executor + otel |

### Interactions

- Tabs are deep-linkable (`?doc=eval`), keyboard `1`–`6` switch tabs; `Ctrl F` stays native in documents.
- AC filter segmented control and Repo filter update `?acs=owner_step&repo=agent-hub`.
- Click a stepper step: opens its evidence (session, approval, PR). Arrow keys move along the stepper when focused.
- Copy buttons on each command; after copy, the button label becomes "Copied" for 2 s and a polite live region announces it.
- `?ac=AC-48.21` scrolls to and expands the row with a 1 s `accent-soft` highlight (none under reduced motion; the row stays selected).
- From any AC row, "Open the session that verified it" goes to the session timeline at the verifying event.

### States

| State | What shows | Exact copy |
|---|---|---|
| Loading (>300 ms) | Header skeleton, 8 stepper dots, 10 table rows skeleton | (none) |
| Missing document | Tab still present, disabled style, content `EmptyState` | "No research.md for this feature." / "Allowed for size spike. Research is written by `/research` in the hub." |
| No features.json | AC tab `EmptyState` | "No features.json yet. Acceptance criteria are tracked once `/create-plan` writes it." |
| No eval yet | Verdict "--"; Evaluation tab empty | "Not evaluated yet. The evaluator agent writes eval.md at the end of the golden path." |
| Blocked by a failed run | `Banner` failure variant under the stepper | "Blocked at Implement: run 01923f1e failed at Verifying (make check exited 2). [Open run]" (guard-bypass sample) |
| Partial: GitHub down | PR state from cache, Shipped step shows `AsOfStamp` | "PR state as of 09:12 (GitHub not reachable)." |
| Parse error in a file | Affected tab shows `ProblemError` inline; other tabs work | "features.json could not be parsed" / "Line 38: trailing comma. The rest of the record is shown." |
| Not found | 404 variant | "Feature layered-memory not found in agent-hub" / "The folder brain/features/layered-memory/ may have been renamed. Search with Ctrl K." |
| Live | File changes refresh the affected tab; a quiet line under the header | "Updated from commit 7b2d0e1 at 14:05." |
| Stale | `AsOfStamp` in header | "As of 14:02 · collector offline" |

### Actions by phase

| Action | Phase | Confirmation? | Consequence |
|---|---|---|---|
| Read, copy commands, open evidence, open in GitHub | P2 | No | None |
| Mark owner step done | Not in the app | n/a | The owner records it in eval.md / features.json through a hub PR (principle 2: the app does not edit the brain) |
| Start run on an issue of this feature | P4 | Dry-run preview first | Same flow as Run detail "Start run on an issue" |

## Screen 3: New feature (AGH-420)

**Route:** `/features/new`, from the list's "New feature" button · **Phase:** P2 (driven sessions,
[ADR 0031](../../../adr/0031-driving-claude-code-sessions-from-the-app.md)) · **Answers:** "What do I want built, and how do
I hand it to Claude?"

### Purpose and primary user

The project owner with an idea, and often a screenshot, a PDF or a CSV: say what to build, attach the material, press
one button. The one action is **Start with Claude**; the issue, slug and size are optional and look it. The screen
writes no file: it starts a Discuss conversation in the project's hub folder (`useStartDiscussion`, AC-419.15) whose
first message asks Claude to run the hub's `feature` skill from step 0. The records stay the skill's: the brief goes
into the tracker issue's description (step 0), then `brain/features/<slug>/spec.md` and its summary, each shown to the
owner before it is written; a `brief.md` the agent writes in the feature folder is one of the folder's record files
([feature-records.md](../../feature-records.md) "`brief.md` and `ux-*.md`"), so the feature shows on the list from it,
its Spec step "Brief only · spec not written".

### Layout (1440 px, sidebar expanded, Discuss panel closed)

```
Features › New
New feature                                                                       ( ▦ demo  ⌄ )
Describe what to build and attach what Claude should see.

What do you want to build?                                              ┌ Options ────────── All optional ┐
╭──────────────────────────────────────────────────────────────────╮    │ Start from an issue             │
│ [img] [▤ client-brief.pdf 1.2 MB ⨯]              (only with any) │    │ [ None                        ] │
│ Describe the feature: who it is for, what they should be able    │    │ Like DEMO-1600. Claude reads its │
│ to do, and why.                                  (placeholder)   │    │ brief first.                    │
│                                                                  │    │ Slug                            │
│ [+ Attach]  Paste or drop images, PDFs and text files            │    │ [ Claude picks one            ] │
│                                Ctrl/⌘ Enter [▸ Start with Claude] │   │ Like orders-csv-export.         │
│ ⓧ the refusal or the failed start, when there is one  (err row)  │    │ Size                            │
╰──────────────────────────────────────────────────────────────────╯    │ [ Let Claude ask            ⌄ ] │
                       Write at least a sentence, or give an issue.     │ Claude proposes a size and asks │
                                                                        │ you.                            │
What happens next                                                       └─────────────────────────────────┘
(1) Claude reads your brief…  (2) It asks one question…  (3) It drafts…
```

The toolbar is one row at the bottom of the box: Attach and the drop note on the left, the key hint and Start on the
right (the drawing wraps only for its width). The box is a grid of its own (`files`, `text`, `plus set . stop send`,
`err`) inside the chat composer's frame, focus ring and drop highlight. The Options card is sticky. At 1100 px or
less, or when `.ft-new` is narrower than 900 px (the Discuss panel docked), one column: brief, Options (its three
fields side by side as the card allows, `auto-fit` of 200 px), What happens next. Below 640 px of box width the drop
note hides, below 480 px the key hint; below 560 px of `.ft-new` the project pill drops under the title.

### Components

| Piece | Decision |
|---|---|
| `.as-composer` frame, `as-composer-drop`, `AttachmentList`, `useMessageAttachments` | reuse (the chat's, AGH-419) |
| `useAttachmentDrop`, `AttachButton` (`components/AttachmentList.tsx`), `useAutoGrow` (`lib/useAutoGrow.ts`) | new, shared: the chat composer's paste/drop/picker handlers and its auto-grow, moved out so the chat and this screen use one copy |
| `useStartDiscussion`, `rememberDiscussSession`, `discussPrompt`, `useDiscussTarget` | reuse (the Discuss panel's) |
| Project pill: `.as-pill` + `.as-pill-select` + `.as-pill-value` + `.as-pill-caret` | reuse; `.as-pill-value` makes any pill as wide as its value (the native select lies invisible over it) |
| Options: `.ah-input` fields; Size a `select.ah-input` with a `chevron-down` caret (`.ft-new-select`) | reuse, one local extension |
| `Button` primary, `Kbd`, `Icon circle-x`, `Banner warning boxed`, `Skeleton`, `ah-card`, `EmptyState` | reuse |
| `.ah-input.ah-mono` (`styles/bundle.css`) | fix: `.ah-input { font: inherit }` no longer drops a code field's mono face |

### Content

| Element | Copy |
|---|---|
| Lead | "Describe what to build and attach what Claude should see." |
| Brief label / placeholder | "What do you want to build?" / "Describe the feature: who it is for, what they should be able to do, and why." · with images "Say what to build, and what Claude should see in the image." · with files "Say what to build, and what Claude should take from the file." |
| Toolbar | "Attach" (title "Attach images, PDFs or text files up to 5 MB (or paste or drop them in the box)") · "Paste or drop images, PDFs and text files" · `Ctrl` / `⌘` `Enter` · "Start with Claude", pending "Starting…" |
| Status line | ready "Opens the Discuss panel. Claude asks before writing any file." · pending "Starting the conversation in the hub folder…" · not ready, the first that holds: the unavailable reason's title ("Session control is locked in this browser.") · "Wait for the files to be read." · "Add a sentence on what to build with the attachments." · "Write at least a sentence, or give an issue." · "Fix the issue id in Options." · "Fix the slug in Options." · the hub folder check ("Looking for the hub folder…") |
| Options | "Options" / "All optional" · "Start from an issue", placeholder "None", hint "Like DEMO-1600. Claude reads its brief first.", error "An issue id, like DEMO-1600." · "Slug", placeholder "Claude picks one", hint "Like orders-csv-export.", errors "Lowercase letters, digits and dashes, starting with a letter." / "A feature with this slug already exists." · "Size": "Let Claude ask", "Spike", "Bounded", "Architectural", with the chosen one's hint |
| Sent card | "Sent to Claude" · the brief and its attachments · "Issue: … · Slug: … · Size: …" · "Claude is working on the brief with you in the panel." with "Open the panel" and "Open the full chat" · once found "`<slug>` has its record." and "Open `<slug>`" · "Start another feature" |

### States

| State | What shows |
|---|---|
| Loading | A pill-shaped skeleton in the header; the form's two blocks (the box's radius, the card) |
| No project | `EmptyState` "No project yet" · "Register a hub to start features in it." · "Open Welcome" |
| Empty form | Instruction placeholder, Start `aria-disabled`, "Write at least a sentence, or give an issue." |
| Sessions unavailable | `Banner warning` above the box with the reason and its fix; the status line says the reason's title; the fields stay editable |
| Error | A refused file or a failed start in the box's last row (`role="alert"`, `circle-x`) |
| Starting | "Starting…" (`aria-busy`), the pending status line; nothing re-sends |
| Sent | The sent card, polling the records every 3 s until the feature appears |

### Acceptance criteria (AGH-420)

- **AC-420.1** Given the Features list, when it opens, then a primary "New feature" button sits on the title row and
  opens `/features/new`; with no feature yet, the empty state says a feature can be started here with New feature.
- **AC-420.2** Given `/features/new`, when it opens, then it shows the breadcrumb "Features › New", the title "New
  feature" and the one-line lead; with more than one project, the project is a pill (folder icon, name, caret) on the
  title row, as wide as the name, its native select (named "Project") covering it; changing it gives the form of that
  project (the brief's draft is kept per project; issue, slug and size reset); with no project, the "No project yet"
  empty state.
- **AC-420.3** Given the brief box, when images, PDFs or UTF-8 text files are pasted, dropped anywhere on the box or
  picked with Attach, then they join the brief as the chat's thumbnails and chips above the text, with the chat's
  limits and refusal sentences, and the placeholder turns to the image or file variant; a drag that carries no file
  (selected text) is left to the browser; a press on the box's empty space puts the caret in the text.
- **AC-420.4** Given the form, when Start cannot run yet, then Start stays focusable with `aria-disabled`, and one
  status line under the box, right-aligned and `aria-live`, gives the first reason that holds (sessions unavailable by
  its title, files being read, no sentence with attachments, no idea of 10 characters and no valid issue, a bad issue
  id, a bad or taken slug, the hub folder check); pressing Start or Ctrl/⌘+Enter then sends nothing and moves focus to
  the field at fault (the brief, the issue or the slug).
- **AC-420.5** Given the Options card, when it shows, then Issue, Slug and Size have one field shape (label, one 32 px
  field, one hint) in that order: the issue upper-cased and checked as `KEY-123`, the slug checked as kebab case and
  against the project's features, Size a select defaulting to "Let Claude ask" with the chosen size's hint; the empty
  fields say their default ("None", "Claude picks one") in the sans face while typed ids show in mono.
- **AC-420.6** Given a ready form, when Start is pressed or Ctrl/⌘+Enter is typed in any field (Enter in a one-line
  field does nothing, an IME composition never starts), then one conversation starts in the project's hub folder with
  the message naming only the filled fields ("Tracker issue: … (read its brief first).", "Slug: …", "Size: …", then the
  idea), the brief asking Claude to follow the hub's `feature` skill from step 0, one question at a time, showing each
  record before writing it, and the images and files attached; the Discuss panel opens on that conversation (kept for
  its target) and the draft is cleared.
- **AC-420.7** Given a started request, when the sent card shows, then it lists the brief, its attachments and the
  options, says Claude works with the owner in the panel ("Open the panel" while it is closed, focus back on it when
  the panel closes, and "Open the full chat"), rereads the features every 3 s and, once the new feature appears (the
  given slug, else the first slug not there at the start), links to it; "Start another feature" closes the panel and
  gives an empty form with the focus in the brief.
- **AC-420.8** Given a file refused earlier, when Start is pressed or that attachment is removed, then the refusal
  clears, and a failed start always shows in the box's error row (the problem's detail or title, else "Could not
  start the conversation. Try again."), both lines when both hold; everything typed and attached stays.
- **AC-420.9** Given the screen at 1440 px, then the brief and its status line sit left and the sticky Options card
  right, What happens next under the brief; at 1100 px or less, or with `.ft-new` under 900 px (the Discuss panel
  docked), one column in the order brief, Options, What happens next; the drop note hides under 640 px of box and the
  key hint under 480 px.
- **AC-420.10** Given the chat composer and this screen, then both use the same `useAttachmentDrop`, `AttachButton`
  and `useAutoGrow` (the brief grows to half the viewport, the chat to 40 %), so paste, drop and the picker behave the
  same in both.

## UX principles applied

| Choice | Principle (brief §7) |
|---|---|
| Golden path stepper with dates and named approvers | Explainability / provenance (W3C PROV): who did what, when |
| "21/21 · 1 owner step" with a hatched amber segment | Calibrated trust: a full bar never hides a manual step; pre-attentive texture + color |
| Owner-step callout above the tabs | Endsley projection: what is still left after "shipped" |
| Copyable verification commands per AC | Trust through verifiability; recognition over recall |
| Sticky TOC with scroll spy | Information scent; orientation in long documents (layer-cake scanning) |
| ACs tab is the default, documents behind tabs | Progressive disclosure; overview first |
| No assignee column in Issues | Principle 6: process, not people |

## Responsive

- **1280×800:** sidebar collapsed; stepper labels show phase + date only (actor in tooltip); AC table hides Evidence (in expanded row); document TOC becomes a dropdown.
- **1920:** document reading area stays 760 px; TOC 280 px; AC table shows description on 2 lines.
- **Mobile:** not a glance screen; the detail renders header, stepper as a vertical list and the AC list (id + passes) read-only.
