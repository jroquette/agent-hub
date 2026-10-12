# Live sessions

**Phase:** P2 (Pause and Cancel P4) · **Route:** `/live?group=repo|run|agent|flat&scope=` · **Answers:** "What are the agents doing right now, and does any of them need me?"

## Purpose and primary user

The control room. The **owner** glances at it (often on a phone) to see whether anything is waiting or going wrong; the **developer** keeps it open in a second window while their sessions run and jumps into a session with follow tail on (flow 2).

The screen is built on Endsley's three levels of situation awareness:

| Level | Question | What carries it on the tile |
|---|---|---|
| Perception | What is happening? | Status, last action in plain language, 60-s activity sparkline, elapsed |
| Comprehension | Is that normal? | Waiting reason, red edge for repeated failures, cost vs budget bar, turns compared with the run's usual ("46 turns · usual 30–60") |
| Projection | What happens next if nobody acts? | "At this rate, budget reached in ~6 min"; "Waiting 6 min · the run's human gate has no timeout" |

Sample state used below (2026-10-11 14:20 local, scope All projects): 4 live, 1 waiting, 1 idle, 1 just ended.

## Layout

### 1440 px, grouped by project › repo

```
┌──────────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│ Live sessions   4 running · 1 waiting                        Group [Project › repo|Run|Agent|Flat]   ● Connected │ page header
├──────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ WAITING FOR YOU                                                                                                   │
│ ┌─amber────────────────────────────────────────────────┐                                                         │
│ ▌‖ hub-workflow:planner        (Waiting · Plan approval)│                                                         │
│ ▌agent-hub · AGH-131 Doctor JSON output · Run › plan    │                                                         │
│ ▌Plan ready: 6 ACs, 3 files. Waiting 6 min             │                                                         │
│ ▌12 turns · 88 k tokens · $0.62 ▁▁▁▁▁▁▁▁ · Open approval│                                                         │
│ └──────────────────────────────────────────────────────┘                                                         │
├──────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ AGENT-HUB › agent-hub                                                                                    2 live   │
│ ┌──────────────────────────────────────────────────────┐ ┌──────────────────────────────────────────────────────┐│
│ │● main                                   (Live) 38 min │ │● hub-workflow:researcher               (Live) 4 min  ││
│ │agent-hub · AGH-112 Cap the tracker team list         │ │agent-hub · no run · branch roquettejh/agh-140-…     ││
│ │Run › implement · attempt 1                            │ │                                                      ││
│ │Editing packages/core/src/…/tracker/teams.py  9 s ago │ │Reading docs/design/doctor.md  3 s ago                ││
│ │└ Subagent spec-reviewer running                      │ │                                                      ││
│ │46 turns · 1.2 M tokens · 7 files · 0 errors          │ │6 turns · 140 k tokens · 0 files · 0 errors           ││
│ │$2.14 of $10.00 ▓▓░░░░░░░░             ▁▃▅▂▆▃▇▅▂▄▆▃ │ │$0.18 · no budget                    ▁▁▂▃▂▁▃▂▄▃▂▁ ││
│ └──────────────────────────────────────────────────────┘ └──────────────────────────────────────────────────────┘│
│ LOKI-TRADER › tradeSentinel                                                                              1 live   │
│ ┌red edge──────────────────────────────────────────────┐                                                         │
│ ▌● main                                   (Live) 52 min │                                                         │
│ ▌loki-trader · LOK-318 Retry policy for order sync      │                                                         │
│ ▌Run › implement · attempt 1                            │                                                         │
│ ▌Running make check-fast  21 s ago                      │                                                         │
│ ▌check-fast failed 2 times in a row                     │                                                         │
│ ▌71 turns · 2.9 M tokens · 12 files · 4 errors          │                                                         │
│ ▌$8.62 of $10.00 ▓▓▓▓▓▓▓▓▓░ amber  ▅▆▇▆▇▇▆▇▅▆▇▆    │                                                         │
│ ▌At this rate, budget reached in ~6 min                 │                                                         │
│ └──────────────────────────────────────────────────────┘                                                         │
│ LOKI-TRADER › loki-trader-ui                                                                             1 idle   │
│ ┌──────────────────────────────────────────────────────┐                                                         │
│ │◐ main                                   (Idle · 7 min)│                                                         │
│ │loki-trader-ui · no run                                │                                                         │
│ │Last: Edited src/components/OrderBook.tsx  7 min ago   │                                                         │
│ │19 turns · 410 k tokens · 3 files · 0 errors · $0.71   │                                                         │
│ └──────────────────────────────────────────────────────┘                                                         │
├──────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ ENDED IN THE LAST 2 MIN                                                                                           │
│ ┌ hub-workflow:evaluator · agent-hub · AGH-48 · Done · 1 h 10 min · $1.27 · ended 40 s ago ┐  (compact row tile)  │
└──────────────────────────────────────────────────────────────────────────────────────────────────────────────────┘
```

Grid: tiles in a CSS grid with `minmax(400px, 1fr)` columns, gap `space-4`; 3 columns at 1440 px with the sidebar expanded, 2 at 1280 px. Tile `radius-lg`, `surface`, `border`, padding `space-4`. Group headers `caption` uppercase-free sentence case in practice ("agent-hub › agent-hub"), shown in wireframe capitals only for legibility.

Order on the page (fixed, top to bottom):
1. "Waiting for you" group: every waiting tile, whatever the grouping, oldest wait first.
2. Groups by the chosen grouping, each sorted: tiles with a red edge first, then by budget projection (soonest first), then by start time (oldest first). Idle tiles go last within their group.
3. "Ended in the last 2 min" as compact single-line tiles, newest first; each disappears 2 min after its `ended_at` (fade out `dur-base`).

### Grouping toggle

`SegmentedControl` "Project › repo | Run | Agent | Flat" (`v` cycles), in `?group=`. Default project › repo; with scope set to one project the project level is dropped ("agent-hub" header becomes repo headers only).

| Grouping | Group header | Notes |
|---|---|---|
| Project › repo (default) | "agent-hub › agent-hub · 2 live" | Repos with no live session are not listed |
| Run | "Run AGH-112 Cap the tracker team list · implementing · $2.14 of $10.00" | Sessions not in a run under "Not in a run"; the run header carries the run budget bar once instead of per tile |
| Agent | "hub-workflow:researcher · 1" | Subagents appear as their own tiles only here (role is the question) |
| Flat | none | Sorted as rule 2 above |

### Subagents

In project/repo, run and flat groupings a subagent is a line inside its parent tile ("└ Subagent spec-reviewer running · 3 min"), not a separate tile: a parent and its subagent are one unit of work, and separate tiles would double the count and the visual noise. Several running subagents: "└ 2 subagents running: spec-reviewer, quality-reviewer". The top count "4 running" (live plus idle) counts parent sessions only; the tooltip adds "plus 1 subagent".

## Components

| Element | Component (variant) |
|---|---|
| Page header counts | `KpiStat` inline variant (no box) |
| Grouping | `SegmentedControl` |
| Tile | `SessionTile` (variants: live, waiting, idle, ended-compact; modifiers: error-edge, budget-warning) |
| Status | `StatusBadge` live (pulse dot), waiting, idle, done, failed, blocked |
| Issue, run | `IssueLink`, `StageChip` (step + attempt) |
| Last action path | `PathText` (middle-truncated) |
| Budget | `BudgetBar` (thin, 4px; amber at ≥ 80 %, red at ≥ 100 %) |
| Activity | `Sparkline` (60 bins of 1 s, bars) |
| Elapsed and ages | `Time` (relative, absolute tooltip) |
| Hover preview | `Popover` with 5 compact `TimelineEvent` rows |
| Tile menu (P4) | `IconButton` `ellipsis` → menu; `ConfirmDialog` |
| States | `Skeleton` (tile), `EmptyState`, `ProblemError`, `Banner`, `AsOfStamp` |

## Tile anatomy

Lines, top to bottom (each line has one job):

1. Role icon (`bot` for subagent roles, `terminal-square` for main) + agent id (`body-strong`) · status badge · elapsed ("38 min", `figure`).
2. Repo (or project · repo when grouping is not by repo) · `IssueLink` + issue title (truncated) · run link.
3. Run step and attempt: "Run › implement · attempt 1" (`StageChip`); absent when not in a run ("no run · branch roquettejh/agh-140-doctor-json").
4. Last action, plain language, with age: "Editing packages/core/src/…/tracker/teams.py · 9 s ago". Waiting tiles show the reason instead ("Plan ready: 6 ACs, 3 files. Waiting 6 min").
5. Optional notice line (only one, by priority): failing pattern ("check-fast failed 2 times in a row", `failed` text), guard ("Guard denied a push to main · 2 min ago", `guard` text with `shield-x`), subagent line.
6. Counters (`small`, `text-muted`, tabular): turns · tokens (compact "1.2 M") · files touched · errors.
7. `BudgetBar` with "$2.14 of $10.00" (or "$0.18 · no budget" without a bar), and the `Sparkline` right-aligned.
8. Projection line, only when it qualifies (see below): "At this rate, budget reached in ~6 min".

Last action phrasing (derived from the most recent `tool.call`; falls back to the last event type):

| Event | Phrase |
|---|---|
| Edit / Write | "Editing {path}" / "Writing {path}" |
| Read group | "Reading {n} files in {dir}" |
| Read | "Reading {path}" |
| Grep / Glob | "Searching for "{pattern}"" / "Listing {glob}" |
| Bash | "Running {command}" (command truncated to 48 chars, mono) |
| Agent | "Started subagent {name}" |
| WebFetch | "Fetching {host}" + `ExternalLabel` |
| MCP | "Calling {server}.{tool}" |
| message | "Writing a reply" |
| reasoning | "Reasoning" (never the content) |
| gate.request | "Waiting for {gate name}" |

Visual encoding rules:
- **Waiting:** 3px `waiting` left edge, `waiting-soft` header strip, `pause` icon; badge "Waiting · Plan approval" / "Waiting · Guard asks before editing docs/adr/". The tile's primary link is "Open approval" (to `/approvals/:id`), the tile body still opens the session.
- **Error edge:** 3px `failed` left edge, no fill change, no animation. Triggered by: the same gate or command failing 2 or more times in a row, or 3 or more tool errors in the last 5 minutes. The notice line says which.
- **Live pulse:** one `live` pulse dot in the badge (`dur-pulse`), never a pulsing tile; static dot under `prefers-reduced-motion`.
- **Idle:** `idle` badge with `moon` icon, counters in `text-subtle`, no sparkline (an empty sparkline reads as broken).
- **Budget bar:** `live` fill below 80 %, `waiting` fill 80–99 % with "of" text in `waiting`, `failed` fill at ≥ 100 % with text "$10.12 of $10.00 · over budget". Colour is never alone: the text states the amount, and at ≥ 80 % the projection line or "over budget" text appears.

## Budget projection

Shown on a tile (and the run group header) only when all hold: the session is in a run with `caps.budget_usd`; at least 3 minutes of cost data exist in the current window; the projected time is under 30 minutes. Otherwise the line is absent (no "never" or "∞").

Formula:

```
remaining      = run.caps.budget_usd − run.cost_usd                 (run-level, all sessions of the run)
burn_rate      = EWMA over the last 5 min of Δcost / Δt, per minute (α = 0.3 on 30-s buckets)
                 summed across the run's live sessions
minutes_left   = remaining / burn_rate
display        = "At this rate, budget reached in ~{round_display(minutes_left)}"
round_display  : < 1 min → "less than a minute"; 1–9 → whole minutes; 10–29 → nearest 5 min
```

Sample LOK-318: remaining $10.00 − $8.62 = $1.38; burn rate $0.23/min → 6.0 min → "At this rate, budget reached in ~6 min". Tooltip shows the inputs: "Run LOK-318 has spent $8.62 of $10.00. Spending $0.23 a minute over the last 5 min. Estimate, updated every 30 s." The API sends `burn_rate_usd_per_min`; the client computes `minutes_left` so it ticks without a new event.

Why EWMA over 5 min: a single expensive turn would otherwise swing the estimate wildly; 5 min matches the idle threshold so the window always has activity when shown. When the cost source is stale (otel > 2 min), the line becomes "Estimate paused · cost as of 14:18".

## Hover preview

Hover (500 ms delay) or keyboard focus + `Space` opens a `Popover` (`shadow-popover`, width 400px) with the last 5 events as compact `TimelineEvent` rows (icon, collapsed text, relative time), newest at the bottom, live-updating. Footer: "Open session · follow tail" and "Copy link". The popover never opens on touch (tap opens the session).

Sample for AGH-112:
```
▤ Read packages/core/src/agent_hub/core/tracker/teams.py          1 min ago
◌ Recorded reasoning summary  Cap at 20 teams; reject more with…   58 s ago
~ Edit packages/core/src/agent_hub/core/tracker/teams.py  +14 −3   41 s ago
▸ Bash uv run pytest tests/unit/test_tracker_teams.py  exit 0      22 s ago
~ Edit packages/core/src/agent_hub/core/tracker/teams.py  +2 −1      9 s ago
```

## Data mapping

| Element | Entity.field (brief §3) | API resource | Source · expected latency |
|---|---|---|---|
| Page counts (running, waiting) | count of Session.status | `GET /live-sessions?scope=`; stream `tile.upsert/remove` | hooks · < 1 s |
| Agent id, role icon | Session.agent | `GET /live-sessions` | hooks · < 1 s |
| Status badge, waiting reason | Session.status; open Gate.kind, Gate.name | `GET /live-sessions` (`status`, `waiting_reason`, `approval_id`) | hooks · < 1 s |
| Elapsed | now − Session.started_at (current segment) | `GET /live-sessions` | client clock |
| Project, repo | Session.project, repo | `GET /live-sessions` | hooks · < 1 s |
| Issue key and title | WorkflowRun.issue | `GET /live-sessions` (embedded) | executor · < 1 s; title linear ≤ 60 s |
| Run step, attempt | Session.step, attempt | `GET /live-sessions` | executor · < 1 s |
| Branch (no run) | session.start payload git branch | `GET /live-sessions` | hooks · < 1 s |
| Last action + age | last tool.call payload, Session.last_activity_at | `GET /live-sessions` (`last_action`, `last_activity_at`) | hooks · < 1 s |
| Notice line: failures | derived from gate.result / tool.result streaks | `GET /live-sessions` (`notice`) | hooks + executor · < 1 s |
| Notice line: guard | latest guard event in last 5 min | `GET /live-sessions` (`notice`) | hooks · < 1 s |
| Subagent line | child Sessions with status live | `GET /live-sessions` (`subagents[]`) | hooks · < 1 s |
| Turns | Session.turns | `GET /live-sessions` | transcript · 2–10 s |
| Tokens | Session.tokens (sum) | `GET /live-sessions` | otel · 1–5 s |
| Files touched, errors | Session.files_touched, errors | `GET /live-sessions` | hooks · < 1 s |
| Cost and budget bar | Session.cost_usd; WorkflowRun.cost_usd, caps.budget_usd | `GET /live-sessions` (`cost_usd`, `run_cost_usd`, `budget_usd`) | otel · 1–5 s |
| Projection | derived from run cost series | `GET /live-sessions` (`burn_rate_usd_per_min`) | otel · 30-s buckets |
| Usual turns range | p25–p75 turns of the same workflow step, last 30 d | `GET /live-sessions` (`turns_usual`) | derived nightly |
| Sparkline | events per second, last 60 s | `GET /live-sessions` (`sparkline_60s`), stream | hooks · < 1 s |
| Hover events | last 5 events | `GET /sessions/{id}/events?limit=5&order=desc` then `GET /sessions/{id}/events/stream` | per source |
| Ended group | Session.ended_at, outcome | stream `tile.upsert` with status ended; `tile.remove` after 2 min | hooks · < 1 s |
| Connection state | heartbeat | `GET /live-sessions/stream` heartbeat | 15 s |

The tile bar shows run cost against run budget (the cap is per run). Tile counters (turns, tokens) are the session's own. The run header in "Run" grouping repeats the run total once.

## SSE behaviour

- On load: `GET /live-sessions?scope=` renders tiles; then `GET /live-sessions/stream?scope=` with `Last-Event-ID` from the list response's `stream_cursor`, so nothing is missed between the two calls.
- `tile.upsert`: patch an existing tile in place (no re-layout unless its sort key changes) or insert a new tile with a fade-in (`dur-base`, fade + 4px slide, opacity only under reduced motion).
- Re-sorting is throttled: positions update at most every 10 s, and never while the pointer is over the grid or a tile has keyboard focus (a tile does not move under the user's hand). The waiting group is the exception: a tile entering Waiting moves up immediately, because that is the event the user is here for.
- `tile.remove` after 2 min in Ended: fade out; focus, if on that tile, moves to the next tile.
- Field updates (last action, counters, sparkline) do not animate; the age text ("9 s ago") ticks every second up to 60 s, then every 15 s.
- Heartbeat every 15 s. Connection state follows the shared rule (Connected ≤ 20 s, Delayed 20–60 s, Offline > 60 s). Delayed: page header shows "Delayed · updates may lag" next to the pill. Offline: tiles freeze, gain `AsOfStamp` "as of 14:18" in their header, sparklines grey out (`idle`), and the projection line is hidden.
- Scope change: close and reopen the stream with the new `scope`.
- Visibility: when the tab is hidden for more than 5 minutes the stream is closed and reopened on return with `Last-Event-ID` (saves the local collector work); counts are refreshed from the list endpoint if the server answers `reset`.

## Accessibility and announcements

- Grid semantics: `role="grid"` with each tile a `gridcell` containing a link; arrow keys move between tiles, `Enter` opens with follow tail, `Space` opens the hover preview, `Esc` closes it.
- Each tile's accessible name is one sentence: "main in agent-hub, AGH-112 Cap the tracker team list, live, editing teams.py 9 seconds ago, $2.14 of $10.00".
- One polite live region (`aria-live="polite"`, `aria-atomic="true"`) for the page. Announcements are rate-limited to one every 15 s and are digests, not per-event: "1 session waiting for approval: planner, AGH-131." · "Session ended: evaluator, AGH-48, done." · "LOK-318 budget warning: about 6 minutes left at this rate." Routine last-action changes are never announced. Same message within 2 min is not repeated.
- Waiting and red-edge states also have text (badge, notice line), never colour or edge alone. Targets ≥ 24×24 (menus and links in tiles use `control-sm`).

## Interactions

| Input | Result | URL |
|---|---|---|
| Click tile (anywhere outside links) / `Enter` | Open Session detail with follow tail | `/sessions/:id?follow=1` |
| Click "Open approval" on a waiting tile | Approval detail | `/approvals/:id` |
| Click issue | Tracker issue in new tab | external |
| Click run link | Run detail at current step | `/runs/:id?step=implement` |
| Click subagent line | Session detail with the subagent lane expanded and selected | `/sessions/:parentId?follow=1&lane=:childId` |
| Hover 500 ms / `Space` | Last 5 events popover | none |
| `v` / grouping control | Change grouping | `?group=` |
| Arrow keys | Move between tiles | none |
| Tile menu `⋯` (P4) | Pause, Cancel | none |
| Project switcher | Re-scope | `?scope=` |

## States

| State | What shows | Exact copy |
|---|---|---|
| Loading (> 300 ms) | 6 tile `Skeleton`s in the grid, group headers as skeleton bars | none |
| Empty (collector up, nothing running) | `EmptyState` centred, `display` headline | Headline "No session is running" · body "Sessions appear here when Claude Code starts in a hub with the collector on." · command `cd ~/agent-hub-hub && claude` (copy button) · link "See recent sessions" (`/sessions`) |
| Empty in scope only | `EmptyState` small | "Nothing running in loki-trader. 2 sessions are running in other projects." + "Show all projects" |
| Only ended in last 2 min | Ended group + small empty line above it | "No session is running. Recently ended:" |
| Partial: otel missing | Cost shows "cost pending", bar hidden, projection hidden | "Cost pending · otel not received" |
| Partial: transcript behind | Turns counter shows "—" with tooltip | "Turns update after each turn (transcript 3 min behind)" |
| Partial: tracker unreachable | Issue keys shown without titles | tooltip "Linear not reachable · titles as of 14:02" |
| Error (list fails) | `ProblemError` | title "Could not load live sessions" · detail from Problem Details · "Try again" |
| Live | Pulse badges, ticking ages | as wireframed |
| Delayed | Page header note | "Delayed · updates may lag (last update 42 s ago)" |
| Stale / offline | `Banner` (global) + per-tile `AsOfStamp`; sparklines greyed | "Collector offline since 14:18. Tiles show the last known state as of 14:18." |
| Waiting | Waiting group first | "Waiting · Plan approval" · "Waiting 6 min" |
| Idle | Idle badge | "Idle · 7 min" · "Last: Edited src/components/OrderBook.tsx 7 min ago" |
| Budget warning (≥ 80 %) | Amber bar + projection when it qualifies | "At this rate, budget reached in ~6 min" |
| Over budget | Red bar | "$10.12 of $10.00 · over budget" |
| Ended (2 min) | Compact tile in Ended group | "hub-workflow:evaluator · agent-hub · AGH-48 · Done · 1 h 10 min · $1.27 · ended 40 s ago" |
| Ended without end event | Tile moves to Ended with badge | "Ended · no end event (last activity 30 min ago)" |
| Many sessions (> 24) | Groups collapse to 6 tiles each with "Show 9 more in agent-hub" | "Show 9 more in agent-hub" |

## Actions by phase

| Action | Phase | Confirmation? | Consequence |
|---|---|---|---|
| Open session, approval, run, issue; change grouping; hover preview | P2 | No | Navigation only |
| Pause session | P4 | Yes · `ConfirmDialog` title "Pause this session?" · body "main in agent-hub (AGH-112) finishes its current tool call, then waits. Nothing is lost; resume it here or by typing in its terminal." · buttons "Pause session" / "Keep running" | Session status Waiting (paused); run stays IMPLEMENTING; tile moves to Waiting group with reason "Paused by you" |
| Resume session | P4 | No (reversible) | Status back to Live |
| Cancel session | P4 | Yes · destructive · title "Cancel this session?" · body "The agent stops after its current tool call. Uncommitted changes stay in the worktree agh-112-tracker-teams. Run AGH-112 is marked failed at implementing, and the issue gets the agent-failed label." · buttons "Cancel session" (`failed` fill) / "Keep running" (default focus) | Session ends outcome stopped; run FAILED(IMPLEMENTING, "cancelled by owner"); tracker write logged |

In P2 the tile menu shows only "Open session", "Open run", "Copy link"; no disabled placeholders for future actions.

## UX principles applied

| Choice | Principle (brief §7) |
|---|---|
| Waiting tiles first, amber edge and plain reason | Endsley perception; pre-attentive processing (colour + position + text) |
| Last action in plain language, not event type | Comprehension; match between system and the real world (Nielsen #2) |
| Budget projection "~6 min", only when under 30 min | Endsley projection; alarm fatigue (no projection noise when far away) |
| "Usual 30–60 turns" comparison | Show deviation from normal (Endsley comprehension) |
| Red edge only for repeated failure; no flashing; one pulse dot | Alarm fatigue (Sendelbach and Funk); WCAG 2.3 flashes; calibrated trust |
| Subagents as a line in the parent tile | Gestalt common region; working memory (fewer chunks) |
| Re-sort throttled and frozen under the pointer | Fitts (targets don't move); user control (Nielsen #3) |
| Hover shows last 5 events | Shneiderman details on demand; working memory ~4 chunks (Cowan) |
| Ended tiles stay 2 min | Visibility of system status; continuity so ends are not missed |
| Polite, rate-limited digests; no toasts | WCAG 4.1.3; alarm fatigue |
| Cancel confirmation states worktree, run and label consequences | Error prevention (Nielsen #5); human decides (principle 2) |

## Responsive

- **1280×800:** 2 tile columns; sidebar collapsed; grouping control becomes a `Popover` "Group: Project › repo ▾"; sparkline width 80px; tiles keep all 8 lines.
- **Mobile glance (< 640 px):** one column; tiles reduced to 4 lines: agent + status + elapsed; issue; last action; cost bar with "$2.14 of $10.00" and projection when present. Waiting group pinned on top with a sticky header "1 waiting for you". No hover preview; long-press opens the tile menu (P4 actions still confirm). Page header shows counts and the collector dot only. Grouping fixed to flat with waiting first.

```
┌──────────────────────────────────┐
│ Live · 4 running · 1 waiting  ●  │
├──────────────────────────────────┤
│ 1 WAITING FOR YOU                │
│ ▌planner (Waiting · Plan)  6 min │
│ ▌AGH-131 Doctor JSON output      │
│ ▌[ Open approval ]               │
├──────────────────────────────────┤
│ ▌main (Live)            52 min   │ red edge
│ ▌LOK-318 Retry policy for order… │
│ ▌Running make check-fast · 21 s  │
│ ▌$8.62 / $10.00 ▓▓▓▓▓▓▓▓▓░       │
│ ▌Budget reached in ~6 min        │
├──────────────────────────────────┤
│ │main (Live)            38 min   │
│ │AGH-112 Cap the tracker team li…│
│ │Editing …/tracker/teams.py · 9 s│
│ │$2.14 / $10.00 ▓▓░░░░░░░░       │
└──────────────────────────────────┘
```
