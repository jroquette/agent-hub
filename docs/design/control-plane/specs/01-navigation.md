# Sitemap and navigation

**Phase:** P2 shell (P3 and P4 destinations tagged inline) · **Route:** every route below · **Answers:** "Where am I, what else is there, and how do I get to the thing I need in one step?"

This section defines the shell every screen sits in: the sitemap with phases and routes, the sidebar, the top bar, breadcrumbs, deep links and the keyboard map. Screen specs refer back here instead of repeating shell behaviour.

## Sitemap

Every screen carries its phase. A screen tagged P3 or P4 is not shown in the sidebar before its phase ships (no "coming soon" teasers); a screen tagged P2 whose actions arrive later shows those actions only from their phase.

```
/                                   Portfolio                                        P2
└ /projects/:project                Project overview                                 P2
    ?section=now|repos|work|sessions|health|cost   (scroll target, not a tab)

/approvals                          retired (AGH-273): an approval is answered in its run or its session

/live                               redirect (replace) to /sessions?view=grid        ADR 0033
    ?group=repo|run|workflow → within=; group=flat and unknown params dropped; scope (project) kept

/sessions                           Sessions (grid or table, status sections)        P2 · P3 compare
    ?view=grid|table&within=repo|run|workflow
    &scope=&period=&repo=&agent=&status=&outcome=&workflow=&cost_min=&cost_max=
    &file=&tool=&guard_denial=1&sort=-started_at   (saved views are filter sets, not a param)
├ /sessions/:id                     Session detail (default tab = timeline)          P2
│   ?tab=timeline&event=:eventId&types=tool.call,decision&q=&errors=1&follow=1&axis=time|turn&lane=:subSessionId
│   ?tab=files&path=:repoRelativePath&repo=:repo                                       P2
│   ?tab=decisions&decision=:decisionId                                               P3
│   ?tab=context&layer=:layerId                                                       P3
│   ?tab=cost&by=turn|subagent                                                        P2
│   ?tab=raw&event=:eventId&source=                                                   P2
└ /sessions/compare?a=:id&b=:id     Compare two sessions                             P3

/agent-sessions/:id                 Chat of a driven session (full page, ADR 0031/0033)   P2

/runs                               Workflow runs list                               P2
    ?project=&repo=&stage=&outcome=&failure_stage=&mode=live|dry-run
└ /runs/:runId                      Run detail                                       P2 · P4 retry
    ?step=:stepKey&attempt=:n&panel=gates|tracker|caps|pr

/knowledge                          Knowledge (redirects to /knowledge/brain)        P3
├ /knowledge/brain?project=&path=   Brain browser                                    P3
├ /knowledge/skills                 Skills: project picker (AGH-164)                 P2
│ └ /projects/:project/skills       Skills catalog                                   P2
│     ?q=&kind=&origin=&mode=&diag=1   (comma lists; replace, not push)
│   └ /projects/:project/skills/:kind/:source/:name   Skill, agent or hook detail   P2
├ /knowledge/learnings              Learnings triage                                 P3 (accept/reject/snooze P3)
│   ?status=proposed|accepted|rejected|snoozed&target=team|repo|personal&learning=:id
│ └ /knowledge/learnings/:id/trace  Provenance trace                                 P3
├ /knowledge/decisions?project=&repo=&topic=&decision=:id  Decisions log            P3
└ /knowledge/context?project=&repo=&agent=  Context inspector                        P3

/features?project=                  Features list                                    P2 read-only
└ /features/:project/:slug          Feature detail                                   P2
    ?doc=spec|plan|research|eval&ac=:acId

/workflows                          Workflow catalog                                 P4
└ /workflows/:workflowId            Workflow detail                                  P4
    ?view=graph|revisions&overlay=failure|wait&rev=:n
  └ /workflows/:workflowId/edit     Workflow editor (visual ⇄ YAML)                  P4
      ?mode=visual|yaml&rev=:n

/metrics                            Metrics                                          P2 basic · P3 learning effect
    ?metric=lead-time&period=7d&group_by=step|gate|repo|size|run
/bench?project=&case=               Bench results                                    P2

/health?project=&severity=&area=    Health (Doctor)                                  P2
/tracker?project=&label=agent-ready|agent-failed   Tracker queue                     P2 · P4 start run

/settings                           Settings (redirects to /settings/hubs)           P2
├ /settings/hubs                    Hubs (add by path, validate, remove)             P2
├ /settings/collector               Collector                                        P2
├ /settings/retention               Retention and privacy                            P2
├ /settings/appearance              Appearance                                       P2
└ /settings/about                   About                                            P2

/welcome                            First run (3-step checklist)                     P2
/offline                            Collector offline full page (only when no cache) P2
/*  (no match)                      Not found (404 Problem page)                     P2
```

Route rules:

- Path segments are plural kebab-case nouns, mirroring the API (`/runs` is the UI alias of `/api/v1/workflow-runs`; "run" means WorkflowRun only).
- `:project` is the project name slug (`agent-hub`, `loki-trader`), the same value the API uses.
- `:id` for sessions, runs, events, approvals and learnings is the full UUIDv7. The UI also accepts the 8-character short id (`/sessions/5091b986`) and redirects (HTTP-style `replace`) to the full id; if the short id is ambiguous it shows a disambiguation list ("2 sessions start with 5091b986").
- Query parameters hold view state (tab, filters, selection, follow, axis). Path holds identity. A link pasted into another browser restores the exact view.
- Default values are omitted from the URL (`?tab=timeline` is not written; `?tab=cost` is).

## Shell layout

```
┌───────────┬─────────────────────────────────────────────────────────────────────────────────────┐
│ ◇ agent-  │ [All projects ▾]  [⌕ Search sessions, runs, issues, files…  ⌘K]  ● Connected · 3 s   │ topbar 48
│   hub     │                                                         [◐] [Local ▾] [JR]          │
├───────────┼─────────────────────────────────────────────────────────────────────────────────────┤
│ OVERVIEW  │ Portfolio › agent-hub › Run AGH-48 › Session 5091b986          (Breadcrumbs)        │
│ ⌂ Portf.  │                                                                                     │
│ ✓ Approv 2│                                                                                     │
│ OBSERVE   │                         page content                                                │
│ ≡ Sess. ●3│                                                                                     │
│ ⇶ Runs    │                                                                                     │
│ UNDERSTAND│                                                                                     │
│ ◫ Knowl.  │                                                                                     │
│ ! Features│                                                                                     │
│ IMPROVE   │                                                                                     │
│ ⌗ Metrics │                                                                                     │
│ ⌬ Bench   │                                                                                     │
│ HUB       │                                                                                     │
│ o Health 1│                                                                                     │
│ = Tracker │                                                                                     │
│ * Settings│                                                                                     │
│ [«]       │                                                                                     │
└───────────┴─────────────────────────────────────────────────────────────────────────────────────┘
  sidebar 240 (56 collapsed)
```

`AppShell` places `Sidebar` (width token `sidebar` 240px, `sidebar-collapsed` 56px, `z-sidebar`) and `TopBar` (height `topbar` 48px, `z-sidebar`). The collector-offline `Banner` sits below the top bar at `z-banner` and pushes content down (never overlays it). Page gutter `space-8` at ≥1440 px, `space-6` below.

## Sidebar

**As built (AGH-273).** The sidebar is grouped by what the user comes to do; where the table and text below say
otherwise, this list wins:

- **AC-273.20** The sidebar lists, in order: Portfolio (no caption); **Work**: Sessions (`list`, the live badge,
  ADR 0033), Workflow runs (`route`), Workflows (`workflow`), Features (`list-checks`); **Knowledge**: Learnings
  (`lightbulb`, the learnings-to-triage badge on the waiting ground), Brain (`book-open`) and Skills (`package`) as
  flat items, Brain and Skills following the project open or in scope; and Health and Settings pinned to the footer,
  next to Shortcuts. There is no Approvals and no Live sessions entry. The command palette lists the same screens,
  Learnings with its `g k` hint.
- **AC-273.21** There is no Approvals screen: `/approvals` is an unknown route (404), `g a` goes nowhere (and still
  never answers a focused permission card), and the shortcut sheet lists no Approvals. A Needs you item, an
  activity row and a search hit for an approval link where it is answered: `/runs/<run>` for a workflow gate, else
  `/sessions/<session>`. A waiting tile with no chat says "Open session" and opens its session; the session page's
  waiting banner says "Approve in the terminal session". The project overview's "See N more" expands Needs you in
  place (`?needs=all`), as the Portfolio does; a Needs you list with nowhere to go shows no "more" line.


Groups appear in this order with `caption` style group labels in `text-subtle`. The selected item uses `accent-soft` ground, `accent` icon and a 2px `accent` left bar; hover uses `surface-hover`. Each item is a 32px (`size.control`) row; collapsed, each becomes a 40×40 icon button with a `Tooltip` showing the label and its shortcut.

| Group | Item | Lucide icon | Route | Badge | Badge data source | Phase |
|---|---|---|---|---|---|---|
| Overview | Portfolio | `layout-dashboard` | `/` | none | none | P2 |
| Overview | Approvals | `stamp` | `/approvals` | Count of open approvals in scope, `StatusBadge` waiting variant (amber number on `waiting-soft`) | `approvals_open` from `GET /events/stream` event `counts`; initial from `GET /approvals?scope=` `total` | P2 |
| Observe | Sessions | `list` | `/sessions` | Count of non-ended observed sessions, number in `live` with the pulse dot (`dur-pulse`, one dot per item, not per session); accessible name "Sessions, 3 live" | `live_sessions` from `GET /events/stream` `counts` (driven sessions count through their observed twin only) | P2 · ADR 0033 |
| Observe | Workflow runs | `git-pull-request-arrow` | `/runs` | Failed runs since last visit, small `failed` number, only when > 0 | `failed_runs_since_seen` from `counts` | P2 |
| Understand | Knowledge | `brain` | `/knowledge/brain` | Learnings awaiting triage, neutral `text-muted` number | `learnings_proposed` from `counts` | P3 |
| Understand | Features | `flag` | `/features` | none | none | P2 |
| Improve | Workflows | `workflow` | `/workflows` | none | none | P4 |
| Improve | Metrics | `chart-line` | `/metrics` | none | none | P2 |
| Improve | Bench | `flask-conical` | `/bench` | none | none | P2 |
| Hub | Health | `heart-pulse` | `/health` | Doctor error count, `failed` number, only when > 0 (warnings are not badged) | `doctor_errors` from `counts` | P2 |
| Hub | Tracker queue | `inbox` | `/tracker` | Ready issue count, neutral | `ready_issues` from `counts` (polled source: linear, ~60 s) | P2 |
| Hub | Settings | `settings` | `/settings` | Dot only when a hub fails validation | `hubs_invalid` from `counts` | P2 |

Knowledge expands into sub-items when its route is active: Brain (`book-open`), Learnings (`lightbulb`), Decisions (`git-commit-vertical`), Context (`layers`).

As built (AGH-201, AGH-164), Knowledge shows Learnings, Brain and Skills, in that order. Skills sits right after
Brain and links to the catalog of the project whose skills are open, else of the project in scope
(`/projects/<p>/skills`), else to the picker `/knowledge/skills`, which lists the registered projects with counts as
Brain's picker does ([19-brain-and-skills.md](19-brain-and-skills.md), AGH-270) (the route is declared before `/knowledge/:section`, so it is not the Phase 3 placeholder). A skill
detail's breadcrumb is Portfolio › project › Skills › name.

Badge rules:
- At most one number per item, max "99+". Numbers are tabular (`figure` style). Badges never animate except the Sessions pulse dot, which stops under `prefers-reduced-motion` (static dot).
- Badges follow the scope switcher: with scope `agent-hub`, Approvals counts only agent-hub approvals.
- Badges are not alarms: no colour for counts that are routine (ready issues, learnings). Only waiting (amber) and failure/error (red) get colour, so colour keeps its meaning (alarm fatigue).
- The accessible name includes the count: "Approvals, 2 waiting".

Collapse: the `IconButton` `panel-left-close` at the bottom toggles collapse; `[` is not used (reserved for tabs). Default collapsed below 1360 px; the choice persists in local storage `ah.sidebar.collapsed`.

## Top bar anatomy

Left to right: `ProjectSwitcher`, `CommandPalette` trigger, flexible space, `CollectorPill`, theme `IconButton`, time zone `SegmentedControl`, identity chip.

### Project scope switcher (`ProjectSwitcher`)

- Label shows the current scope: "All projects" or the project name with its hub health dot. Menu lists "All projects" then each registered project with live session count ("agent-hub · 3 live"), then "Manage hubs" linking to `/settings/hubs`.
- Data: `GET /projects` (`items[].name`, `hub_health`, `live_sessions`).
- Persistence: the scope is written to the URL as `?scope=agent-hub` on every list or overview route, and to local storage `ah.scope`. On load, the URL wins; with no `?scope=` the stored value applies and is written into the URL (replace, not push). "All projects" is the absence of `scope`.
- On detail routes (`/sessions/:id`, `/runs/:id`) the entity's project is shown read-only in the switcher; changing scope there navigates to that project's list of the same kind (Session detail → `/sessions?scope=loki-trader`).
- An entity outside the current scope still opens from a deep link: the switcher shows the entity's project and leaves the stored scope unchanged. Scope filters lists, never blocks links.
- Shortcut: `g o` opens the switcher ("go to project"). Number keys `1`–`9` inside the open menu pick the n-th entry.

### Command palette (`CommandPalette`)

Opens with `⌘K` (macOS) or `Ctrl K` (others), and from the search field click. Overlay at `z-palette`, `radius-xl`, `shadow-overlay`, `scrim` behind, width 640px, max 8 visible rows per group.

Input placeholder: "Search sessions, runs, issues, files, agents, notes, screens…". Prefix filters: `>` screens and actions only, `#` issues, `@` agents, `/` file paths.

Result groups, in this fixed order (empty groups hidden):

| Group | Matches | Example row | Opens |
|---|---|---|---|
| Exact id | Full or 8-char session, run, event, approval id | `5091b986` Session · hub-workflow:evaluator · AGH-48 · ended done | entity route |
| Issues | `AGH-48`, `LOK-311`, title words | `AGH-48` Layered memory · Run reported · PR #69 merged | the run of the issue, or the feature if no run |
| Sessions | agent id, issue, repo | hub-workflow:quality-reviewer · AGH-48 · 2026-10-09 14:02 | `/sessions/:id` |
| Workflow runs | run id, issue | Run 01923f1e · AGH-79 Guard bypass · failed at verifying | `/runs/:id` |
| Files | repo-relative paths touched by any session | `packages/core/.../brain_memory_rule.py` · touched in 4 sessions | `/sessions?file=…` |
| Agents | `plugin:name` | `hub-workflow:evaluator` · 12 sessions this week | `/sessions?agent=…` |
| Brain notes | title and path under `brain/` (P3; before P3 they open the hub file link) | `brain/learnings/gotchas/testing.md` | `/knowledge/brain?path=…` |
| Screens and actions | sidebar items, settings sections, "Toggle theme", "Switch to UTC" | Sessions `g s` (only Sessions: no Live sessions entry) | route or action |

Ranking (within a group, then the groups above are ordered as listed but an exact match always wins the first row):
1. Exact id or exact issue key match: score 1.0, pinned top.
2. Prefix match on id, issue key or file basename: 0.8.
3. Token match in title/path, scored by fuzzy distance: 0.3–0.7.
4. Boost +0.15 when the item is in the current scope; +0.1 when live; +0.1 when opened in the last 7 days (local history `ah.palette.recent`, max 50 entries, per browser only).
5. Ties: most recent activity first.

Empty input shows "Recent" (last 8 opened entities) and "Screens". No-result copy: "No match for "brain_memry". Try an issue key like AGH-48, an 8-character id, or a file name." Data: `GET /search?q=&scope=` (debounced 120 ms; results under 1 s or a `Skeleton` row after 300 ms). Keyboard: `↑`/`↓` move, `Enter` opens, `⌘Enter`/`Ctrl Enter` opens in a new tab, `Tab` cycles groups, `Esc` closes.

### Collector pill (`CollectorPill`)

Shows whether data is flowing. Derived on the client from the global SSE `GET /events/stream` (heartbeat every 15 s, see `02-data-and-api.md`).

| State | Condition | Look | Copy | Tooltip |
|---|---|---|---|---|
| Connected | SSE open and last heartbeat ≤ 20 s ago | `done` dot on `surface`, `text-muted` label | "Connected · last event 3 s ago" | "Collector at 127.0.0.1:7420 · 1,284 events today · hooks 0.4 s, transcript 6 s, otel 1 s behind" |
| Delayed | SSE open and last heartbeat 20–60 s ago, or any source behind its stale threshold | `waiting` dot on `waiting-soft` | "Delayed · last event 42 s ago" | "No heartbeat for 42 s. Live views may lag. Transcript events are 4 min behind." |
| Offline | SSE closed and reconnect failing, or no heartbeat for > 60 s | `failed` dot on `failed-soft` | "Offline · as of 14:02" | "Collector not reachable since 14:02. Start it with `hub collector start` in the hub directory." |
| Reconnecting (transient) | SSE closed < 10 s, retry in progress | `idle` dot, spinner replaced by static dot under reduced motion | "Reconnecting…" | "Trying again in 4 s" |

The "last event" age updates every second while < 60 s, then every 15 s ("2 min ago"). Click opens a `Popover` with per-source health (last event, lag, state) from `GET /collector/status` and a link "Open collector settings" (`/settings/collector`). Offline also raises the non-blocking `Banner` (`z-banner`): "Collector offline since 14:02. Views show data as of 14:02. Start it with `hub collector start`." with a copy button for the command and a "Dismiss" (dismissal lasts until the state changes).

### Theme, time zone, identity

- Theme `IconButton`: icons `sun` / `moon` / `monitor` cycling Light → Dark → System. Stored in `ah.theme`; mirrored in Settings › Appearance. `aria-label` "Theme: system".
- Time zone `SegmentedControl` "Local | UTC". Stored in `ah.tz` and `?tz=utc` when not default so shared links keep the reader's intent ("the times I saw were UTC"). Every `Time` component reads it; tooltips always show both ("14:02:11 local · 12:02:11 UTC").
- Identity chip: initials avatar (`radius-full`) "JR" with the git `user.name` from the hub config. Menu: "José Henrique Roquette · roquettejh@gmail.com" (read-only, from hub config), "Keyboard shortcuts ?", "Settings", "About agent-hub". No sign-out (local single-user app, brief §12).

## Breadcrumbs

`Breadcrumbs` appear only on detail screens, under the top bar, `small` style, separator `chevron-right` 12px in `text-subtle`.

Rules:
1. Path reflects containment, not history: Portfolio › Project › Run › Session › (Subagent session). Example: "Portfolio › agent-hub › Run AGH-48 › Session 5091b986".
2. A session not in a run omits the run crumb: "Portfolio › agent-hub › Session 7a31c0e2".
3. A subagent session shows its parent session: "… › Session 5091b986 › Subagent 9c4e12aa (quality-reviewer)".
4. Each crumb is a link except the last. Entity crumbs show the human key when one exists (issue key for runs, short id for sessions).
5. Tabs are not crumbs. Filters are not crumbs.
6. Middle crumbs collapse into "…" (with a menu) when the bar is narrower than the content; the first and the last two always show.
7. With scope "All projects" the project crumb still shows (it is containment, not scope).
8. Keyboard: `g u` goes up one crumb.

## Deep links

Every entity, tab, filter and selected item is addressable. The URL is the source of truth for view state; local storage only remembers defaults (scope, theme, tz, density, sidebar).

| Target | URL | Notes |
|---|---|---|
| Project | `/projects/agent-hub` | `?section=work` scrolls to Work in flight |
| Session | `/sessions/01923f1e-5091-7b98-8a6e-3f20c1d4a7b2` | short-id form redirects |
| Session tab | `/sessions/:id?tab=files` | `timeline` default, omitted |
| Selected event | `/sessions/:id?event=:eventId` | scrolls to and highlights the event (`accent-soft`), expands it; works for nested subagent events (lane auto-expands) |
| Timeline filters | `/sessions/:id?types=tool.call,tool.result&errors=1&q=check-fast` | `errors=1` is "Show only errors and decisions" |
| Follow tail | `/sessions/:id?follow=1` | ignored when the session has ended |
| Time axis | `/sessions/:id?axis=turn` | `time` default |
| File in session | `/sessions/:id?tab=files&repo=agent-hub&path=brain/features/layered-memory/eval.md` | |
| Decision | `/sessions/:id?tab=decisions&decision=:id` (P3) or `/knowledge/decisions?decision=:id` | |
| Raw event | `/sessions/:id?tab=raw&event=:eventId` | |
| Run step | `/runs/:id?step=verify&attempt=2` | |
| Approval | `/runs/:runId` (a workflow gate, Open gates) or `/sessions/:id` (any other) | the Approvals inbox is retired (AGH-273) |
| Learning | `/knowledge/learnings?learning=:id`, trace `/knowledge/learnings/:id/trace` | |
| Brain note | `/knowledge/brain?project=agent-hub&path=brain/now.md` | |
| Skills catalog | `/projects/agent-hub/skills?q=plan&kind=skill&mode=user-only` | search and facets in the query, updated with `replace` (a departure from the push rule below: typing must not fill the history); unknown values ignored |
| Skill detail | `/projects/agent-hub/skills/skill/hub-workflow/feature` | `kind/source/name`; `source` is the folder (`claude` for `.claude/`, `settings` / `settings-project` for hooks) |
| Feature AC | `/features/agent-hub/layered-memory?ac=AC-48.21` | |
| Metrics chart | `/metrics?metric=failure-stage&period=30d&group_by=step` | |
| Health finding | `/health?project=agent-hub&finding=:id` | |
| Lists with filters | `/sessions?agent=hub-workflow:evaluator&outcome=error&from=2026-10-01` | |

Rules:
- Selection changes (`event`, `decision`, `learning`) use `history.replaceState` so `Back` leaves the screen instead of stepping through 40 selected events. Tab changes and filter changes use `pushState` (they change what the page is about).
- Every event row, decision, finding and AC has a "Copy link" action (`link` icon) that copies the absolute URL with the current `tz`.
- A link to something that no longer exists (deleted hub, expired transcript content) resolves to the entity with an explanation, not a 404, whenever the structured record still exists.
- Unknown routes and unknown ids show the 404 `ProblemError`: title "Session not found", detail "No session has the id 5091b986 in the registered hubs. It may belong to a hub that was removed.", actions "Open command palette" and "Go to Portfolio".

## Keyboard map

Shortcuts are listed in the `ShortcutSheet` (`?`). Two-key sequences start with `g` and must complete within 1 s; a pending `g` shows a small `Kbd` hint at the bottom right ("g …"). Single-letter shortcuts are disabled while focus is in a text input, textarea, contenteditable or the palette (WCAG 2.1.4 character key shortcuts: the sheet offers "Turn off single-key shortcuts", stored in `ah.keys.single`).

### Global

| Keys | Action | Notes |
|---|---|---|
| `⌘K` / `Ctrl K` | Command palette | Works in inputs too |
| `?` | Shortcut sheet | `Shift /` on US layouts |
| `/` | Focus the page's search or filter field | On Session detail: search in session |
| `Esc` | Close the topmost layer: palette → dialog → popover → side panel → clear selection | Never navigates |
| `g p` | Portfolio | |
| `g l` | Sessions, grid view (`/sessions?view=grid`; alias kept from the retired Live sessions) | |
| `g s` | Sessions | |
| `g r` | Workflow runs | |
| `g k` | Learnings | |
| `g f` | Features | |
| `g w` | Workflows | P4 |
| `g m` | Metrics | |
| `g b` | Bench | |
| `g h` | Health | |
| `g t` | Tracker queue | |
| `g ,` | Settings | |
| `g o` | Open project switcher | |
| `g u` | Up one breadcrumb | |
| `t` | Toggle Local / UTC | |
| `Shift D` | Cycle theme | |

### Lists and tables (Sessions, Runs, Health, Tracker, Learnings)

| Keys | Action |
|---|---|
| `j` / `k` | Next / previous row (focus ring on row); on Sessions, next / previous tile or row across status sections |
| `Enter` / `o` | Open focused row |
| `x` | Select row (multi-select where supported; compare 2 in Sessions is P3) |
| `Shift J` / `Shift K` | Extend selection |
| `l` | Load more (when "Load more" is visible) |

### Session detail

| Keys | Action |
|---|---|
| `[` / `]` | Previous / next tab |
| `1`–`6` | Jump to the n-th visible tab (P3 order: Timeline, Files and diffs, Decisions, Context, Cost, Raw events; in P2 Decisions and Context are not shown, so `3` is Cost and `4` is Raw events) |
| `j` / `k` | Next / previous event |
| `Shift J` / `Shift K` | Next / previous turn |
| `e` / `Shift E` | Next / previous error or guard denial |
| `d` | Next decision |
| `Enter` / `Space` | Expand or collapse focused event |
| `Shift Enter` | Expand all in the focused group |
| `r` | Toggle Raw disclosure of focused event |
| `c` | Copy link to focused event |
| `Shift C` | Copy event id |
| `f` | Toggle follow tail (live only) |
| `Shift G` | Jump to latest event (and turn follow on if live) |
| `g g` | Jump to first event (does not collide with `g` navigation because `g` then `g` is unassigned elsewhere) |
| `Ctrl F` / `⌘F` | Search in session (scoped). Pressing it again while the scoped search is focused hands over to the browser's own find |
| `n` / `Shift N` | Next / previous search match |
| `a` | Toggle time axis wall-clock ⇄ turn |

### Sessions

| Keys | Action |
|---|---|
| `v` | Toggle grid / table view |
| `Enter` / `o` | Open the focused tile or row (the chat for a driven session) |

The Live sessions screen and its keys are retired ([ADR 0033](../../../adr/0033-sessions-and-chat-interaction-model.md));
the chat's own keys are in [agent-sessions.md](../../agent-sessions.md#chat-behaviour).

### Learnings triage (P3)

`a` accept, `r` reject (opens reason field), `s` snooze, `j`/`k` move. These are scoped to the triage list and override nothing global.

### Conflict notes

- `/` is the page search, not the browser's quick find (Firefox): the app calls `preventDefault` only when focus is on the page body.
- `Ctrl F` / `⌘F` is captured only on Session detail and only while the timeline has rendered; elsewhere the browser find works. A second press releases it, so the browser's find is never unreachable.
- `[` and `]` collide with nothing in Chrome/Firefox/Safari; on keyboards where they need AltGr (German, Portuguese layouts), `Alt ←` / `Alt →` are aliases that only work inside the tab list's focus scope (they are browser Back/Forward elsewhere and are not captured).
- `g g` vs `g <letter>`: the second key decides. `g` followed by nothing for 1 s cancels silently.
- `t` (time zone) and `f` (follow) are single keys; both are disabled in inputs and can be turned off with single-key shortcuts.
- `e` is "next error", not "edit": nothing in P2–P4 edits content in place.
- `⌘K` overrides the Safari/Chrome "focus address bar search" only on macOS Firefox (`⌘K` focuses web search); accepted because ⌘K is the de facto standard for command palettes. `Ctrl K` on Windows/Linux Chrome focuses the omnibox search; the app captures it only when the page has focus.
- Number keys `1`–`6` on Session detail do not conflict with list views (they mean nothing there).

## Navigation model rationale

| Choice | Principle (brief §7) |
|---|---|
| Five question-shaped top destinations (Portfolio, Sessions, Session timeline, Knowledge, Workflows) inside five groups that read as a verb sequence (Overview → Observe → Understand → Improve → Hub) | Shneiderman mantra: overview first (Portfolio), zoom and filter (lists, scope), details on demand (Session detail, Raw) |
| Sidebar with ≤ 13 visible items, grouped, with labels always visible when expanded | Hick–Hyman: choice time grows with log of options, grouping cuts the effective set to ~3 per group; recognition over recall (Nielsen #6) |
| Command palette accepts ids, issue keys, file paths and screen names | Recognition over recall for people who know an id; information scent (Pirolli and Card) for people who know only a fragment |
| Badges only on items that may need a person (Approvals, failed runs, doctor errors); routine counts neutral | Alarm fatigue (Sendelbach and Funk); pre-attentive colour reserved for exceptions (Healey and Enns) |
| Scope switcher filters every view and persists in URL and storage | Consistency and standards (Nielsen #4); working memory (Cowan ~4 chunks): one scope to remember, always visible |
| Collector pill always visible with "last event N s ago" | Visibility of system status (Nielsen #1); calibrated trust (Lee and See): the user knows how fresh what they see is |
| URL is the view state; every event has a permalink | Auditor persona reconstructs and shares exact moments; user control and freedom (Nielsen #3) |
| `g`-prefixed sequences, `j`/`k`, `?` sheet | Convention reuse from GitHub/Gmail lowers learning cost; accelerators for experts (Nielsen #7) while the mouse path stays complete |
| Breadcrumbs follow containment, not history | Gestalt common region: the run contains its sessions, and the trail tells the user where the evidence lives |
| P3/P4 screens hidden until shipped | Aesthetic and minimalist design (Nielsen #8); no dead ends |

## States of the shell

| State | What shows | Exact copy |
|---|---|---|
| Loading (first paint) | Sidebar and top bar render immediately from static config; badges show `Skeleton` pills after 300 ms | none |
| No hub registered | Every route redirects to `/welcome` except `/settings/*` | "Register your first hub to start" |
| Collector offline | Pill Offline + `Banner`; views keep cached data with `AsOfStamp` | "Collector offline since 14:02. Views show data as of 14:02. Start it with `hub collector start`." |
| Global stream error | Pill Reconnecting, then Offline | see pill table |
| Badge source unavailable | Badge hidden, item tooltip explains | "Approval count unavailable: collector offline" |
| Scope refers to removed project | Scope resets to All projects, `Toast` (result of user state, not routine) | "Project loki-trader is no longer registered. Showing all projects." |

## Responsive

- 1280×800 laptop: sidebar collapsed to 56 px by default (below 1360 px), top bar keeps all items; the search field shrinks to an `IconButton` `search` with `⌘K` hint below 1200 px. Breadcrumbs collapse middle crumbs.
- Mobile (< 640 px), glance routes only (`/sessions?view=grid`, `/sessions/:id` header; `/live` redirects to the first): sidebar becomes a bottom tab bar with three items (Portfolio, Sessions with live count, Search); the Approvals tab went with the screen (AGH-273). The top bar keeps scope switcher and collector pill (dot only, label in tooltip). Other routes render a simplified read-only page with "Best viewed on a larger screen" note under the title. Targets ≥ 44 px on touch (above the 24 px `control-sm` floor). Keyboard shortcuts are not advertised on touch.
