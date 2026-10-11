# Health (Doctor)

**Phase:** P2 (re-run from the app P4) · **Route:** `/health` (params `project`, `severity`, `area`, `rule`, `run`) · **Answers:** "Is this hub set up correctly, and what exactly do I fix?"

## Purpose and primary user

Shows the findings of `hub doctor` (health checks on a hub: config, lock, links, instructions, brain, secrets, settings). Each finding has a rule, a severity (error / warning / info), a path and line, a message and a fix. The screen exists to turn a finding into a fix in one read: "How to fix" is the most prominent text on each row, not the message.

Primary user: owner / tech lead after a platform upgrade or when Portfolio shows a health dot that is not green. Secondary: developer who was told by the Stop hook or CI that the doctor fails.

Glossary: Doctor, never "lint". A finding is not an error unless its severity is error.

## Layout (1440 px), scope agent-hub

```
+--------+-------------------------------------------------------------------------------------------------+
|Sidebar | TopBar: [agent-hub v]  [Search or jump to... Ctrl K]   (o Connected · last event 3 s ago)       |
+--------+-------------------------------------------------------------------------------------------------+
|        | Health                                                                                          |
|        | SUMMARY STRIP                                                                                   |
|        | (x) 1 error   (!) 2 warnings   (i) 0 info  | Last run 11 Oct 08:58 (2 h ago) · ./hub doctor     |
|        | Platform 0.7.0 synced · pinned 0.8.0 [sync pending] | Lock: drift                               |
|        |                                                     [Copy re-run command]  [Run doctor] P4      |
|        +---------------------+---------------------------------------------------------------------------+
|        | FILTERS             | TREND  findings per run, last 30 d (stacked: error / warning / info)     |
|        | Severity            |   5|      ..                                                             |
|        |  [x] Error      1   |   3| ..  ..  ..  ##                                                      |
|        |  [x] Warning    2   |   1| ##  ##  ##  ##  ##                                                  |
|        |  [ ] Info       0   |    +-----------------------------  regression on 09 Oct: +1 error        |
|        | Area                +---------------------------------------------------------------------------+
|        |  [ ] config     0   | FINDINGS, grouped by rule                       [Expand all] [Collapse]   |
|        |  [ ] lock       1   |                                                                           |
|        |  [ ] instructions 1 | v (x) instructions.size        1 error                     area: instr.   |
|        |  [ ] brain      1   |   AGENTS.md:1                                                             |
|        |  [ ] links      0   |   AGENTS.md: 132 lines, limit 100                                         |
|        |  [ ] secrets    0   |   HOW TO FIX                                                              |
|        |  [ ] settings   0   |   Keep it a map, not a manual: move detail into docs/ and link it from    |
|        |                     |   AGENTS.md until it is 100 lines or fewer.          [Open AGENTS.md]     |
|        | Show                |                                                                           |
|        |  (o) Open findings  | v (!) brain.memory             1 warning                   area: brain    |
|        |  ( ) Resolved (30 d)|   .gitignore                                                              |
|        |                     |   No line ignoring brain/auto/workspace/                                  |
|        |                     |   HOW TO FIX                                                              |
|        |                     |   Add these lines to .gitignore:                                          |
|        |                     |   +-----------------------------------------+                             |
|        |                     |   | brain/auto/workspace/*                  | [Copy]                      |
|        |                     |   | !brain/auto/workspace/.gitkeep          |                             |
|        |                     |   +-----------------------------------------+                             |
|        |                     |                                                                           |
|        |                     | v (!) lock.drift               1 warning                   area: lock     |
|        |                     |   hub.lock                                                                |
|        |                     |   Sync pending (lock 0.7.0, pin 0.8.0)                                    |
|        |                     |   HOW TO FIX                                                              |
|        |                     |   Run the sync for the pinned version, review the diff, open a hub PR:    |
|        |                     |   ./hub sync                                                  [Copy]      |
+--------+---------------------+---------------------------------------------------------------------------+
```

Regions: header + summary strip (sticky under the top bar once scrolled), filter rail (240 px), trend chart (full width of the content column, 120 px tall), findings list (grouped). In All-projects scope, a project column appears in each finding row and the summary strip shows one line per project.

## Components

| Component | Variant / notes |
|---|---|
| `AppShell`, `Sidebar` ("Health" selected; small severity dot when errors > 0), `TopBar`, `ProjectSwitcher`, `CollectorPill` | Standard |
| `KpiStat` | Inline variant, three counts with severity icons; each is a filter shortcut |
| `StatusBadge` | `waiting` "sync pending" next to platform version; lock state badge: in sync (done), drift (waiting), sync pending (waiting), not adopted (idle) |
| `AsOfStamp` | "Last run 11 Oct 08:58 (2 h ago)"; turns into the stale variant after 24 h |
| `FilterRail` + `FilterChip` | Severity, Area, Show (open / resolved) |
| `BarChart` (stacked, small) | Trend: findings per doctor run, stacked by severity; regression annotations |
| `FindingRow` | Variants: error, warning, info; collapsed / expanded; group header variant (rule id + count) |
| `PathText` | `path:line`, links to the file view (opens the file in the hub on GitHub, or a local `vscode://` link when configured in Settings) |
| `CodeBlock` | Fix snippets and commands, copy button |
| `Tooltip` / `Popover` | Rule explanation on hover of the rule id |
| `Button` | "Copy re-run command" (secondary), P4 "Run doctor" (primary) |
| `Banner` | Stale doctor results |
| `Skeleton`, `EmptyState`, `ProblemError` | States |

## Severity and area vocabulary

| Severity | Icon | Token (text/icon on surface; badge ground) | Meaning shown in tooltip |
|---|---|---|---|
| error | octagon with x | `failed` / `failed-soft` | "Breaks the hub or a gate. Fix before the next run." |
| warning | triangle with ! | `waiting` / `waiting-soft` | "Works today, likely to cause a problem. Fix soon." |
| info | circle with i | `idle` / `idle-soft` | "For your information. No action required." |

Areas (closed list, from the rule prefix map): config, lock, links, instructions, brain, secrets, settings. Rule ids in the sample: `instructions.size` (instructions), `brain.memory` (brain), `lock.drift` (lock); other known rules: `brain.leak` (brain), `secrets.config` (secrets), `links.dead` (links).

## Sample findings (synthetic, brief §10)

| Severity | Rule | Path:line | Message | How to fix |
|---|---|---|---|---|
| error | `instructions.size` | `AGENTS.md:1` | AGENTS.md: 132 lines, limit 100 | Keep it a map, not a manual: move detail into `docs/` and link it from AGENTS.md until it is 100 lines or fewer. |
| warning | `brain.memory` | `.gitignore` | No line ignoring brain/auto/workspace/ | Add `brain/auto/workspace/*` and `!brain/auto/workspace/.gitkeep` to `.gitignore`. |
| warning | `lock.drift` | `hub.lock` | Sync pending (lock 0.7.0, pin 0.8.0) | Run `./hub sync`, review the diff, open a hub PR. |

Summary for these: "1 error · 2 warnings · 0 info". (The brief's example "2 errors · 5 warnings · 1 info" is the All-projects total when loki-trader adds 1 error, 3 warnings, 1 info.)

## FindingRow anatomy

```
+-----------------------------------------------------------------------------------------------+
| (!)  brain.memory  [?]           .gitignore                       area: brain   first seen 09 Oct |
|      No line ignoring brain/auto/workspace/                                                   |
|  +-----------------------------------------------------------------------------------------+  |
|  | HOW TO FIX                                                                              |  |
|  | Add these lines to .gitignore:                                                          |  |
|  |   brain/auto/workspace/*                                                     [Copy]     |  |
|  |   !brain/auto/workspace/.gitkeep                                                        |  |
|  | Why: personal memory must never be committed (privacy rule).                            |  |
|  +-----------------------------------------------------------------------------------------+  |
|      [Open .gitignore]   [Copy finding as Markdown]                                           |
+-----------------------------------------------------------------------------------------------+
```

- Line 1: severity icon + text (screen readers read "Warning"), rule id (`mono-sm`), help glyph, `PathText` with line, area chip, "first seen" date (`Time`).
- Line 2: message (`body`).
- "How to fix" block: `surface-sunken` ground, left edge 3 px in the severity color, label "HOW TO FIX" in `caption`, text in `body-strong`, commands and snippets in `CodeBlock` with copy. This block is always visible (not collapsed) in expanded groups: the fix is the point.
- "Why" line: one sentence from the rule's documentation.
- "Copy finding as Markdown" produces: `- [warning] brain.memory .gitignore: No line ignoring brain/auto/workspace/. Fix: add brain/auto/workspace/* and !brain/auto/workspace/.gitkeep to .gitignore.`

**Grouping by rule.** Group header: chevron, worst severity icon, rule id, count by severity ("1 warning", "3 errors · 1 warning"), area. Groups are sorted by worst severity, then count, then rule id. Groups with errors start expanded; warning-only groups start expanded when the total is 10 or fewer findings, else collapsed; info groups start collapsed. Expand/collapse state is in the URL (`open=instructions.size,brain.memory`).

**Rule explanation on hover.** Hovering (or focusing) the rule id opens a `Popover` after 300 ms (`shadow-popover`, 360 px):

> **instructions.size** · area instructions
> Checks that AGENTS.md, AGENTS.project.md and each repo's AGENTS.md stay short (default limit 100 lines). Long instruction files are loaded into every session's context, cost tokens on every turn, and dilute the rules that matter.
> Configure: `hub.json` → `doctor.rules.instructions.size.max_lines` (proposed config key).
> Added in platform 0.6.0.

For `lock.drift`: "Compares `hub.lock` (what `hub sync` last wrote) with the version pinned in `hub.json` → `platform.version`. Drift means the managed files are older than the pin, or were edited by hand." For `brain.memory`: "Checks that personal memory under `brain/auto/workspace/` is gitignored, so it is never committed or synced."

The popover is keyboard reachable (focus the rule id, the popover opens; `Esc` closes) and contains a link "All findings of this rule" (sets `rule=` filter).

## Trend

`BarChart`, stacked by severity, one bar per doctor run over the selected period (default 30 d, max 60 bars; more runs aggregate to one bar per day showing the last run of the day). Y axis: count of findings. Annotations above bars: "+1 error" where a run added errors (a regression), "platform 0.8.0 pinned" markers from hub.json history. Hover a bar: "Run 09 Oct 18:12 · 1 error, 2 warnings · +1 error vs previous (instructions.size)". Click a bar: shows that run's findings (`run=` param) with a header "Findings as of the run on 09 Oct 18:12 · [Back to latest]". Colors: `failed`, `waiting`, `idle` fills with 1 px `surface` separators (so stacks are not distinguished by color alone; tooltip and legend name each).

With fewer than 3 runs the chart is replaced by text: "Trend appears after 3 doctor runs. 1 run so far."

## Data mapping

| Element | Entity.field (brief §3) | API resource | Source · latency |
|---|---|---|---|
| Counts by severity | Doctor findings: severity | `GET /doctor/findings?project=` → `summary.{error,warning,info}` | doctor run output, read by the collector · on each doctor run |
| Last run | doctor run timestamp | `GET /doctor/runs?project=` → `items[0].{ran_at, command, platform_version, exit_code}` | doctor output file in the hub (proposed `.hub/doctor/last.json`) |
| Platform synced vs pinned | Hub: platform version pinned; hub.lock version | `GET /projects/{project}` → `hub.{platform_pinned, platform_locked, lock_state}` | hub.json + hub.lock · on file change |
| Lock state badge | Hub: lock state (in sync / drift / sync pending / not adopted) | same | hub files |
| Finding rows | Doctor findings: rule, severity, path, line, message, fix | `GET /doctor/findings?project=&severity=&area=&rule=&run=` → `items[]` `{rule, severity, area, path, line, message, fix, first_seen_at}` | doctor output |
| How to fix | finding.fix (text + optional snippet/command) | `items[].fix.{text, snippet, command}` | doctor output |
| Area | derived from rule prefix | `items[].area` | derived server-side |
| First seen | earliest run containing the same (rule, path) | `items[].first_seen_at` | derived across runs |
| Rule explanation | rule documentation | `GET /doctor/findings` → `rules{rule_id: {title, explanation, configure, since}}` (included once per response) | platform package metadata |
| Trend | findings per run | `GET /doctor/runs?project=&period=30d` → `items[].counts` | derived |
| Resolved (30 d) | findings present in an earlier run, absent in latest | `GET /doctor/findings?project=&status=resolved&period=30d` | derived |
| Health dot in sidebar | worst open severity | `GET /events/stream` → `doctor.worst` | real time on new run |

## Interactions

- Click a severity count in the summary: toggles that severity filter.
- Filters: severity and area (multi-select OR within, AND across), Show open / resolved. URL: `/health?severity=error,warning&area=brain`.
- `j` / `k` move between findings; `Enter` / Space toggles a group; `c` copies the focused finding's fix command or snippet; `o` opens the path.
- "Copy re-run command": copies `cd ~/code/agent-hub-hub && ./hub doctor` (hub path from `GET /hubs`). A `Toast` is not shown; the button label changes to "Copied" for 2 s (inline, accessible via live region).
- The page refreshes itself when a new doctor run lands (SSE `doctor.run` event): the summary updates, new findings fade in, resolved ones move to Resolved with a single polite announcement "Doctor ran at 11:04: 1 finding resolved, 0 new."
- In All-projects scope, `group_by=project` is offered (toggle "Group by rule | Group by project"); default stays by rule.

## States

| State | What shows | Exact copy |
|---|---|---|
| Loading (>300 ms) | Summary strip skeleton, 3 group skeletons, trend skeleton | (none) |
| Healthy (no findings) | `EmptyState` in the findings area, summary shows zeros with `done` icon | "No findings. The hub passed every doctor check at 08:58." / "Re-run after changing hub.json or upgrading: `./hub doctor`" |
| Never ran | `EmptyState` | "The doctor has not run on this hub yet." / "Run it in the hub directory: `cd ~/code/agent-hub-hub && ./hub doctor`. Results appear here within a few seconds." |
| Stale (last run > 24 h) | `Banner` (info, `idle-soft`) under the summary; findings still listed, each group header shows `AsOfStamp` | "Doctor last ran 3 days ago (08 Oct 09:14). Findings may be out of date. Re-run: `./hub doctor`" [Copy] |
| Stale + config changed since | Same banner, stronger wording, `waiting-soft` | "hub.json changed after the last doctor run (10 Oct 17:30). Re-run to see current findings: `./hub doctor`" |
| Partial: some checks skipped | Group "Skipped checks" at the end (info) | "2 checks did not run: links.dead (no network), secrets.config (gitleaks not installed). Install gitleaks and re-run `./hub doctor`." |
| Partial: one project unreadable (All projects) | Project line in summary shows `ProblemError` inline | "loki-trader: cannot read hub.json (path /home/dev/code/loki-trader-hub not found). Fix the path in Settings › Hubs." |
| Error | `ProblemError` in content area | e.g. "Could not load doctor findings" / "status 500 · The doctor output is not valid JSON (line 14)." [Retry] |
| Live | New run arrives: counts animate (no motion under reduced motion), rows fade in | (announcement above) |
| Collector offline | `AsOfStamp` in header | "As of 14:02 · collector offline. New doctor runs will not appear until it reconnects." |
| Resolved view | Rows in `text-muted`, `done` check icon, "Resolved on 10 Oct (run 17:42)" | "Resolved in the last 30 days" |

## Actions by phase

| Action | Phase | Confirmation? | Consequence |
|---|---|---|---|
| Filter, expand, copy fix, copy command, open file | P2 | No | None |
| Copy finding as Markdown (for an issue or PR) | P2 | No | Clipboard |
| Run doctor | P4 | No (read-only check, safe) | `POST /doctor/runs` `{"project":"agent-hub"}` (proposed endpoint) runs `./hub doctor` in the hub directory; the button shows "Running… 12 s" then the results replace the list |
| Apply a fix automatically | Not planned | n/a | Fixes change hub files and go through a hub PR made by a person (principle 2) |

## UX principles applied

| Choice | Principle (brief §7) |
|---|---|
| "How to fix" is the most prominent block of each finding, with copyable commands | Nielsen 9 (recognize, diagnose, recover); recognition over recall |
| Group by rule with counts; errors expanded first | Shneiderman (overview first); Gestalt proximity; Miller / Cowan (a few groups, not 40 rows) |
| Severity as icon + word + color | WCAG 1.4.1; pre-attentive shape (Treisman & Gelade) |
| Rule explanation on hover, not inline | Progressive disclosure; cognitive load (Sweller) |
| Stale banner with the exact re-run command | Endsley perception (how fresh is this?); Nielsen visibility of system status |
| Trend with regression annotations | Endsley comprehension: deviation from normal |
| No automatic fix | Principle 2: human decides; hub changes go through a PR |

## Responsive

- **1280×800:** sidebar collapsed; filter rail becomes a row of `FilterChip`s under the summary; trend height 96 px; finding rows wrap the path to a second line.
- **1920:** two-column findings grid is not used (scanning a single column is faster); extra width goes to the trend (90 d default at >= 1800 px).
- **Mobile:** not a glance screen; summary strip and an error-only list render, with "Open on a larger screen for fixes and trend."
