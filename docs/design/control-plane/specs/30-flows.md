# Prototype flows

The eight flows of the brief (§6), step by step. Each table gives the screen and its state, what the user does (mouse and keyboard), how the system responds, the data or API call behind it, and the time budget (perceived latency target, not user think time unless stated).

**Clickable in the "Prototype" page of this design system:** flows 1, 2, 3 and 8. **Specified only:** flows 4, 5, 6 and 7 (their screens exist as static frames; P3/P4 actions are drawn but not wired).

Time budgets follow the response time limits: 0.1 s for direct manipulation (hover, focus, toggles), 1 s for navigation within loaded data, skeletons after 300 ms, 10 s ceiling with progress for anything longer.

---

## Flow 1 · Morning check (target: under 30 s end to end) · Clickable

Persona: owner. Goal: "anything stuck or failing? what needs me?" then find why AGH-79 failed.

| Step | Screen + state | User action (mouse / keyboard) | System response | Data / API call | Time budget |
|---|---|---|---|---|---|
| 1 | Portfolio, scope All projects, period 7 d, live | Opens app (`g p`) | Needs-you strip shows 2 items: "Approve plan for AGH-48 · 3 h", "Run failed: AGH-79 Guard bypass at Verifying · 2 h". KPI "Cost this week $84.20 (+18 %)". | `GET /needs-you?scope=all`, `GET /projects`, `GET /activity?scope=all&period=7d`, `GET /events/stream` | First paint < 1 s; skeletons if > 300 ms |
| 2 | Portfolio | Reads the strip (user ~5 s) | — | — | User: 5 s |
| 3 | Portfolio | Clicks "Run failed: AGH-79…" (or `j` to item 2, Enter) | Navigates to Run detail | `GET /workflow-runs/01923f1e` | < 1 s |
| 4 | Run detail AGH-79, failed | Scans pipeline | `StagePipeline`: Picked (done), Worktree (done), Implementing (done), Verifying (failed) "attempt 2 of 2" with loop arrow. Failure banner: "Failed at Verifying. make check exited 2: 3 failing tests in test_guard.py. Diagnosis posted to AGH-79." Button "Go to failing moment". | same | User: 6 s |
| 5 | Run detail | Clicks "Go to failing moment" (`f`) | Opens Session detail of the attempt-2 implement/verify session, timeline scrolled to the Bash `make check` event, highlighted `accent-soft`, test output summary expanded | `GET /sessions/{id}`, `GET /sessions/{id}/events?cursor=…&around={event_id}` | < 1 s |
| 6 | Session detail, timeline, event selected | Reads "3 failed: test_deny_push_main_alias, test_force_push_short_flag, test_bash_subcommand_match" (exit code 2 chip) | — | — | User: 6 s |
| 7 | Session detail | Clicks `IssueLink` AGH-79 in the header | Opens the Linear issue in a new tab (diagnosis comment visible) | external `https://linear.app/…/AGH-79` | < 1 s (tab) |

Total target: < 30 s (about 4 s system, ~20 s reading). Deep links: `/workflow-runs/01923f1e`, `/sessions/{id}?event={event_id}`.

---

## Flow 2 · Follow live · Clickable

Persona: developer following AGH-112.

| Step | Screen + state | User action | System response | Data / API call | Time budget |
|---|---|---|---|---|---|
| 1 | Live sessions, grouped by project › repo, live | `g l` | Tiles stream in; tile "main · implementing AGH-112 · Editing packages/core/…/tracker_teams.py · 46 turns · $2.14 of $10" with `BudgetBar` at 21 % | `GET /live-sessions?scope=all`, `GET /live-sessions/stream` | < 1 s; SSE events fade in `dur-base` |
| 2 | Live sessions | Hovers tile | `Popover` with last 5 events | from stream buffer | < 0.1 s |
| 3 | Live sessions | Clicks tile (Enter) | Session detail, Timeline, follow-tail on (toggle shows "Following"); header `StatusBadge` live | `GET /sessions/{id}`, `GET /sessions/{id}/events/stream` | < 1 s |
| 4 | Session detail, live | Watches | New events append at bottom; when user scrolls up, pill "12 new events ↓" | SSE | Event to screen < 1 s after hook |
| 5 | Session detail | — | An `Agent` tool call starts subagent `hub-workflow:spec-reviewer`: a nested `SubagentLane` appears indented `space-5`, collapsed with its live dot | SSE `session.start` (child) | < 1 s |
| 6 | Session detail | Clicks lane header to expand | Lane shows the subagent's events inline; "Open as session" link | `GET /sessions/{child}/events` | < 1 s |
| 7 | Session detail | — | Guard event: shield marker row `guard` "Push to main denied · git push origin main" and a marker on the `Minimap` | SSE `tool.result` (denied by guard) | < 1 s |
| 8 | Session detail | — | `session.end` (outcome done): header badge to done, follow-tail stops, polite live region "Session ended: done" | SSE | < 1 s |
| 9 | Session detail | — | Summary card fades in labelled "Summary · generated after the session", 4 lines each linking to a moment | `GET /sessions/{id}/summary` (polled until ready) | Ready within 30 s; skeleton "Writing summary…" until then |

---

## Flow 3 · Audit a decision · Clickable

Persona: auditor.

| Step | Screen + state | User action | System response | Data / API call | Time budget |
|---|---|---|---|---|---|
| 1 | Any screen | `Ctrl K`, types "brain_memory_rule.py" | `CommandPalette` groups results: Files (packages/core/…/brain_memory_rule.py), Sessions (3 touched it) | `GET /search?q=brain_memory_rule.py` | Results < 300 ms per keystroke (debounce 120 ms) |
| 2 | Palette | Enter on the file | File view: path, sessions that touched it (table: session, agent, issue, date, +/−) | `GET /sessions?touched_file=…` | < 1 s |
| 3 | File view | Clicks session 5091b986 (AGH-48 implement) | Session detail opens on Files & diffs with the file selected | `GET /sessions/{id}/files/diff?path=…` | < 1 s |
| 4 | Session detail | Clicks "Decisions" tab (`4`) | List of decisions; top: "Use line match, not git's matcher" `DerivedLabel` "Decision · extracted from transcript" confidence 0.86 | `GET /sessions/{id}/decisions` (P3) | < 1 s |
| 5 | Decisions tab | Expands it | Alternatives struck through: "~~Use git check-ignore~~", "~~Parse .gitignore with pathspec~~"; rationale "git's matcher needs a repo and differs on negations; a line match is what doctor checks"; evidence links | same | < 0.1 s |
| 6 | Decisions tab | Clicks "Jump to moment" | Timeline tab at the reasoning summary event (italic, "Recorded reasoning summary") | `GET /sessions/{id}/events?around=` | < 1 s |
| 7 | Timeline | Clicks "Context" tab (`5`) | Layered context: instruction files, brain notes read (incl. `brain/decisions/D7.md`), skills; personal memory "present, private" | `GET /sessions/{id}/context` (P3) | < 1 s |

---

## Flow 4 · Triage learnings (P3) · Specified only

| Step | Screen + state | User action | System response | Data / API call | Time budget |
|---|---|---|---|---|---|
| 1 | Portfolio | Clicks Needs-you item "15 learnings to triage" | Knowledge › Learnings, Proposed (15), first selected | `GET /learnings?status=proposed` | < 1 s |
| 2 | Learnings | `j` / `k` through items | Detail updates | `GET /learnings/{id}` | < 0.3 s per item (prefetch next 2) |
| 3 | Learnings | `r` on "Retry flaky CI…" (agent-from-external), picks "Not true for this project" (`2`), Enter | Row collapses, next selected | P3 `POST /learnings/{id}/reject` | Optimistic < 0.1 s |
| 4 | Learnings | `s` on two items | Snoozed 7 days | P3 `POST /learnings/{id}/snooze` | < 0.1 s optimistic |
| 5 | Learnings | On "Flaky: bench stderr test gets a stray quote", target shows `brain/learnings/gotchas/testing.md`; `a` | Row "Accepting…"; then Accepted with `StatusBadge` "accepted, PR pending"; `Toast` "Accepted. PR #142 opened…" [Undo] | P3 `POST /learnings/{id}/accept` | Optimistic < 0.1 s; PR confirmed < 6 s |
| 6 | Learnings › Accepted | Opens the item's "Trace" | Provenance trace: 5 nodes; nodes 4–5 dashed ("PR #142 open · not merged") | `GET /learnings/{id}/trace` | < 1 s |
| 7 | Trace (after merge, days later) | Opens again | Node 5 "loaded in 9 sessions since 2026-10-03"; effect small multiples with n and caveats | same + `GET /metrics/learning-effect` | < 2 s |

---

## Flow 5 · Approve plan (P4) · Specified only

| Step | Screen + state | User action | System response | Data / API call | Time budget |
|---|---|---|---|---|---|
| 1 | Approvals (badge 1) | `g a` | List: "Plan approval · AGH-48 Layered memory · requested by hub-workflow:planner · 3 h" | `GET /approvals?scope=all` | < 1 s |
| 2 | Approvals | Selects it | `ApprovalPanel`: rendered plan, `AcTable` (21 ACs), "What changes if I approve: the run moves from human gate to implement; budget $10.00; repo agent-hub" | `GET /approvals/{id}` | < 1 s |
| 3 | Approval panel | Clicks "Approve plan" | Opens `ConfirmDialog` (approving starts agents and spends budget, so it is confirmed): "Approve plan for AGH-48? The run starts implementing now and can spend up to $10.00." | — | < 0.1 s |
| 4 | Dialog | Confirms | Panel shows "Approved by José Henrique Roquette · now"; item leaves list; badge 0 | P4 `POST /approvals/{id}/decision` `{"decision":"approve"}` | < 1 s |
| 5 | Run detail (link) | Clicks "Open run" | Pipeline: human gate done, Implementing live with pulse; new session tile in Live | `GET /workflow-runs/{id}/stream` | Stage change visible < 2 s |

Note: approving a plan starts spending, so it is confirmed; "Request changes" requires a comment and is not confirmed (reversible).

---

## Flow 6 · Where stuck (P4) · Specified only

| Step | Screen + state | User action | System response | Data / API call | Time budget |
|---|---|---|---|---|---|
| 1 | Workflows catalog | Clicks issue-to-pr | Workflow detail, graph | `GET /workflows/issue-to-pr` | < 1 s |
| 2 | Workflow detail | Clicks "Where it gets stuck" (`o`) | Overlay: verify node red "38 % failed (10 of 26)", thick on_fail edge "16" | `GET /workflows/issue-to-pr/stats?period=30d` | < 1 s |
| 3 | Overlay | Clicks "View 10 runs" on verify | Workflow runs list filtered `failed_step=verify` | `GET /workflow-runs?workflow=issue-to-pr&failed_step=verify` | < 1 s |
| 4 | Runs list | Clicks "Compare in Metrics" | Metrics › "Where do runs fail?" filtered to issue-to-pr | `GET /metrics/failure-stage?workflow=issue-to-pr&period=30d` | < 1 s |
| 5 | Metrics | Card menu › "Copy evidence for an issue" | Clipboard: chart question, period, n, top reasons, run links (no transcript content); then "Open Linear" link to new issue in team AGH | client | < 0.1 s |

---

## Flow 7 · Investigate cost · Specified only

The all-projects week is $84.20 (+18 %). The loki-trader card shows "+60 % vs last week", which starts this flow.

| Step | Screen + state | User action | System response | Data / API call | Time budget |
|---|---|---|---|---|---|
| 1 | Portfolio | Hovers loki-trader cost delta "+60 %" | `Tooltip`: "$31.40 this week vs $19.60 last week (7 d)" | from `GET /projects` | < 0.1 s |
| 2 | Portfolio | Clicks the delta | Metrics › Cost, scope loki-trader, "What does a run cost, by ticket size?" | `GET /metrics/cost-per-run?scope=loki-trader&group_by=size` | < 1 s |
| 3 | Metrics | Clicks outlier dot "LOK-298 $14.62" | Run detail LOK-298, budget bar red "$14.62 of $10.00 · budget reached at Implementing" | `GET /workflow-runs/{id}` | < 1 s |
| 4 | Run detail | Clicks the implement session in the Gantt | Session detail | `GET /sessions/{id}` | < 1 s |
| 5 | Session detail | Clicks "Cost" tab (`6`) | Stacked area over turns; cost per subagent table: `hub-workflow:spec-reviewer` 40 turns, $9.12, flagged "Loop: same tool call repeated 31 times" (`DerivedLabel`) | `GET /sessions/{id}/cost` | < 1 s |
| 6 | Cost tab | Clicks the subagent row | Timeline jumps to the subagent lane, repeated `Bash pytest tests/ws` calls grouped "Ran the same command 31 times" | `GET /sessions/{id}/events?around=` | < 1 s |

---

## Flow 8 · First run · Clickable

| Step | Screen + state | User action | System response | Data / API call | Time budget |
|---|---|---|---|---|---|
| 1 | First run (no hubs), `display` headline "Set up agent-hub" | Opens app | 3-step checklist; step 1 active: "Register your hub" with path field and copyable command `hub app add-hub ~/code/agent-hub-hub` (proposed CLI) | `GET /hubs` (empty) | < 1 s |
| 2 | Checklist step 1 | Pastes path, Enter | Validates: "Found hub.json for agent-hub · platform 0.8.0" → check turns green (`done`) | P2 `POST /hubs` `{"path":"~/code/agent-hub-hub"}` | < 1 s |
| 3 | Step 2 "Start the collector" | Copies `hub collector start`, runs in terminal | Live check: "Waiting for the collector…" → "Collector connected" green | `GET /events/stream` heartbeat | Detects within 3 s of start |
| 4 | Step 3 "Start a Claude Code session in the hub" | Copies `cd ~/code/agent-hub-hub && claude`, runs it | "Waiting for the first event…" → "First event received from session 5091b986" green; button "Open Portfolio" enabled | `GET /events/stream` | Detects within 2 s of first hook |
| 5 | Portfolio with one project | Clicks "Open Portfolio" | Portfolio: one project card agent-hub; Needs-you "Nothing needs you. 1 session running." | `GET /projects`, `GET /needs-you` | < 1 s |

Skipping: each step has "I did this already" which re-runs the live check; the checklist is reachable later from Settings › Hubs.
