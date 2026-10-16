# Data and API map

**Phase:** P2 (P3/P4 endpoints tagged inline) · **Base:** `/api/v1` · **Answers:** "Which entity, field and source is behind every pixel, and how fresh is it?"

This section is the contract between the screen specs and the REST API. Screen specs cite fields as `Entity.field` from the reference below and endpoints by path from the catalogue. Items not in the brief are labelled **Proposal** with the reason.

Conventions: JSON snake_case; ids UUIDv7 (displayed as 8-character `IdChip`, full id copied on click); timestamps ISO 8601 UTC with milliseconds; money as decimal strings with 4 places (`"1.2734"`) so totals add up exactly (never floats); cursor pagination `{ "items": [], "next_cursor": "…" | null, "total_estimate": 1240 }`; errors RFC 9457 Problem Details.

## Sources

| Source | What it sends | Transport | Expected latency (event time → visible) |
|---|---|---|---|
| `claude_code` hooks | session.start/end, tool.call, tool.result (status, sizes), gate.request for guard asks, guard denials | Hook POSTs to the local collector | < 1 s |
| `transcript` | message, reasoning (summary), decision (extracted), learning.proposed, tool details, token counts per turn | Tail of the JSONL transcript after each turn | 2–10 s after the turn ends |
| `otel` | Tokens (input, output, cache read, cache write), cost USD, model | OTLP to collector | 1–5 s (batched) |
| `executor` | WorkflowRun state, step.start/end, gate.result for scripted gates, caps, run.end | `hub run` writes to collector | < 1 s |
| `github` | PR url, state, CI checks per commit, review rounds, merge time | Polling every 60 s (webhook when configured) | 60 s polling, < 5 s webhook |
| `linear` | Issue title, state, labels (agent-ready, agent-failed), comments written by runs | Polling every 60 s | ≤ 60 s |
| hub files | hub.json, hub.lock, brain/, features/, doctor findings, AGENTS.md | File watcher on registered hub paths | < 2 s after save; doctor on demand or every 15 min |
| `control_plane` (AGH-201) | learning.accepted, learning.rejected for a decision taken in the app, with the hub PR it opened | Written by `hub web` itself after the PR opens | immediate |

## Entity reference

Field lists are the API shapes. "Source" names who writes the field; "Latency" is when it is first correct.

### Project

| Field | Type | Source | Latency |
|---|---|---|---|
| `name` | slug, e.g. `agent-hub` | hub files (hub.json `project.name`) | < 2 s |
| `hub_id` | uuid | collector registry | on register |
| `hub_repo` | `jroquette/agent-hub-hub` | hub files | < 2 s |
| `tracker` | `{ kind: "linear", teams: ["AGH"], ready_label: "agent-ready", failed_label: "agent-failed" }` | hub files | < 2 s |
| `default_branch`, `branch_prefix` | string | hub files | < 2 s |
| `hub_health` | `ok \| warning \| error` | derived from doctor findings | ≤ 15 min |
| `live_sessions`, `runs_in_flight_by_stage`, `open_prs`, `failed_runs_7d`, `ready_issues`, `cost_period`, `cost_previous_period` | numbers / money | derived (sessions, runs, github, linear, otel) | per input source |

### Hub

| Field | Type | Source | Latency |
|---|---|---|---|
| `id`, `path` | uuid, absolute local path | collector registry | on register |
| `platform_version`, `platform_pin` | `0.8.0` | hub.lock / hub.json | < 2 s |
| `lock_state` | `in_sync \| drift \| sync_pending \| not_adopted` | derived from hub.lock vs pin | < 2 s |
| `modules` | `["bench","cloud","marketplace"]` | hub.json | < 2 s |
| `guard` | `{ ask_before_edit: ["docs/adr/"] }` | hub.json | < 2 s |
| `valid`, `validation_errors[]` | bool, Problem list | schema check | on register and on change |

### Repo

| Field | Type | Source | Latency |
|---|---|---|---|
| `name`, `dir`, `github` (`owner/name`), `role`, `default_branch` | string | hub.json | < 2 s |
| `check_fast`, `check` | `make check-fast`, `make check` | hub.json | < 2 s |
| `agents_md_present`, `agents_md_lines` | bool, int | hub files (repo checkout) | < 2 s |
| `last_ci_default` | `{ status, sha, url, finished_at }` | github | ≤ 60 s |
| `open_prs` | int | github | ≤ 60 s |

### Agent

| Field | Type | Source | Latency |
|---|---|---|---|
| `id` | `hub-workflow:evaluator`; the main session is `main` | hooks (session.start `agent`) | < 1 s |
| `plugin`, `name`, `role_icon` | derived from id | derived | n/a |
| `model` | `claude-opus-4-1` etc. | otel, transcript fallback | 1–5 s |
| `instructions_path` | `plugin/hub-workflow/agents/evaluator.md` | hub files | < 2 s |

### Session

| Field | Type | Source | Latency |
|---|---|---|---|
| `id`, `project`, `repo`, `agent` | `agent` is deprecated (AGH-201): read `label` and `actors` | hooks session.start | < 1 s |
| `parent_session_id` | always null: subagents share their session's id (AGH-201) | — | — |
| `run_id`, `step`, `attempt` | | executor | < 1 s |
| `issue` | `AGH-48` | executor, or branch name parse (derived, labelled) | < 1 s |
| `label` (AGH-201) | `{ issue: "DEMO-1511" \| null, workflow: "/feature", workflows: ["/feature","/fix"], repo, branch, worktree, derived: true }` | derived (transcript `git_branch`, `cwd`, slash commands, Skill calls; the hub's tracker teams) | 2–10 s |
| `actors` (AGH-201) | `[{ kind: "main" \| "subagent", type, agent_id, description, started_by_event_id }]` | derived (hooks `agent_id`, Agent tool calls) | < 1 s |
| `problems` (AGH-201) | `{ needs_you, open, handled, by_you }`; the items via `/problems` | derived (tool results, guard asks, gates) | < 1 s |
| `started_at`, `ended_at`, `last_activity_at` | | hooks | < 1 s |
| `segments[]` | `[{ started_at, ended_at, end_reason }]` resumed segments | hooks | < 1 s |
| `status` | `live \| waiting \| idle \| ended` | derived (see rules below) | < 1 s |
| `outcome` | `done \| stopped \| blocked \| error \| null`, `end_reason` raw Claude Code reason | hooks + executor | < 1 s |
| `turns` | int | transcript | 2–10 s |
| `tool_counts` | `{ "Read": 31, "Bash": 7 }` | hooks | < 1 s |
| `files_touched` | int, list via `/files` | hooks (tool.call paths) | < 1 s |
| `errors`, `guard_denials` | int | hooks | < 1 s |
| `tokens` | `{ input, output, cache_read, cache_write }` | otel (transcript fallback, labelled "estimated") | 1–5 s |
| `cost_usd` | `"1.2734"` | otel | 1–5 s; may change after end (late) |
| `decisions`, `gates`, `learnings_proposed` | int | transcript, hooks | 2–10 s |
| `transcript` | `{ state: "available \| expires_soon \| expired", expires_on: "2026-11-10" }` | collector retention | n/a |
| `pr` | `{ number: 69, url, state }` or null | github | ≤ 60 s, often after end |
| `late_fields[]` | `["cost_usd","pr"]` fields changed after `ended_at` | derived | n/a |

Status rules (decisions other specs use):
- `waiting`: an unresolved `gate.request` exists. Wins over all other live states.
- `live`: any event in the last 5 minutes.
- `idle`: no event for 5 minutes or more and no `session.end`. **Proposal:** idle threshold 5 min (a long `make check` runs about 3 min; 5 min keeps a normal check from flapping to idle).
- `ended`: `session.end` received, or **Proposal:** no event for 30 minutes and no `session.end` → `ended` with `outcome = null`, `end_reason = "no_end_event"` and copy "Ended · no end event received (last activity 14:02)". A later event reopens the session as a new segment.

### WorkflowRun

| Field | Type | Source | Latency |
|---|---|---|---|
| `id`, `project`, `repo`, `issue` (`{ key, title, url }`) | | executor (+ linear for title) | < 1 s (title ≤ 60 s) |
| `workflow` | `{ name: "issue-to-pr", revision: 3, content_hash: "9f2c1a7" }` | executor | < 1 s |
| `stage` | `PICKED \| WORKTREE \| IMPLEMENTING \| VERIFYING \| PR_OPEN \| REPORTED \| FAILED` | executor | < 1 s |
| `failure` | `{ stage, reason, diagnosis_comment_url, failing_event_id }` | executor + linear | < 1 s (comment ≤ 60 s) |
| `steps[]` | `[{ key, attempt, status, started_at, ended_at, session_ids[] }]` | executor | < 1 s |
| `mode` | `live \| dry_run` | executor | < 1 s |
| `caps` | `{ budget_usd: "10.0000", max_turns: 80, model, tracker_transport }` | executor | < 1 s |
| `cost_usd` | sum of sessions | derived (otel) | 1–5 s |
| `gate_results[]` | `{ command, exit_code, duration_ms, log_excerpt }` | executor | < 1 s |
| `tracker_writes[]` | `{ kind: "label_add \| comment", value, at }` | executor | < 1 s |
| `pr` | `{ number, url, state, checks[] }` | github | ≤ 60 s |

### Step / attempt

Keyed `(step, attempt)`: `{ key: "verify", attempt: 2, max_attempts: 2, status: "failed", started_at, ended_at, session_ids, gate_result_id }`. Source executor, < 1 s.

### Gate

`{ id, kind: "command \| human \| guard_ask", name, requested_at, requested_by (agent or step), resolved_at, result: "passed \| failed \| approved \| changes_requested \| rejected \| pending", command?, exit_code?, approver? }`. Command gates from executor (< 1 s); human and guard_ask gates from hooks (< 1 s); approval decisions from the decision endpoint (P4) or the terminal.

### Learning

`{ id, text, target: { kind: "team \| repo \| personal", path: "brain/learnings/gotchas/testing.md" }, author: { kind: "agent \| person", id }, provenance: "agent \| agent-from-code \| agent-from-external \| human", source_session_id, source_event_id, status: "proposed \| accepted \| rejected \| snoozed", decided_by, decided_at, brain_path, commit, rejection_reason }`. Proposal events from transcript (2–10 s); inbox files from hub files (< 2 s); decisions P3.

As built (AGH-201): `status` is `proposed | accepted | rejected` (no `snoozed`; snooze stays P3). `target` is deprecated in favour of `note_path` (the inbox note, `brain/_inbox/<name>.md`). Added: `state` (`proposed | accepted_pr_open | rejected_pr_open | in_brain | archived`; the last two inferred from the hub checkout), `summary` (the note's first paragraph, 200 chars, read on request), `note_unavailable` and `actions_unavailable` (a reason, e.g. "Note not in the hub checkout", "Hub is read-only here"), `pr_url`, `branch`. `GET /learnings/{id}` adds `note` (frontmatter and markdown, read on request, never stored), `suggested_target` and `target_choices`. Decisions are taken in the app through a hub PR (ADR 0024). As built (AGH-272, ADR 0037, proposed): the accept body takes an optional `note_body`, the owner's edited text after the frontmatter, written in the PR's one commit; a note only in the hub checkout is added from there. Edit drafts and the link to Claude's review session are kept in the browser, never in the database.

### Decision

`{ id, project, repo, session_id, event_id, choice, alternatives[], rationale, evidence[] (event ids, paths), origin: "extracted \| recorded", confidence: "high \| medium \| low" (extracted only), approved_by }` plus brain decisions `D1, D2…` and ADRs `{ key: "D4", status: "active \| superseded", superseded_by }`. Source transcript (extracted, 2–10 s) and hub files (brain/decisions).

### Feature

`{ project, slug: "layered-memory", issues: ["AGH-48"], size: "spike \| bounded \| architectural", phase: "spec \| research \| plan \| tickets \| implement \| review \| evaluate \| shipped", acs: { passing: 21, total: 21 }, verdict: "SHIP \| SHIP-WITH-OWNER-STEPS \| NO-SHIP \| null", repos[] }`. Source hub files (< 2 s).

### Finding (Doctor)

`{ id, rule: "instructions.size", severity: "error \| warning \| info", area, path: "AGENTS.md", line: 1, message: "132 lines, limit 100", fix: "Keep it a map, not a manual", first_seen_at }`. Source hub files (doctor run), ≤ 15 min.

### Event (canonical)

```json
{
  "id": "01929a4e-6c1d-7f3a-9b2e-5d1c0a8e4f17",
  "project": "agent-hub",
  "session": "01929a40-5091-7b98-8a6e-3f20c1d4a7b2",
  "type": "tool.result",
  "timestamp": "2026-10-09T14:05:41.882Z",
  "received_at": "2026-10-09T14:05:42.103Z",
  "source": "claude_code",
  "source_id": "toolu_01Xk…:post",
  "repo": "agent-hub",
  "agent": "hub-workflow:evaluator",
  "workflow": "issue-to-pr",
  "step": "evaluate",
  "turn": 14,
  "parent_event_id": "01929a4e-6a02-7c11-8f00-1b2c3d4e5f60",
  "payload": { "tool": "Bash", "status": "ok", "exit_code": 0, "duration_ms": 192400, "output_bytes": 18234, "blob_ref": "tx/01929a40/14/3" }
}
```

**Proposal:** add `received_at` (ingestion time, gives the latency column in Raw events), `turn` (turn number, enables the turn axis and grouping) and `parent_event_id` (links a result to its call, a child session to its Agent call). All three are derivable at ingestion; storing them avoids recomputation on every read.

## Event type → timeline row mapping

Icons are Lucide names; colour tokens from `tokens.json`. "Collapsed" is the one-line row text (pattern with `{}` fields); "Detail" is what expanding shows. Rows use `TimelineEvent` unless stated.

| Type | Source | Icon | Colour token | Label | Collapsed text pattern | Expandable detail |
|---|---|---|---|---|---|---|
| `session.start` | claude_code | `play` | `ev-lifecycle` | Session started | "Session started · {agent} in {repo} · {model}" ; resumed: "Session resumed · segment {n}" | cwd, git branch, permission mode, hub brief size |
| `session.end` | claude_code | `square` | `ev-lifecycle` | Session ended | "Session ended · {outcome} · {end_reason}" | end reason raw, totals at end |
| `message` (role user) | transcript | `user` | `ev-prompt` | Prompt | "{first 120 chars}" | Full text (`Markdown`), or `ExpiredContent` |
| `message` (role assistant) | transcript | `message-square` | `ev-message` | Agent message | "{first 120 chars}" | Full text, or `ExpiredContent` |
| `reasoning` | transcript | `brain` | `ev-reasoning` | Recorded reasoning summary | italic "{first 120 chars}" | Full summary, `DerivedLabel` "Recorded reasoning summary" |
| `tool.call` Read/Glob/Grep | claude_code | `file-text` / `folder-search` / `search` | `ev-tool` | Read / Glob / Grep | "Read `{path}`"; grouped: "Read {n} files in `{common prefix}`" (`ToolGroup`) | list of paths, sizes, line ranges |
| `tool.call` Edit/Write | claude_code | `file-pen` / `file-plus` | `ev-tool` | Edit / Write | "Edit `{path}` · +{added} −{removed}" | inline `DiffViewer` (unified, 3 lines context) |
| `tool.call` Bash | claude_code | `terminal` | `ev-tool` | Bash | mono "`{command}`" + result chip "exit {code} · {duration}" | `CodeBlock` command, output excerpt (first 40 + last 40 lines) |
| `tool.call` Agent | claude_code | `bot` | `ev-tool` | Subagent | "Started {subagent id}"; as built: "Main agent · Started subagent {type}: {description}", its rows nested under it | opens `SubagentLane` |
| `tool.call` Skill (AGH-201) | claude_code | the tool icon | `ev-tool` | Skill | "Main agent · Ran skill /{skill}" | skill name |
| `tool.call` WebFetch | claude_code | `globe` | `ev-tool` | WebFetch | "Fetched {host}{path}" + `ExternalLabel` | URL, bytes, status |
| `tool.call` MCP | claude_code | `plug` | `ev-tool` | MCP · {server} | "{server}.{tool}" | args (redacted), result size |
| `tool.result` ok | claude_code | (merged into its call row as a status chip `check`) | `ev-tool` | Result | chip "ok" | output metadata; content blob |
| `tool.result` error | claude_code | `circle-x` | `failed` | Tool error | "{tool} failed · {error first line}" | error text (as built: `error_message`, 300 chars, redacted, else `error_line`), exit code, problem status |
| `tool.result` denied | claude_code | `shield-x` | `guard` on `guard-soft` | Denied by guard | "Push to main denied" / "Force-push blocked" | rule id, hook, matched command, hub.json path |
| `gate.request` (command) | executor | `flag` | `ev-gate` | Gate | "Gate {name} requested · `{command}`" | requester, step |
| `gate.request` (human) | claude_code / executor | `stamp` | `ev-gate` | Approval requested | "Waiting for plan approval for {issue}" | material link (Approvals) |
| `gate.request` (guard_ask) | claude_code | `shield-alert` | `guard` | Guard asks | "Edit under docs/adr/ needs approval" | path, rule `guard.ask_before_edit` |
| `gate.result` | executor / claude_code | `flag` (passed `check`, failed `x`) | `done` / `failed` / `ev-gate` | Gate result | "`{command}` passed · exit 0 · 3 min 12 s" / "failed · exit 2" | log excerpt, approver |
| `decision` | transcript | `git-commit-vertical` | `ev-decision` | Decision | "{choice}" + `DerivedLabel` "Extracted from transcript" or "Recorded with /decide" | alternatives struck through, rationale, evidence |
| `learning.proposed` | transcript | `lightbulb` | `ev-learning` | Learning proposed | "Proposed: {text}" · target path | target, provenance, status link |
| `learning.accepted` | hub files / app action (`control_plane`) | `lightbulb` (check overlay) | `ev-learning` | Learning accepted | "Accepted: {text}" | brain path, commit or PR link |
| `learning.rejected` | app action (`control_plane`) | `lightbulb-off` | `ev-lifecycle` | Learning rejected | "Rejected: {text} · {reason}" | reason, who, PR link |
| `step.start` / `step.end` **Proposal** | executor | `circle-dot` / `circle-check` | `ev-lifecycle` | Step | "Step {key} attempt {n} started / ended {status}" | step caps, gate link |
| `run.end` **Proposal** | executor | `flag-triangle-right` | `ev-lifecycle` | Run ended | "Run {issue} reported / failed at {stage}" | failure reason |
| `session.summary` **Proposal** | collector (derived) | `text-quote` | `ev-lifecycle` | Summary | not a row: feeds the summary card | n/a |
| `hook.blocked` **Proposal** | claude_code | `shield-off` | `guard` | Stop blocked | "Stop blocked: check_fast failing for changed code" | failing command, exit code, files |
| late enrichment (any event with `received_at` > session `ended_at`) | otel / github | `clock-arrow-up` | `ev-lifecycle` | Updated after end | "Cost updated after the session ended · $1.2734 → $1.3102" | before/after |

Notes: `session.summary` uses icon `text-quote` (no sparkle iconography: the summary is derived text, not magic). Guard events (denied, ask, Stop blocked) share the `shield-*` family and `guard` colour so they are pre-attentively distinct from tool errors (`failed`) and gates (`waiting`). Why `hook.blocked` is a new type: a blocked Stop is neither a tool result nor a gate; folding it into either would make "guard denials" metrics wrong.

## Endpoint catalogue

All paths under `/api/v1`. Shapes are trimmed sketches; lists are paginated.

| Endpoint | Params | Response sketch | Used by |
|---|---|---|---|
| `GET /projects` | `period` | `{"items":[{"name":"agent-hub","hub_health":"warning","repos":1,"live_sessions":3,"runs_in_flight_by_stage":{"IMPLEMENTING":1},"open_prs":2,"failed_runs_7d":1,"cost_period":"84.2000","cost_previous_period":"71.3600","ready_issues":4,"platform_version":"0.8.0","lock_state":"sync_pending"}]}` | Portfolio, ProjectSwitcher |
| `GET /projects/{project}` | | `{"name":"agent-hub","hub_repo":"jroquette/agent-hub-hub","tracker":{"kind":"linear","teams":["AGH"]},"platform_version":"0.8.0","lock_state":"sync_pending","modules":["bench","cloud","marketplace"]}` | Project overview header |
| `GET /projects/{project}/now` | | `{"focus":[{"text":"…","last_verified":"2026-10-01","provenance":"human"}],"next":[],"watch":[]}` | Project overview Now |
| `GET /projects/{project}/repos` | | `{"items":[{"name":"agent-hub","default_branch":"main","last_ci_default":{"status":"passed"},"open_prs":2,"check_fast":"make check-fast","agents_md_present":true}]}` | Project overview Repos |
| `GET /needs-you` | `scope` | `{"items":[{"kind":"approval","verb":"Approve plan for AGH-48","age_s":2520,"href":"/approvals/…"}],"total":6}` | Portfolio Needs you |
| `GET /activity` | `scope`, `period`, `cursor` | `{"items":[{"kind":"pr_merged","text":"PR agent-hub #69 merged","at":"…","href":"…"}]}` | Portfolio, Project overview |
| `GET /search` | `q`, `scope`, `limit` | `{"groups":[{"kind":"issues","items":[{"key":"AGH-48","title":"Layered memory","href":"/runs/…","score":1.0}]}]}` | CommandPalette |
| `GET /sessions` | `project, repo, agent, outcome, workflow, from, to, cost_min, cost_max, file, tool, guard_denial, has_decisions, sort, cursor` | `{"items":[{"id":"…","started_at":"…","duration_ms":4210000,"agent":"hub-workflow:evaluator","issue":"AGH-48","outcome":"done","turns":38,"tokens":{"input":412330},"cost_usd":"1.2734","transcript":{"state":"available","expires_on":"2026-11-10"}}],"next_cursor":"…","total_estimate":1240}` | Sessions list, Project overview |
| `GET /sessions/{id}` | | full Session entity (above) | Session detail header |
| `GET /sessions/{id}/summary` | | `{"lines":[{"text":"Ran make check-fast: passed in 3 min 12 s","event_id":"…"}],"generated_at":"…","derived":true}` | Session detail summary card |
| `GET /sessions/{session_id}/problems` (AGH-201) | | `{"session_id":"…","summary":[{"text":"2 problems: 1 needs you, 1 handled by the agent","event_id":"…"}],"items":[{"event_id":"…","kind":"command_exit","tool":"Bash","where":"make check","message":"…","at":"…","actor":{"kind":"main"},"resolution":"recovered","resolved_by_event_id":"…","derived":true}]}` | What went wrong, Live tiles |
| `GET /sessions/{id}/events` | `cursor, types, around` (event id), `limit` (default 200), `include_children` | `{"items":[Event],"next_cursor":"…","prev_cursor":"…"}` | Timeline, Raw events |
| `GET /sessions/{id}/events/stream` | header `Last-Event-ID` | SSE (below) | Timeline live |
| `GET /sessions/{id}/files` | | `{"items":[{"repo":"agent-hub","path":"brain/features/layered-memory/eval.md","ops":["edited"],"added":64,"removed":0,"event_ids":["…"]}]}` | Files and diffs |
| `GET /sessions/{id}/files/diff` | `path`, `repo` | `{"path":"…","hunks":[…],"content_state":"available \| expired"}` | Files and diffs, DiffViewer |
| `GET /sessions/{id}/decisions` P3 | | `{"items":[Decision]}` | Decisions tab |
| `GET /sessions/{id}/context` P3 | | `{"layers":[{"kind":"managed_rules","path":"AGENTS.md","lines":96,"tokens":2140}]}` | Context tab |
| `GET /sessions/{id}/cost` | `by=turn\|subagent` | `{"series":[{"turn":1,"input":…,"output":…,"cache_read":…,"cache_write":…,"cost_usd":"0.0412"}],"by_subagent":[…],"budget_usd":"10.0000","total_usd":"1.2734","run_total_usd":"6.8000"}` | Cost tab |
| `GET /live-sessions` | `scope` | `{"items":[{"id":"…","status":"waiting","waiting_reason":"Plan approval","last_action":"Running make check-fast","sparkline_60s":[0,2,1,…],"cost_usd":"2.1400","budget_usd":"10.0000","burn_rate_usd_per_min":"0.0812"}]}` | Live sessions |
| `GET /live-sessions/stream` | `scope`, `Last-Event-ID` | SSE | Live sessions |
| `GET /workflow-runs` | `project, repo, stage, outcome, failure_stage, mode, cursor` | list of WorkflowRun (summary) | Runs list, Kanban |
| `GET /workflow-runs/{id}` | | WorkflowRun with steps, gates, tracker writes, caps | Run detail |
| `GET /workflow-runs/{id}/stream` | `Last-Event-ID` | SSE | Run detail live |
| `POST /workflow-runs` P4 | `{"issue":"AGH-112","workflow":"issue-to-pr","dry_run":true}` | `{"id":"…","mode":"dry_run","plan":[{"kind":"command","value":"make check"}]}` | Tracker queue, Run detail |
| `POST /workflow-runs/{id}/retry` P4 | `{"from_step":"verify"}` | `202 {"id":"…"}` | Run detail |
| `GET /approvals` / `GET /approvals/{id}` | `scope` | `{"items":[{"id":"…","kind":"plan","issue":"AGH-48","requested_by":"hub-workflow:planner","waiting_since":"…"}]}` | Approvals, badge |
| `POST /approvals/{id}/decision` P4 | `{"decision":"approve","comment":""}` | `200 {"status":"approved"}` | Approvals |
| `GET /brain/notes`, `/brain/notes/backlinks` P3 | `project, path` | `{"path":"brain/now.md","frontmatter":{…},"markdown":"…"}` | Brain browser, Now |
| As built (AGH-201): `GET /projects/{project}/brain`, `GET /projects/{project}/brain/note` | `path` (under `brain/`) | tree `{"project","entries":[{"path","size"}],"truncated","skipped"}`; note `{"project","path","frontmatter","frontmatter_problem","markdown","size"}`; 400 / 404 / 413 problems | Brain browser, Feature detail tabs |
| `GET /learnings`, `/learnings/{id}`, `/learnings/{id}/trace` | `status` | Learning; trace `{"nodes":[…],"edges":[…]}` | Learnings, Portfolio |
| `POST /learnings/{id}/accept\|reject\|snooze` P3 | reject `{"reason"}` | Learning | Learnings |
| As built (AGH-201): `POST /learnings/{learning_id}/accept`, `/reject` (snooze and trace stay P3) | accept `{"target"}`, reject `{"reason"}` | `201 {"state":"accepted_pr_open","pr_url":"…","branch":"…"}`; 409 / 415 / 502 / 504 problems ([API.md](../../../API.md)) | Learning detail |
| `GET /decisions` P3 | `project, repo` | list of Decision | Decisions log |
| `GET /features`, `/features/{project}/{slug}` | `project` | Feature | Features |
| `GET /workflows…` P4 | | catalog, revisions, stats | Workflows |
| `GET /metrics/{metric}` | `scope, period, group_by` | `{"metric":"cost-per-run","period":"7d","n":11,"series":[…],"definition":"…"}` | Metrics, Portfolio cost |
| `GET /bench/results` | `project` | cases × arms | Bench |
| `GET /doctor/findings`, `/doctor/runs` | `project` | list of Finding; runs with counts | Health, Project overview |
| `GET /tracker/issues` | `project, label` | `{"items":[{"key":"AGH-112","repo":"agent-hub","title":"Cap the tracker team list","age_s":…,"url":"…"}]}` | Tracker queue, Portfolio |
| `GET /hubs`, `POST /hubs`, `DELETE /hubs/{id}` | `{"path"}` | Hub | Settings, First run |
| `GET /collector/status` | | `{"state":"running","db_path":"~/.agent-hub/events.db","events_today":1284,"sources":[{"source":"claude_code","last_event_at":"…","lag_ms":400,"state":"fresh"}]}` | CollectorPill, Settings |
| `GET /settings`, `PATCH /settings` | | `{"transcript_retention_days":30,"redaction_rules":["github_token","aws_key"]}` | Settings |
| `GET /events/stream` | `scope`, `Last-Event-ID` | SSE global | Shell badges, pill |

## SSE contract

All streams are `text/event-stream`, UTF-8, one JSON object per `data:` line.

| Stream | Event names | Data |
|---|---|---|
| `/events/stream` (global) | `heartbeat`, `counts`, `collector` | heartbeat `{"at":"…","sources":{"claude_code":"…","transcript":"…"}}`; counts `{"approvals_open":2,"live_sessions":3,"failed_runs_since_seen":1,"learnings_proposed":15,"doctor_errors":1,"ready_issues":4}` |
| `/sessions/{id}/events/stream` | `event` (canonical Event), `session` (patched Session fields), `heartbeat`, `end` | `session` carries only changed fields: `{"status":"waiting","cost_usd":"2.1400"}` |
| `/live-sessions/stream` | `tile.upsert`, `tile.remove`, `heartbeat` | tile shape as in `GET /live-sessions` |
| `/workflow-runs/{id}/stream` | `run` (patch), `step`, `gate`, `heartbeat` | |

Rules:
- Every message carries `id:` = the event's UUIDv7 (ordered). Heartbeats carry the last real id so resumption is exact.
- Resumption: the browser's `EventSource` resends `Last-Event-ID`; the server replays everything after it (up to 10,000 events or 24 h; beyond that it sends `event: reset` and the client refetches with `GET …/events?cursor=`).
- `retry: 3000` is sent on connect. Client backoff on repeated failure: 3 s, 6 s, 12 s, max 30 s, with ±20 % jitter.
- Heartbeat every 15 s on every stream, even when idle.
- Out-of-order events (transcript arrives after hooks) are inserted by `timestamp`, not arrival; the UI marks rows inserted above the viewport without moving the scroll position.
- Client state derivation (shared by `CollectorPill` and live screens): Connected = stream open and last message ≤ 20 s ago; Delayed = open and 20–60 s since last message, or any source past its stale threshold below; Offline = closed and reconnect failing for 10 s, or > 60 s without any message. 20 s = one missed heartbeat plus 5 s network allowance.

## Problem Details examples

The UI renders `ProblemError` with `title`, `detail` and a "Try again" button (plus a specific action when the `type` maps to one).

```json
{
  "type": "https://agent-hub.dev/problems/transcript-expired",
  "title": "Transcript content expired",
  "status": 410,
  "detail": "The transcript for session 5091b986 was deleted on 2026-11-10 under the 30-day retention rule. Structured events and the summary remain.",
  "instance": "/api/v1/sessions/01929a40-5091-7b98-8a6e-3f20c1d4a7b2/files/diff?path=brain/features/layered-memory/eval.md"
}
```
UI: inline `ExpiredContent` in the diff pane, no retry button (retry cannot help); link "Retention settings".

```json
{
  "type": "https://agent-hub.dev/problems/source-unreachable",
  "title": "GitHub not reachable",
  "status": 503,
  "detail": "The last 3 polls of github.com/jroquette/agent-hub failed (timeout after 10 s). PR and CI status are as of 14:02.",
  "source": "github",
  "as_of": "2026-10-11T14:02:00Z"
}
```
UI: partial state; PR and CI cells show "CI unknown" with `AsOfStamp` "as of 14:02"; the rest of the screen renders.

```json
{
  "type": "https://agent-hub.dev/problems/hub-invalid",
  "title": "hub.json does not match the schema",
  "status": 422,
  "detail": "repos[0].check_fast is missing in /home/jr/agent-hub-hub/hub.json. Run hub doctor in the hub directory for the full report.",
  "errors": [{ "pointer": "/repos/0/check_fast", "message": "required" }]
}
```
UI: Settings › Hubs row in `failed` with the detail and a copyable `hub doctor` command; "Try again" re-validates.

## Freshness and "as of"

`AsOfStamp` appears on any element whose source is past its stale threshold. Copy: "as of 14:02" (absolute, local or UTC per toggle), tooltip "GitHub last answered at 14:02:11 (12 min ago). Polling every 60 s.". Ground `idle-soft`, text `idle`, icon `clock`.

| Source | Fresh | Stale threshold | When stale |
|---|---|---|---|
| `claude_code` hooks | continuous while a session is live | > 60 s without an event for a session marked live, and no heartbeat movement | Live tiles show "as of"; status stays last known |
| `transcript` | within 10 s of turn end | > 5 min behind the last hook event of the same session | Messages and reasoning show "Transcript catching up · 4 min behind" |
| `otel` | within 5 s | > 2 min without a metric for a live session | Cost shows "as of" and "estimated from transcript" if available |
| `executor` | < 1 s | > 60 s without heartbeat during a run in a non-terminal stage | Run stage shows "as of" |
| `github` | ≤ 60 s | > 10 min since last successful poll | "GitHub not reachable, CI unknown" partial state |
| `linear` | ≤ 60 s | > 10 min since last successful poll | Issue titles and labels "as of" |
| hub files | < 2 s | watcher error, or doctor run older than 24 h | Health "Last doctor run 2 days ago" |
| collector (global) | heartbeat ≤ 20 s | > 60 s | Offline banner; every view shows "as of" |

## Deduplication of the same fact

1. Event identity is `(source, source_id)`. Ingestion is idempotent: a repeated pair is dropped. Two events from different sources are both kept (they are separate records).
2. The UI shows a fact once. **Proposal:** a `fact_key` is computed at ingestion and returned on every event: tool calls and results use Claude Code's `tool_use_id`; messages use transcript message uuid; tokens/cost use `(session, turn)`; PR link uses `(repo, pr_number)`; gate results use `(run, step, attempt)`.
3. When several events share a `fact_key`, the API returns one merged row with `sources: ["claude_code","transcript"]` and the fields taken by precedence:

| Fact | Precedence (first wins per field) | Why |
|---|---|---|
| Tool call, status, timing | claude_code hooks → transcript | Hooks are real time and authoritative for what ran and what the guard did |
| Tool input and output content | transcript → hooks | Transcript holds the full redacted content; hooks hold sizes |
| Messages, reasoning, decisions | transcript only | |
| Tokens and cost | otel → transcript (labelled "estimated") | otel is billing-grade |
| Step, gate and run state | executor → hooks | Executor owns the state machine |
| PR and CI | github → linear (comment links) → transcript mention (derived) | |
| Issue title and labels | linear → executor cache | |

4. Conflicts (same field, different values from two sources) keep the winner and expose the loser in Raw events with a `conflict` chip: "Transcript reports 41 turns; hooks counted 40". No silent averaging.
5. Totals (cost, tokens) are summed from merged facts only, so a session's cost appears once in its run total and once in the portfolio.
