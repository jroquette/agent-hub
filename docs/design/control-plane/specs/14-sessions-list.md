# Sessions list

**Phase:** P2 (compare view P3) · **Route:** `/sessions?view=grid|table&within=repo|run|workflow` (filters below) ·
**Decision:** [ADR 0033](../../../adr/0033-sessions-and-chat-interaction-model.md) (one screen; replaces
[11-live-sessions.md](11-live-sessions.md), retired) · **Answers:** "Which sessions happened, and which one do I need to look at?"

## Purpose and primary user

The historical index of every Session (one Claude Code session = one execution of an agent) across the projects in scope. Primary users:

- **Developer:** "find the session that edited `brain_memory_rule.py` last Tuesday", "find the session that broke CI".
- **Auditor:** filters by "had a guard denial" or "has decisions" to reconstruct what happened.
- **Owner:** sorts by cost to spot outliers.

It is a dense, fast table, not a dashboard: overview (counts per facet) → zoom and filter (rail) → details on demand (hover preview, then Session detail).

## One screen, two views, status sections (ADR 0033)

Sessions is the only sessions screen: the sidebar's Sessions entry carries the live badge, and `/live` redirects here
(see [01-navigation.md](01-navigation.md)). It shows both kinds of session: **observed** ones (hook-fed, open
`/sessions/:id`) and **driven** ones (started by `hub web`, open the chat at `/agent-sessions/:id`).

```
Sessions                    [Grid | Table]  [Views ▾] [Columns] [24 h|7 d|30 d|Custom]  [New session]
[chips…]
▾ Waiting · 1          tiles or table, oldest wait first
▾ Live · 4             within=repo|run|workflow sub-groups (grid)
▸ Idle · 2             (collapsed)
▾ Ended or failed · ~1,233   period applies here only            [Load more]
▸ Cloud sessions       (collapsed details: `claude --cloud` / `--teleport` guidance)
```

- **View.** `view=grid|table` in the URL (header `SegmentedControl` or `v`); stored in `ah.sessions.view`; the URL wins
  over the stored value; with neither, the grid. Unknown values fall back to the default.
- **Sections**, in this order: Waiting (`waiting`; driven `waiting_permission`), Live (`live`; driven `running`), Idle,
  Ended or failed (`ended`, `outcome=error` in red text; driven `ended`, `failed`). Troubled sessions
  (`needs_you > 0`) keep their section and get the red edge (`data-trouble`). Each section is its own
  `GET /sessions?status=` query (50 per page, "Load more" by cursor) and its header count is that query's
  `total_estimate` plus the section's driven sessions without an observed twin. A header button with `aria-expanded` collapses it; the collapsed set persists in
  `ah.sessions.collapsed`. Empty sections are hidden; when all are empty, one empty state shows.
- **Grid view.** Each session is a `SessionTile` (waiting reason, last action, problems, stats, sparkline while not
  ended; fields from `GET /sessions`). `within=repo|run|workflow` sub-groups the tiles inside each section.
- **Table view.** Each section is its own table with the chosen columns and density; sort applies within a section;
  a section over 100 rows is virtualised.
- **Filters.** Chips, saved views and the column picker apply to both views (columns to the table only). A status
  facet value shows only that section; "Live now" shows only Live. The period filters the Ended section only, so a
  running session older than the period still shows.
- **Driven sessions.** A driven session with an observed twin shows once, as the twin, with a "Chat" badge, and opens
  the chat. One without a twin (`observed_session_id` null) shows in its section with the fields it has. "New session"
  sits in the page header; the 401, 404 `agent-sessions-off` and 503 banners stay. There is no separate "Driven from
  hub web" list. Cloud guidance is a collapsed "Cloud sessions" details below the sections.
- **Open.** Every tile and row has a visible primary button: "Open" (observed), "Open chat" (driven), "Answer" when
  waiting (the chat or Approvals). The title is a real `<a href>`. No "…" button.
- **Keys.** `j` / `k` move across tiles and rows of every section with a visible focus ring; `Enter` or `o` opens;
  `v` toggles the view.
- **Live updates.** Sections refetch on the live-tile stream at most once per 2 s (and on the driven-list poll). The
  first visible row keeps its scroll offset; a focused row keeps focus when it moves to another section. A polite
  digest is announced at most every 15 s; offline shows `AsOfStamp`.

The rest of this file describes the table view; the tile anatomy is in [11-live-sessions.md](11-live-sessions.md).

## Layout (1440 px)

```
+--------+-----------------------------------------------------------------------------------------------------+
|Sidebar | TopBar: [All projects v]  [Search or jump to... Ctrl K]   (o Connected · last event 3 s ago) [UTC|Local]|
+--------+-----------------------------------------------------------------------------------------------------+
|        | Sessions                                      [Views: Default v] [Columns] [24 h|7 d|30 d|Custom]    |
|        | Showing 50 of ~1,240 · 7 d · 2 projects            Selected 2: [Compare (P3)] [Clear]               |
|        +-------------------+-----------------------------------------------------------------------------------+
|        | FILTER RAIL 264px | [x] Started v   Dur.    Project    Repo        Agent              Issue/run      |
|        | [Filter facets..] |                 Outcome  Turns  Tokens   Cost    Files Err Dec  Transcript      |
|        |                   |-----------------------------------------------------------------------------------|
|        | Project           | [ ] 11 Oct 09:03 38 min  agent-hub  agent-hub   main               AGH-112·01923f9c|
|        |  [x] agent-hub 812|                 (o) live  46   1.92 M   $2.14   9     0   1   available        |
|        |  [ ] loki-trader 428| [ ] 11 Oct 07:20 52 min loki-trader tradeSentinel main           LOK-311·01923e77|
|        | Repo              |                 done      61   2.40 M   $3.95   14    1   0   expires in 29 d  |
|        | Agent             | [x] 10 Oct 23:29 17 min  agent-hub  agent-hub   main               AGH-79·01923f1e |
|        | Outcome           |                 error     38   1.21 M   $3.12   6     3   2   expires in 29 d  |
|        |  done        1,051| [x] 10 Oct 22:43 24 min  agent-hub  agent-hub   main               AGH-79·01923f1e |
|        |  stopped/blocked 63|                done      46   0.98 M   $2.31   5     0   1   expires in 29 d  |
|        |  error          48| [ ] 08 Oct 17:02 21 min  agent-hub  agent-hub   hub-workflow:evaluator AGH-48·01922b10|
|        |  live            3|                 done      33   0.71 M   $1.27   4     0   1   expires in 27 d  |
|        | Workflow          |  ...  (virtualized: only visible rows + 10 overscan rendered)                   |
|        | Date range        |                                                                                 |
|        | Cost range [..-..]|                                                                                 |
|        | Touched file [..] |                                                                                 |
|        | Used tool         |                                                                                 |
|        | [ ] Had a guard denial  91                                                                          |
|        | [ ] Has decisions      402                                                                          |
|        | [Clear all]       |                [Load more]     Showing 50 of ~1,240                              |
+--------+-------------------+---------------------------------------------------------------------------------+
```

The table uses single-line rows at the 1440 width when all default columns fit (the two-line drawing above is for legibility only). Default visible columns at 1440 px: Started, Duration, Project, Repo, Agent, Issue / run, Outcome, Turns, Tokens, Cost, Files, Errors, Decisions, Transcript (14 columns, compact density). The project column is hidden automatically when the scope is one project.

## Components

| Component | Variant / notes |
|---|---|
| `AppShell`, `Sidebar` ("Sessions" selected), `TopBar`, `ProjectSwitcher`, `CollectorPill` | Standard |
| `SavedViewMenu` | Built-in views (read-only) + user views (stored locally in v1, see below) |
| `Popover` (column chooser) | Checklist of columns, drag handles to reorder, "Reset to default" |
| `SegmentedControl` | Period; drives the "Date range" facet |
| `FilterRail` | 264 px, collapsible to 0 with `[` key; facet search box at top |
| `FilterChip` | Applied filters also shown as removable chips above the table when the rail is collapsed |
| `DataTable` | Virtualized, sticky header (`z-sticky`), compact density (`row-compact` 32 px), checkbox column, sortable headers with `aria-sort` |
| `Time` | Absolute in table ("11 Oct 09:03"), relative in tooltip ("3 h ago") |
| `IdChip` | Session id (`5091b986`) appears in the row's hover preview and the first column tooltip; run id chip in Issue / run |
| `IssueLink` | `AGH-112` (out to tracker) |
| `StatusBadge` | Outcome: live, done, blocked (stopped/blocked), failed (error), ended (other Claude Code end reasons, label = reason) |
| `Money` | 2 decimals in the table, 4 in tooltip |
| `PathText` | In the touched-file facet suggestions |
| `Popover` (row preview) | Mini timeline preview, see Interactions |
| `Minimap` | Reused horizontally (variant `strip`) inside the row preview |
| `Button` | "Load more" (secondary), "Compare" (P3, primary when exactly 2 selected) |
| `Skeleton`, `EmptyState`, `ProblemError`, `Banner`, `AsOfStamp` | States |

## Columns

| Column | Content and format | Align | Sortable | Default |
|---|---|---|---|---|
| Select | checkbox, 24×24 target | center | no | on |
| Started | absolute local/UTC per toggle, `figure` | left | yes (default desc) | on |
| Duration | "1 h 12 min", "38 min", "47 s"; live rows tick | right | yes | on |
| Project | name | left | yes | on (auto-hidden in single-project scope) |
| Repo | dir name | left | yes | on |
| Agent | `plugin:name` mono-sm, or "main" for the implementing session | left | yes | on |
| Issue / run | `IssueLink` + run `IdChip` + step·attempt ("verify #2") on hover | left | yes (by issue key) | on |
| Outcome | `StatusBadge` | left | yes | on |
| Turns | integer, thousands separators | right | yes | on |
| Tokens | total in/out/cache, compact "1.92 M"; tooltip shows in / out / cache read / cache write exact | right | yes | on |
| Cost | `$2.14`; tooltip `$2.1388`; late-updated cost shows a dot | right | yes | on |
| Files | files touched (edited + created + deleted; reads excluded) | right | yes | on |
| Errors | tool errors + guard denials count; `failed` text when > 0 | right | yes | on |
| Decisions | count (P2 shows recorded `/decide` ones; P3 adds extracted) | right | yes | on |
| Transcript | "available" / "expires in 12 d" (`waiting` text when <= 7 d) / "expired 2026-09-30" (`idle`) | left | yes (by expiry) | on |
| Session id | `IdChip` | left | no | off |
| Model | e.g. "claude-opus-4" | left | yes | off |
| Workflow · step | `issue-to-pr@4 · implement #1` | left | yes | off |
| Ended | absolute | left | yes | off |
| Guard denials | count with shield icon | right | yes | off |
| PR | `#69` link | left | no | off |
| Resumed | "3 segments" when the session was resumed | right | yes | off |

Transcript retention column (privacy principle): it tells the user before they click whether the raw content can still be read. Structured events and the summary remain after expiry, so the row stays clickable; the column only states what level of detail remains.

## Data mapping

| Element | Entity.field (brief §3) | API resource | Source · latency |
|---|---|---|---|
| Row set | Session (derived) | `GET /sessions?project=&repo=&agent=&outcome=&workflow=&from=&to=&cost_min=&cost_max=&file=&tool=&guard_denial=&has_decisions=&sort=&cursor=&limit=50` → `items`, `next_cursor`, `total_estimate` | collector DB · < 300 ms target |
| Started / Ended | Session.start, end | `items[].started_at`, `ended_at` | claude_code hooks · real time |
| Duration | end − start, minus nothing (wall clock) | derived client-side from the two fields | derived |
| Project, Repo | Session.project, repo | `items[].project`, `repo` | hooks |
| Agent | Session.agent | `items[].agent` | hooks / transcript |
| Issue / run | Session.workflow/step; WorkflowRun.issue | `items[].run.{id,issue_key,step,attempt}` | executor |
| Outcome | Session.status, outcome | `items[].status`, `items[].outcome` | hooks (session.end) |
| Turns | count of turns | `items[].turns` | transcript · after each turn |
| Tokens | tokens input/output/cache | `items[].tokens.{input,output,cache_read,cache_write}` | otel · real time |
| Cost | cost USD exact decimals | `items[].cost_usd` (string decimal) | otel; late enrichment flag `cost_updated_after_end` |
| Files | files touched | `items[].files_touched_count` | hooks (tool.call Edit/Write) |
| Errors | errors | `items[].error_count`, `items[].guard_denial_count` | hooks (tool.result error / denied) |
| Decisions | decisions | `items[].decision_count` | transcript (recorded) / P3 extraction |
| Transcript | transcript ref + deletion date | `items[].transcript.{status,expires_at}` | collector retention policy |
| "Showing 50 of ~1,240" | count | `total_estimate` (approximate, from the query planner; "~" always shown unless exact flag) | DB |
| Facet counts | aggregates over current filters minus the facet itself | `GET /sessions?…&facets=project,repo,agent,outcome,workflow,tool,guard_denial,has_decisions` → `facets` | DB · may arrive after rows |
| Row hover preview | last events + density | `GET /sessions/{id}/events?types=tool.call,tool.result,decision,gate.request,gate.result&limit=5` + `items[].density` (60 buckets, included in the list payload) | DB |
| Live rows | status changes | `GET /events/stream` (global SSE, `session.*` events for rows on screen) | real time |
| Saved views | user preference | browser local storage in v1 (per viewer); see Open question | local |

## Interactions

**Sorting.** Click a header to sort desc, again for asc, third click clears to the default (Started desc). Shift+click adds a secondary sort (shown as "1", "2" superscripts). Sort is server-side; cursor resets.

**Pagination.** Cursor-based. 50 rows per page. "Load more" appends the next 50 (`cursor=next_cursor`); the label updates "Showing 100 of ~1,240". No infinite scroll: an explicit button keeps the footer reachable and the count honest. When the end is reached: "Showing all 1,238". `~` is dropped once the count is exact.

**Faceted filter rail.**
- Each facet shows values with counts in the current filter context (counts exclude the facet's own selection, so you see alternatives).
- Multi-select inside a facet = OR; across facets = AND. The rail header shows "3 filters" and "Clear all".
- Facets with more than 6 values show the top 6 and "Show 14 more" with a search box.
- Range facets: date range (calendar popover, presets), cost range (two inputs, `$` prefix, histogram behind the slider).
- Touched file: autocomplete over paths (`PathText`), supports a glob (`packages/core/**/guard*.py`). Used tool: chips Read, Edit, Write, Bash, Grep, Glob, Agent, WebFetch, MCP (plus MCP server names).
- Boolean facets: "Had a guard denial", "Has decisions".
- Every filter is in the URL: `/sessions?scope=agent-hub&outcome=error&file=packages/core/src/agent_hub/core/guard.py&guard_denial=1`.

**Saved views.** `SavedViewMenu` lists built-in views first:
- "Default" (all, 7 d)
- "Live now" (status=live)
- "Errors this week" (outcome=error, 7 d)
- "Guard denials" (guard_denial=1, 30 d)
- "Expensive sessions" (sort=cost desc, 30 d)

Not built: a "Transcript expiring soon" view and "Save current view…" (user-saved views are out of scope for ADR 0033). As designed, "Save current view…" asks for a name (max 40 chars), saves filters, columns, order, sort, density. Views are per viewer (local, single-user app in v1); they survive reloads. "Copy link to view" copies the URL, which carries the full state, so views are shareable without a server.

**Column chooser.** `Popover` with checkboxes and drag handles; "Reset to default". Choices persist with the view.

**Row hover mini timeline preview.** After 400 ms of hover (or focus + Space), a `Popover` (`shadow-popover`, 420 px wide) anchored to the row shows:

```
+-----------------------------------------------------------------+
| 9b0d1f37 · main · AGH-79 implement #2           error · 17 min  |
| [|||| ||| |  ||||| x |||  |||| x  || x |]  <- density strip     |
|  22:43                                     23:00                |
| Last 5 events                                                   |
|  23:00:12  Bash  make check-fast        exit 2   (failed)       |
|  22:59:40  Edit  packages/core/.../guard.py   +6 -2             |
|  22:58:03  Read  packages/core/tests/unit/test_guard.py         |
|  22:57:51  Decision  Keep the alias check in the guard          |
|  22:55:10  Bash  uv run pytest -k guard   exit 1                |
| Enter to open · Space to close                                  |
+-----------------------------------------------------------------+
```

The strip uses `Minimap` colors (`ev-tool`, `ev-decision`, `failed` markers, `guard` markers). No content of messages or reasoning appears in the preview (privacy: metadata only). Moving the pointer into the popover keeps it open; leaving both closes it after 150 ms.

**Row click.** Opens Session detail (`/sessions/{id}`), Timeline tab. Cmd/Ctrl-click opens a new tab. Clicking the issue link or run chip goes to that entity instead.

**Multi-select.** Checkbox per row; Shift+click selects a range; `x` toggles the focused row. Selection count shows in the header: "Selected 2". With exactly 2 selected, "Compare" becomes active (P3). With 3+, Compare is disabled with tooltip "Compare works on 2 sessions. Deselect 1." Selection persists across "Load more" but clears on filter change (with a polite live-region note "Selection cleared because filters changed").

**Keyboard.** `j` / `k` row focus (across sections), Enter or `o` open, `x` select, `/` focus the rail search, `[` toggle rail, `c` column chooser, `v` grid / table, `g s` comes here from anywhere (`g l` opens the grid).

## Compare two sessions (P3, brief)

**Route:** `/sessions/compare?a={id}&b={id}`. Purpose: "Why did the second attempt behave differently?" or "Did the new rule change behaviour?" Typical pair: AGH-79 Implement #1 (7c2e41a0) vs Implement #2 (9b0d1f37).

```
+-----------------------------------------------------------------------------------------+
| Compare sessions        A 7c2e41a0 (implement #1)    vs    B 9b0d1f37 (implement #2)    |
|  Duration 24 min | 17 min (-7 min)   Turns 46 | 38    Cost $2.31 | $3.12 (+$0.81)       |
|  Errors 0 | 3    Files 5 | 6         Decisions 1 | 2   Guard denials 0 | 0               |
|-----------------------------------------------------------------------------------------|
| Aligned timelines (by turn)        A                         B                          |
|  turn 1-6   Read 8 files ...                     Read 3 files (diagnosis given)         |
|  turn 7     Edit guard.py +12 -4                 Edit guard.py +6 -2                    |
|  ...                                                                                    |
| Files: only in A (1) · only in B (2) · both (4) -> per-file diff A vs B                 |
| Context differences (P3): B read brain/learnings/gotchas/testing.md (not read in A)     |
+-----------------------------------------------------------------------------------------+
```

Header deltas (B − A), timelines aligned by turn number with a toggle to wall clock, file set comparison, context differences. Deltas use neutral `text` with sign; no green/red judgement on cost or duration (difference is not quality). Out of scope: comparing more than 2, any per-person comparison.

## States

| State | What shows | Exact copy |
|---|---|---|
| Loading (>300 ms) | 12 `Skeleton` rows keeping column widths; facet counts show `Skeleton` pills | (none) |
| Facet counts slow | Rows render first; counts fill in when ready (no layout shift: counts are right-aligned in a reserved 48 px slot) | (none) |
| Empty, never any session | `EmptyState` (display style headline) | "No sessions yet." / "Sessions appear when Claude Code runs in a registered hub with the collector on. Start one in the hub directory: `cd ~/code/agent-hub-hub && claude`." [Open setup checklist] |
| Empty, filters | Inline row | "No sessions match these filters." [Clear filters] [Widen to 30 d] |
| Partial: otel down | Tokens and Cost cells `--`, header tooltip | `Banner` info: "Token and cost data unavailable since 08:40 (OpenTelemetry receiver not reporting). Sessions and events are current." |
| Partial: transcripts not yet ingested | Turns cell shows "…" for live/just-ended rows | Tooltip: "Turns are counted after each turn's transcript arrives." |
| Error | `ProblemError` replaces the table, rail stays | e.g. "Could not load sessions" / "Filter `cost_min` must be a decimal (status 400)." [Retry] [Clear filters] |
| Live | Live rows show a pulse dot in Outcome and ticking duration; a session moves to its new status section on the next refetch (≤ 1 per 2 s) without moving the reader's scroll position or focus | (none) |
| Stale | `AsOfStamp` next to the title; pulse dots stop | "As of 14:02 · collector offline" |
| Transcript expired row | Transcript column "expired 2026-09-30" (`idle`); row still clickable | Tooltip: "Raw content expired. Summary and structured events remain." |
| Redacted values | Never shown in this table (metadata only) | n/a |

## Actions by phase

| Action | Phase | Confirmation? | Consequence |
|---|---|---|---|
| Filter, sort, choose columns, paginate | P2 | No | URL updates |
| Save / rename / delete a view | P2 | Delete: no (undo `Toast` "View deleted · Undo" for 6 s) | Local only |
| Copy link to view | P2 | No | Clipboard |
| Export visible rows as CSV | P2 | No | Downloads metadata only (no content); filename `sessions-2026-10-11.csv` |
| Compare 2 sessions | P3 | No | Opens compare view |
| Pause / cancel a live session | P4 | Yes | Available from Session detail and the chat, not from this list (keeps the list a read surface) |

## UX principles applied

| Choice | Principle (brief §7) |
|---|---|
| Facets with counts in the current context | Shneiderman (zoom and filter); information scent (Pirolli & Card) |
| "Load more" + "Showing 50 of ~1,240" instead of infinite scroll | Nielsen visibility of system status; keeps the footer reachable (Fitts) |
| New live sessions announced by a pill, never inserted under the cursor | Avoids disorientation; alarm fatigue (no toast) |
| Hover preview with metadata only, after 400 ms | Progressive disclosure; privacy first |
| Transcript retention column | Privacy first; sets expectations before navigation |
| Numbers right-aligned, tabular, compact units with exact tooltips | Tufte data-ink; legibility |
| Default 14 columns, the rest in the chooser | Cognitive load (Sweller); Hick-Hyman |
| No per-person column or filter | Principle 6, metrics about the process |
| Status as icon + text in Outcome | WCAG 1.4.1 (not color alone) |

## Responsive

- **1280×800:** sidebar collapsed; rail collapsed by default to a "Filters" button with applied `FilterChip`s above the table; default columns drop to Started, Duration, Repo, Agent, Issue / run, Outcome, Cost, Errors, Transcript (others in the chooser). About 17 rows visible at compact density.
- **1920:** rail open, comfortable density allowed; all default columns plus Model.
- **Mobile:** not a glance screen. The route renders a simple list (started, agent, outcome, cost) with no filters except outcome and period, and a note "Open on a larger screen for filters and comparison."

## Open question

Saved views are per viewer and local in v1 (single-user, local-first). Recommendation: keep local, rely on URL sharing. Alternative: store in `GET/PATCH /settings` under `saved_views`, so they survive a browser reset; adopt when multi-device use appears.
