# Session detail

**Phase:** P2 (Decisions and Context tabs P3; no actions before P4, tagged inline) · **Route:** `/sessions/:id?tab=timeline&event=:eventId&types=&q=&errors=1&follow=1&axis=time|turn&lane=:subSessionId` · **Answers:** "What did this agent do, in what order, and why?"

The flagship screen. It is where every other screen's "why" link lands: the failing moment of a run, a guard denial on a live tile, a decision in the log, a file in the palette. It must let a person reconstruct a session of 38 turns in under a minute and a session of 5,000 events without losing their place.

Sample used throughout: session `5091b986` (full id `01929a40-5091-7b98-8a6e-3f20c1d4a7b2`), agent `hub-workflow:evaluator`, project agent-hub, repo agent-hub, run AGH-48 Layered memory, step `evaluate` attempt 1 of 1, started 2026-10-09 14:02:07, ended 15:12:19 (1 h 10 min), outcome done, model `claude-opus-4-1`, 38 turns, tokens 412,330 in / 38,904 out / 2,104,551 cache read / 118,200 cache write, cost $1.2734, PR agent-hub #69, transcript available until 2026-11-10. One subagent session: `9c4e12aa` `hub-workflow:quality-reviewer`.

## Purpose and primary user

- **Developer** auditing why the agent edited a file, or finding the Bash call that broke CI (flow 1 lands here at the failing call).
- **Owner** following a session live (flow 2) and checking guard behaviour and cost.
- **Auditor** reconstructing a decision: context, alternatives, who approved (flow 3 uses the Decisions and Context tabs).

The screen shows only what the record shows (principle 3): reasoning is the recorded summary and says so; the summary card and extracted decisions are labelled derived; redacted values are markers, never partial values.

## Layout

Regions, top to bottom: `Breadcrumbs`; sticky session header (`z-sticky`, gains `shadow-sm` and `border-strong` bottom edge once content scrolls under it); summary card; `Tabs`; tab body. In the Timeline tab the body is three columns: filter rail (collapsible), trace, `Minimap` (width token `minimap` 56px). The event inspector is not a side panel by default: events expand in place, so reading order is preserved. A side inspector (`size.panel` 480px) opens only for Raw JSON of very large payloads (> 200 lines).

### Timeline tab at 1440 px

```
┌──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│ Portfolio › agent-hub › Run AGH-48 › Session 5091b986                                                                  │
├──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ [bot] hub-workflow:evaluator   (Done)   agent-hub · AGH-48 Layered memory ↗ · Run AGH-48 › evaluate · attempt 1 of 1  │
│ 2026-10-09 14:02 → 15:12 · 1 h 10 min · claude-opus-4-1 · 38 turns · 412,330 in · 38,904 out · 2.22 M cache · $1.2734│
│ PR #69 merged ↗ · Transcript available until 2026-11-10 · 1 segment                     [Copy link] [5091b986 ⧉]   │
├──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ Summary · derived, generated after the session                                                          [Collapse ^] │
│ 1 Verified 20 of 21 ACs; AC-48.21 stays passes:false as a manual owner step.                         → 15:04:51     │
│ 2 make check-fast passed in 3 min 12 s.                                                               → 14:03:02     │
│ 3 quality-reviewer subagent found no blocking issues (2 nits).                                        → 14:06:25     │
│ 4 Wrote eval.md with verdict SHIP-WITH-OWNER-STEPS (+64 lines).                                       → 15:08:40     │
│ 5 Guard denied a push to main; the branch roquettejh/agh-48-layered-memory was pushed instead.        → 15:10:02     │
├──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ Timeline 142 · Files and diffs 23 · Decisions 1 · Context · Cost $1.2734 · Raw events 311                              │
├───────────────┬───────────────────────────────────────────────────────────────────────────────────────────────┬──────┤
│ FILTERS   [«] │ [⌕ Search in session  Ctrl F]  [Errors and decisions only ○]  Axis [Time|Turn]  [Expand all]  │ ▮▮▮▮ │
│ Type          │───────────────────────────────────────────────────────────────────────────────────────────────│ ▮▮   │
│ [x] Prompts   2 │ Turn 1                                                                         14:02:07       │ ▮▮▮▮ │
│ [x] Messages 19 │ ▷ Session started · hub-workflow:evaluator in agent-hub · claude-opus-4-1      14:02:07       │ ▮▮▮  │
│ [x] Reasoning 14│ ● Prompt  Evaluate feature layered-memory (AGH-48) against spec.md and fea…   14:02:07       │ ◆ ── │
│ [x] Tools    88 │ ◌ Recorded reasoning summary  Start from features.json to see which ACs cl…   14:02:15       │ ▮▮▮▮ │
│ [x] Gates     3 │ Turn 2                                                                                         │ ▮▮▮▮ │
│ [x] Decisions 1 │ ▤ Read  brain/features/layered-memory/features.json                  ok        14:02:18       │ ▮▮   │
│ [x] Learnings 1 │ ▤ Read 12 files in packages/core/src/agent_hub/core/memory/   ▸     ok        14:02:20       │ ◈ ── │
│ [x] Guard     2 │ Turn 3                                                                                         │ ▮▮▮  │
│ [x] Lifecycle 2 │ ▸ Bash  make check-fast                          exit 0 · 3 min 12 s  ok       14:03:02       │ ▮▮▮▮ │
│ Tool          │ ▾ Subagent  hub-workflow:quality-reviewer · 9c4e12aa · 14 turns · $0.3120      14:06:25       │ ▮▮   │
│ [x] Read     41 │ ┊  ▤ Read 8 files in packages/core/src/agent_hub/core/memory/        ok        14:06:31       │ ▮▮▮▮ │
│ [x] Bash      7 │ ┊  ⌕ Grep  "brain/auto/workspace" in packages/          4 matches   ok         14:07:02       │ ▮▮▮  │
│ [x] Edit      3 │ ┊  ▭ Agent message  No blocking issues. Two nits: rename _LINE_RE; add…       14:11:48       │ ▮▮   │
│ Lane          │ ┊  ▷ Subagent ended · done                                                    14:11:50       │ ▮▮▮▮ │
│ [x] Main        │ ◆ Decision  AC-48.21 stays passes:false (manual owner step)  Extracted from…  15:04:51       │ ▮▮   │
│ [x] quality-r.. │ ~ Edit  brain/features/layered-memory/eval.md                  +64 −0  ok      15:08:40       │ ▮▮▮  │
│               │ ◈ Guard asks  Edit under docs/adr/ needs approval  · declined in terminal       15:09:12       │ ▮▮   │
│ [Reset]       │ ◈ Denied by guard  Push to main denied  · git push origin main                 15:10:02       │ ◈ ── │
│               │ ▸ Bash  git push origin roquettejh/agh-48-layered-memory   exit 0  ok          15:10:09       │ ▮▮▮▮ │
│               │ + Learning proposed  Two-PR features: compare render impact per merge          15:11:30       │ ▮▮   │
│               │ □ Session ended · done · end_turn                                              15:12:19       │ 15:12│
└───────────────┴───────────────────────────────────────────────────────────────────────────────────────────────┴──────┘
   filter rail 200          trace (fluid, max line length ~110 ch)                                           minimap 56
```

Symbols in wireframes stand for Lucide icons listed in the mapping table (`play`, `user`, `brain`, `file-text`, `terminal`, `bot`, `git-commit-vertical`, `file-pen`, `shield-alert`, `shield-x`, `lightbulb`, `square`).

### Timeline tab at 1280×800 (laptop)

```
┌──┬───────────────────────────────────────────────────────────────────────────────────────────────────────┐
│≡ │ Portfolio › … › Session 5091b986                                                                      │
│  ├───────────────────────────────────────────────────────────────────────────────────────────────────────┤
│◉ │ [bot] hub-workflow:evaluator (Done) · AGH-48 ↗ · Run › evaluate 1/1 · 1 h 10 min · 38 turns · $1.2734  │
│≡ │ 14:02 → 15:12 · PR #69 merged ↗ · Transcript until 2026-11-10                     [More ▾] [⧉]        │
│⇶ ├───────────────────────────────────────────────────────────────────────────────────────────────────────┤
│  │ Summary · derived  Verified 20 of 21 ACs; AC-48.21 stays false as an owner step.  [Show 4 more ▾]    │
│◫ ├───────────────────────────────────────────────────────────────────────────────────────────────────────┤
│! │ Timeline 142 · Files 23 · Decisions 1 · Context · Cost · Raw 311                                      │
│  ├───────────────────────────────────────────────────────────────────────────────────────────────┬───────┤
│⌗ │ [Filters ▾ 0] [⌕ Search  Ctrl F] [Errors and decisions only ○] [Time|Turn]                    │ ▮▮▮▮  │
│  │ ▤ Read  brain/features/layered-memory/features.json                         ok  14:02:18     │ ▮▮    │
│o │ ▤ Read 12 files in packages/core/src/…/memory/  ▸                           ok  14:02:20     │ ◆ ──  │
│  │ ▸ Bash  make check-fast                         exit 0 · 3 min 12 s         ok  14:03:02     │ ▮▮▮   │
│* │ ▸ Subagent  hub-workflow:quality-reviewer · 14 turns · $0.3120                  14:06:25     │ ◈ ──  │
│  │ ◆ Decision  AC-48.21 stays passes:false (manual owner step)                     15:04:51     │ ▮▮    │
│  │ ~ Edit  brain/features/layered-memory/eval.md               +64 −0          ok  15:08:40     │ 15:12 │
└──┴───────────────────────────────────────────────────────────────────────────────────────────────┴───────┘
 56 (sidebar collapsed)                                                                        minimap 56
```

At 1280×800: sidebar collapsed (token `sidebar-collapsed`); filter rail becomes a `Popover` behind "Filters" with an active-count; header compresses to two lines with secondary fields (model, tokens split, segments) in "More"; summary card collapses to its first line with "Show 4 more"; rows switch to compact density (`row-compact` 32px) by default. About 17 rows are visible above the fold.

### Mobile glance header (< 640 px)

Only the header and summary are designed for mobile (glance); the timeline renders as a read-only list without minimap or filter rail.

```
┌────────────────────────────────────┐
│ ‹ Sessions          ● Connected    │
├────────────────────────────────────┤
│ hub-workflow:evaluator             │
│ (Done)  AGH-48 Layered memory ↗    │
│ 1 h 10 min · 38 turns · $1.27      │
│ Run AGH-48 › evaluate · 1 of 1     │
│ ◈ 2 guard events · 0 errors        │
├────────────────────────────────────┤
│ Summary · derived                  │
│ Verified 20 of 21 ACs; AC-48.21    │
│ stays false as an owner step.      │
│ make check-fast passed (3 min 12 s)│
│ [Show 3 more]                      │
├────────────────────────────────────┤
│ [ Open timeline ]                  │
└────────────────────────────────────┘
```

Live variant replaces "(Done)" with "(Live) · last action 12 s ago" and adds one line "Running make check-fast" under the agent; waiting adds an amber row "Waiting · Plan approval · 6 min" linking to `/approvals/:id`.

## Components

- Header: `Breadcrumbs`, `Icon`, `StatusBadge` (live, waiting, idle, done, failed, blocked, ended), `IssueLink`, `StageChip`, `Time`, `Money`, `IdChip`, `IconButton`, `ExpiredContent` (inline).
- Summary and tabs: card with `DerivedLabel`; `Tabs` with counts.
- Timeline: `FilterRail`, `FilterChip`, `SegmentedControl`, `TimelineEvent` (one variant per type, see `02-data-and-api.md`), `ToolGroup`, `SubagentLane`, `DiffViewer` (inline unified), `CodeBlock`, `RedactionChip`, `DerivedLabel`, `ProvenanceBadge`, `ExternalLabel`, `JsonViewer`, `Minimap`, `Button` (follow toggle, new events pill).
- Other tabs: `FileTree`, `DiffViewer` (split/unified), `StackedArea`, `BarChart`, `KpiStat`, `DataTable`, `Markdown`.
- States: `Skeleton`, `EmptyState`, `ProblemError`, `Banner`, `AsOfStamp`, `ConfirmDialog` (P4).

## Header

Order follows the reading question "who did what for which work, how did it end, what did it cost":

1. Role icon + agent id (`body-strong`), status badge, repo, issue link (opens Linear in a new tab, `external-link` icon), run link "Run AGH-48 › evaluate · attempt 1 of 1" (opens `/runs/:runId?step=evaluate&attempt=1`).
2. Start → end (absolute, `Time`, local/UTC per toggle), duration "1 h 10 min", model, turns, tokens "412,330 in · 38,904 out · 2.22 M cache" (tooltip splits cache read 2,104,551 and cache write 118,200), cost `$1.2734`.
3. PR link "PR #69 merged" with state colour (`done` merged, `live` open, `failed` closed), transcript retention, segments indicator.

Retention line variants:
- "Transcript available until 2026-11-10" (`text-muted`).
- "Transcript expires in 3 days (2026-11-10)" (`waiting` text) when ≤ 7 days.
- "Transcript expired on 2026-11-10 · summary and structured events remain" (`idle` on `idle-soft`, icon `clock`).

Segments indicator: "1 segment" hidden when 1. With resumed segments: "3 segments · resumed twice" as a `Popover` listing each segment's start, end and end reason, each linking to its `session.start` event.

Status badge copy: "Live", "Waiting · Plan approval", "Idle · 7 min", "Done", "Stopped", "Blocked", "Error", "Ended · no end event". Outcome tooltip carries the raw Claude Code `end_reason` ("end_turn").

## Summary card

- Title "Summary · derived" with `DerivedLabel` tooltip: "Generated after the session from its events by the collector. It may miss nuance; each line links to the moment it describes."
- 3–5 lines, each a link: clicking scrolls the timeline to `event_id`, selects and expands it, and sets `?event=` (replace).
- Appears only after `session.end` (or when the session goes idle for 30 min). While live: the card is replaced by a one-line "Summary appears when the session ends" in `text-subtle`, so no derived content pretends to be current.
- Collapsible; state remembered per browser (`ah.session.summaryCollapsed`).

## Timeline tab

### Row anatomy

`TimelineEvent` row, height `row-comfortable` 40px (or `row-compact` 32px), grid: 4px type bar in the event colour token · 16px icon · label (`caption`, `text-muted`) · collapsed text (`body`, mono for paths and commands) · status chip · time (`figure` style, `text-subtle`, right-aligned) · hover actions (`link` copy link, `copy` copy id, `braces` Raw). Hover actions are always in the DOM and reachable by keyboard; they show on hover/focus (never invisible to assistive tech).

Turn separators: "Turn 14" headers (`caption`, `text-subtle`) with sticky behaviour inside the trace so the reader always knows the turn. On the turn axis the time column shows "T14 · +31 min".

Selected event: `accent-soft` ground and a 2px `accent` left bar; it is the event in `?event=`.

### Type rendering (sample rows)

| Type | Collapsed row (sample) | Expanded |
|---|---|---|
| Session start | "Session started · hub-workflow:evaluator in agent-hub · claude-opus-4-1" | cwd `/home/jr/agent-hub/.claude/worktrees/agh-48-layered-memory`, branch, permission mode "default", session brief 2.1 k tokens |
| Prompt | "Evaluate feature layered-memory (AGH-48) against spec.md and features.json. Write eval.md with a verdict." | full text in `Markdown` |
| Agent message | "check-fast passes. Handing quality review to the quality-reviewer subagent before writing eval.md." | full text |
| Reasoning | italic "Start from features.json to see which ACs claim to pass, then verify each claim against its verification command." with caption "Recorded reasoning summary" | full summary; never labelled "thinking" |
| Read | "Read `brain/features/layered-memory/features.json`" · "ok" | path, 214 lines, 6.8 KB, read range "all" |
| Read group | "Read 12 files in `packages/core/src/agent_hub/core/memory/`" | list of 12 `PathText` rows each with its own permalink |
| Bash | "`make check-fast`" · chip "exit 0 · 3 min 12 s" | `CodeBlock` command; output excerpt: last 40 lines ("412 passed, 3 skipped in 188.21s"); "Show full output" when transcript available |
| Edit | "Edit `brain/features/layered-memory/eval.md`" · "+64 −0" (`diff-add`/`diff-del`) | inline `DiffViewer` unified, 3 lines of context, first 80 lines then "Show 120 more lines" |
| Subagent | "Subagent hub-workflow:quality-reviewer · 9c4e12aa · 14 turns · $0.3120" | nested lane |
| Decision | "AC-48.21 stays passes:false (manual owner step)" + `DerivedLabel` "Extracted from transcript" | choice; alternatives struck through ("Mark AC-48.21 passing because the doc exists"); rationale "The AC requires the owner to confirm the memory rule in their own setup; no command can verify it."; evidence links (features.json event, spec.md Read); P3 link "Open in Decisions" |
| Learning proposed | "Two-PR features: compare render impact per merge" · target `brain/learnings/` · `ProvenanceBadge` agent | text, target path, status "proposed", P3 link "Triage in Learnings" |
| Gate request/result | "Gate check-fast requested · `make check-fast`" then "passed · exit 0 · 3 min 12 s" (merged into one row via `parent_event_id` when both exist) | log excerpt, requester |
| Session end | "Session ended · done · end_turn" | totals at end |

### Collapsing rules (progressive disclosure)

1. Consecutive `Read`, `Glob` and `Grep` calls in the same turn and lane with no other event between them collapse into one `ToolGroup`: "Read 12 files in `{longest common directory}`" (if no common directory: "Read 12 files in 4 folders"). Mixed: "Read 9 files, searched 3 times in `packages/core/`". A group with an error never hides it: the error is pulled out as its own row under the group.
2. A `tool.result` merges into its `tool.call` row as the status chip; a separate row appears only for errors and guard denials.
3. Bash always shows command and exit code; output is collapsed.
4. Edit shows +/− collapsed; diff on expand. `Write` of a new file shows "Write `{path}` · new file · 48 lines".
5. Messages and reasoning truncate to one line (ellipsis), full on expand.
6. "Expand all" expands rows in the visible window only (not 5,000 rows); "Collapse all" restores defaults.

### Subagent lanes

- A `tool.call` of tool `Agent` creates a `SubagentLane`: indented by `space-5` (20px) per nesting level, with a 1px dashed `border-strong` guide line on the left (the "┊" in wireframes), header row showing subagent id, short id, turns, cost and outcome.
- Collapsed by default when the session has ended; expanded by default while it is live (so flow 2 sees the lane appear). The lane's expansion state goes into `?lane=` when a single lane is focused.
- Inside the lane, events render with the same rules. Nested lanes indent again (max visual depth 3; deeper levels show "Nested 2 more levels · Open as own session").
- Header actions: "Expand in place" (chevron) and "Open as own session" (`square-arrow-out-up-right`, navigates to `/sessions/9c4e12aa…`, breadcrumbs then show the parent).
- Parallel subagents (two Agent calls in one turn) render as sibling lanes in start-time order; their events are not interleaved with each other inside the trace (each lane is contiguous), and the minimap shows both.
- Cost and turns in the lane header are the subagent's own; the session header total includes them (stated in the cost tooltip: "Includes 1 subagent: $0.3120").

### Guard and hook markers

Guard events are a distinct family: `guard` colour on `guard-soft` ground, `shield-*` icons, a full-width row (not a chip), and a matching minimap marker. They are never coloured as errors: a denial is the system working.

| Event | Row copy | Icon | Expanded detail | Sample session |
|---|---|---|---|---|
| Push to main denied | "Denied by guard · Push to main denied" + mono "`git push origin main`" | `shield-x` | "Rule: no push to main (hub-workflow guard, PreToolUse). The command was not run." · link "Guard settings in hub.json" | 5091b986, 15:10:02 |
| Force-push blocked | "Denied by guard · Force-push blocked" + "`git push --force-with-lease`" | `shield-x` | same, rule "no force-push" | AGH-79 implementer session |
| Ask before editing | "Guard asks · Edit under docs/adr/ needs approval" + path `docs/adr/0009-layered-memory.md` | `shield-alert` | status "approved in terminal at 15:09:40" / "declined in terminal" / "waiting" (then the session status is Waiting) | 5091b986, 15:09:12 (declined) |
| Stop blocked | "Stop blocked · check_fast failing for changed code" + "`make check-fast` exit 2" | `shield-off` | failing tests summary "3 failed in tests/unit/test_guard.py", changed files list, link to the Bash row that produced it | AGH-79 implementer session `e1b07c33`, 11:42:18 |

Filter chip "Guard" (with count) and the header counter "2 guard events" both link to these rows.

### Minimap and scrubber

- Right column, width `minimap` 56px, `surface-sunken` track, full height of the viewport below the tabs.
- Density strip: the session is divided into N bins (one per pixel row); each bin's fill is the dominant type's colour token (`ev-tool`, `ev-message`, `ev-reasoning`…), opacity by event count (log scale). Decorative fill; markers carry meaning.
- Markers (8px glyphs with 16px hit area, aligned to the left edge, `radius-sm`): errors `failed` × (`circle-x`), decisions `ev-decision` diamond, gates `ev-gate` flag, guard events `guard` shield, subagent start `bot` dot. Markers never rely on colour alone: each has its own shape.
- Viewport indicator: a translucent `accent` outline box showing the visible range; drag it to scroll.
- Click anywhere: jump to that time (or turn). Click a marker: jump to and select its event. Hover: `Tooltip` "15:10:02 · Denied by guard · Push to main denied".
- Axis labels at top and bottom: start and end time ("14:02", "15:12"); with axis = turn: "T1", "T38". Idle gaps over 2 min render as a hatched band labelled in the tooltip ("Idle 6 min").
- Keyboard: the minimap is a `slider` (`aria-valuetext` "14:41, turn 19 of 38"); `↑`/`↓` move by one turn, `Page Up`/`Page Down` by 10 %.

### Time axis

`SegmentedControl` "Time | Turn" (`a`). Time: wall-clock `HH:MM:SS` in the row time column, gaps over 2 min shown as a divider "6 min later". Turn: "T14" in the column and relative offset "+31 min" in the tooltip. Persisted in `?axis=`.

### Filters and search

- Filter rail facets: Type (with counts), Tool (Read, Edit, Write, Bash, Grep, Glob, Agent, WebFetch, MCP servers by name), Lane (Main, each subagent), Status (ok, error, denied). Counts reflect the whole session, not the filtered view.
- "Errors and decisions only" toggle (`errors=1`): shows errors, guard events, decisions, gate results and the session start/end for orientation. Hidden rows leave a thin "38 events hidden" divider that expands on click, so the reader never loses the sense of distance.
- Search in session (`/` or `Ctrl F` / `⌘F`): matches collapsed text, paths, commands and, when the transcript is available, message and output content (server-side, `GET /sessions/{id}/events?q=`). Shows "3 of 17" with `n` / `Shift N`. Matches highlight in `accent-soft`; matches inside collapsed groups expand their group. Redacted values are never matched (searching a secret does not reveal its existence).
- Filters go into the URL (`types=`, `tool=`, `lane=`, `q=`, `errors=1`) and survive reload.

### Live mode

Applies while status is live, waiting or idle.

- Header status "Live" with the pulse dot (`dur-pulse`; static under reduced motion), and "last action 12 s ago" updating every second.
- Follow tail `Button` (toggle, `f`), on by default when arriving from Live sessions (`?follow=1`) or when the page opens at the bottom. With follow on, new events fade in (`dur-base`, fade + 4px slide) at the bottom and the trace stays pinned.
- Scrolling up more than one row turns follow off automatically and shows the pill "12 new events ↓" (bottom centre, `accent` fill, `on-accent` text). Click or `Shift G` jumps to the latest and turns follow back on. The count includes nested lane events.
- Events that arrive out of order (transcript after hooks) are inserted at their timestamp. If the insertion point is above the viewport, scroll position is preserved (no jump) and the minimap shows the new density.
- Waiting: a `Banner` (waiting variant) under the header: "Waiting for approval · Plan approval for AGH-48 · 6 min · Approve in the terminal session or open Approvals" with link to `/approvals/:id`. P4 adds inline approve actions there (see Actions).
- Idle: header badge "Idle · 7 min"; the trace shows a divider "No activity since 14:41". No alarm styling.
- Connection: if the session stream drops, the header shows `AsOfStamp` "as of 14:41" next to the status, and the collector pill handles global messaging. On reconnect, missed events replay via `Last-Event-ID` and the "new events" count includes them.
- Session ends while watching: the session end row appears, follow turns off after it, the status becomes "Done", and the summary card fades in above the tabs (one time, `dur-slow`) with a polite live-region announcement "Session ended: done. Summary available." No toast.
- Accessibility: new events are not announced individually. A polite live region announces at most once every 10 s a digest: "4 new events. Latest: Bash make check-fast, exit 0." Errors and guard events are included in the digest but never use `assertive`.

### Permalinks, copy and Raw disclosure

Every event row has:
- Copy link (`link`, `c`): absolute URL `/sessions/:id?event=:eventId` (+ `tz` when UTC is on). Confirmation is the button's own transient label "Link copied" (no toast).
- Copy id (`copy`, `Shift C`): full UUIDv7.
- Raw (`braces`, `r`): an inline disclosure under the row with `JsonViewer` showing the canonical event (redacted), `source`, `source_id`, `received_at`, latency ("received 0.22 s after the event"), `sources` when merged, and conflicts. Large payloads (> 200 lines) open in the side inspector (`size.panel`). Raw never shows unredacted content and has no "copy all" for content fields over 2 KB (principle 5: never invite copying sensitive data); it has "Copy event JSON" only for metadata.

## Files and diffs tab

- Layout: `FileTree` (left, 320px) grouped by repo, then folders; each file with op badges Read (`text-muted`), Created (`done`), Edited (`live`), Deleted (`failed`), and `+N −N`. Header line: "23 files · 3 edited · 1 created · 19 read only".
- Right: cumulative `DiffViewer` for the selected file (`?path=&repo=`), unified by default, split toggle at ≥ 1440 px. Above the diff: "Touched by 4 events" list with links to each timeline row (time, tool, lane).
- Sample: `brain/features/layered-memory/eval.md` Edited, +64 −0 (the file existed with a template header); `packages/core/src/agent_hub/core/memory/brain_memory_rule.py` Read 3 times.
- Read-only files show "Read only · no changes" and the read events, no diff.
- Expired transcript: tree and counts remain; the diff pane shows `ExpiredContent` "Diff content expired on 2026-11-10. The file list and change counts remain." with link to the PR files on GitHub when a PR exists ("See the change in PR #69").
- Data: `GET /sessions/{id}/files`, `GET /sessions/{id}/files/diff?path=&repo=`.

## Decisions tab (P3)

- One card per decision, in time order: choice (`subheading`), alternatives each struck through with `text-subtle`, rationale, evidence links (event rows, files), origin label ("Extracted from transcript" with confidence "medium", or "Recorded with /decide"), approver ("Approved by José Henrique Roquette in the terminal" when tied to a gate), "Jump to moment" link.
- Sample: "AC-48.21 stays passes:false (manual owner step)". Alternative struck through: "Mark AC-48.21 passing because the README section exists". Rationale: "The AC requires the owner to confirm the memory rule in their own setup; no command verifies it." Origin: Extracted from transcript · confidence high.
- In P2 the tab is absent; decision events still show in the timeline with their label.
- Empty: "No decisions recorded in this session. Decisions appear when the agent uses /decide or when the collector extracts a choice with alternatives from the transcript."
- Data: `GET /sessions/{id}/decisions`.

## Context tab (P3)

- Stacked horizontal bar (one bar, 100 % = context at session start) of composition by layer: managed rules (AGENTS.md, CLAUDE.md), project rules (AGENTS.project.md), repo rules (agent-hub/AGENTS.md), session brief, brain notes read, skills invoked, tool schemas (MCP), personal memory. Colours `chart-1`…`chart-5` with labels on segments (no legend-only colour).
- Table below: layer, path, lines, tokens, loaded at (session start or turn N), link to file (hub) or note (Brain browser). Sample row: "Repo rules · `agent-hub/AGENTS.md` · 58 lines · 1,204 tokens · start".
- Skills invoked: `/feature`, `/learn` with turn numbers. MCP servers and allowed tools listed with counts.
- Personal memory (`brain/auto/workspace/`): shows "Personal memory · present, private" with no path, size or content, to anyone but its owner.
- Data: `GET /sessions/{id}/context`.

## Cost tab

- `KpiStat` row: Total `$1.2734` · Input 412,330 · Output 38,904 · Cache read 2,104,551 · Cache write 118,200 · Run AGH-48 total `$5.6210` ("this session is 23 % of the run").
- `StackedArea` tokens over turns (or time, follows the axis toggle): `chart-1` input, `chart-2` output, `chart-3` cache read, `chart-4` cache write; cumulative cost line on a second axis with `chart-budget` dashed budget line labelled "Run budget $10.00" when the run has a cap (scaled to run cost so far).
- `BarChart` cost per subagent: "Main session $0.9614 · quality-reviewer $0.3120" (sum shown: $1.2734, exact).
- Table per turn (`DataTable`, compact): turn, time, tokens by kind, cost `$0.0412` (4 decimals), tool calls; turns over 3× the session median cost flagged with a `text-muted` "high" chip (deviation from normal, not alarm).
- Reconciliation note: "Totals match run AGH-48 (otel). Cost updated after the session ended: $1.2511 → $1.2734 at 15:14." when late enrichment exists.
- Data: `GET /sessions/{id}/cost?by=turn|subagent`.

## Raw events tab

- `DataTable` virtualized: time (ms), type, source, source_id (mono-sm, middle-truncated), lane, turn, latency ("0.22 s"), sources merged, conflict chip. Row click expands `JsonViewer`.
- Filters by source and type; "311 events · 142 timeline rows" explains why counts differ (merges and results folded into calls).
- Sort by `timestamp` default, toggle `received_at` to debug ingestion.
- Data: `GET /sessions/{id}/events?cursor=&types=` with `include_children=true`.

## Data mapping

| Element | Entity.field (brief §3) | API resource | Source · expected latency |
|---|---|---|---|
| Breadcrumb project, run, session | Session.project, Session.run_id, WorkflowRun.issue, Session.id | `GET /sessions/{id}` | hooks + executor · < 1 s |
| Agent id and role icon | Session.agent | `GET /sessions/{id}` | hooks · < 1 s |
| Status badge | Session.status, Session.outcome, end_reason | `GET /sessions/{id}`, stream `session` | derived · < 1 s |
| Repo | Session.repo | `GET /sessions/{id}` | hooks · < 1 s |
| Issue link | WorkflowRun.issue (key, title, url) | `GET /sessions/{id}` (embedded) | executor + linear · ≤ 60 s for title |
| Run link, step, attempt | Session.run_id, step, attempt; Step.max_attempts | `GET /sessions/{id}` | executor · < 1 s |
| Start, end, duration | Session.started_at, ended_at, segments | `GET /sessions/{id}` | hooks · < 1 s |
| Model | Agent.model | `GET /sessions/{id}` | otel (transcript fallback) · 1–5 s |
| Turns | Session.turns | `GET /sessions/{id}` | transcript · 2–10 s |
| Tokens in/out/cache | Session.tokens | `GET /sessions/{id}` | otel · 1–5 s |
| Cost | Session.cost_usd | `GET /sessions/{id}` | otel · 1–5 s, late updates |
| PR link and state | Session.pr | `GET /sessions/{id}` | github · ≤ 60 s |
| Transcript retention line | Session.transcript.state, expires_on | `GET /sessions/{id}` | collector retention |
| Segments indicator | Session.segments[] | `GET /sessions/{id}` | hooks · < 1 s |
| Guard and error counters | Session.guard_denials, errors | `GET /sessions/{id}` | hooks · < 1 s |
| Summary lines and links | session.summary (Proposal) lines[].text, event_id | `GET /sessions/{id}/summary` | collector derived · ≤ 30 s after end |
| Tab counts | events total, files count, decisions, raw count | `GET /sessions/{id}` (counts) | derived |
| Timeline rows | Event.type, timestamp, payload, turn, parent_event_id | `GET /sessions/{id}/events`, stream `event` | per source (see 02) |
| Tool group text | derived from consecutive tool.call payload.path | client-side from events | n/a |
| Bash exit code, duration | tool.result payload.exit_code, duration_ms | events | hooks · < 1 s |
| Edit +/− and inline diff | tool.call payload.added/removed; diff hunks | events; `GET /sessions/{id}/files/diff` | hooks (counts) · transcript (content) |
| Reasoning text | reasoning payload (summary) | events + blob | transcript · 2–10 s |
| Decision row | decision payload; Decision.origin, confidence | events; `GET /sessions/{id}/decisions` (P3) | transcript · 2–10 s |
| Learning row | learning.proposed payload; Learning.target, provenance, status | events; `GET /learnings/{id}` | transcript · 2–10 s |
| Guard rows | tool.result status denied; gate.request kind guard_ask; hook.blocked (Proposal) | events | hooks · < 1 s |
| Subagent lane header | child Session.agent, id, turns, cost_usd, outcome | events `include_children`; `GET /sessions/{childId}` | hooks + otel |
| Minimap bins and markers | Event.type, timestamp per bin | `GET /sessions/{id}/events?fields=type,timestamp` (density) | client |
| New events pill count | stream events after scroll-off | stream | < 1 s |
| Raw JSON | full canonical Event (redacted), received_at, sources | events | n/a |
| Files tree | file ops, added, removed | `GET /sessions/{id}/files` | hooks · < 1 s |
| Context layers (P3) | instruction files, brain notes, skills, MCP, sizes | `GET /sessions/{id}/context` | transcript + hub files |
| Cost charts | tokens and cost per turn, per subagent, run budget | `GET /sessions/{id}/cost` | otel · 1–5 s |

## Interactions

Keyboard: the Session detail map in `01-navigation.md` (j/k, Shift J/K turns, e errors and guard, d decisions, Enter expand, r Raw, c / Shift C copy, f follow, Shift G / g g, `/` and Ctrl F search, [ ] and 1–6 tabs, a axis).

| Input | Result | URL |
|---|---|---|
| Click row, `j` / `k` | Expand or select in place; selection kept 1/3 from top | `?event=` (replace) |
| Click summary line, minimap marker, `e`, `d` | Scroll to, select and expand the target event | `?event=` (replace) |
| Click minimap track | Jump to that time or turn | none |
| Follow button, `f` | Toggle follow tail (live only) | `?follow=1` |
| Search, filters, axis | Update the trace | `?q=`, `?types=`, `?errors=1`, `?axis=` |
| Tabs | Switch tab | `?tab=` (push) |
| Lane chevron / "Open as own session" | Expand lane / navigate to the subagent session | `?lane=` / `/sessions/:childId` |
| Issue link / run link | Tracker in a new tab / Run detail at step and attempt | external / `/runs/:id?step=&attempt=` |
| Deep link `?event=` inside a collapsed group or lane | Expands group and lane, scrolls, selects, flashes `accent-soft` once (`dur-slow`; none under reduced motion) | |
| Deep link outside the loaded window | `GET /sessions/{id}/events?around=:eventId` loads 200 around it; more pages load on scroll | |

## States

| State | What shows | Exact copy |
|---|---|---|
| Loading (> 300 ms) | Header `Skeleton` (2 lines), summary skeleton (3 lines), 12 row skeletons with type bar placeholders, minimap track empty | none |
| Loading more (scroll) | 3 skeleton rows at the edge being loaded | none |
| Empty (session started, no events yet beyond start) | Session start row, then `EmptyState` small | "No events yet. Tool calls appear within a second; messages appear after each turn." |
| Filtered to nothing | Inline empty in trace | "No events match these filters. 142 events are hidden." + "Reset filters" |
| Search no match | Inline under search | "No match for "check-full" in this session." |
| Partial: transcript not yet processed | Messages and reasoning rows show placeholder rows with `AsOfStamp` | "Transcript catching up · 4 min behind. Tool calls are current." |
| Partial: otel missing | Cost and tokens show "estimated" | "Cost estimated from transcript · otel not received" |
| Partial: GitHub unreachable | PR link shows | "PR #69 · state unknown · as of 14:02" |
| Error (session fetch) | `ProblemError` full body | title "Could not load session" · detail from Problem Details · "Try again" |
| Error (events page) | Inline `ProblemError` in trace where the page failed; rest stays | "Could not load events 200–400. Try again." |
| Not found | 404 page | "Session not found" · "No session has the id 5091b986 in the registered hubs. It may belong to a hub that was removed." · "Open command palette" · "Go to Portfolio" |
| Live | Pulse badge, follow tail, new events pill | "Live · last action 12 s ago" · "12 new events ↓" |
| Waiting | Waiting banner | "Waiting for approval · Plan approval for AGH-48 · 6 min · Approve in the terminal session or open Approvals" |
| Idle | Idle badge, divider | "Idle · 7 min" · "No activity since 14:41" |
| Stale (stream or collector down) | `AsOfStamp` next to status | "as of 14:41" · tooltip "Live updates paused: collector offline since 14:41." |
| Ended without end event | Badge and divider at last event | "Ended · no end event received (last activity 14:41)" |
| Transcript expired | Header retention line; content rows show `ExpiredContent` inside the expanded body, rows still list type, tool, path, exit code, counts | "Content no longer available (transcript expired on 2026-11-10). Summary and structured events remain." |
| Expires soon | Header line in `waiting` | "Transcript expires in 3 days (2026-11-10)" |
| Redacted | `RedactionChip` inline in commands, messages, Raw | "[redacted: github token]" · tooltip "Removed before storage by the github_token rule. The original value was never stored." |
| Late events | Row with `clock-arrow-up`, header cost tooltip | "Cost updated after the session ended · $1.2511 → $1.2734" · "PR #69 linked after the session ended" |
| Very long (5,000+ events) | Virtualized trace grouped by turn; turns collapsed to one summary row each beyond the first and last 3; banner | "Long session · 5,214 events in 412 turns. Turns are collapsed; expand a turn or use search and the minimap." Turn summary row: "Turn 212 · 14 events · Read 9 files, Bash 2, Edit 1 · 2 min 4 s" |
| Resumed segments | `session.start` rows labelled "Session resumed · segment 2", gap divider | "Resumed after 3 h 12 min" |
| Subagent still running in ended parent | Lane header badge | "Still running" |
| Personal memory referenced | Context and Raw | "Personal memory · present, private" |

## Actions by phase

| Action | Phase | Confirmation? | Consequence |
|---|---|---|---|
| Copy link, copy id, view Raw, filter, search, switch tabs | P2 | No | None (read-only) |
| Open run, issue, PR, subagent as own session | P2 | No | Navigation |
| "Triage in Learnings" from a learning row | P3 | No | Opens `/knowledge/learnings?learning=:id` |
| "Open in Decisions" | P3 | No | Opens decisions tab / log |
| Approve / Request changes / Reject from the waiting banner | P4 | Yes for all three (approval resumes the agent, so it is treated as irreversible). Approve: `ConfirmDialog` "Approve plan for AGH-48? The implementing session resumes and starts editing code in agent-hub." Request changes requires a comment. Reject: `ConfirmDialog` "Reject plan for AGH-48? The run stops at the human gate and the issue gets the agent-failed label." | `POST /approvals/{id}/decision` |
| Pause session | P4 | Yes: "Pause this session? It finishes the current tool call, then waits. You can resume it from here or the terminal." | Session status Waiting (paused) |
| Cancel session | P4 | Yes, destructive `ConfirmDialog`: "Cancel this session? The agent stops after the current tool call. Uncommitted changes stay in the worktree agh-112-tracker-teams. The run is marked failed at implementing." Button "Cancel session" (failed fill), secondary "Keep running" | Session ends outcome stopped; run FAILED(IMPLEMENTING, "cancelled by owner") |

Actions are placed in the header's overflow menu ("More ▾") and the waiting banner; none appear before their phase.

## UX principles applied

| Choice | Principle (brief §7) |
|---|---|
| Header answers who/what/how it ended/cost in two lines; summary card second; trace third | F-pattern and layer-cake scanning; Shneiderman overview first |
| Summary lines link to moments; derived label always present | Explainability and provenance (W3C PROV); calibrated trust (Lee and See) |
| Consecutive reads collapse; results fold into calls; diffs and outputs on expand | Progressive disclosure; cognitive load (Sweller); Tufte data-ink |
| Guard events in their own colour and shield shape, separate from errors | Pre-attentive processing (Treisman and Gelade): shape + colour; calibrated trust: denials read as the system working |
| Minimap with distinct marker shapes for errors, decisions, gates, guard | Shneiderman zoom and details on demand; no information by colour alone (WCAG 1.4.1) |
| Follow tail auto-off on scroll up with "12 new events" pill | User control and freedom (Nielsen #3); visibility of system status (#1) |
| Live announcements as a polite digest every 10 s, no toasts | Alarm fatigue (Sendelbach and Funk); WCAG 4.1.3 status messages |
| Turn headers and turn axis | Working memory (Cowan ~4 chunks): turns chunk the trace |
| Expand in place rather than a side inspector | Gestalt continuity; keeps the reader's place |
| "Recorded reasoning summary", "Extracted from transcript" labels | Show only what the record shows (principle 3) |
| Redaction as a marker with no reveal | Privacy first (principle 5); error prevention (Nielsen #5) |
| Filter "Errors and decisions only" keeps a hidden-count divider | Information scent (Pirolli and Card); orientation |
| Skeletons after 300 ms; events page in 200s; virtualized | Response time limits (0.1 / 1 / 10 s) |
| Confirmation only for irreversible P4 actions, with consequences stated | Error prevention (Nielsen #5); human decides (principle 2) |

## Responsive

- **1440 px and wider:** three columns as wireframed; filter rail 200px expanded; split diff available.
- **1280×800:** sidebar collapsed; filter rail in a popover; header two lines with "More"; summary collapsed to one line; compact rows; minimap kept (it is the fastest way to navigate long sessions).
- **1024–1279 px:** minimap reduced to markers only (no density strip) at 32px; hover actions in a row overflow menu.
- **Mobile (< 640 px, glance):** header and summary as wireframed; timeline as a plain list (no minimap, no Raw, no diff, filters limited to "Errors and decisions only"); "Open on a larger screen for diffs and raw events" note; live digest only via the status line (no live region chatter on mobile). Touch targets ≥ 44px.
