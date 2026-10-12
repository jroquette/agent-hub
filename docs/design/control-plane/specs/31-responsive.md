# Responsive behaviour

Desktop first. The design targets 1440 px, must be fully usable on a 1280×800 laptop, is best-effort on tablets, and offers a reduced "glance" layout on phones for three screens only.

## Breakpoints
| Name | Width | Support | Shell | Page gutter |
|---|---|---|---|---|
| Wide | ≥ 1600 px | Full | `Sidebar` expanded (`sidebar` 240 px); side panels dock | `space-8` (32 px) |
| Desktop / laptop | 1280–1599 px | Full | Expanded ≥ 1360; collapsed to icons (`sidebar-collapsed` 56 px) below 1360 by default (user can pin open) | `space-6` (24 px) |
| Tablet | 768–1279 px | Best effort (read, no editing) | Sidebar hidden behind a menu button in `TopBar`; opens as overlay with `scrim` | `space-4` (16 px) |
| Mobile glance | < 768 px | Glance screens only: Live sessions, Approvals, Session header | Bottom tab bar (Live · Approvals · Needs you) replaces sidebar | 16 px side gutter |

Rules everywhere: no horizontal page scroll at any width (wide tables scroll inside their own container with a sticky first column); targets stay ≥ 24 × 24 (`control-sm`); text never below `caption` 12 px; density switches to compact automatically at < 900 px height only if the user has not chosen one.

Below 768 px, every non-glance screen shows: "This view needs a wider screen." · "[Open Live sessions] [Open Approvals]" and keeps its deep link so it can be opened later on a desktop.

## Shell at 1280×800
```
+----+-----------------------------------------------------------------------------------------------+
|[=] | [agent-hub v]  [Search  Ctrl K]                         (o) 3 s ago  [sun] [Local]           |  48
|----+-----------------------------------------------------------------------------------------------|
| P  |                                                                                               |
| A3 |  content area: 1280 - 56 - 2*24 = 1176 px                                                     |
| L* |                                                                                               |
| S  |                                                                                               |
| R  |                                                                                               |
| K  |                                                                                               |
| ...|                                                                                               |
+----+-----------------------------------------------------------------------------------------------+
 56
```
- Sidebar icons with `Tooltip` labels on hover/focus; badge counts become dots with the number in the tooltip (Approvals "3"), Live sessions keeps its pulse dot.
- `CollectorPill` shortens to the dot + "3 s ago"; full text in tooltip.
- `ProjectSwitcher` max 200 px with truncation.
- Vertical budget at 800 px: top bar 48 + page header ~72 leaves ~680 px; sticky headers stay ≤ 120 px combined.

## What collapses at 1280×800, per major screen
| Screen | At 1440 | At 1280×800 |
|---|---|---|
| Portfolio | Needs-you strip + 3-column project cards + activity feed right (360) | Cards 2 columns; activity feed moves under cards (collapsible, 5 items); sparkline kept, "ready issues" moves into card footer |
| Project overview | Now cards 3 across; Kanban 7 columns | Now cards 3 across, compact; Kanban scrolls horizontally inside its region with column headers sticky; "Reported" column collapsed to a count |
| Live sessions | 4 tiles per row (≈ 320 px) | 3 tiles per row; tile hides files-touched line and sparkline shrinks to 48 px; hover preview becomes focus/hover popover anchored right |
| Sessions list | All default columns | Columns hidden by priority (below) |
| Session detail | Header 2 lines + summary card + timeline + `Minimap` 56 px + inspector panel docked (480) | Header 1 line with overflow "More" popover (model, tokens split, transcript retention); summary card collapsed to 1 line "Summary · 4 points [Expand]"; minimap narrows to 32 px (markers kept, density strip simplified); event inspector overlays as a side panel with `shadow-overlay` instead of docking |
| Run detail | Pipeline full labels; Gantt + gate results side by side | Pipeline shows short labels (Pick, Tree, Impl, Verify, PR, Report) with full names in tooltip; Gantt above gate results |
| Approvals | List 440 + detail panel docked | List 360; detail panel overlays (`panel` 480, `scrim` none, `shadow-overlay`) |
| Health | Findings table + rule rail | Rail becomes filter chips row |
| Knowledge | Tree 280 + note + rail 280 | Tree 240; rail becomes a "Backlinks (4)" popover; Provenance lineage nodes 148 px, effect panels 2 × 2 |
| Metrics | 2-column chart grid | 1 column below 1360; KPI sparklines hidden |
| Workflows | Graph + docked step inspector | Inspector overlays; editor panes switch via "Visual | YAML" segmented control |

### Table column priority (hide from the end of the list first)
| Table | Priority order (kept → hidden first at the end) | Hidden at 1280 |
|---|---|---|
| Sessions list | Started, Agent, Issue/run, Outcome, Duration, Cost, Repo, Project, Errors, Turns, Tokens, Files, Decisions, Transcript | Tokens, Files, Decisions, Transcript (Project hides when scoped to one project) |
| Runs list | Run, Issue + title, Stage, Outcome, Started, Cost vs budget, PR + CI, Duration, Repo, Workflow + revision, Attempt, Dry-run | Workflow + revision, Attempt, Dry-run |
| Learnings queue | Text, Provenance, Target, Age, Source | Source |
| Tracker queue | Issue, Title, Age, Action, Repo | Repo |
| Health findings | Severity, Rule, Path:line, Message, Fix | — (Fix moves under Message) |
| Collector sources | Source, Health, Last event, Latency p95, p50, Events 24 h | p50, Events 24 h |

Hidden columns stay available from the column chooser and in the row hover preview; the URL keeps chosen columns.

## Tablet (768–1279) best effort
Same as laptop plus: side panels are full-height overlays; `Minimap` hidden (scrubber via "Jump to" menu); tables show the first 4 priority columns; editing (workflow editor) shows "Editing needs a desktop screen."

## Mobile glance views (< 768 px, drawn at 390 px)
Only reading, plus P4 approve/reject where the decision is fully visible. Bottom tab bar: Live · Approvals · Needs you. Pull to refresh is not used (SSE keeps live); `AsOfStamp` shows when the connection drops.

### Live sessions (390 px)
```
+--------------------------------------+
| agent-hub v          (o) 3 s ago     |
|--------------------------------------|
| Live sessions  4                     |
| [All] [Waiting 1] [Errors 0]         |
|--------------------------------------|
| ! WAITING · Plan approval            |
| hub-workflow:planner  AGH-48         |
| agent-hub · 3 h                      |
|--------------------------------------|
| * LIVE  main · AGH-112               |
| Editing packages/core/.../teams.py   |
| 46 turns · $2.14 of $10.00           |
| [====------------------]  21 %       |
|--------------------------------------|
| * LIVE  spec-reviewer · AGH-112      |
| Reading docs/SPEC.md                 |
| 12 turns · $0.41                     |
|--------------------------------------|
| * LIVE  main · LOK-311               |
| Running make check                   |
| 31 turns · $1.88 of $10.00           |
|--------------------------------------|
| Ended (2 min)                        |
|   evaluator · AGH-48 · done          |
|--------------------------------------|
| [Live]     [Approvals 1] [Needs you] |
+--------------------------------------+
```
One tile per row, full width; waiting first with `waiting` left edge (3 px); tap opens the Session header view. No hover preview; no sparkline (saves height). Group headers (project › repo) become thin sticky labels.

### Approvals (390 px)
```
+--------------------------------------+
| < Approvals                          |
|--------------------------------------|
| Plan approval · AGH-48               |
| Layered memory                       |
| requested by hub-workflow:planner    |
| waiting 3 h                          |
|--------------------------------------|
| What changes if I approve            |
| The run starts implementing in       |
| agent-hub. Budget up to $10.00.      |
|--------------------------------------|
| Plan (rendered)            [Expand]  |
| 1. Add MemoryLayer port ...          |
| 2. ...                               |
| Acceptance criteria   21  [View all] |
|--------------------------------------|
| [Request changes]   [Approve plan]   |  P4
| P2: Approve in the terminal session. |
+--------------------------------------+
```
P4 buttons sit in a sticky footer (48 px, `control` height targets). "Approve plan" still confirms with a bottom-sheet `ConfirmDialog`. Guard "ask" approvals show the diff summary only ("+14 −3 in docs/adr/0009-….md") with "Open on desktop to see the full diff" when the diff exceeds 40 lines.

### Session header (390 px)
```
+--------------------------------------+
| < AGH-112 · Session 5091b986         |
|--------------------------------------|
| * LIVE   main                        |
| agent-hub · run 01923f1e             |
| Implementing · attempt 1             |
|--------------------------------------|
| Started 09:12 · 38 min               |
| 46 turns                             |
| $2.14 of $10.00                      |
| [====------------------]  21 %       |
| At this rate, budget in ~1 h 40 min  |
|--------------------------------------|
| Last action                          |
| Editing packages/core/.../teams.py   |
| 12 s ago                             |
|--------------------------------------|
| Recent                               |
| Edit teams.py         +14 -3   12 s  |
| Bash make check-fast  exit 0   1 m   |
| Read tracker.py                3 m   |
|--------------------------------------|
| Summary appears when it ends.        |
| Full timeline needs a wider screen.  |
+--------------------------------------+
```
Shows the session header fields, projection line (Endsley), last action and the last 5 events as one-line rows. No timeline, minimap or tabs. P4 "Pause" / "Cancel" live in a "…" menu with confirmation that states consequences.

## UX principles applied
| Choice | Principle |
|---|---|
| Column priority lists instead of ad-hoc truncation | Progressive disclosure; information scent |
| Panels overlay at laptop width | Fitts (keep targets large); working memory (context stays visible behind) |
| Mobile limited to glance screens | Persona fit (owner on the move); cognitive load |
| Waiting tiles first on mobile | Situation awareness: perception first |
| Never horizontal page scroll; ≥ 24 px targets | WCAG 2.2 (reflow, target size) |
