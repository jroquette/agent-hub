# Control plane design (Phase 2 reference)

The approved UI design system of the agent-hub control plane: its principles and foundations below, and the screen
specs in [specs/](specs/) (navigation, the data and API map, one file per Phase 2 screen, flows, responsive behaviour
and the design's decisions). It is the UI contract of `apps/web` and the `/api/v1` read models. The specs of Phase 3
and 4 screens (Knowledge beyond Learnings, Metrics, Workflows, Bench and Tracker) are not copied here.

## Departures

Phase 2 builds this design with the changes below, and the control-plane clarity pass (AGH-201) adds its own at the
end; where a spec file says otherwise, this list wins.

- **`hub web`, not `hub app` or `hub collector`.** One local process, `hub web [--port N] [--db PATH]`, serves
  `/api/v1` and the built app on `127.0.0.1:7420` only (no host option). Every "Start it with `hub collector start`"
  or `hub app` reads "Start it with `hub web`"; port 4317 is not used. `cli` imports the API only from its `web`
  command, and the API never imports `cli`.
- **Event types.** Phase 2 adds `step.start`, `step.end`, `run.end`, `learning.rejected` and `session.summary`. The
  proposed `hook.blocked` type is dropped: a blocked Stop is a `gate.result` with `kind: stop_gate` and
  `result: failed`, and guard-denial counts read only `tool.result` events with `status: denied`.
- **Metadata only.** No prompt, message, reasoning, successful tool output, file content or diff is stored. Short
  texts are kept redacted and truncated: a Bash command (500 characters), a Grep or Glob pattern (200), the first line
  of a tool error (200) and, since AGH-201, a failed tool's error message (300, [ADR
  0023](../../adr/0023-short-error-message.md)), a subagent type and description (80), a skill name and a SendMessage
  recipient (80), a git branch (200), a slash-command name and a learning title (120). WebFetch keeps
  scheme, host and path; MCP keeps server, tool and argument key names. Expandable message rows say "Content not
  stored. agent-hub keeps metadata only; the transcript stays in Claude Code's folder on this machine." and the diff
  pane says "Diff content is not stored in this version."
- **Sources not connected.** OpenTelemetry, GitHub and Linear are not connected in Phase 2: the fields they own are
  `null` in the API with `sources_missing`, and the UI shows "—" with the tooltip "<Source> is not connected in this
  version.". Cost comes from transcript usage and a dated price table, always labelled "Estimated from transcript";
  an unknown model gives "Cost unknown: model <id> has no price".
  Exception (AGH-136, ADR 0025): the feature Tickets tab reads Linear server-side, read-only, when
  `LINEAR_API_KEY` is set; without it the tab shows the plan from `features.json` with a notice.
- **Screens in Phase 2.** Portfolio, Project overview, Approvals (read-only), Live sessions, Sessions list (merged into one Sessions screen by
  [ADR 0033](../../adr/0033-sessions-and-chat-interaction-model.md)), Session
  detail (Timeline, Files, Cost and Raw events tabs; no Decisions or Context tab), Workflow runs, Run detail,
  Features, Feature detail, Health, Knowledge › Learnings and Knowledge › Brain (both since AGH-201, no `P3` tag),
  Settings (Hubs, Collector, Privacy, Appearance, About), Welcome and 404. Workflows ships read-only in Phase 4
  (AGH-226: catalog, layered graph, document). Metrics, Bench, Tracker queue, Decisions and Context are hidden;
  the other Knowledge items show only their title and "Arrives in Phase 3.".
- **Phase 3 and 4 actions.** Where the design puts an action in a screen body (the Approvals action bar, Run detail
  "Retry from verify", Runs list "Start run on an issue", Learnings snooze), it renders disabled with a `PhaseTag` and
  the tooltip "Available in Phase 3/4. This version is read-only.". Overflow menus keep only Phase 2 items. No Phase
  3 or 4 endpoint exists in the OpenAPI document, except the two learning decisions AGH-201 moved to Phase 2.
- **Copy.** "Proposed CLI" chips are dropped for `hub web`, `hub collect --transcript` and `hub collect --runs`, and
  kept for `./hub run <issue> --dry-run`. Welcome step 2 "Start the collector" becomes "Keep hub web running", checked
  as "agent-hub is running at 127.0.0.1:7420 · db <path>". Empty states that name OpenTelemetry say "Cost is estimated
  from transcripts. OpenTelemetry is not connected in this version.". Transcript column values are "local file" or
  "—".
- **Hook events.** The hook sensor is registered for eleven events: SessionStart, UserPromptSubmit, PreToolUse,
  PostToolUse, PostToolUseFailure, Notification, Stop, SubagentStart, SubagentStop, PreCompact and SessionEnd. A
  failed tool is reported by PostToolUseFailure (status `error`, the first line of the error and the short error
  message, or "interrupted"), not PostToolUse, and a guard ask also resolves `approved` on a PostToolUseFailure with
  its tool use id.
- **Session fields from hooks.** `session.start` takes its trigger from the hook's `source` (adding the value `fork`);
  the git branch comes only from the transcript, whose mapper writes `git_branch` on every event of a line that names
  one. Events from inside a subagent carry `agent` = its agent type and the payload key `agent_id`. Stop,
  SubagentStart, SubagentStop, PreCompact and Notification hooks other than permission prompts produce no event of
  their own. `Session.parent_session_id` is always `null`: subagents share their session's id, and are told apart as
  its `actors` instead.

AGH-201 (control-plane clarity) changes the design further
([event-derivations.md](../event-derivations.md), [API.md](../../API.md), ADRs 0023 and 0024):

- **Session identity.** Lists, tiles and the header show the session's `label` (`DEMO-1511 · /feature`, then `repo ·
  branch`, then the short id), never the stored agent `main`; the Agent column is gone and `agent` is deprecated.
- **Problems, not error counts.** `GET /sessions/{session_id}/problems` and the "What went wrong" panel; problem
  kinds add `guard_ask_open` (an unanswered guard ask) and `guard_ask_declined` resolves "You declined" (E4);
  resolution `open` ("Agent is on it") covers a problem while the session is live, so it becomes `needs_you` only once
  the session waits, idles or ends (E5). A live tile's red edge means a needs-you problem only; `failing_notice` keeps
  its text without the edge (E11). What the agent or the owner already dealt with folds into one line under
  "Show N handled"; only what needs the owner stays listed (AGH-265, [agent-sessions.md](../agent-sessions.md) AC-265.6).
- **Timeline.** Rows name the actor ("Main agent", "Subagent · <type>") and a plain verb ("Ran skill /feature",
  "Started subagent Explore: …"); runs of Reads collapse, with a legend.
- **Learnings.** `status` has no `snoozed` value: snooze stays a disabled P3 button. A learning adds `note_path`,
  `state` (`proposed`, `accepted_pr_open`, `rejected_pr_open`, `in_brain`, `archived`), `summary`,
  `note_unavailable`, `actions_unavailable`, `pr_url` and `branch`; `target` is deprecated. Accept and reject answer
  201 `{state, pr_url, branch}`, not a Learning, and work in a temporary clone of the hub's `origin`, never a worktree
  of the user's checkout (E8). There is no `/learnings/{id}/trace`.
- **Brain.** `GET /projects/{project}/brain` and `GET /projects/{project}/brain/note?path=` replace the design's
  `/brain/notes` (no backlinks); `brain/auto/` is never listed or served. Feature detail adds Spec, Research, Plan,
  Eval and Criteria tabs over the same note route.
- **Security.** Only the two learning POSTs need the server's own `Origin`, a same-origin fetch and a JSON body
  (E9); the CSP is unchanged.

## Design system

The control plane of agent-hub is an observability and governance console for teams of AI coding agents. It answers five questions: how are my projects doing (Portfolio), what are the agents doing right now (Live sessions), why did the agent do that (Session timeline), what does it know and what did it learn (Knowledge), and how should work flow and where does it get stuck (Workflows). A busy engineering lead should understand any screen in five seconds and be able to trust it.

This system is the north star for the people and agents building the REST API (`/api/v1`) and the React front end. Every screen is specified, not just drawn: the sections after this one give each screen's question, layout, data mapping, states and interactions; the components are live React; the **Screens** group holds hi-fi pages with a state switcher and an annotation overlay; **Prototype** clicks through the key flows.

## Product principles (they decide every design question)

1. **Observe, don't replace.** No chat and no "talk to the agent" box, anywhere.
2. **Human decides.** Agents only propose. Gates, approvals and accepted learnings are human acts, and they are the most visible things on any screen they appear on (`waiting` amber, hand icon, top of the list).
3. **Show only what the record shows.** Reasoning is the *recorded reasoning summary*, labelled. Anything computed by agent-hub (summaries, extracted decisions, inferred ends) carries a `DerivedLabel` and a dashed outline.
4. **Provenance everywhere.** Every brain item, learning, decision and summary line links back to its session and events (`ProvenanceBadge`, `ProvenanceLineage`).
5. **Privacy first.** Secrets appear only as `RedactionChip` (`[redacted: github token]`), never partially and never with a reveal button. Personal memory (`brain/auto/workspace/`) is shown to others only as "present, private". Expired transcripts show `ExpiredContent`; structured events and summaries remain.
6. **Metrics about the process, never about people.** Group by step, gate, repo, issue size or run. No per-person chart, ranking or filter exists in this system.
7. **Read-only first.** Phase 2 is read-only. Actions from Phases 3–4 are designed now and always carry a `PhaseTag` (`P3`, `P4`) until they ship.

## Content fundamentals

**Voice.** Calm, precise, plain. Active voice, sentence case, no exclamation marks, no emoji, no "AI magic" words (no sparkles, no "smart", no "insights"). Verbs on buttons: "Approve plan", "Retry from verify", "Open failing moment", never "OK" or "Submit". Link text says where it goes: "3 failed runs in verify", not "See more".

**Glossary.** Use these words exactly; never mix them.

| Say | Meaning | Never say |
| --- | --- | --- |
| Project | A product with 1..N repos and a tracker (`agent-hub`, `loki-trader`) | workspace, org |
| Hub | The project's control repo (rules, brain, workflows) | — |
| Repo | A code repository managed by the hub | project |
| Agent | A role with instructions, tools and a model: `hub-workflow:evaluator` | bot, assistant |
| Session | One Claude Code session of an agent | run, job, execution |
| Workflow | A versioned sequence of steps | pipeline |
| Run | One WorkflowRun (one issue taken to a PR); it contains sessions | session |
| Gate | An automatic check or a human approval a step must pass | — |
| Brain · Learning · Inbox · Decision | Curated knowledge · something learned (proposed → accepted/rejected) · unreviewed proposals · a recorded choice | wiki · insight, tip |
| Issue | A tracker item, `AGH-48` | ticket, task |
| Doctor · finding | `hub doctor` and what it reports | lint |

"Run" names a WorkflowRun only. A session is never a run.

**Formatting.** Ids short and mono (`5091b986`), full UUIDv7 on copy (`IdChip`). Issues as `AGH-48`, linking out. Recent times relative ("3 min ago") with the absolute time in the tooltip; tables absolute; local time by default, UTC on toggle. Durations "1 h 12 min". Money in USD: 2 decimals in summaries (`$1.27`), 4 in details (`$1.2734`); totals add up exactly. Numbers use tabular figures, thousands separators, right-aligned. Paths and commands are mono and middle-truncated (`packages/core/…/brain_memory_rule.py`) with the full value on hover (`PathText`). External content (issue text, PR comments, web pages) is labelled `ExternalLabel` and never styled as fact.

## Visual foundations

**Personality.** Calm, precise, trustworthy, engineering-grade: the clarity of a good issue tracker, the density of a metrics console, the trace view of a tracing tool. Not playful. No gradients as decoration, no 3D, no robot or spark imagery.

**Color.** A cool 11-step neutral scale (`gray-50` … `gray-950`, inverted in dark so each step keeps its role) carries almost everything. Grounds: `bg` (app), `surface` (panels, tables, timeline), `surface-sunken` (wells, code, table header), `surface-hover`, `surface-overlay` (menus, dialogs). Text: `text`, `text-muted`, `text-subtle`, each at least 4.5:1 on every ground in both themes. Lines: `border` (hairlines, decorative), `border-strong`, `border-control` (inputs, 3:1). One accent, deep indigo `accent`, used sparingly: the primary action of a view, links, the selected nav item and `focus-ring`. Text on an accent fill is `on-accent`.

**Status is one pre-attentive channel.** Only status colors pop; everything else stays neutral. Every status is icon + label, never color alone (`StatusBadge`):

| Status | Token | Icon | Meaning |
| --- | --- | --- | --- |
| Live / running | `live` | pulse dot | Streaming events now |
| Waiting for you | `waiting` | hand | An open gate request or human step |
| Done / passed | `done` | circle-check | Bluish green, off the red axis |
| Failed / error | `failed` | circle-x | |
| Blocked / stopped | `blocked` | octagon-x | |
| Idle / stale | `idle` | moon / clock | No activity for 5 min; data older than its expected latency |
| Denied by guard | `guard` | shield-x | A hook or guard refused an action |
| Derived | dashed `text-subtle` outline | circle-dashed | Computed by agent-hub, not recorded |

Each status has a `-soft` ground for badges. The only animation that loops is the live pulse (2 s, `dur-pulse`); there is no flashing, and toasts are reserved for results of the user's own actions (alarm fatigue).

**Timeline events** use eight categorical marks, each at least 3:1 on `surface` in both themes and always paired with an icon and a label: `ev-prompt` (user), `ev-message` (agent message), `ev-reasoning` (recorded reasoning summary, dashed mark, italic text), `ev-tool`, `ev-gate`, `ev-decision`, `ev-learning`, `ev-lifecycle`. Errors use `failed`; guard denials use `guard` on a `guard-soft` row.

**Charts** use `chart-1` … `chart-5` with direct labels instead of legends where possible, `chart-grid` for gridlines, and `chart-budget` (dashed) for limits. Bars start at zero. Small samples (n < 5) are greyed and say "Too few to compare". Every chart's title is the question it answers.

**Type.** Geist for the interface, Geist Mono for ids, paths, commands, code and every number in a table (tabular figures). Base is `body` 14/20; `small` 13/18 for metadata, `caption` 12/16 for badges and column headers, `subheading` 16/24 for panel titles, `heading` 20/28 for sections, `title` 24/32 for detail headers, `display` 32/40 only for empty-state and first-run headlines. Figures: `figure` 13/20 and `figure-lg` 24/32 for KPI values. Left-align text, right-align numbers.

**Space and layout.** A 4px grid (`space-1` 4 … `space-16` 64). Page padding `space-8` horizontal (`space-6` on laptops). Two densities: comfortable (`row-comfortable` 40px rows) and compact (`row-compact` 32px), set with `data-density="compact"` on any container. Shell: `sidebar` 240px (collapses to `sidebar-collapsed` 56px, default below 1360px), `topbar` 48px. Minimum target `control-sm` 24px.

**Shape and depth.** Radii are small: `radius-sm` 4 (chips), `radius-md` 6 (controls), `radius-lg` 8 (cards, tiles), `radius-xl` 12 (dialogs, palette), `radius-full` only for status badges and dots. Structure comes from 1px borders; elevation (`shadow-popover`, `shadow-overlay`) is only for things that float. No colored left-border cards.

**Motion.** 120–200 ms ease-out (`dur-fast`, `dur-base`, `dur-slow`, `ease-out`). Streaming insertions fade and slide 4px in 150 ms. Everything is off under `prefers-reduced-motion`.

**Focus and accessibility.** WCAG 2.2 AA. Every interactive element shows a 2px solid `focus-ring` with a 2px offset (3:1 or more on every surface). Full keyboard: `g p` portfolio, `g l` live, `g s` sessions, `j/k` in lists and timelines, `/` filter, `f` follow live tail, `?` shortcut sheet, `Esc` closes. Streaming regions are polite ARIA live regions with rate-limited announcements. Nothing is conveyed by color or motion alone.

## Iconography

One outline set: **Lucide** (ISC licence, 24px grid, 2px stroke, round caps), drawn at `icon` 16px in rows and 14px in chips; use `lucide-react` in the app with the same names as `Icon`. Tools: Read `file-text`, Edit `file-pen`, Write `file-plus`, Bash `terminal`, Grep `text-search`, Glob `folder-search`, Agent/subagent `network`, WebFetch `globe`, MCP `plug`. Entities: project `folder-kanban`, repo `book`, session `square-terminal`, run `route`, workflow `workflow`, gate `check-check`, learning `sprout`, decision `split`, brain `library`, issue `circle-dot`, PR `git-pull-request`. Guard: `shield-x` (denied), `shield-alert` (asks). No emoji, no robot or sparkle icons. agent-hub has no logo yet: the product is set as the word "agent-hub" in `subheading` weight beside a mono `ah` monogram tile in `text` on `bg`.

## Using this system

- Load `tokens.css` (generated from `tokens.json`), then `components/bundle.css`, React 18 and `components/bundle.js`; components are on `window.AgentHub` (`AgentHub.SessionTile`, `AgentHub.TimelineEvent`…). Hi-fi screens are on `AgentHub.screens`. Props are documented in `components/index.d.ts` and each component's README.
- Themes: set `data-theme="light"` or `"dark"` on `<html>`; never hard-code a color, use the tokens.
- The specification sections that follow are the contract for the API and the front end: navigation and routes, the data and API map, one section per screen, the prototype flows, responsive behaviour, and the decisions and open questions.
