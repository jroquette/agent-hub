# Features

**Phase:** P2 (read-only) · **Routes:** `/features`, `/features/{project}/{slug}` (params `doc=spec|plan|research|eval|issues` (as built: `tickets`, see Departures), `ac=AC-48.21`, `phase=`) · **Answers:** "Where is each feature on the golden path, and is it really done?"

This section holds two screens: the **Features list** and **Feature detail**. A feature is a folder `brain/features/<slug>/` in the hub with `spec.md`, `research.md`, `plan.md`, `features.json`, `issues.md` and `eval.md`. The app only reads these files; editing a feature record stays a human act in a hub PR (principle 2).

## Departures (AGH-136, ticket planning)

Built with the changes below; where this file says otherwise, this list wins (records:
[feature-records.md](../../feature-records.md); route: [API.md](../../../API.md) "Feature tickets";
[ADR 0025](../../../adr/0025-reading-the-tracker-from-the-app.md)). For Linear, it replaces the control-plane
README's "Sources not connected": Linear is read for a feature's tickets; GitHub stays not connected.

- **Records.** A feature folder adds `evals/<delivery>.md` (one per evaluation, never overwritten; `eval.md` is read
  as the delivery `legacy`) and `reviews/<ticket>.md`. Tickets come from `features.json` (`tickets` and `linear`),
  not from `issues.md`, which only marks the plan as written.
- **Tabs.** Spec, Research, Plan, Eval, Criteria and Tickets (`?doc=spec|research|plan|eval|acs|tickets`; the old
  `?doc=issues` opens Tickets). Eval lists every delivery with its verdict, tickets, ACs, PRs and commit. Tickets
  loads `GET /features/{project}/{slug}/tickets` only while it is open.
- **Tickets tab.** Columns Ticket, Title, Status (badge with text, never color alone), Assignee, Blocked by (links,
  each edge tagged plan, Linear or both), ACs (links to Criteria `?ac=`) and Readiness ("Can start now", "Waiting on
  …", "Done", "Canceled", "Waiting: cycle", "Unknown"). The assignee is shown: the owner asked for it (D1), a departure from
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

---

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
| `GoldenPathStepper` (compact variant) | 8 segments, filled up to the current phase; current phase name + "since" date under it |
| `BudgetBar` (progress variant, reused for ACs) | Segments: passing (`done`), owner step (`waiting`, hatched), failing (`failed`), not yet verified (`gray-300`); label "19/21" |
| `StatusBadge` (verdict variant) | SHIP (`done`), SHIP-WITH-OWNER-STEPS (`waiting`), NO-SHIP (`failed`); "--" when no eval yet |
| `SegmentedControl` / filter menus | Phase, Verdict, Repo, Size |
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
- Filters in URL: `/features?phase=implement,review&verdict=none`.

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
