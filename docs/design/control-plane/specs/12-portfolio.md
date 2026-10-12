# Portfolio and project overview

**Phase:** P2 (no actions before P3/P4; tagged inline) · **Route:** `/?scope=&period=24h|7d|30d|custom&from=&to=&view=cards|table` and `/projects/:project?period=&section=` · **Answers:** "How are my projects doing, and what needs me?"

Two screens share this section: the Portfolio (all projects, the app's home) and the Project overview (one project, zoomed in). The Portfolio is the first step of the morning check (flow 1, under 30 s) and of the cost investigation (flow 7).

Sample state: 2026-10-11 09:12 local, period 7 d (2026-10-04 09:12 → now), last visit 2026-10-10 18:40.

---

## Portfolio

### Purpose and primary user

The **owner / tech lead** opens it first thing: "anything stuck or failing? what needs me?" must be answered in under 10 seconds, before reading any project. Then: are the projects healthy, is cost moving, what happened since yesterday. The developer uses it as a launcher to their project.

### Layout

#### 1440 px, cards view

```
┌──────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│ Portfolio                                                        Period [24 h|7 d|30 d|Custom]  View [▦|≡]   │
│ 2 projects · 4 running · since your last visit (yesterday 18:40): 1 run failed, 1 PR merged                   │
├──────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ NEEDS YOU · 5                                                                                                 │
│ ▌⊡ Approve plan for AGH-131              agent-hub · planner · 6 ACs, 3 files              waiting 41 min  ›  │
│ ▌⊗ Look at failed run AGH-79             agent-hub · failed at verifying, attempt 2 of 2   2 h ago         ›  │
│ ▌⊘ Unblock session in tradeSentinel     loki-trader · Stop blocked: check_fast failing     14 min ago      ›  │
│ ▌⊗ Fix doctor error in agent-hub          instructions.size · AGENTS.md: 132 lines, limit 100  since 3 d  ›  │
│   Show 1 more (Triage 15 learnings)                                                                           │
├──────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ ┌───────────────────────────────────────────────────┐ ┌───────────────────────────────────────────────────┐  │
│ │ ● agent-hub                       0.8.0 (Sync pending)│ ● loki-trader                    0.8.0             │  │
│ │ jroquette/agent-hub-hub · AGH · 1 repo             │ │ jroquette/loki-trader-hub · LOK · 2 repos          │  │
│ │                                                    │ │                                                    │  │
│ │ Live 3 ●   Runs in flight 2   Ready issues 4       │ │ Live 2 ●   Runs in flight 2   Ready issues 6       │  │
│ │ [P W I V R] ░░█░▒░  implementing 1 · plan gate 1   │ │ [P W I V R] ░░█░█░  implementing 1 · PR open 1     │  │
│ │ Open PRs 2 · CI ✓ 1 ⋯ 1    Failed runs 1           │ │ Open PRs 3 · CI ✓ 2 ⋯ 1    Failed runs 1           │  │
│ │ Cost $61.40  ▁▂▃▂▅▃▆  +22.6 % vs $50.10            │ │ Cost $22.80  ▂▃▂▂▃▂▃  +7.2 % vs $21.26             │  │
│ └───────────────────────────────────────────────────┘ └───────────────────────────────────────────────────┘  │
├──────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ Totals · 7 d   Cost $84.20 (+18 %)   Runs finished 10 (8 reported, 2 failed)   Median run $4.10              │
├──────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ ACTIVITY                                                                         [All|PRs|Runs|Learnings|Health]│
│ ⇲ PR agent-hub #69 merged · AGH-48 Layered memory                                agent-hub      yesterday 17:05│
│ ! Run AGH-48 reported · SHIP-WITH-OWNER-STEPS · 21/21 ACs                         agent-hub      yesterday 16:58│
│ ⊗ Run AGH-79 failed at verifying · make check exit 2                              agent-hub      today 07:10    │
│ + Learning accepted · Bash rules match subcommands → brain/learnings/gotchas/…    agent-hub      2 d ago        │
│ △ Doctor regression · instructions.size error (AGENTS.md 132 lines)               agent-hub      3 d ago        │
│ ⇲ PR loki-trader-ui #212 merged · LOK-302 Depth chart tooltip                     loki-trader    3 d ago        │
│ [Load more]                                                                                                   │
└──────────────────────────────────────────────────────────────────────────────────────────────────────────────┘
```

Layer-cake order: page header with "since your last visit" line → Needs you → projects → totals → activity. The first two answer the 10-second question; the rest is for the next 20.

#### Table view (`?view=table`)

```
│ Project      Health  Repos  Live  In flight (P W I V R)  Open PRs · CI   Failed 7 d  Cost 7 d       Δ      Ready  Platform          │
│ agent-hub    ● warn     1     3   ░░█░▒░  2              2 · ✓1 ⋯1       1           $61.40 ▁▂▃▅▆  +22.6 %   4   0.8.0 Sync pending │
│ loki-trader  ● ok       2     2   ░░█░█░  2              3 · ✓2 ⋯1       1           $22.80 ▂▃▂▃▃  +7.2 %    6   0.8.0             │
│ Total                   3     5           4              5               2           $84.20        +18.0 %  10                     │
```

`DataTable` with sticky header (`z-sticky`), sortable columns, row click opens the project. The table is the better view from 5 projects up; the toggle remembers the choice in `ah.portfolio.view` and `?view=`.

### Components

| Element | Component (variant) |
|---|---|
| Period | `SegmentedControl` (24 h, 7 d, 30 d, Custom → `Popover` with date range) |
| View toggle | `SegmentedControl` icon variant (`layout-grid`, `table`) with labels in tooltips |
| Needs you | `NeedsYouList` (rows variant, `waiting-soft` ground per item, kind icon) |
| Project card | `ProjectCard` with `StatusBadge` (health dot), `KpiStat` (inline small), `MiniStageBar`, `Sparkline`, `Money`, `StatusBadge` "Sync pending" (waiting variant) |
| Project table | `DataTable` (comfortable density), same cells |
| Totals | `KpiStat` row |
| Activity | `ActivityFeed` with `FilterChip` group |
| States | `Skeleton`, `EmptyState`, `ProblemError`, `AsOfStamp`, `Banner` |

### Needs you strip

One line per item: kind icon · verb phrase (`body-strong`) · context (project, who, short reason; `small`, `text-muted`) · age (`Time`, relative; absolute in tooltip) · chevron. Whole row is the link. Ground `waiting-soft` with a 3px left edge whose colour follows the kind (waiting amber for approvals; `failed` for failures and doctor errors; `blocked` for blocked sessions; `text-muted` neutral for learnings).

Kinds, verbs and destinations:

| Kind | Verb pattern | Context | Destination | Included when |
|---|---|---|---|---|
| Approval (plan, spec, human gate) | "Approve plan for AGH-131" | project · requester · material size | `/approvals/:id` | open `gate.request` kind human |
| Guard ask | "Answer guard ask in session 3e8d0a11" | "Edit under docs/adr/ needs approval" | `/approvals/:id` | open `gate.request` kind guard_ask |
| Failed run | "Look at failed run AGH-79" | "failed at verifying, attempt 2 of 2" | `/runs/:id` (failure banner focused) | run FAILED since last visit and not yet opened |
| Blocked or stuck session | "Unblock session in tradeSentinel" | "Stop blocked: check_fast failing" / "Idle 45 min with uncommitted changes" | `/sessions/:id?event=:blockingEventId` | outcome blocked, `hook.blocked` in last hour, or idle > 30 min inside a live run |
| Doctor error | "Fix doctor error in agent-hub" | rule · path · message | `/health?project=agent-hub&finding=:id` | severity error (warnings never appear here) |
| Learnings | "Triage 15 learnings" | "oldest 9 days · 1 from external content" | `/knowledge/learnings?status=proposed` (P3); before P3 the item links to the hub inbox path `brain/_inbox/` on GitHub | ≥ 1 proposed learning; always one aggregated line |

Ordering rules:
1. Kind priority: approvals and guard asks (an agent is blocked on a person) → blocked sessions → failed runs → doctor errors → learnings.
2. Within a kind: oldest first (longest wait first), because wait time is the cost being paid.
3. A failed run whose failing session is also the blocked session appears once, as the failed run.
4. Items the user opened since they appeared drop below unopened items of the same kind and lose their left edge colour (they stay until resolved, because "seen" is not "done").

Cap: 4 visible lines (working memory ~4 chunks, Cowan 2001). The rest collapse into "Show N more (…)" listing the hidden kinds in the label ("Show 1 more (Triage 15 learnings)"). Expanding shows all, max 12, then "Open Approvals" / "Open Health" links per kind. The strip header shows the total: "Needs you · 5".

Empty copy (no items): "Nothing needs you. 4 sessions running." in `body` with a `done` check icon; with nothing running: "Nothing needs you. No session is running."

### Project card

| Line | Content | Notes |
|---|---|---|
| Title | Hub health dot (`done` ok / `waiting` warning / `failed` error, plus text in tooltip "Health: 1 error, 2 warnings"), project name (`subheading`), platform version, "Sync pending" badge when `lock_state` is sync_pending or drift ("Drift") | Name links to `/projects/:project` |
| Subtitle | hub repo, tracker team keys, repo count | `small`, `text-muted` |
| KPI line | Live sessions (with pulse dot when > 0, links to `/live?scope=`), Runs in flight, Ready issues (links to `/tracker?project=`) | Numbers `figure` |
| Stages | `MiniStageBar`: 6 segments Picked · Worktree · Implementing · Verifying · PR open · Reported, filled where runs sit now; a waiting gate shows as hatched amber on its stage; caption lists non-zero stages "implementing 1 · plan gate 1" | Hover a segment: run list |
| PRs and failures | "Open PRs 2 · CI ✓ 1 ⋯ 1" (passed, running, failed with icons, not colour alone), "Failed runs 1" (period) | Failed count links to `/runs?project=&outcome=failed&from=` |
| Cost | Cost this period, `Sparkline` (daily), delta vs previous period with the previous value ("+22.6 % vs $50.10") | Delta text neutral; arrow icon `trending-up`/`trending-down`; red only when > +50 % (deviation, not every increase) |

Tooltip on every number states the period: "Cost 2026-10-04 09:12 → 2026-10-11 09:12 (7 d), all sessions of agent-hub. Previous 7 d: $50.10."

Card order: projects with Needs-you items first, then by live sessions, then alphabetical. Cards are 2 per row at 1440 px (min width 480px), 1 per row below 1100 px.

### Activity feed

Merged, reverse-chronological events of interest (not every event): PR merged, run reported, run failed, learning accepted, doctor regression (new error or warning), hub synced to a new platform version. Each row: icon, sentence with the key entity linked, project, `Time`. Filter chips: All, PRs, Runs, Learnings, Health. 20 rows, "Load more" (cursor). Routine items (session started, tool calls) never appear. External content (a PR title) is shown as data in mono-free body text; it is not styled as a statement.

### Period selector

- Options: 24 h, 7 d (default), 30 d, Custom (date range popover, max 180 d). Stored in `?period=` (and `?from=&to=` for custom) and in `ah.period`.
- Applies to every number on the page: failed runs, cost, delta (previous period of equal length), runs finished, median run, activity window. Live, in flight, ready issues and Needs you are "now" values and say so in their tooltip ("Now, not affected by the period").
- Every period number's tooltip names the period with absolute dates.

### Data mapping

| Element | Entity.field (brief §3) | API resource | Source · expected latency |
|---|---|---|---|
| "Since your last visit" line | counts of runs failed, PRs merged after `last_seen_at` | `GET /activity?scope=&since=` (client passes `ah.lastVisit`) | executor, github · ≤ 60 s |
| Needs you items | Gate (open), WorkflowRun.failure, Session.outcome blocked, Finding severity error, Learning status proposed | `GET /needs-you?scope=`; updates from `GET /events/stream` `counts` | hooks, executor, hub files · < 1 s to 15 min |
| Needs you age | Gate.requested_at, WorkflowRun failure time, Finding.first_seen_at | `GET /needs-you` | as above |
| Project name, hub repo, teams | Project.name, hub_repo, tracker.teams | `GET /projects` | hub files · < 2 s |
| Repo count | count Project repos | `GET /projects` | hub files |
| Health dot | Project.hub_health | `GET /projects` | doctor · ≤ 15 min |
| Platform version, Sync pending | Hub.platform_version, lock_state | `GET /projects` | hub files · < 2 s |
| Live sessions | Project.live_sessions | `GET /projects`; `counts` stream | hooks · < 1 s |
| Runs in flight, stage bar | Project.runs_in_flight_by_stage | `GET /projects` | executor · < 1 s |
| Ready issues | Project.ready_issues (agent-ready label) | `GET /projects` | linear · ≤ 60 s |
| Open PRs and CI | Project.open_prs, CI per head commit | `GET /projects` (`open_prs`, `ci_summary`) | github · ≤ 60 s |
| Failed runs (period) | count WorkflowRun stage FAILED in period | `GET /projects?period=` | executor |
| Cost, sparkline, delta | Project.cost_period, cost_previous_period, daily series | `GET /projects?period=` (`cost_series`) | otel · 1–5 s |
| Totals row | sums of project fields; median WorkflowRun.cost_usd | `GET /metrics/cost-per-run?scope=&period=` | otel |
| Activity rows | merged PRs, run.end, learning.accepted, doctor regressions | `GET /activity?scope=&period=&kinds=` | github, executor, hub files |

### Interactions

| Input | Result | URL |
|---|---|---|
| Click a Needs-you row / `Enter` on focused row | Destination per kind | entity route |
| `j` / `k` | Move through Needs-you rows, then project cards | none |
| "Show 1 more" | Expand strip | `?needs=all` (replace) |
| Click project card title or card body | Project overview | `/projects/agent-hub?period=7d` |
| Click a KPI on a card | Filtered list (live, tracker, runs) | e.g. `/runs?project=agent-hub&outcome=failed&from=2026-10-04` |
| Hover stage segment | Popover listing runs in that stage | none |
| Click cost delta | Metrics cost per run for that project | `/metrics?metric=cost-per-run&scope=agent-hub&period=7d` (flow 7) |
| Period control | Recompute all period numbers | `?period=` |
| View toggle | Cards ⇄ table | `?view=` |
| Activity chip | Filter feed | `?activity=runs` |

### States

| State | What shows | Exact copy |
|---|---|---|
| Loading (> 300 ms) | Needs-you 3 skeleton rows; 2 card skeletons; feed 6 rows | none |
| First run (no hub) | Redirect to `/welcome` | "Register your first hub to start" |
| Empty: hubs registered, no events yet | Cards with zeros and a note; Needs you shows empty copy; feed empty | Card note "No sessions yet. Start Claude Code in jroquette/agent-hub-hub with the collector on." · feed "Nothing happened in this period." |
| Needs you empty | Single line | "Nothing needs you. 4 sessions running." |
| Partial: GitHub unreachable | PR cells show unknown with as-of | "Open PRs · CI unknown" · `AsOfStamp` "as of 08:40" · tooltip "GitHub not reachable, CI unknown. Last answer 08:40." |
| Partial: Linear unreachable | Ready issues "—" | tooltip "Linear not reachable · as of 08:40" |
| Partial: otel missing | Cost shows "estimated" label | "Estimated from transcripts · otel not received for 2 sessions" |
| Partial: one hub invalid | Card in error variant | "hub.json does not match the schema · Open hub settings" |
| Error | `ProblemError` per region (Needs you, projects, feed fail independently) | title "Could not load projects" · detail · "Try again" |
| Live | Counts update from `counts` stream without re-layout; new Needs-you rows slide in at their sorted place (`dur-base`) | none |
| Stale (collector offline) | Global banner; `AsOfStamp` in page header | "as of 08:40" |
| Too few data for delta | Delta replaced | "No previous period to compare" |

### Actions by phase

| Action | Phase | Confirmation? | Consequence |
|---|---|---|---|
| Open any item, filter, change period, toggle view | P2 | No | Navigation |
| Approve plan directly from Needs you | P4 | Yes (same dialog as Approvals) | Run resumes |
| Accept/reject learning from Needs you | Not offered | n/a | Triage happens in Learnings (P3) where provenance is visible |

The Portfolio never performs actions inline; it routes to the screen where the evidence is (principle 2: a person decides with the material in front of them).

### UX principles applied

| Choice | Principle (brief §7) |
|---|---|
| Needs you first, verbs, oldest wait first | Shneiderman overview first; F-pattern (first lines read); Hick–Hyman (one obvious next step) |
| Cap 4 visible items | Working memory (Cowan ~4 chunks) |
| Only errors (not warnings) reach Needs you; colour only for exceptions | Alarm fatigue; pre-attentive processing reserved for what matters |
| "Since your last visit" line | Visibility of system status; recognition over recall |
| Period on every tooltip; "now" values labelled | Calibrated trust; consistency (Nielsen #4) |
| Mini stage bar per project | Pre-attentive position encoding; Tufte data-ink |
| Delta with previous absolute value | Show deviation from normal (Endsley comprehension) |
| Cards ⇄ table | Flexibility and efficiency (Nielsen #7) |
| No metrics by person anywhere | Principle 6 |

### Responsive

- **1280×800:** sidebar collapsed; 2 cards per row at 560px min each fits (1280 − 56 − 2×24 gutter); Needs-you context column truncates first; activity feed below the fold is acceptable (Needs you + cards visible without scrolling).
- **Mobile:** not a glance screen; the Approvals glance covers the Needs-you need. A simplified Portfolio shows Needs you and one-line project rows only.

---

## Project overview

**Phase:** P2 · **Route:** `/projects/:project?period=7d&section=now|repos|work|sessions|health|cost` · **Answers:** "How is this project doing, what is in flight, and what does the team know right now?"

### Purpose and primary user

The owner and developers of one project. It zooms the Portfolio card into sections, each answering one question and linking to its full screen. Sample: agent-hub.

### Layout (1440 px)

```
┌──────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│ Portfolio › agent-hub                                                                                         │
│ agent-hub   ● Warning (1 error)                                                Period [24 h|7 d|30 d|Custom]  │
│ jroquette/agent-hub-hub ↗ · Linear AGH · platform 0.8.0 pinned, lock 0.7.0 (Sync pending) · bench · cloud · marketplace │
│ Jump to: Now · Repos · Work in flight · Recent sessions · Health · Cost                                       │
├──────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ NOW  from brain/now.md                                                                    Open note ›          │
│ ┌ Focus ───────────────────────────┐ ┌ Next ─────────────────────────────┐ ┌ Watch ───────────────────────────┐│
│ │ Ship the web control plane P2:   │ │ AGH-131 doctor JSON output         │ │ Bench stderr test is flaky       ││
│ │ read-only Session detail first.  │ │ AGH-140 collector retention        │ │ (stray quote). Do not trust a    ││
│ │                                  │ │                                    │ │ single red run.                  ││
│ │ verified 2026-10-08 · human      │ │ verified 2026-10-08 · human        │ │ verified 2026-07-30 · agent  △  ││
│ └──────────────────────────────────┘ └────────────────────────────────────┘ └──────────────────────────────────┘│
├──────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ REPOS                                                                                                          │
│ Repo       Role  Default  Last CI on main        Open PRs  Fast check        Full check   AGENTS.md            │
│ agent-hub  app   main     ✓ passed · 2 h ago      2        make check-fast   make check   ✓ 58 lines           │
├──────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ WORK IN FLIGHT                                                                       Show failed (7 d) [x]      │
│ Picked    Worktree   Implementing          Verifying   PR open         Reported (7 d)         │ Failed (7 d)    │
│ ·         ·          ┌──────────────────┐  ·           ·               ┌───────────────────┐  │ ┌─────────────┐│
│                      │AGH-112 Cap the   │                              │AGH-48 Layered mem.│  │ │AGH-79 Guard ││
│                      │tracker team list │                              │PR #69 merged      │  │ │bypass       ││
│                      │attempt 1 · 38 min│                              │SHIP-WITH-OWNER-…  │  │ │verifying 2/2││
│                      │$2.14 / $10.00 ▓░ │                              │$5.62              │  │ │make check 2 ││
│                      └──────────────────┘                              └───────────────────┘  │ │$6.80        ││
│ Waiting at a gate: AGH-131 Doctor JSON output · plan approval · 41 min                                       │ └─────────────┘│
├──────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ RECENT SESSIONS                                                                         All sessions ›        │
│ Started      Agent                           Issue    Outcome   Duration    Turns   Cost      Errors          │
│ 08:31        main                            AGH-112  (Live)    41 min         46   $2.1400        0          │
│ 08:29        hub-workflow:planner            AGH-131  (Waiting) 43 min         12   $0.6200        0          │
│ yest. 14:02  hub-workflow:evaluator          AGH-48   Done      1 h 10 min     38   $1.2734        0          │
│ yest. 06:52  main                            AGH-79   Error     52 min         88   $3.9120        6          │
├────────────────────────────────────────────┬─────────────────────────────────────────────────────────────────┤
│ HEALTH                       Open Health › │ COST · 7 d                                       Open Metrics ›  │
│ 1 error · 2 warnings · 0 info              │ $61.40  +22.6 % vs $50.10      median run $4.10 (n = 7)         │
│ ⊗ instructions.size  AGENTS.md:1           │  ▁▂▃▂▅▃▆  daily, previous period dashed                          │
│ △ brain.memory  .gitignore                 │  By step: implement $34.10 · verify $12.80 · evaluate $7.40 …   │
│ △ lock.drift  hub.lock (0.7.0 vs 0.8.0)    │                                                                 │
│ Last doctor run 2 h ago                    │                                                                 │
└────────────────────────────────────────────┴─────────────────────────────────────────────────────────────────┘
```

### Components

| Section | Component (variant) |
|---|---|
| Header | `Breadcrumbs`, `StatusBadge` (health), `StatusBadge` waiting "Sync pending", `IdChip`-style module chips, `SegmentedControl` (period), anchor links |
| Now | three cards with `Markdown` (inline), `FrontmatterChips` (last_verified, provenance), `ProvenanceBadge` |
| Repos | `DataTable` (compact), `CodeBlock` inline variant for commands (copyable) |
| Work in flight | Kanban of 6 stage columns + Failed column; cards are `SessionTile`-like run cards using `StageChip`, `BudgetBar`, `IssueLink`; gate strip uses `StatusBadge` waiting |
| Recent sessions | `DataTable` (10 rows) with `StatusBadge`, `Money` (4 decimals), `Time` |
| Health | `FindingRow` (compact) × 3 + summary line |
| Cost | `KpiStat`, `LineChart` (daily with previous period dashed `chart-5`), `BarChart` small (by step) |

### Sections

#### Now

- Reads `brain/now.md` sections Focus, Next, Watch, each a card with the rendered bullet list (max 5 bullets; "and 2 more" links to the note).
- Each card shows `last_verified` and provenance. `last_verified` older than 60 days turns `waiting` with icon `clock-alert` and tooltip "Not verified for 73 days. It may be out of date." (sample: Watch, 2026-07-30).
- Read-only. "Open note" goes to `/knowledge/brain?project=agent-hub&path=brain/now.md` (P3) or, before P3, to the file on GitHub in the hub repo (`external-link`).
- Missing file: "No brain/now.md in this hub. Create it with the focus, next and watch sections; `/handoff` updates it at the end of a session."

#### Repos

One row per repo: name, role, default branch, last CI on the default branch (status icon + text + age, links to the CI run), open PRs (links to GitHub filtered), fast check and full check commands (mono, copy button), AGENTS.md present with line count (amber when over 100 lines, matching doctor rule `instructions.size`). Missing AGENTS.md: `failed` "Missing" with tooltip "Each repo needs its own AGENTS.md. Run hub doctor for the fix."

#### Work in flight (Kanban)

- Columns follow the WorkflowRun state machine: Picked · Worktree · Implementing · Verifying · PR open · Reported (period) and, separated by a vertical divider, Failed (period, toggle "Show failed (7 d)").
- Card: issue key + title (2 lines max), attempt and elapsed in stage ("attempt 1 · 38 min"), cost vs budget bar, PR link and CI icon in PR open, verdict in Reported, failure stage + attempt + reason in Failed ("verifying 2/2 · make check exit 2").
- Runs waiting at a human gate (not a stage in the state machine) are listed in a strip under the board: "Waiting at a gate: AGH-131 Doctor JSON output · plan approval · 41 min" linking to the approval. Proposal: a gate is shown on the stage it blocks, as a hatched amber marker on the card, and in this strip, because the state machine has no "awaiting approval" stage.
- Columns cap at 5 cards; "Show 3 more" expands. Reported shows the latest 5 in the period.
- Kanban is read-only: no dragging (runs move by the executor). Cards link to `/runs/:id`.
- Empty board: "No run in flight. Ready issues: 4 (label agent-ready). Runs start with `hub run AGH-112` in the hub directory." with link to Tracker queue.

#### Recent sessions

Last 10 sessions of the project (any agent), live first, then by start time. Columns: started (absolute in table; relative "08:31" today, "yest. 14:02"), agent, issue, outcome badge, duration, turns, cost (4 decimals), errors. Row click → Session detail. "All sessions" → `/sessions?project=agent-hub`.

#### Health

Summary "1 error · 2 warnings · 0 info", the 3 most severe findings as compact `FindingRow` (severity icon + label, rule id mono, path link), last doctor run age. Sample findings from the doctor data: error `instructions.size` AGENTS.md "132 lines, limit 100"; warning `brain.memory` .gitignore "no line ignoring brain/auto/workspace/"; warning `lock.drift` "sync pending (lock 0.7.0, pin 0.8.0)". "Open Health" → `/health?project=agent-hub`.

#### Cost

Total for the period with delta and previous value, median run cost with sample size ("n = 7"; under 5 shows "n = 4, too few to compare" instead of the median), daily `LineChart` with the previous period dashed in `chart-5`, and a small `BarChart` cost by workflow step. Never by person. "Open Metrics" → `/metrics?metric=cost-per-run&scope=agent-hub&period=7d`.

### Data mapping

| Element | Entity.field (brief §3) | API resource | Source · expected latency |
|---|---|---|---|
| Project name, hub repo, teams | Project.name, hub_repo, tracker | `GET /projects/{project}` | hub files · < 2 s |
| Health badge | Project.hub_health | `GET /projects/{project}` | doctor · ≤ 15 min |
| Platform pin, lock, Sync pending | Hub.platform_pin, platform_version, lock_state | `GET /projects/{project}` | hub files · < 2 s |
| Modules | Hub.modules | `GET /projects/{project}` | hub files |
| Now cards | brain/now.md sections; frontmatter last_verified, provenance | `GET /projects/{project}/now` | hub files · < 2 s |
| Repos rows | Repo.name, role, default_branch, check_fast, check, agents_md_present, agents_md_lines | `GET /projects/{project}/repos` | hub files · < 2 s |
| Last CI on default, open PRs | Repo.last_ci_default, open_prs | `GET /projects/{project}/repos` | github · ≤ 60 s |
| Kanban cards | WorkflowRun.stage, issue, attempt, cost_usd, caps.budget_usd, pr, failure | `GET /workflow-runs?project=agent-hub&in_flight=true` + `&stage=REPORTED,FAILED&from=` | executor · < 1 s; github ≤ 60 s |
| Gate strip | open Gate kind human for runs | `GET /approvals?scope=agent-hub` | hooks · < 1 s |
| Recent sessions | Session.started_at, agent, issue, status/outcome, duration, turns, cost_usd, errors | `GET /sessions?project=agent-hub&limit=10&sort=-started_at` | hooks, otel, transcript |
| Health summary and rows | Finding.severity, rule, path, message; last doctor run | `GET /doctor/findings?project=agent-hub`, `GET /doctor/runs?project=agent-hub&limit=1` | hub files · ≤ 15 min |
| Cost total, delta, series | Project.cost_period, cost_previous_period, daily series | `GET /metrics/cost-per-run?scope=agent-hub&period=7d` | otel · 1–5 s |
| Cost by step | sum WorkflowRun step costs | `GET /metrics/cost-per-run?scope=agent-hub&period=7d&group_by=step` | otel |

### Interactions

| Input | Result | URL |
|---|---|---|
| "Jump to" anchors | Smooth scroll (instant under reduced motion) | `?section=work` (replace) |
| Click Kanban card | Run detail | `/runs/:id` |
| Click Failed card | Run detail with failure banner focused | `/runs/:id?step=verify&attempt=2` |
| Click gate strip item | Approval | `/approvals/:id` |
| Copy check command | Copies `make check-fast`; button label "Copied" | none |
| Click session row | Session detail | `/sessions/:id` |
| Period control | Recomputes period sections (Reported, Failed, Cost, Health trend) | `?period=` |
| `j` / `k` | Move within the focused section's list | none |

### States

| State | What shows | Exact copy |
|---|---|---|
| Loading (> 300 ms) | Header skeleton; each section skeleton independently | none |
| Project not found | 404 `ProblemError` | "Project not found" · "No registered hub has a project named agent-hb." · "Open command palette" · "Go to Portfolio" |
| Now missing | Empty card row | "No brain/now.md in this hub. Create it with the focus, next and watch sections; /handoff updates it at the end of a session." |
| Now stale | Card in `waiting` | "Not verified for 73 days" |
| Repos: AGENTS.md missing | Row cell | "Missing" |
| Work in flight empty | Empty board | "No run in flight. Ready issues: 4 (label agent-ready). Runs start with `hub run AGH-112` in the hub directory." |
| Recent sessions empty | `EmptyState` small | "No sessions yet. Start Claude Code in the hub directory with the collector on: `cd ~/agent-hub-hub && claude`." |
| Health: never run | Section note | "Doctor has not run for this hub. Run `hub doctor` in the hub directory." |
| Health: all clear | Section line | "No findings · last doctor run 2 h ago" |
| Partial: GitHub unreachable | CI and PR cells | "CI unknown · as of 08:40" |
| Partial: Linear unreachable | Issue titles from executor cache with as-of | tooltip "Linear not reachable · titles as of 08:40" |
| Error (section) | `ProblemError` inside the section only | title "Could not load work in flight" · detail · "Try again" |
| Live | Kanban cards move between columns with `dur-base` transition (none under reduced motion); session rows update in place | none |
| Stale | Header `AsOfStamp` | "as of 08:40" |
| Cost too few runs | Median replaced | "n = 4, too few to compare" |

### Actions by phase

| Action | Phase | Confirmation? | Consequence |
|---|---|---|---|
| Open runs, sessions, approvals, findings, notes; copy commands; change period | P2 | No | Navigation / clipboard |
| "Start run on an issue" (from the empty board's ready issues link) | P4 | Dry-run preview first, then "Run live" confirmation | `POST /workflow-runs` with `dry_run: true`, then live |
| "Retry from verify" on a Failed card menu | P4 | Yes: "Retry run AGH-79 from verify? A new attempt starts in the existing worktree agh-79-guard-bypass. Budget left: $3.20 of $10.00." | `POST /workflow-runs/{id}/retry` `{"from_step":"verify"}` |
| "Run doctor now" | P4 | No | Re-runs doctor; Health section updates |

### UX principles applied

| Choice | Principle (brief §7) |
|---|---|
| Now first: the team's own words before machine metrics | Recognition over recall; information scent |
| last_verified amber after 60 days | Calibrated trust (show the age of knowledge) |
| Kanban by the run state machine, read-only | Match with the real world (Nielsen #2); no false affordance |
| Waiting gate strip separate from stages | Show only what the record shows (the state machine has no gate stage) |
| Each section ends with "Open X ›" | Shneiderman zoom then details on demand |
| Cost with n and "too few to compare" | Calibrated trust; honest small samples |
| Health shows top 3 findings with fix in full screen | Progressive disclosure; Hick–Hyman |

### Responsive

- **1280×800:** header wraps to 3 lines; Now cards stay 3 across (min 320px); Kanban columns scroll horizontally inside the section with the Failed column pinned right; Health and Cost stack vertically.
- **Mobile:** not a glance screen; renders sections stacked with the Kanban as a list grouped by stage.
