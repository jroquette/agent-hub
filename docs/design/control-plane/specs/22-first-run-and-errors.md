# First run, empty, offline and errors

**Phase:** P2 · **Routes:** `/welcome` (first run), any route (empty, offline, stale, loading), `/404` (not found), error states in place · **Answers:** "Is the app set up, is the data current, and what do I do when it is not?"

This section defines the cross-cutting states every screen inherits: the first-run checklist, per-screen "no events yet" copy, the collector offline banner, stale "as of" behaviour, the 404 page, Problem Details error rendering, and global loading / skeleton rules. Screen specs reference these instead of redefining them.

## CLI commands used in this section

The app quotes commands the user copies into a terminal. Existing `hub` commands are used as they are; commands the CLI does not have yet are marked **proposed CLI** everywhere they appear (in this spec and in the UI, as a small `idle` chip "proposed CLI" until the platform ships them, then removed by a version check against `platform.version`).

| Command | Status | Purpose |
|---|---|---|
| `./hub sync` | exists | Rewrite managed files from hub.json |
| `./hub doctor` | exists | Health checks (Health screen) |
| `./hub brief` | exists | Print the session brief |
| `./hub worktree <name>` | exists | Isolated worktree per issue |
| `./agent` | exists | Start Claude Code in the hub with every repo attached |
| `hub app` | proposed CLI | Start the local web app (`http://localhost:4317`) |
| `hub app add-hub <path>` | proposed CLI | Register a hub path (same as the in-app form, `POST /hubs`) |
| `hub collector start` | proposed CLI | Start the local event collector (`127.0.0.1:7420`, db `~/.agent-hub/events.db`) |
| `hub collector status` | proposed CLI | Print collector state, last event per source |
| `hub collector stop` | proposed CLI | Stop the collector |
| `./hub run <issue> --dry-run` | proposed CLI | Preview a workflow run on an issue (same plan as the P4 dry-run preview) |
| `make bench` | proposed (bench module target) | Run the bench cases in the hub |

The hub path in commands is taken from `GET /hubs` once a hub is registered; before that, the sample path `~/code/agent-hub-hub` is replaced by the placeholder `<path-to-your-hub>` in copy-ready commands.

---

## Screen 1: First run (onboarding checklist)

**Route:** `/welcome`; shown instead of Portfolio while `GET /hubs` returns no items or no event has ever been received. Reachable later from Settings › Hubs › "Setup checklist". **Answers:** "What do I need to do to see my agents?"

### Purpose and primary user

The first person to open the app on their machine (owner or developer). Goal: three steps, each verifiable live, ending on Portfolio with one project (flow 8). No account, no login (local single-user app).

### Layout (1440 px)

```
+--------+-------------------------------------------------------------------------------------------------+
|Sidebar | TopBar: [No projects]  [Search or jump to... Ctrl K]   (o Collector offline)                    |
|(items  +-------------------------------------------------------------------------------------------------+
| dimmed)|                                      (space-16 top margin)                                      |
|        |               Set up agent-hub on this machine                         (display style)          |
|        |               Three steps. Each one turns green when the app sees it work.                      |
|        |                                                                                                 |
|        |   +-------------------------------------------------------------------------------------------+ |
|        |   | (1) Register your hub                                                      (v) Done       | |
|        |   |     ~/code/agent-hub-hub · agent-hub · platform 0.8.0 · hub.json valid                    | |
|        |   +-------------------------------------------------------------------------------------------+ |
|        |   | (2) Start the collector                                          ( ) Waiting... (live)    | |
|        |   |     The collector receives events from Claude Code hooks and stores them locally.         | |
|        |   |     +-------------------------------------------------------------+                       | |
|        |   |     | hub collector start                                  [Copy] |  proposed CLI         | |
|        |   |     +-------------------------------------------------------------+                       | |
|        |   |     Check: collector reachable at 127.0.0.1:7420 ........ not yet (checked 2 s ago)       | |
|        |   +-------------------------------------------------------------------------------------------+ |
|        |   | (3) Start a Claude Code session in the hub                       ( ) Not started          | |
|        |   |     cd ~/code/agent-hub-hub && claude                                         [Copy]      | |
|        |   |     or, with every repo attached: cd ~/code/agent-hub-hub && ./agent          [Copy]      | |
|        |   |     Check: first event from this hub ........ waiting for step 2                          | |
|        |   +-------------------------------------------------------------------------------------------+ |
|        |                                                                                                 |
|        |   Your data stays on this machine. Secrets are redacted before storage.                        |
|        |   Transcripts are kept 30 days; structured events are kept. [Retention settings]               |
|        |                                                         [Skip for now]  [Go to Portfolio] (dim) |
+--------+-------------------------------------------------------------------------------------------------+
```

The column is centered, max 880 px. Steps are `ol` items with large step numbers. The current step is expanded; done steps collapse to one line with what was detected; future steps are visible but muted (so the whole path is known up front).

### Step details

**Step 1: Register your hub.**
- Form: label "Hub path", input placeholder `~/code/agent-hub-hub`, helper "The folder that contains hub.json.", button "Register hub" (primary). Alternative line: "Or from a terminal: `hub app add-hub ~/code/agent-hub-hub`" (proposed CLI).
- On submit: `POST /hubs` `{"path":"~/code/agent-hub-hub"}`. The response validates hub.json against `hub.schema.json` and reads `platform.version`, the lock, and the repos.
- Success line: "~/code/agent-hub-hub · agent-hub · platform 0.8.0 · hub.json valid". If the lock lags: "~/code/agent-hub-hub · agent-hub · platform 0.8.0 pinned, 0.7.0 synced (sync pending) · run `./hub sync` later". This is a warning, not a blocker.
- Errors (inline under the input, `failed` text, input keeps the value):
  - Path missing: "No folder at ~/code/agent-hub-hubb. Check the path."
  - No hub.json: "No hub.json in ~/code/agent-hub. This looks like a repo, not a hub. The hub is usually next to it, e.g. ~/code/agent-hub-hub."
  - Invalid: "hub.json does not match the schema: repos[0].check is required (line 22)."
  - Already registered: "This hub is already registered as agent-hub." (step marked done).
- "Add another hub" link appears after success (loki-trader can be added now or later in Settings › Hubs).

**Step 2: Start the collector.**
- Explanation: "The collector receives events from Claude Code hooks and stores them locally."
- Command: `hub collector start` (proposed CLI), copy button. Secondary: "Check from a terminal: `hub collector status`" (proposed CLI).
- Live check: the app polls `GET /collector/status` every 2 s while this step is open (and listens on `GET /events/stream` once reachable). States: "not yet (checked 2 s ago)" → "reachable · db ~/.agent-hub/events.db · waiting for events" (green).
- If not reachable after 60 s: helper expands: "Still not reachable. Is something else using port 7420? Run `hub collector status` (proposed CLI) to see the error. Change the port in Settings › Collector."

**Step 3: Start a Claude Code session in the hub.**
- Commands: `cd ~/code/agent-hub-hub && claude` and `cd ~/code/agent-hub-hub && ./agent`.
- Why in the hub: "The hub's hooks send events to the collector. Sessions started outside the hub directory do not load them."
- Live check: first `session.start` event whose project matches a registered hub. Line updates: "waiting for step 2" → "listening for the first event…" → "Session 5091b986 started 4 s ago in agent-hub (claude_code hooks)" (green).
- If events arrive from an unregistered folder: "Events are arriving from ~/code/agent-hub (a repo, not a registered hub). Start the session in the hub directory instead."

**Completion.** When the three checks are green: headline changes to "You are set up" and the primary button "Go to Portfolio" becomes active; after 3 s without interaction, a non-intrusive line offers "Opening Portfolio…" with "Stay here" (no auto-redirect under reduced motion preference; the button stays). Portfolio then shows one project (agent-hub) with one live session.

### Components

`AppShell` (sidebar items dimmed but navigable), `TopBar`, `CollectorPill`, `EmptyState` (display headline variant), `Button`, `CodeBlock` (copy), `StatusBadge` (done / waiting / idle per step), `Banner` (none on this screen: the checklist itself carries status), `Kbd`, `Tooltip` (for "proposed CLI" chip: "This command is planned. Until it ships, see Settings › Collector for the manual start command.").

### Data mapping

| Element | Entity.field (brief §3) | API resource | Source · latency |
|---|---|---|---|
| Step 1 status | Hub registered, hub.json valid, platform version, lock state | `GET /hubs` → `items[].{path, project, platform_pinned, platform_locked, lock_state, valid, errors[]}`; `POST /hubs` | local filesystem · < 1 s |
| Step 2 status | Collector status | `GET /collector/status` → `{state, address, db_path, events_today, last_event_by_source}` | collector · polled 2 s |
| Step 3 status | first session.start for a registered project | `GET /events/stream` (`session.start`) or `GET /sessions?limit=1` | claude_code hooks · real time |
| Privacy line | retention settings | `GET /settings` → `retention.transcript_days` | local |

### States

| State | What shows | Exact copy |
|---|---|---|
| Fresh install | Step 1 open | Headline "Set up agent-hub on this machine" |
| Partially done (returning) | Done steps collapsed with detected values | (as above) |
| All done | Headline swap | "You are set up" / "agent-hub is sending events. Your first session is live." |
| Skip for now | Goes to Portfolio with empty states; a `Banner` (info) offers to return | "Setup not finished: the collector is not running. [Resume setup]" |
| App API not reachable | `ProblemError` full page | "The app's server is not responding" / "Start it with `hub app` (proposed CLI) and reload this page." [Reload] |

### Actions by phase

| Action | Phase | Confirmation? | Consequence |
|---|---|---|---|
| Register hub | P2 | No | `POST /hubs`; reversible from Settings |
| Remove hub (Settings) | P2 | Yes | `DELETE /hubs/{id}`; stops reading its files; collected events kept until retention ends |
| Start collector from the app | Not planned in P2 | n/a | The app does not run processes in P2 |

---

## Per-screen "no events yet" copy

Every `EmptyState` names the source that feeds the screen and the next action. Pattern: headline (what is missing, plain) + one sentence (which source fills it, and when) + one command or link. Commands are copyable `CodeBlock`s. These apply when the hub is registered and the collector is running but the screen's source has not produced data yet; if the collector is offline, the offline banner is shown in addition and the copy is unchanged.

| Screen (sitemap) | Feeding source | Headline | Body and action |
|---|---|---|---|
| Portfolio | hubs + all sources | "No activity yet" | "Projects appear when a hub is registered; numbers fill in as sessions and runs report. [Register a hub] or start a session: `cd ~/code/agent-hub-hub && claude`" |
| Portfolio › Needs you (empty is good) | approvals, runs, doctor, learnings | "Nothing needs you." | "3 sessions running." (or "No session is running.") |
| Project overview › Now | `brain/now.md` | "No current focus recorded" | "This reads brain/now.md in the hub. `/handoff` updates it at the end of a session." |
| Project overview › Work in flight | executor | "No run in flight" | "Runs appear when the executor picks an issue labelled agent-ready." |
| Approvals | claude_code hooks (gate.request), executor (human steps) | "Nothing waits for you." | "Plan approvals, human gates and guard requests appear here when an agent asks." |
| Live sessions | claude_code hooks (real time) | "No session is running." | "Sessions appear here when Claude Code starts in a hub with the collector on: `cd ~/code/agent-hub-hub && claude`" |
| Sessions list | claude_code hooks + transcript | "No sessions yet." | "Each Claude Code session in a registered hub is listed here after its first event." |
| Session detail › Timeline | hooks + transcript | "No events in this session yet" | "Tool calls arrive in real time from hooks; messages and reasoning summaries arrive after each turn's transcript is read." |
| Session detail › Files & diffs | hooks (Edit, Write, Read tool calls) | "No files touched" | "This session has not read or changed a file yet." |
| Session detail › Decisions (P3) | transcript extraction, `/decide` | "No decisions recorded" | "Decisions appear when the agent records one with /decide, or when they are extracted from the transcript after the session." |
| Session detail › Context (P3) | hooks (session.start), transcript | "Context not captured" | "The context is read at session start. This session started before the collector was running." |
| Session detail › Cost | otel | "No token or cost data" | "Cost comes from OpenTelemetry. Enable it in the hub: see Settings › Collector › OpenTelemetry." |
| Session detail › Raw events | all sources | "No events" | "Nothing has been recorded for this session." |
| Workflow runs list | executor | "No workflow runs yet." | "Runs appear when the executor picks an issue labelled agent-ready. Start one: `./hub run AGH-112 --dry-run` (proposed CLI)." |
| Run detail › Gantt | hooks + executor | "No sessions in this run yet" | "The run is at Picked. Sessions appear when the Implement step starts." |
| Run detail › PR and CI | github | "No PR yet" | "The PR appears when the run reaches PR open. GitHub is polled every minute." |
| Knowledge › Brain (P3) | hub files `brain/` | "No brain in this hub" | "This reads brain/ in the hub. Run `./hub sync` to create the skeleton." |
| Knowledge › Learnings (P3) | learning.proposed events + `brain/_inbox/` | "Inbox empty" | "Agents propose learnings with /learn; notes in brain/_inbox/ appear here for triage." |
| Knowledge › Provenance trace (P3) | learnings + git history | "Nothing to trace yet" | "Accept a learning to see its path from the session to the rule in effect." |
| Knowledge › Decisions log (P3) | `brain/decisions/`, `docs/adr/`, extracted decisions | "No decisions yet" | "This lists brain/decisions/index.md, ADRs in each repo's docs/adr/, and decisions extracted from sessions." |
| Knowledge › Context inspector (P3) | instruction files, brain, session.start | "No session to inspect" | "The inspector shows what a session loaded. Start a session in the hub first." |
| Features | `brain/features/` | "No feature records yet." | "Features appear when /feature writes brain/features/<slug>/spec.md. Start one in a session: `/feature AGH-112`" |
| Feature detail › Evaluation | `eval.md` | "Not evaluated yet." | "The evaluator agent writes eval.md at the end of the golden path." |
| Workflows › Catalog (P4) | hub workflow files | "No workflows defined" | "Workflows are YAML files in the hub. `./hub sync` installs the default issue-to-pr workflow." |
| Workflows › Detail overlay (P4) | executor (runs per node) | "No runs of this revision" | "The stuck-points overlay needs at least 1 run. n = 0." |
| Metrics | derived from runs, sessions, github | "Not enough data" | "Charts need at least 3 runs in the period. 0 runs in the last 7 days. [Widen to 30 d]" |
| Bench | bench module results | "No bench results" | "Run the bench in the hub: `make bench` (proposed target, bench module). Results are read from the hub after each run." |
| Health | `hub doctor` output | "The doctor has not run on this hub yet." | "`cd ~/code/agent-hub-hub && ./hub doctor`" |
| Tracker queue | linear | "No issue labelled agent-ready" | "Label an issue agent-ready in Linear team AGH. The queue is polled every minute." |
| Settings › Collector | collector | "Collector not running" | "`hub collector start` (proposed CLI)" |

---

## Collector offline banner

**Trigger:** same rule as the `CollectorPill` in the navigation spec: SSE closed and reconnect failing, or no heartbeat for more than 60 s, or `GET /collector/status` returns `state: stopped|unreachable`. Recovery: first heartbeat.

```
+-----------------------------------------------------------------------------------------------+
| (!) Collector offline since 14:02. Views show data as of 14:02.                               |
|     Start it with hub collector start  [Copy]  (proposed CLI)    [Collector settings]   [x]  |
+-----------------------------------------------------------------------------------------------+
```

- `Banner` variant `offline`: ground `idle-soft`, icon and left edge `waiting`, text `text`. Placed under the `TopBar`, above page content, `z-banner`. Not modal: every view stays usable.
- Dismissible (x) until the state changes; when dismissed, the `CollectorPill` keeps the state ("Offline · as of 14:02") so it is never hidden completely.
- `CollectorPill` states (defined in the navigation spec, repeated here): "Connected · last event 3 s ago" (`done` dot), "Delayed" (`waiting` dot), "Offline · as of 14:02" (`failed` dot on `failed-soft`, no pulse).
- On recovery: the banner is replaced for 5 s by "Collector back at 14:09. Catching up: 1,204 events." then disappears; no toast (routine event).
- Partial source outages (otel, github, linear) do not use this banner: they show inline partial states on the screens that depend on them, and the pill popover lists each source: "claude_code hooks · ok · 0.4 s", "transcript · ok · after each turn", "otel · not reporting since 08:40", "github · ok · polled 34 s ago", "linear · error 401 since 09:12".

---

## Stale "as of" behaviour

A view is stale when its data cannot be current: collector offline, a source not reporting, or SSE disconnected.

- `AsOfStamp` appears next to the page title: "As of 14:02" (`idle-soft` ground, clock icon, `caption`). Tooltip: "Last update received at 14:02:31 (11 Oct, local). The collector is offline."
- Live affordances stop: pulse dots become a static `idle` clock icon; ticking durations freeze and show "≥ 38 min"; "now" lines in Gantt / timelines stop at the as-of time with a dashed extension.
- Statuses do not change by themselves: a session shown as live stays "live (as of 14:02)" rather than being guessed as ended.
- Relative times are computed against the as-of time for live values ("last action 1 min before 14:02"), but historical timestamps keep their absolute values.
- Per-source staleness is local to elements: CI cells "as of 09:12" when GitHub is down; cost "as of 08:40" when otel is down.
- SSE reconnect uses `Last-Event-ID`; on resume, missed events are merged without reordering what the user is reading; a pill "12 new events ↓" appears where follow-tail is off.

---

## Screen 2: Not found (404)

**Route:** `/404` (also rendered in place for any unknown route or entity). The shell stays.

```
+--------+-------------------------------------------------------------------------------------------------+
|Sidebar | TopBar                                                                                          |
|        |                                                                                                 |
|        |               This page does not exist                                   (display)              |
|        |               No session with id 5091b98x in agent-hub or loki-trader.                          |
|        |               It may be in a hub that is no longer registered, or the id is mistyped.           |
|        |                                                                                                 |
|        |               [Search with Ctrl K]   [Go to Portfolio]                                          |
|        |               Requested: /sessions/5091b98x                                                     |
+--------+-------------------------------------------------------------------------------------------------+
```

Copy by entity (body line 1):
- Unknown route: "There is no page at /sesions. Check the address or search."
- Session: "No session with id 5091b98x in agent-hub or loki-trader."
- Run: "No workflow run with id 01923f1x."
- Feature: "No feature layered-memroy in agent-hub."
- Issue (palette): "AGH-999 has no runs or sessions in this app. [Open AGH-999 in Linear]"
- Expired session: not a 404. Sessions with expired transcripts still exist; the session page shows `ExpiredContent`.

Primary action "Search with Ctrl K" opens the `CommandPalette` prefilled with the id or path from the URL. Secondary "Go to Portfolio".

---

## Problem Details error rendering

All API errors are RFC 9457 Problem Details (`type`, `title`, `status`, `detail`, optional `instance`). `ProblemError` renders them consistently.

```
+-----------------------------------------------------------------------------+
| (x) Could not load workflow runs                       (title)              |
|     The collector database is locked by another process.  (detail)         |
|     status 503 · request 0192a7c4             [Retry]  [Copy details]       |
+-----------------------------------------------------------------------------+
```

- Scope: the error replaces only the region whose request failed (table, panel, chart). The shell, header, filters and other regions stay. A full-page error only when the route's primary resource fails and nothing else can render.
- Title = Problem `title` (the API writes them in sentence case and plain words); detail = `detail`; footer = status + the `instance` short id. "Copy details" copies the full JSON (redacted by the server already).
- Retry: re-sends the same request; the region shows its skeleton while retrying. After 3 failed retries, the button text becomes "Retry again" and the hint "If this keeps failing, check the collector: `hub collector status` (proposed CLI)."
- Automatic retry only for 502/503/504 with backoff 1 s, 3 s, 10 s, visible as "Retrying in 3 s…" with "Retry now".
- Client-side fallbacks (no Problem body, e.g. network down): title "The app's server is not responding", detail "Check that `hub app` (proposed CLI) is still running, then retry."
- 400 errors from filters show inline at the filter, not as a region error: "Cost range: enter a number like 2.50."
- 409 on P4 actions shows inline at the action bar with what to do (e.g. "Approve in the terminal instead").

Sample messages (final copy, server-side titles):

| Status | Title | Detail |
|---|---|---|
| 400 | Invalid filter | Filter `cost_min` must be a decimal, for example 2.50. |
| 404 | Not found | No session with id 5091b98x. |
| 409 | Session not reachable | Session 5f21c0aa ended before the decision was delivered. |
| 422 | Hub configuration invalid | hub.json: repos[0].check is required (line 22). |
| 500 | Internal error | Reading steps for run 01923f1e failed. The error was logged at ~/.agent-hub/app.log. |
| 503 | Collector database busy | The collector database is locked by another process. |

---

## Global loading and skeleton rules

| Rule | Value |
|---|---|
| Nothing shown before | 300 ms: no spinner, no skeleton (avoids flashes on fast loads) |
| After 300 ms | `Skeleton` shaped like the final layout (same row heights `row-compact` / `row-comfortable`, same column widths, same card sizes) so nothing shifts on arrival |
| Minimum skeleton time | Once shown, at least 300 ms, to avoid flicker |
| After 10 s | Inline line under the skeleton: "Still loading… large sessions can take a few seconds." with "Cancel" for user-started queries (filters) |
| Shimmer | `gray-400` on `gray-100`, one sweep per 1.6 s; static (no shimmer) under prefers-reduced-motion |
| Region independence | Each region loads and fails on its own; the fastest region renders first (e.g. table rows before facet counts) |
| Navigation | Route change keeps the previous screen visible with a 2 px `accent` progress bar under the top bar until the new primary data arrives or 300 ms passes (then skeleton) |
| Buttons | Actions show the verb in progress ("Approving…", "Registering…") and are disabled while pending; no optimistic UI except for reversible local changes (filters, saved views) |
| Live insertion | New streamed items fade + 4 px slide (`dur-base`, `ease-out`); none under reduced motion |
| Accessibility | Skeleton regions have `aria-busy="true"` and one polite announcement "Loading sessions" only if loading passes 1 s |

Response-time limits drive these values: 0.1 s feels instant (hover, chips: `dur-fast`), 1 s keeps flow (navigation bar), 10 s is the attention limit (explicit "still loading" message and cancel).

---

## Components (all states above)

| Component | Variant |
|---|---|
| `EmptyState` | Default (headline `subheading`, body, one action) and display (first run, "Nothing needs you.") |
| `Banner` | offline, info (partial source), failure (run failed; defined in Run detail) |
| `CollectorPill` | connected / delayed / offline, with per-source popover |
| `AsOfStamp` | inline (title), cell (per-source) |
| `ProblemError` | region, full page |
| `Skeleton` | row, card, chart, text-block |
| `CodeBlock` | copyable command with optional "proposed CLI" chip |
| `CommandPalette` | Opened from 404 with the query prefilled |

## Data mapping (cross-cutting)

| Element | Entity.field (brief §3) | API resource | Source · latency |
|---|---|---|---|
| Collector pill and offline banner | collector heartbeat, last event per source | `GET /events/stream` (heartbeat every 5 s), `GET /collector/status` | collector · real time |
| Per-source health in pill popover | source latency (claude_code, transcript, otel, executor, github, linear) | `GET /collector/status` → `sources[]` `{source, state, last_event_at, latency_ms, error}` | collector |
| As-of time | last received event / last successful fetch | client state from SSE + response `Date` | derived client-side |
| Problem Details | error responses | any endpoint → `application/problem+json` | API |
| Hubs for commands | hub path | `GET /hubs` | local |

## Interactions

- Copy buttons everywhere: label switches to "Copied" for 2 s; polite live region "Command copied".
- `Esc` dismisses the offline banner when focused; `?` opens the `ShortcutSheet` from any state, including 404.
- Ctrl K works on every state screen; on 404 it opens prefilled.
- First-run checklist: Tab order follows steps; the live check lines are `aria-live="polite"` and announce only status changes ("Collector reachable.").

## States (summary)

| State | What shows | Exact copy |
|---|---|---|
| Loading | Skeleton after 300 ms | "Loading sessions" (screen reader only, after 1 s) |
| Empty | Per-screen copy table above | (see table) |
| Partial | Inline per-source states + pill popover | "GitHub not reachable, CI unknown." |
| Error | `ProblemError` | Title + detail + status + Retry |
| Live | Pill "Connected · last event 3 s ago" | (as written) |
| Stale | `AsOfStamp` + frozen live affordances | "As of 14:02" |
| Offline | Banner + stale | "Collector offline since 14:02. Views show data as of 14:02. Start it with `hub collector start`." |
| Not found | 404 | "This page does not exist" + entity line |

## Actions by phase

| Action | Phase | Confirmation? | Consequence |
|---|---|---|---|
| Register hub | P2 | No | Adds a hub (`POST /hubs`) |
| Copy commands, retry, search | P2 | No | None |
| Dismiss offline banner | P2 | No | Hidden for this outage; pill still shows state |
| Start / stop collector from the app | Not planned (P2–P4) | n/a | Process control stays in the terminal (local-first, least privilege for the web app) |

## UX principles applied

| Choice | Principle (brief §7) |
|---|---|
| Three steps, each with a live check that turns green | Nielsen visibility of system status; calibrated trust (the app shows it really receives events) |
| Every empty state names its source and the command that fills it | Nielsen help users recover; information scent |
| Offline banner non-blocking, views usable with "as of" | Endsley perception (data age is explicit); graceful degradation |
| Live affordances freeze instead of guessing | Principle 3: show only what the record shows |
| No skeleton before 300 ms; message at 10 s | Response time limits (0.1 / 1 / 10 s) |
| Errors scoped to the failing region with Problem title + detail | Nielsen error recovery; keeps the rest of the screen useful |
| No toast for collector recovery | Alarm fatigue (Sendelbach & Funk) |
| "proposed CLI" chip on unreleased commands | Honesty and trust; principle 3 |
| Privacy line on first run | Principle 5: privacy first, stated at the moment of setup |

## Responsive

- **1280×800:** first-run column 720 px; commands wrap with the copy button kept on the first line; the offline banner collapses to one line ("Collector offline since 14:02 · data as of 14:02 · [Copy start command]").
- **Mobile (glance screens only):** offline state is a one-line strip under the header ("Offline · as of 14:02"); empty states keep headline + body, commands are hidden behind "Show command" (copy is rarely useful on a phone); 404 and errors render the same copy in a single column. First run on mobile shows: "Set up agent-hub on the computer where your hub lives." with no steps.
