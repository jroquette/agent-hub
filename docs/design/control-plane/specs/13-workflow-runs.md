# Workflow runs and run detail

**Phase:** P2 (read-only; actions P4 tagged inline) · **Routes:** `/runs`, `/runs/{run_id}`, `/runs/{run_id}?tab=…&step=…` · **Answers:** "Which runs are moving, which failed, where, and why?"

This section holds two screens: the **Runs list** (`/runs`) and **Run detail** (`/runs/{run_id}`). Glossary reminder: "run" always means a WorkflowRun (one execution of a workflow, e.g. one issue to one PR). A run contains Sessions; a Session is never called a run.

---

## Screen 1: Runs list

**Route:** `/runs` (URL params: `stage`, `outcome`, `failure_stage`, `repo`, `workflow`, `mode=live|dry_run`, `period`, `sort`, `cursor`) · **Answers:** "What is in flight and what broke?"

### Purpose and primary user

Owner/tech lead scans for failed and stuck runs; developer finds "the run that broke CI". Overview first: the table is sorted with failed and in-progress runs at the top by default (`sort=attention`), then by started time descending.

### Layout (1440 px)

```
+--------+-----------------------------------------------------------------------------------------------+
|Sidebar | TopBar: [All projects v]   [Search or jump to... Ctrl K]   (o Connected · last event 3 s ago)  |
| 240    +-----------------------------------------------------------------------------------------------+
|        | Workflow runs                                               [24 h | 7 d | 30 d | Custom]     |
|        | 11 runs · 8 reported · 2 failed · 1 in progress · median $4.10          [Start run on an issue]P4|
|        +---------------+-------------------------------------------------------------------------------+
|        | FILTERS       | Run      Issue                         Repo        Workflow      Stage        |
|        | Stage         |          Att  Started      Duration  Cost / budget    Mode   PR · CI   Outcome  |
|        | [ ] Picked  0 |-------------------------------------------------------------------------------|
|        | [ ] Impl.   1 | 01923f1e AGH-79 Guard bypass           agent-hub   issue-to-pr@4 [FAILED·VERIFY]|
|        | [ ] Verif.  0 |          2/2  10 Oct 22:41  1 h 12 min $6.80 ======--  live   --        Failed   |
|        | [ ] PR open 1 | 01923f9c AGH-112 Cap the tracker team… agent-hub   issue-to-pr@4 [IMPLEMENTING] |
|        | [ ] Failed  2 |          1/2  11 Oct 09:03  38 min     $2.14 ==------  live   --        Running  |
|        | Outcome       | 01923e77 LOK-311 Order book websocket… tradeSentinel issue-to-pr@4 [PR OPEN]   |
|        | Failure stage |          1/2  11 Oct 07:20  52 min     $3.95 ====----  live   #214 o CI   Running|
|        | Repo          | 01922b10 AGH-48 Layered memory         agent-hub   feature@2     [REPORTED]    |
|        | Workflow      |          1/1  08 Oct 08:31  9 h 12 min $9.12 =========  live   #69 v merged Done|
|        | Mode          | ...                                                                           |
|        |               | Showing 11 of 11                                                              |
+--------+---------------+-------------------------------------------------------------------------------+
```

Regions: page header (title, `SegmentedControl` period, KPI line, P4 primary button), `FilterRail` (264 px, left), `DataTable` (fills the rest).

### Components

| Component | Variant / notes |
|---|---|
| `AppShell`, `Sidebar` (item "Workflow runs" selected), `TopBar`, `ProjectSwitcher`, `CollectorPill` | Standard shell |
| `SegmentedControl` | Period: 24 h / 7 d / 30 d / Custom; default 7 d |
| `KpiStat` | Inline variant (one line of text with `figure` numbers), not cards: the list is the content |
| `FilterRail` + `FilterChip` | Facets with counts: Stage, Outcome, Failure stage, Repo, Workflow, Mode (live / dry run) |
| `DataTable` | Density compact (`row-compact` 32 px) by default; two-line rows when the issue title column is narrow |
| `IdChip` | Run id short (`01923f1e`), copy full UUIDv7 on click |
| `IssueLink` | `AGH-79` linking out to Linear, title truncated |
| `StageChip` | One per stage; failed variant shows `FAILED · VERIFYING` on `failed-soft` |
| `BudgetBar` | Thin bar, cost / budget; amber at 80 %, `failed` at 100 % |
| `Money` | 2 decimals in the list |
| `StatusBadge` | Outcome: live (running), done (reported), failed, blocked |
| `Button` | Primary "Start run on an issue" (P4, hidden in P2) |

### Data mapping

| Element | Entity.field (brief §3) | API resource | Source · latency |
|---|---|---|---|
| Run id | WorkflowRun.run_id | `GET /workflow-runs` → `items[].id` | executor · real time |
| Issue id + title | WorkflowRun.issue (id, title, url) | `items[].issue` | linear · polling 60 s (title), executor (id) |
| Repo | WorkflowRun.repo | `items[].repo` | executor |
| Workflow + revision | WorkflowRun.workflow name, revision, content hash | `items[].workflow.{name,revision,hash}` | executor |
| Stage chip | WorkflowRun.state (PICKED…REPORTED / FAILED(stage, reason)) | `items[].state`, `items[].failed_stage` | executor · real time (step.start/step.end, proposed) |
| Attempt | max(step.attempt) of the current step / workflow cap | `items[].attempt`, `items[].max_attempts` | executor |
| Started | first step.start timestamp | `items[].started_at` | executor |
| Duration | ended_at − started_at, or now − started_at while running | `items[].ended_at` | derived client-side for live rows |
| Cost / budget | WorkflowRun.total cost, caps.budget USD | `items[].cost_usd`, `items[].caps.budget_usd` | otel · real time; late enrichment possible |
| Mode | WorkflowRun live / dry-run | `items[].dry_run` | executor |
| PR + CI | WorkflowRun.PR url; Tracker & GitHub CI per commit | `items[].pr.{number,url,state,ci}` | github · polling 60 s |
| Outcome | derived from state | `items[].outcome` | derived |
| Facet counts | aggregate over current filter set | `GET /workflow-runs?…&facets=stage,outcome,failure_stage,repo,workflow,dry_run` → `facets` | derived · on query |
| KPI line | count by outcome, median cost in period | `GET /metrics/runs-by-outcome?scope=&period=` and `GET /metrics/cost-per-run?scope=&period=` | derived |

### Interactions

- Click a row or press Enter on the focused row: open Run detail. Middle click / Cmd-click: new tab (rows are real links).
- `j` / `k` move the row focus; `/` focuses the filter rail search; `Esc` clears the focused facet.
- Click the issue id: opens Linear in a new tab (external icon). Click the PR number: opens GitHub.
- Hover the stage chip of a failed run: tooltip with the plain reason ("make check exited 2 · 3 failing tests in test_guard.py").
- Hover a cost bar: "$6.80 of $10.00 budget · 68 % · period 7 d".
- Live rows update over `GET /workflow-runs/{id}/stream` subscriptions for in-progress rows only (max 20; beyond that, the list polls every 15 s).
- All filters, sort and period are in the URL; "Copy link" from the page menu.

### States

| State | What shows | Exact copy |
|---|---|---|
| Loading (>300 ms) | `Skeleton` rows (8) with column widths kept; KPI line skeleton | (no text) |
| Empty, no runs ever | `EmptyState` | "No workflow runs yet." / "Runs appear when the executor picks an issue labelled agent-ready. Label an issue in Linear, or start one from the terminal: `./hub run AGH-112 --dry-run` (proposed CLI)." |
| Empty, filters exclude all | Inline in the table | "No runs match these filters." [Clear filters] |
| Partial: GitHub down | PR · CI cells show `--` with `idle` icon; `Banner` (info) above table | "GitHub not reachable since 09:12. PR and CI status unknown; other columns are current." |
| Partial: Linear down | Issue titles fall back to the last cached title, italic, with `AsOfStamp` | "Issue titles as of 08:55 (Linear not reachable)." |
| Error | `ProblemError` replacing the table | Title + detail from Problem Details, e.g. "Could not load workflow runs" / "The collector database is locked by another process (status 503)." [Retry] |
| Live | Running rows show a pulse dot in the outcome cell; duration ticks every 1 s; stage chip transitions fade (`dur-base`) | "Running" |
| Stale (collector offline) | `AsOfStamp` next to the title; live dots replaced by `idle` clock | "As of 14:02 · collector offline" |

### Actions by phase

| Action | Phase | Confirmation? | Consequence |
|---|---|---|---|
| Open run, filter, sort, copy link | P2 | No | Navigation only |
| Start run on an issue | P4 | Dry-run preview first, then "Run live" | See Run detail section "Start run on an issue" |

---

## Screen 2: Run detail

**Route:** `/runs/{run_id}` (params: `step=<step>:<attempt>` selects a step; `tab=sessions|gates|tracker|caps|pr`; `event=<event_id>` for a deep-linked failing moment is resolved by the session route) · **Breadcrumbs:** `agent-hub › Workflow runs › Run AGH-79 (01923f1e)` · **Answers:** "Where did this run stop, why, and what do I do about it?"

### Purpose and primary user

The owner arriving from "Needs you" (flow 1, morning check) must see in under 5 seconds: the stage it failed at, the plain reason, that a diagnosis is already on the issue, and a one-click path to the failing moment in the session. The developer uses the Gantt and gate log to find what to fix.

### Layout (1440 px), sample: AGH-79 Guard bypass, FAILED at VERIFYING

```
+--------+-----------------------------------------------------------------------------------------------+
|Sidebar | agent-hub › Workflow runs › Run AGH-79                                                        |
|        +-----------------------------------------------------------------------------------------------+
|        | HEADER (sticky, z-sticky)                                                                     |
|        | AGH-79 Guard bypass   [FAILED]  run 01923f1e  issue-to-pr rev 4 (a3f9c21)  agent-hub  live    |
|        | Started 10 Oct 22:41 · 1 h 12 min · $6.80 of $10.00 [=======---]  · 3 sessions · no PR        |
|        |                                       [Retry from verify] P4   [Open issue AGH-79 ->]  [...]  |
|        +-----------------------------------------------------------------------------------------------+
|        | FAILURE BANNER (failed-soft, failed left edge 4 px)                                           |
|        | (x) Failed at Verifying · attempt 2 of 2                                                      |
|        |     make check exited 2: 3 failing tests in packages/core/tests/unit/test_guard.py.           |
|        |     Diagnosis posted to AGH-79 at 23:53 · label agent-failed added.                           |
|        |     [Open failing moment ->]   [View diagnosis comment]   [View gate log]                     |
|        +-----------------------------------------------------------------------------------------------+
|        | STAGE PIPELINE                                                                                |
|        |  (v)Picked --> (v)Worktree --> (v)Implementing ==> (x)Verifying -.-> ( )PR open -.-> ( )Reported|
|        |   2 s           14 s           41 min, 2 att.      6 min, 2 att.     not reached    not reached |
|        |                                  ^                    |                                       |
|        |                                  +--- on fail: back --+  "attempt 2 of 2 · cap reached"       |
|        +-----------------------------------------------------------------------------------------------+
|        | [Sessions (Gantt)] [Gates 2] [Tracker writes 4] [Caps] [PR and CI]                            |
|        | GANTT                22:40     22:50     23:00     23:10     23:20     23:30     23:40   23:53  |
|        | Picked       #1      |                                                                        |
|        | Worktree     #1      ||                                                                       |
|        | Implement    #1        [==== 7c2e41a0 main · 24 min · $2.31 ====]                             |
|        |   subagent              [= spec-reviewer 3 min =]                                             |
|        | Verify       #1                                            [=x 3 min exit 2]                  |
|        | Implement    #2                                                 [== 9b0d1f37 · 17 min · $3.12 ==]|
|        |   subagent                                                         [= quality-reviewer =]     |
|        | Verify       #2                                                                   [=x 3 min] |
|        | Report fail  #1                                                                          [|] |
+--------+-----------------------------------------------------------------------------------------------+
```

Below the tabs, the right column (360 px, at >= 1440 px only) holds a **Run facts** card: workflow, revision + hash, caps, model, tracker transport, worktree path, branch. At narrower widths, Run facts moves under the tabs as the "Caps" tab.

### Components

| Component | Variant / notes |
|---|---|
| `Breadcrumbs` | Project › Workflow runs › Run AGH-79 |
| Header | `IssueLink` (title variant, `title` type style), `StatusBadge` failed, `IdChip` run id, `BudgetBar` with label, `Money` 2 decimals in header, 4 decimals in Caps tab |
| `Banner` | Variant `failure`: ground `failed-soft`, left edge `failed`, icon octagon-x; not dismissible while the run is FAILED |
| `StagePipeline` | Horizontal, six nodes; node states done / failed / running / not reached / skipped; loop back-edge drawn as a curved arrow under the pipeline with label "attempt 2 of 2"; attempt count badge on looping nodes |
| `Tabs` | Sessions (Gantt), Gates, Tracker writes, Caps, PR and CI; counts in tab labels |
| `GanttLane` | One lane per (step, attempt); bars = Sessions or script executions; subagent sessions as thinner nested bars indented `space-5`; failed segment end marked with an x glyph and `failed` color |
| `CodeBlock` | Gate log excerpt, mono, `code-bg` ground, line numbers, failing lines highlighted with `diff-del-bg` |
| `DataTable` | Gates and Tracker writes tables |
| `RedactionChip` | Inside log excerpts and tracker comment bodies when content was redacted |
| `Button` | "Open failing moment" (secondary, with arrow), "Retry from verify" (primary, P4), "Start run on an issue" (P4) |
| `ConfirmDialog` | Retry and Run live |
| `AsOfStamp`, `ProblemError`, `Skeleton`, `EmptyState` | States |

### Run detail: element-by-element

**Header.** Issue id and title (title style), outcome badge, run id chip, workflow name + revision + 7-char content hash (mono, hover = full hash and "Pinned revision: this run used revision 4 even though revision 5 exists" when applicable), repo, mode (`live` or `dry run` badge in `idle` color), started (absolute), duration, cost vs budget, sessions count, PR link or "no PR".

**Failure banner.** Shown only when `state = FAILED`. Four lines max:
1. "Failed at {Stage} · attempt {n} of {max}" (body-strong).
2. Plain reason, generated from the failing gate result: "{command} exited {code}: {summary}". Summary is the executor's parsed test summary when available ("3 failing tests in packages/core/tests/unit/test_guard.py"), else "see the gate log".
3. Diagnosis: "Diagnosis posted to AGH-79 at 23:53 · label agent-failed added." If the tracker write failed: "Diagnosis not posted: Linear returned 401. The text is in Tracker writes." (`blocked` color).
4. Links: **Open failing moment** goes to `/sessions/9b0d1f37?tab=timeline&event={event_id}`, the Bash `make check` tool.result (exit 2) that session 9b0d1f37 ran just before handing off to Verify #2, with its test summary. When no session ran the failing command (the gate was only a script step), the link goes to the gate log anchor `#gate-verify-2` and its label reads "Open gate log" instead. **View diagnosis comment** opens the Tracker writes tab scrolled to the comment. **View gate log** opens the Gates tab with the failing gate expanded.

**Stage pipeline.** Each node: icon + label + duration + attempts ("2 att."). The loop arrow from Verifying back to Implementing appears only when an on_fail loop happened; label "attempt 2 of 2 · cap reached" when exhausted, "attempt 1 of 2" while still looping. Not-reached nodes are outlined, `text-subtle`, with "not reached". Clicking a node sets `step=` in the URL and filters the Gantt to that step.

**Gantt (default tab).** Time axis is wall clock (local or UTC per the top bar toggle). Lane label: step name + attempt (`Implement #2`). Bar label: session short id, role ("main" or agent id), duration, cost. Script steps (worktree, verify) render as hatched bars without cost. Gaps between bars are shown (they are waiting time and matter for "where does it get stuck"). Click a bar: open the session; hover: popover with agent, turns, tokens, cost $3.1240, outcome, last event.

**Gates tab.**

| Gate | Step · attempt | Command | Exit | Duration | Result | When |
|---|---|---|---|---|---|---|
| check (full) | Verify #1 | `make check` | 2 | 3 min 04 s | failed | 23:21 |
| check (full) | Verify #2 | `make check` | 2 | 2 min 58 s | failed | 23:50 |

Expanding a row shows the log excerpt: the last 40 lines plus every line matching the failure parser, with a "Show full log (1,284 lines)" disclosure. Sample excerpt:

```
FAILED packages/core/tests/unit/test_guard.py::test_denies_push_to_main_via_alias - AssertionError
FAILED packages/core/tests/unit/test_guard.py::test_bash_rules_match_subcommands - AssertionError
FAILED packages/core/tests/unit/test_guard.py::test_force_push_with_lease_is_blocked - AssertionError
================ 3 failed, 412 passed, 2 skipped in 171.40s ================
make: *** [Makefile:41: test-unit] Error 2
```

A human gate (plan approval) appears here too, with "Approved by José Henrique Roquette at 22:44 in the terminal session" and a link to the gate.result event.

**Tracker writes tab.** Chronological table: time, kind (label added / label removed / comment / state change), target (`AGH-79`), content (comment body rendered as Markdown, collapsed to 3 lines), status (written / failed with HTTP status), source event. Sample rows:
- 22:41 label removed `agent-ready`
- 22:41 comment "Picked by run 01923f1e (issue-to-pr rev 4)."
- 23:53 label added `agent-failed`
- 23:53 comment "Run 01923f1e failed at Verifying after 2 attempts. `make check` exited 2: 3 failing tests in test_guard.py (test_denies_push_to_main_via_alias, test_bash_rules_match_subcommands, test_force_push_with_lease_is_blocked). Likely cause: the subcommand matcher change in guard.py:88 no longer handles `git -c` prefixes. Branch roquettejh/agh-79-guard-bypass kept for inspection."

The diagnosis comment is agent-written: it carries `DerivedLabel` "Written by the run's report step".

**Caps tab.** Budget $10.0000 (used $6.8040, 68 %), max turns 120 per session (used 46 and 38), model, tracker transport (`linear-graphql`), max attempts per loop (2), worktree path (`agent-hub/.claude/worktrees/agh-79-guard-bypass`), branch `roquettejh/agh-79-guard-bypass`. Each cap shows "used / limit" and turns `waiting` at 80 %, `failed` at 100 %. Cost totals add up exactly to the sum of session costs (row "Sessions: $2.3140 + $3.1240 + $1.3660 = $6.8040").

**PR and CI tab.** When a PR exists: number, title, state (open / merged / closed), head commit, CI checks list (name, status, duration, link), review rounds. Sample for LOK-311: PR tradeSentinel #214, checks `lint` passed 41 s, `unit` passed 2 min 10 s, `integration` running 3 min. For AGH-79: `EmptyState` "No PR. The run failed before the PR open stage."

### Data mapping

| Element | Entity.field (brief §3) | API resource | Source · latency |
|---|---|---|---|
| Title, issue link | WorkflowRun.issue | `GET /workflow-runs/{id}` → `issue.{key,title,url}` | executor + linear · 60 s |
| Outcome badge | WorkflowRun.state | `state`, `failed_stage`, `failed_reason` | executor · real time |
| Workflow, revision, hash | WorkflowRun.workflow name, revision, content hash | `workflow.{name,revision,hash}` | executor |
| Mode | live / dry-run | `dry_run` | executor |
| Cost vs budget | total cost, caps.budget | `cost_usd`, `caps.budget_usd` | otel · real time; late enrichment |
| Failure banner reason | FAILED(stage, reason) + failing gate result | `failed_reason`, `gate_results[]` (last failed) | executor |
| Diagnosis posted | tracker write of kind comment, by report step | `tracker_writes[]` where `kind=comment` and `step=report` | linear write ack · seconds |
| Failing moment link | session id + event id of the failing tool.result | `failure.moment.{session_id,event_id}` | derived by executor/collector |
| Pipeline nodes | steps keyed (step, attempt), status, duration | `steps[]` with `{step, attempt, status, started_at, ended_at}` | executor (step.start/step.end, proposed events) |
| Loop arrow + "attempt 2 of 2" | steps grouping + workflow on_fail cap | `steps[]`, `workflow.loops[].max_attempts` | executor |
| Gantt bars | Sessions in run | `sessions[]` with `{id, step, attempt, agent, parent_session_id, started_at, ended_at, cost_usd, turns}` | claude_code hooks · real time |
| Gate table + log | gate results | `gate_results[]` `{command, exit_code, duration_ms, log_excerpt, log_ref}` | executor |
| Tracker writes | label changes, comments | `tracker_writes[]` | executor + linear |
| Caps | caps (budget, max turns, model, transport) | `caps` | hub.json + executor |
| PR, CI checks | PR url, CI per commit | `pr.{number,url,state,checks[]}` | github · polling 60 s / webhook |
| Live updates | all of the above | `GET /workflow-runs/{id}/stream` (SSE) | real time |

### Interactions

- `Open failing moment` (Enter when the banner has focus): navigates to the session timeline with that event selected and highlighted; the browser Back returns to this run with the same tab and scroll.
- Pipeline: click a node or press Left / Right when focused to move between stages; Enter filters the Gantt.
- Gantt: horizontal scroll with Shift+wheel; `+` / `-` zoom; `0` fit; bars are focusable in reading order (lane by lane).
- `g r` returns to the Runs list. `Esc` clears the step filter.
- Copy buttons on commands and on the run id. The diagnosis comment has "Copy as Markdown".
- Deep link: `/runs/01923f1e?tab=gates&gate=verify-2` opens with the log expanded.

### States

| State | What shows | Exact copy |
|---|---|---|
| Loading | Header skeleton, pipeline skeleton (6 grey nodes), Gantt skeleton lanes | (no text) |
| Running (live) | Running node has a pulse dot; Gantt has a "now" line moving right; new bars fade in (`dur-base`); banner absent | Pipeline node label "Implementing · 38 min" |
| Waiting on a human gate | Pipeline shows a human gate node in `waiting`; header badge waiting | "Waiting for plan approval since 09:05 · see Approvals" |
| Failed | Failure banner as above | See banner copy |
| Reported (success) | All nodes done; banner replaced by a quiet `done-soft` line | "Reported at 17:43 · PR agent-hub #69 merged · 21/21 ACs passing" |
| Dry run | `idle` "Dry run" badge in header; Gantt shows planned bars hatched; no tracker writes performed | "Dry run: no commands executed and nothing written to Linear. Below is what a live run would do." |
| Partial: GitHub down | PR and CI tab: last known checks with `AsOfStamp` | "GitHub not reachable. CI as of 09:12." |
| Partial: session events missing | Gantt bar drawn from step timing only, hatched | "No session events for this step. The collector was offline from 23:02 to 23:09." |
| Late enrichment | Cost figure gets a small `ev-lifecycle` dot | "Cost updated after the run ended (+$0.0410 at 23:58)." |
| Not found | 404 page variant | "Run 01923f1e not found" / "It may belong to a hub that is no longer registered." |
| Error | `ProblemError` in the content area, header kept if loaded | e.g. "Could not load run" / "status 500 · Internal error reading steps" [Retry] |
| Stale | `AsOfStamp` in header; pulse dots off | "As of 14:02 · collector offline" |

### Actions by phase

| Action | Phase | Confirmation? | Consequence |
|---|---|---|---|
| Open failing moment, view logs, copy | P2 | No | Read only |
| Retry from verify | P4 | Yes, `ConfirmDialog` | `POST /workflow-runs/{id}/retry` `{"from_step":"verify"}`; creates a new attempt (attempt 3 is allowed only above the cap with explicit override, see below); spends budget |
| Retry from implement | P4 | Yes | Same, `from_step: "implement"` |
| Start run on an issue | P4 | Dry-run preview mandatory, then confirm "Run live" | `POST /workflow-runs` `{"issue":"AGH-112","workflow":"issue-to-pr","dry_run":true}`, then the same with `dry_run:false` |
| Cancel a running run | P4 | Yes | Ends sessions, writes `agent-failed` with reason "cancelled by owner" |

**Retry from verify (P4) dialog.**
- Title: "Retry AGH-79 from Verifying?"
- Body: "This runs `make check` again in the existing worktree `agh-79-guard-bypass` without new agent work. If it fails, the run fails again and a new diagnosis is posted to AGH-79. Budget left: $3.20."
- Checkbox (only when cap reached): "Allow attempt 3 of 2 (over the workflow's limit)". Unchecked by default; the primary button stays disabled until checked.
- Buttons: "Retry from verify" (primary), "Cancel".
- Why confirm: it spends money and writes to the tracker, which is not reversible.

**Start run on an issue (P4).** Opened from the Runs list header, Tracker queue rows and the command palette ("Start run on AGH-112").

```
+--------------------------------------------------------------------------------+
| Start run on an issue                                                      [x] |
| Issue   [AGH-112 Cap the tracker team list           v]  (agent-ready)         |
| Workflow[issue-to-pr · rev 4 (a3f9c21)               v]                        |
| Caps    budget $10.00 · max turns 120 · model from hub.json · transport linear |
|--------------------------------------------------------------------------------|
| DRY-RUN PREVIEW  (generated 09:02:11 · nothing has been executed)              |
| Commands, in order                                                             |
|  1 git -C agent-hub fetch origin                                               |
|  2 ./hub worktree agh-112-cap-tracker-teams --only agent-hub                   |
|  3 claude -p "/fix AGH-112" (session in the worktree, agent: main)             |
|  4 make check-fast            (gate, fast, on_fail -> step 3, max 2 attempts)  |
|  5 make check                 (gate, full)                                     |
|  6 git push -u origin roquettejh/agh-112-cap-tracker-teams                     |
|  7 gh pr create --base main --head roquettejh/agh-112-cap-tracker-teams        |
| Tracker writes, in order                                                       |
|  a remove label agent-ready from AGH-112                                       |
|  b comment "Picked by run <id> (issue-to-pr rev 4)."                           |
|  c on success: comment with PR link; state -> In Review                        |
|  d on failure: add label agent-failed; comment with diagnosis                  |
|--------------------------------------------------------------------------------|
|                                        [Cancel]  [Copy preview]  [Run live]    |
+--------------------------------------------------------------------------------+
```

- The preview comes from `POST /workflow-runs` with `dry_run: true`; it is the executor's own plan, not a client-side guess. Commands are mono, copyable; secrets never appear (tokens are `[redacted: env]`).
- "Run live" is disabled until the preview has loaded and for 1 s after (prevents a double-click skipping the read).
- Confirmation copy on "Run live": "Start a live run on AGH-112? It will execute the 7 commands above and write to Linear. Budget cap $10.00." Buttons "Run live" / "Back to preview".
- Result: navigate to the new run's detail (live). A `Toast` confirms: "Run started on AGH-112." (user's own action, so a toast is allowed).
- Errors: issue not labelled agent-ready → inline warning "AGH-112 is not labelled agent-ready. The run can still start; the label will not be removed." Issue already has an open run → "AGH-112 already has run 01923f9c in Implementing. Open it." and "Run live" disabled.

### UX principles applied

| Choice | Principle (brief §7) |
|---|---|
| Failure banner states stage, reason, diagnosis, and the one next step above the fold | Endsley comprehension; Nielsen "help users recognize, diagnose, recover from errors" |
| Pipeline with explicit loop arrow and "attempt 2 of 2" | Endsley projection (no attempts left); Gestalt continuity |
| Gantt shows gaps as well as bars | Tufte data-ink; makes waiting visible for "where does it get stuck" |
| Default sort puts failed and running first | Overview first (Shneiderman); F-pattern scanning |
| Dry-run preview lists every command and tracker write before "Run live" | Calibrated trust in automation (Lee & See); Parasuraman levels of automation: human approves the action set |
| Confirmation only for retry / run live / cancel (spend or write) | Optimistic UI only for reversible; avoids confirmation fatigue |
| Stage + icon + text, never color alone | WCAG 2.2 AA 1.4.1 |
| Costs 4 decimals in Caps and they add up exactly | Trust; Nielsen consistency |

### Responsive

- **1280×800:** sidebar collapsed (`sidebar-collapsed` 56 px); Run facts column moves into the Caps tab; pipeline labels shorten to stage name + duration; Gantt fits 1 h by default with horizontal scroll.
- **Runs list at 1280:** columns Workflow and Mode hidden by default (column chooser restores them); the filter rail collapses to a "Filters (2)" button that opens a `Popover`.
- **Mobile:** not a glance screen. A run linked from a phone shows a reduced read-only card: title, outcome, failure banner, pipeline as a vertical list. No Gantt.
