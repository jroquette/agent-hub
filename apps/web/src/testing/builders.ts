/**
 * Typed builders of API response bodies for tests; every web fixture comes from here
 * (AC-200.64), with synthetic values only. `renderWithApi` renders a UI against a stubbed API.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import type { RenderResult } from "@testing-library/react";
import { createElement } from "react";
import type { ReactElement, ReactNode } from "react";
import { createMemoryRouter, RouterProvider } from "react-router";
import { onTestFinished, vi } from "vitest";

import type { components } from "../api/schema";
import { PreferencesProvider } from "../lib/preferences";

type Schemas = components["schemas"];
export type Session = Schemas["Session"];
export type TimelineEventBody = Schemas["TimelineEvent"];
export type WorkflowRun = Schemas["WorkflowRun"];
export type Approval = Schemas["Approval"];
export type Learning = Schemas["Learning"];
export type LiveTile = Schemas["LiveTile"];
export type ProjectSummary = Schemas["ProjectSummary"];
export type FeatureView = Schemas["FeatureView"];
export type FindingView = Schemas["FindingView"];
export type HubView = Schemas["HubView"];
export type CollectorStatus = Schemas["CollectorStatus"];
export type ProblemDetails = Schemas["ProblemDetails"];
export type SessionLabel = Schemas["SessionLabel"];
export type Actor = Schemas["Actor"];
export type SessionProblem = Schemas["Problem"];
export type SessionProblems = Schemas["SessionProblems"];
export type LearningDetail = Schemas["LearningDetail"];
export type LearningActionResult = Schemas["LearningActionResult"];
export type BrainTree = Schemas["BrainTree"];
export type BrainNote = Schemas["BrainNote"];
export type FeatureRecord = Schemas["FeatureRecord"];
export type GoldenStep = Schemas["GoldenStep"];
export type GoldenPath = Schemas["GoldenPath"];
export type EvalRecord = Schemas["EvalRecord"];
export type TicketRow = Schemas["TicketRow"];
export type TicketPlan = Schemas["TicketPlan"];
export type FeatureTickets = Schemas["FeatureTickets"];
export type AgentSession = Schemas["AgentSession"];
export type LogRecord = Schemas["LogRecord"];
export type RecordKind = Schemas["RecordKind"];
export type OpenPermission = Schemas["OpenPermission"];
export type PermissionSuggestion = Schemas["PermissionSuggestion"];
export type Workdir = Schemas["Workdir"];
export type DriverCapabilities = Schemas["DriverCapabilities"];
export type CloudSession = Schemas["CloudSession"];
export type PastSession = Schemas["PastSession"];

/** The synthetic clock every builder uses. */
export const T0 = "2026-10-11T14:00:00.000Z";

/** A time `seconds` after T0, as the API writes it. */
export function at(seconds: number): string {
  return new Date(Date.parse(T0) + seconds * 1000).toISOString();
}

/** A deterministic UUIDv7-shaped id: `01923f1e-0000-7000-8000-<n in 12 hex>`. */
export function anId(n: number, prefix = "01923f1e"): string {
  return `${prefix}-0000-7000-8000-${n.toString(16).padStart(12, "0")}`;
}

export function aPage<T>(items: T[], extra: { next_cursor?: string | null } = {}) {
  return { items, next_cursor: extra.next_cursor ?? null, total_estimate: items.length };
}

/** What session `anId(1, "5091b986")` is about: AGH-48 in /feature (a derived label). */
export function aSessionLabel(overrides: Partial<SessionLabel> = {}): SessionLabel {
  return {
    branch: "dev/agh-48-live-tiles",
    derived: true,
    issue: "AGH-48",
    repo: "agent-hub",
    workflow: "/feature",
    workflows: ["/feature", "/create-plan"],
    worktree: "agh-48-live-tiles",
    ...overrides,
  };
}

/** The main agent; a subagent with `{ kind: "subagent", type, agent_id, description }`. */
export function anActor(overrides: Partial<Actor> = {}): Actor {
  return {
    agent_id: null,
    description: null,
    kind: "main",
    started_by_event_id: null,
    type: null,
    ...overrides,
  };
}

export function aSession(overrides: Partial<Session> = {}): Session {
  return {
    actors: [anActor()],
    agent: "claude",
    agent_session_id: null,
    cost_usd: "1.2500",
    derived: true,
    end_inferred: false,
    end_reason: null,
    ended_at: null,
    errors: 0,
    files_touched: 3,
    gates: 1,
    guard_denials: 0,
    has_transcript: true,
    id: anId(1, "5091b986"),
    issue: "AGH-48",
    label: aSessionLabel(),
    last_activity_at: at(600),
    learnings_proposed: 0,
    model: "claude-model-a",
    outcome: null,
    parent_session_id: null,
    pr: null,
    problems: { by_you: 0, handled: 0, needs_you: 0, open: 0 },
    project: "agent-hub",
    repo: "agent-hub",
    run_id: null,
    segments: [{ end_inferred: false, end_reason: null, ended_at: null, index: 0, started_at: T0 }],
    sources_missing: ["otel", "github", "linear"],
    started_at: T0,
    status: "live",
    step: null,
    tokens: { cache_read: 1200, cache_write: 300, input: 4000, output: 900 },
    tool_counts: { Read: 4, Bash: 2 },
    turns: 5,
    ...overrides,
  };
}

export function aTimelineEvent(overrides: Partial<TimelineEventBody> = {}): TimelineEventBody {
  const seq = overrides.seq ?? 1;
  return {
    agent: "claude",
    conflict: false,
    event_id: anId(seq, "0192aaaa"),
    fact_key: null,
    latency_ms: 40,
    merged_sources: [],
    payload: { tool: "Bash", command: "make check-fast", tool_use_id: `toolu_${String(seq)}` },
    project: "agent-hub",
    received_at: at(seq),
    repo: "agent-hub",
    seq,
    session: anId(1, "5091b986"),
    source: "claude_code",
    source_id: `session:PreToolUse:toolu_${String(seq)}`,
    step: null,
    timestamp: at(seq),
    type: "tool.call",
    workflow: null,
    ...overrides,
  };
}

/** `n` timeline events of one session, cycling prompts, tool calls and results. */
export function manyEvents(n: number, session = anId(1, "5091b986")): TimelineEventBody[] {
  const kinds: Pick<TimelineEventBody, "type" | "payload">[] = [
    { type: "message", payload: { role: "user", chars: 120, turn: 1 } },
    { type: "tool.call", payload: { tool: "Read", path: "packages/core/src/x.py" } },
    { type: "tool.result", payload: { tool: "Read", status: "ok" } },
    { type: "tool.call", payload: { tool: "Bash", command: "make check-fast" } },
    { type: "tool.result", payload: { tool: "Bash", status: "ok", exit_code: 0 } },
  ];
  return Array.from({ length: n }, (_, i) => {
    const kind = kinds[i % kinds.length] ?? kinds[0];
    const turn = Math.floor(i / kinds.length) + 1;
    return aTimelineEvent({
      seq: i + 1,
      session,
      type: kind?.type ?? "message",
      payload: { ...kind?.payload, turn },
    });
  });
}

export function aRun(overrides: Partial<WorkflowRun> = {}): WorkflowRun {
  return {
    caps: {
      budget_usd: "5.0000",
      max_turns: 80,
      model: "claude-model-a",
      tracker_transport: "mcp",
    },
    cost_source: "sessions",
    cost_usd: "2.4000",
    derived: true,
    ended_at: null,
    failure: null,
    gate_results: [],
    id: "a1b2c3d4e5f6",
    issue: { key: "AGH-48", title: null, url: null },
    last_activity_at: at(900),
    mode: "live",
    pr_url: null,
    project: "agent-hub",
    repo: "agent-hub",
    session_ids: [anId(1, "5091b986")],
    sources_missing: ["github", "linear"],
    stage: "IMPLEMENTING",
    started_at: T0,
    steps: [
      {
        attempt: 1,
        ended_at: at(30),
        key: "pick",
        max_attempts: 1,
        reason: null,
        session_ids: [],
        started_at: T0,
        status: "ok",
      },
    ],
    workflow: "issue-to-pr",
    ...overrides,
  };
}

export function anApproval(overrides: Partial<Approval> = {}): Approval {
  return {
    decided: false,
    decided_at: null,
    decision_event_id: null,
    derived: true,
    feature: null,
    gate_id: "toolu_ask_1",
    how_to_decide: "cd /home/dev/agent-hub-hub && claude --resume 5091b986",
    hub_path: "/home/dev/agent-hub-hub",
    id: anId(7, "0192bbbb"),
    inferred: false,
    issue: "AGH-48",
    kind: "guard_ask",
    path: "packages/storage/migrations/0003.py",
    project: "agent-hub",
    repo: "agent-hub",
    request_event_id: anId(8, "0192aaaa"),
    requested_at: at(300),
    requested_by: "claude",
    rule: "ask_before_edit",
    session_id: anId(1, "5091b986"),
    sources_missing: [],
    status: "open",
    title: "Edit a guarded path",
    ...overrides,
  };
}

export function aLearning(overrides: Partial<Learning> = {}): Learning {
  return {
    actions_unavailable: null,
    author: "claude",
    brain_path: null,
    branch: null,
    commit: null,
    decided_at: null,
    decided_by: null,
    derived: true,
    id: anId(9, "0192cccc"),
    note_path: "brain/_inbox/web-gates.md",
    note_unavailable: null,
    pr_url: null,
    project: "agent-hub",
    proposed_at: at(500),
    provenance: "agent",
    rejection_reason: null,
    source_event_id: anId(10, "0192aaaa"),
    source_session_id: anId(1, "5091b986"),
    sources_missing: [],
    state: "proposed",
    status: "proposed",
    summary: "Run `npm ci` in apps/web before the web gates.",
    target: { kind: "repo", path: "agent-hub/AGENTS.md" },
    text: "Run the web gates with npm ci first",
    ...overrides,
  };
}

/** A learning read with its inbox note (GET /learnings/{learning_id}). */
export function aLearningDetail(overrides: Partial<LearningDetail> = {}): LearningDetail {
  return {
    ...aLearning(),
    note: aBrainNote({
      frontmatter: { provenance: "agent", type: "learning" },
      markdown:
        "# Run the web gates with npm ci first\n\nRun `npm ci` in apps/web before the web gates.\n",
      path: "_inbox/web-gates.md",
      size: 84,
    }),
    suggested_target: "learnings/",
    target_choices: ["learnings/", "playbooks/"],
    ...overrides,
  };
}

/** What an accept or reject answered (201). */
export function aLearningActionResult(
  overrides: Partial<LearningActionResult> = {},
): LearningActionResult {
  return {
    branch: "dev/learning-accept-web-gates",
    pr_url: "https://github.com/acme/agent-hub-hub/pull/12",
    state: "accepted_pr_open",
    ...overrides,
  };
}

/** One problem of session `anId(1, "5091b986")`: a failed `make check-fast` that needs you. */
export function aSessionProblem(overrides: Partial<SessionProblem> = {}): SessionProblem {
  return {
    actor: anActor(),
    at: at(420),
    derived: true,
    event_id: anId(7, "0192aaaa"),
    kind: "command_exit",
    message: "1 failed, 12 passed",
    resolution: "needs_you",
    resolved_by_event_id: null,
    tool: "Bash",
    where: "make check-fast",
    ...overrides,
  };
}

/** The problems route's body: its summary lines link to the problems' events. */
export function aSessionProblems(overrides: Partial<SessionProblems> = {}): SessionProblems {
  const problem = aSessionProblem();
  return {
    derived: true,
    items: [problem],
    session_id: anId(1, "5091b986"),
    sources_missing: [],
    summary: [{ event_id: problem.event_id, text: "Needs you: command_exit in make check-fast" }],
    ...overrides,
  };
}

/** The brain tree of project `agent-hub`. */
export function aBrainTree(overrides: Partial<BrainTree> = {}): BrainTree {
  return {
    entries: [
      { path: "_inbox/web-gates.md", size: 84 },
      { path: "decisions/index.md", size: 210 },
      { path: "features/control-plane/plan.md", size: 4096 },
      { path: "index.md", size: 180 },
      { path: "now.md", size: 140 },
    ],
    project: "agent-hub",
    skipped: 0,
    truncated: false,
    ...overrides,
  };
}

/** A brain note of project `agent-hub` (index.md by default). */
export function aBrainNote(overrides: Partial<BrainNote> = {}): BrainNote {
  return {
    frontmatter: { last_verified: "2026-10-11", type: "index" },
    frontmatter_problem: null,
    markdown: "# Brain\n\nStart at [now](now.md) and [decisions](decisions/index.md).\n",
    path: "index.md",
    project: "agent-hub",
    size: 180,
    ...overrides,
  };
}

export function aLiveTile(overrides: Partial<LiveTile> = {}): LiveTile {
  return {
    actors: [anActor()],
    agent: "claude",
    attempt: null,
    budget_usd: null,
    cost_usd: "0.8000",
    derived: true,
    ended_at: null,
    errors: 0,
    failing_notice: null,
    files_touched: 2,
    group: "live",
    guard_denials: 0,
    id: anId(1, "5091b986"),
    is_subagent: false,
    issue: "AGH-48",
    label: aSessionLabel(),
    last_action: "make check-fast",
    last_activity_at: at(590),
    last_tool: "Bash",
    needs_you_problem: null,
    outcome: null,
    problems: { by_you: 0, handled: 0, needs_you: 0, open: 0 },
    project: "agent-hub",
    repo: "agent-hub",
    run_id: null,
    sources_missing: [],
    sparkline_60s: [0, 1, 2, 0, 3, 1, 0, 0, 2, 1, 0, 1],
    started_at: T0,
    status: "live",
    step: null,
    tokens_total: 6400,
    turns: 5,
    waiting_reason: null,
    ...overrides,
  };
}

export function aProjectSummary(overrides: Partial<ProjectSummary> = {}): ProjectSummary {
  return {
    cost_daily: ["1.0000", "2.0000", "0.5000", "3.0000", "1.5000", "0.0000", "2.5000"],
    cost_period: "10.5000",
    cost_previous_period: "8.0000",
    derived: true,
    failed_runs_7d: 1,
    hub_health: "ok",
    hub_id: anId(20, "0192dddd"),
    hub_repo: "agent-hub-hub",
    live_sessions: 1,
    lock_state: "in_sync",
    lock_version: "0.4.0",
    name: "agent-hub",
    open_prs: null,
    platform_version: "0.4.0",
    ready_issues: null,
    repos: ["agent-hub"],
    runs_in_flight_by_stage: { IMPLEMENTING: 1 },
    sources_missing: ["github", "linear"],
    tracker_teams: ["AGH"],
    ...overrides,
  };
}

export function aProjectDetail(
  overrides: Partial<Schemas["ProjectDetail"]> = {},
): Schemas["ProjectDetail"] {
  return {
    branch_prefix: "dev/",
    default_branch: "main",
    hub_id: anId(20, "0192dddd"),
    hub_path: "/home/dev/agent-hub-hub",
    hub_repo: "agent-hub-hub",
    lock_state: "in_sync",
    lock_version: "0.4.0",
    modules: ["claude"],
    name: "agent-hub",
    platform_version: "0.4.0",
    tracker: {
      failed_label: "agent-failed",
      kind: "linear",
      ready_label: "agent-ready",
      teams: ["AGH"],
    },
    warnings: [],
    ...overrides,
  };
}

export function aProjectNow(overrides: Partial<Schemas["ProjectNow"]> = {}): Schemas["ProjectNow"] {
  return {
    focus: [{ text: "Control plane MVP", last_verified: "2026-10-11", provenance: "human" }],
    next: [{ text: "Phase 2 gate" }],
    problem: null,
    project: "agent-hub",
    source_path: "brain/now.md",
    watch: [],
    ...overrides,
  };
}

export function aRepo(overrides: Partial<Schemas["RepoView"]> = {}): Schemas["RepoView"] {
  return {
    agents_md_lines: 60,
    agents_md_present: true,
    check: "make check",
    check_fast: "make check-fast",
    default_branch: "main",
    derived: true,
    dir: "agent-hub",
    github: "example/agent-hub",
    name: "agent-hub",
    open_prs: null,
    role: "app",
    sources_missing: ["github"],
    ...overrides,
  };
}

export function aFeature(overrides: Partial<FeatureView> = {}): FeatureView {
  return {
    acs: { owner_steps: 1, passing: 40, total: 66 },
    derived: true,
    files: ["spec.md", "research.md", "plan.md"],
    issues: ["AGH-200"],
    phase: "implement",
    problem: null,
    project: "agent-hub",
    repos: ["agent-hub"],
    size: "architectural",
    slug: "control-plane",
    sources_missing: ["github"],
    verdict: null,
    verdict_line: null,
    golden_path: aGoldenPath(),
    tickets_source: "plan",
    ...overrides,
  };
}

/** One golden-path step: Implement, current, with its progress. */
export function aGoldenStep(overrides: Partial<GoldenStep> = {}): GoldenStep {
  return {
    name: "implement",
    state: "current",
    meta: "1/3 tickets · 40/66 ACs",
    reason: null,
    progress: { done: 1, total: 3 },
    ...overrides,
  };
}

/** The golden path of feature `control-plane`: in Implement, 1 of 3 tickets done. */
export function aGoldenPath(overrides: Partial<GoldenPath> = {}): GoldenPath {
  const gate = "Implement is not done";
  return {
    phase: "implement",
    steps: [
      aGoldenStep({ name: "spec", state: "done", meta: null, progress: null }),
      aGoldenStep({ name: "research", state: "done", meta: null, progress: null }),
      aGoldenStep({ name: "plan", state: "done", meta: null, progress: null }),
      aGoldenStep({
        name: "tickets",
        state: "done",
        meta: "3 of 3 created",
        progress: { done: 3, total: 3 },
      }),
      aGoldenStep(),
      aGoldenStep({
        name: "review",
        state: "pending",
        meta: "1/3 reviewed",
        reason: gate,
        progress: { done: 1, total: 3 },
      }),
      aGoldenStep({
        name: "evaluate",
        state: "partial",
        meta: "partial: covers 3 of 66 ACs",
        reason: gate,
        progress: { done: 3, total: 66 },
      }),
      aGoldenStep({ name: "shipped", state: "pending", meta: null, reason: gate, progress: null }),
    ],
    ...overrides,
  };
}

/** The SHIP eval of the first delivery of feature `control-plane`. */
export function anEvalRecord(overrides: Partial<EvalRecord> = {}): EvalRecord {
  return {
    delivery: "agh-201",
    path: "features/control-plane/evals/agh-201.md",
    verdict: "SHIP",
    tickets: ["AGH-201"],
    acs: ["AC-200.1", "AC-200.2", "AC-200.3"],
    prs: ["agent-hub#80"],
    commit: "0a1b2c3",
    evaluated_at: "2026-10-11",
    legacy: false,
    problem: null,
    ...overrides,
  };
}

/** Ticket `T2` (`AGH-202`) of feature `control-plane`: in progress, its blocker done. */
export function aTicketRow(overrides: Partial<TicketRow> = {}): TicketRow {
  return {
    ref: "AGH-202",
    key: "T2",
    id: "AGH-202",
    title: "Serve the ticket summaries",
    state: { name: "In Progress", type: "started" },
    assignee: "Ada Example",
    url: "https://linear.app/demo/issue/AGH-202",
    priority: 2,
    estimate: 3,
    repo: "agent-hub",
    order: 2,
    acs: ["AC-200.4"],
    blocked_by: [{ ref: "AGH-201", source: "both" }],
    blocks: ["AGH-203"],
    readiness: "can_start",
    waiting_on: [],
    reviewed: false,
    ...overrides,
  };
}

/** The planning of the three tickets of feature `control-plane` (`AGH-201` done). */
export function aTicketPlan(overrides: Partial<TicketPlan> = {}): TicketPlan {
  return {
    layers: [["AGH-202"], ["AGH-203"]],
    can_start: ["AGH-202"],
    order: ["AGH-202", "AGH-203"],
    waiting: ["AGH-203"],
    cycles: [],
    external_blockers: [],
    critical_path: ["AGH-202", "AGH-203"],
    warnings: [],
    ...overrides,
  };
}

/** The tickets of feature `control-plane` as Linear answered: done, can start, waiting. */
export function aFeatureTickets(overrides: Partial<FeatureTickets> = {}): FeatureTickets {
  return {
    project: "agent-hub",
    slug: "control-plane",
    source: "linear",
    stale: false,
    as_of: T0,
    notice: null,
    tracker_problem: null,
    tickets: [
      aTicketRow({
        ref: "AGH-201",
        key: "T1",
        id: "AGH-201",
        title: "Collect the events",
        state: { name: "Done", type: "completed" },
        url: "https://linear.app/demo/issue/AGH-201",
        order: 1,
        acs: ["AC-200.1", "AC-200.2", "AC-200.3"],
        blocked_by: [],
        blocks: ["AGH-202"],
        readiness: "done",
        reviewed: true,
      }),
      aTicketRow(),
      aTicketRow({
        ref: "AGH-203",
        key: "T3",
        id: "AGH-203",
        title: "Show the planning view",
        state: { name: "Todo", type: "unstarted" },
        assignee: null,
        url: "https://linear.app/demo/issue/AGH-203",
        priority: 0,
        estimate: null,
        order: 3,
        acs: ["AC-200.5"],
        blocked_by: [{ ref: "AGH-202", source: "plan" }],
        blocks: [],
        readiness: "waiting",
        waiting_on: ["AGH-202"],
      }),
    ],
    planning: aTicketPlan(),
    golden_path: aGoldenPath(),
    derived: true,
    sources_missing: ["github"],
    ...overrides,
  };
}

/** A record of feature `control-plane`, read through the brain note route. */
export function aFeatureRecord(overrides: Partial<FeatureRecord> = {}): FeatureRecord {
  const name = overrides.name ?? "spec";
  return {
    name,
    path: `features/control-plane/${name}.md`,
    present: true,
    ...overrides,
  };
}

export function aFeatureDetail(
  overrides: Partial<Schemas["FeatureDetail"]> = {},
): Schemas["FeatureDetail"] {
  return {
    ...aFeature(),
    ac_rows: [
      {
        command: "npm test",
        description: "The sidebar lists the Phase 2 items",
        evidence: "src/shell/Sidebar.test.tsx",
        id: "AC-200.42",
        manual: false,
        passes: true,
        repo: "agent-hub",
      },
    ],
    records: [
      aFeatureRecord({ name: "spec" }),
      aFeatureRecord({ name: "research" }),
      aFeatureRecord({ name: "plan" }),
      aFeatureRecord({ name: "eval", present: false }),
      aFeatureRecord({ name: "issues", present: false }),
    ],
    evals: [anEvalRecord()],
    ...overrides,
  };
}

export function aFinding(overrides: Partial<FindingView> = {}): FindingView {
  return {
    fix: "Run ./hub sync in the hub.",
    line: null,
    message: "hub.lock is older than the pinned platform version.",
    path: "hub.lock",
    project: "agent-hub",
    rule: "lock.in_sync",
    severity: "error",
    ...overrides,
  };
}

export function aHub(overrides: Partial<HubView> = {}): HubView {
  return {
    added_at: T0,
    guard_ask_before_edit: ["docs/adr"],
    id: anId(20, "0192dddd"),
    lock_state: "in_sync",
    lock_version: "0.4.0",
    modules: ["claude"],
    path: "/home/dev/agent-hub-hub",
    platform_pin: "0.4.0",
    project: "agent-hub",
    repos: ["agent-hub"],
    running_version: "0.4.0",
    valid: true,
    validation_errors: [],
    warnings: [],
    ...overrides,
  };
}

export function aCollectorStatus(overrides: Partial<CollectorStatus> = {}): CollectorStatus {
  return {
    appended: 120,
    db_path: "/home/dev/.local/share/agent-hub/events.db",
    duplicates: 3,
    events_total: 1284,
    hooks_received: 123,
    last_event_at: at(590),
    redaction_ruleset: "r1",
    running_version: "0.4.0",
    sources: [
      { last_event_at: at(590), source: "claude_code", state: "fresh" },
      { last_event_at: at(400), source: "transcript", state: "fresh" },
      { last_event_at: null, source: "executor", state: "never" },
    ],
    started_at: T0,
    state: "running",
    transcript_lines_skipped: 0,
    transcript_refused: 0,
    ...overrides,
  };
}

export function aSettings(
  overrides: Partial<Schemas["SettingsView"]> = {},
): Schemas["SettingsView"] {
  return {
    db_path: "/home/dev/.local/share/agent-hub/events.db",
    metadata_only: true,
    port: 7420,
    prices_as_of: "2026-10-11",
    redaction_kinds: ["github token", "anthropic key", "secret"],
    redaction_ruleset: "r1",
    registry_path: "/home/dev/.config/agent-hub/hubs.json",
    running_version: "0.4.0",
    ...overrides,
  };
}

export function aNeedsYouItem(
  overrides: Partial<Schemas["NeedsYouItem"]> = {},
): Schemas["NeedsYouItem"] {
  return {
    context: "agent-hub · AGH-48 · guarded path",
    href: `/approvals/${anId(7, "0192bbbb")}`,
    kind: "approval",
    project: "agent-hub",
    since: at(300),
    verb: "Approve an edit",
    ...overrides,
  };
}

export function anActivityItem(
  overrides: Partial<Schemas["ActivityItem"]> = {},
): Schemas["ActivityItem"] {
  return {
    at: at(800),
    event_id: anId(11, "0192aaaa"),
    href: "/runs/a1b2c3d4e5f6",
    kind: "reported",
    project: "agent-hub",
    text: "Run AGH-48 reported",
    ...overrides,
  };
}

export function aSearchHit(overrides: Partial<Schemas["SearchHit"]> = {}): Schemas["SearchHit"] {
  return {
    detail: "agent-hub · live",
    event_id: null,
    href: `/sessions/${anId(1, "5091b986")}`,
    kind: "session",
    label: "Session 5091b986",
    project: "agent-hub",
    ...overrides,
  };
}

export function aSessionSummary(
  overrides: Partial<Schemas["SessionSummary"]> = {},
): Schemas["SessionSummary"] {
  return {
    derived: true,
    generated_at: at(900),
    lines: [{ event_id: anId(5, "0192aaaa"), text: "Ran make check-fast: passed" }],
    session_id: anId(1, "5091b986"),
    sources_missing: [],
    stored: false,
    ...overrides,
  };
}

export function aSessionCost(
  overrides: Partial<Schemas["SessionCost"]> = {},
): Schemas["SessionCost"] {
  return {
    budget_usd: null,
    derived: true,
    model: "claude-model-a",
    prices_as_of: "2026-10-11",
    run_total_usd: null,
    series: [
      { cache_read: 100, cache_write: 20, cost_usd: "0.2000", input: 900, output: 200, turn: 1 },
      { cache_read: 300, cache_write: 0, cost_usd: "0.3500", input: 1200, output: 300, turn: 2 },
    ],
    session_id: anId(1, "5091b986"),
    sources_missing: ["otel"],
    total_usd: "0.5500",
    unknown_reason: null,
    ...overrides,
  };
}

export function aSessionFile(
  overrides: Partial<Schemas["SessionFileChange"]> = {},
): Schemas["SessionFileChange"] {
  return {
    added: 12,
    event_ids: [anId(3, "0192aaaa")],
    ops: ["read", "edited"],
    path: "packages/core/src/agent_hub/core/x.py",
    removed: 4,
    repo: "agent-hub",
    ...overrides,
  };
}

/** The global stream's `counts` message (StreamCounts in core). */
export interface StreamCounts {
  approvals_open: number;
  live_sessions: number;
  failed_runs_7d: number;
  learnings_proposed: number;
  doctor_errors: number | null;
  ready_issues: number | null;
}
export function aStreamCounts(overrides: Partial<StreamCounts> = {}): StreamCounts {
  return {
    approvals_open: 2,
    live_sessions: 3,
    failed_runs_7d: 1,
    learnings_proposed: 4,
    doctor_errors: 1,
    ready_issues: null,
    ...overrides,
  };
}

/* ---------- Agent sessions (AGH-165) ---------- */

const AGENT_SESSION_WORKDIR = "3f2a9c1d4b5e6f70";
const CLOUD_ID = "cse_01synthetic";

/** Claude's two suggestions for "always allow": one `localSettings` rule, one `session` mode. */
export function aSuggestions(): PermissionSuggestion[] {
  return [
    {
      destination: "localSettings",
      index: 0,
      rule: {
        behavior: "allow",
        destination: "localSettings",
        rules: [{ ruleContent: "git status", toolName: "Bash" }],
        type: "addRules",
      },
    },
    {
      destination: "session",
      index: 1,
      rule: { destination: "session", mode: "acceptEdits", type: "setMode" },
    },
  ];
}

/** An idle local agent session in the hub's workdir, linked to Claude session `anId(1, "5091b986")`. */
export function anAgentSession(overrides: Partial<AgentSession> = {}): AgentSession {
  return {
    claude_session_id: anId(1, "5091b986"),
    cloud_id: null,
    cost_usd: "0.0012",
    created_at: T0,
    end_reason: null,
    ended_at: null,
    id: anId(1, "0192a5e5"),
    kind: "local",
    last_seq: 4,
    mode: "default",
    model: "sonnet",
    open_permission: null,
    project: "agent-hub",
    status: "idle",
    title: "Run the tests",
    updated_at: at(60),
    url: null,
    usage: { cache_read: 0, cache_write: 0, input: 12, output: 5 },
    workdir_id: AGENT_SESSION_WORKDIR,
    workdir_label: "agent-hub-hub",
    ...overrides,
  };
}

/** A pending `Bash` permission request, as `GET /agent-sessions/{id}` shows it. */
export function aPermissionRequest(overrides: Partial<OpenPermission> = {}): OpenPermission {
  return {
    asked_at: at(30),
    deadline_at: at(630),
    input: null,
    request_id: "req-1",
    request_kind: "tool",
    suggestions: aSuggestions(),
    summary: "git status",
    tool: "Bash",
    ...overrides,
  };
}

/** The body of a record of each kind, as core writes it (synthetic text only). */
const RECORD_BODIES: Record<RecordKind, LogRecord["body"]> = {
  init: { model: "sonnet", session_id: anId(1, "5091b986"), slash_commands: ["/feature"] },
  text: { block: 0, text: "The tests pass." },
  thinking: { text: "Check the failing test first." },
  "tool.call": {
    input: { file_path: "src/app.py", new_string: "a = 2", old_string: "a = 1" },
    name: "Edit",
    parent_tool_use_id: null,
    tool_use_id: "toolu_01",
  },
  "tool.result": { content: "edited", is_error: false, tool_use_id: "toolu_01" },
  todos: { items: [{ active_form: null, content: "Fix the test", status: "in_progress" }] },
  "permission.request": {
    request_id: "req-1",
    request_kind: "tool",
    suggestions: aSuggestions(),
    summary: "git status",
    tool: "Bash",
  },
  result: {
    cost_usd: "0.0012",
    duration_ms: 40,
    model_usage: null,
    num_turns: 1,
    subtype: "success",
    terminal_reason: "completed",
    usage: { cache_read: 0, cache_write: 0, input: 12, output: 5 },
  },
  error: { message: "claude exited with code 1" },
  exited: { code: 0 },
  "user.message": { text: "Run the tests." },
  "permission.decision": { decision: "allow", request_id: "req-1" },
  interrupt: {},
  settings: { mode: "plan" },
  close: {},
  "log.truncated": { cap: "records", limit: 50000 },
  "cloud.start": { cloud_id: CLOUD_ID },
  "cloud.followup": { cloud_id: CLOUD_ID },
};
const SERVER_RECORDS: RecordKind[] = ["log.truncated"];
const WEB_RECORDS: RecordKind[] = [
  "user.message",
  "permission.decision",
  "interrupt",
  "settings",
  "close",
  "cloud.start",
  "cloud.followup",
];

/** A persisted record of `kind` with that kind's body; `by` is who caused it. */
export function aLogRecord(
  kind: RecordKind = "text",
  overrides: Partial<LogRecord> = {},
): LogRecord {
  const by = WEB_RECORDS.includes(kind)
    ? "web"
    : SERVER_RECORDS.includes(kind)
      ? "server"
      : "driver";
  const body = overrides.body ?? RECORD_BODIES[kind];
  return {
    at: at(overrides.seq ?? 1),
    body,
    by,
    kind,
    seq: 1,
    text_bytes: JSON.stringify(body).length,
    ...overrides,
  };
}

/** The hub's own folder, with one skill. */
export function aWorkdir(overrides: Partial<Workdir> = {}): Workdir {
  return {
    kind: "hub",
    label: "agent-hub-hub",
    repo: null,
    skills: ["feature"],
    workdir_id: AGENT_SESSION_WORKDIR,
    worktree: null,
    ...overrides,
  };
}

/** A machine that can drive sessions and start cloud ones. */
export function aCapabilities(overrides: Partial<DriverCapabilities> = {}): DriverCapabilities {
  return {
    available: true,
    cli_version: "2.1.296",
    cloud: true,
    cloud_followup: true,
    engine: "sdk",
    models: ["default", "opus", "sonnet", "haiku"],
    reason: null,
    ...overrides,
  };
}

/** A cloud start with its claude.ai/code link and teleport command. */
export function aCloudSession(overrides: Partial<CloudSession> = {}): CloudSession {
  return {
    cloud_id: CLOUD_ID,
    created_at: T0,
    followups: 0,
    id: anId(2, "0192a5e5"),
    project: "agent-hub",
    teleport_command: `claude --teleport ${CLOUD_ID}`,
    title: "Upgrade the linter",
    url: `https://claude.ai/code/${CLOUD_ID}`,
    workdir_id: AGENT_SESSION_WORKDIR,
    ...overrides,
  };
}

/** A text delta on the agent-session stream (`event: delta`, id `<after_seq>.<index>`, E8). */
export interface DeltaFrame {
  after_seq: number;
  block: number;
  index: number;
  text: string;
}
export function aDeltaFrame(overrides: Partial<DeltaFrame> = {}): DeltaFrame {
  return { after_seq: 3, block: 0, index: 0, text: "Hel", ...overrides };
}

/* ---------- Stubbed API ---------- */

/** A problem reply for `renderWithApi` routes. */
export class ProblemReply {
  constructor(readonly body: ProblemDetails) {}
}
export function aProblem(overrides: Partial<ProblemDetails> = {}): ProblemReply {
  return new ProblemReply({
    status: 500,
    title: "Internal server error",
    type: "about:blank",
    detail: null,
    ...overrides,
  });
}

/** A route's answer: a JSON body, a problem, "pending" (never answers) or a function of the request. */
export type RouteReply =
  ProblemReply | "pending" | ((request: Request) => unknown) | Record<string, unknown> | unknown[];

/** Keys are API paths ("/api/v1/hubs"), optionally prefixed by a method ("POST /api/v1/hubs"). */
export type ApiRoutes = Record<string, RouteReply>;

function jsonResponse(body: unknown, status: number, type = "application/json"): Response {
  return new Response(body === undefined ? null : JSON.stringify(body), {
    status,
    headers: { "content-type": type },
  });
}

/** Answers fetches from `routes`; an unknown route is a 404 problem naming it. */
export function stubApi(routes: ApiRoutes): Request[] {
  const requests: Request[] = [];
  vi.spyOn(globalThis, "fetch").mockImplementation(
    (input: RequestInfo | URL, init?: RequestInit) => {
      const request = input instanceof Request ? input : new Request(input, init);
      requests.push(request);
      const path = new URL(request.url).pathname;
      const reply =
        routes[`${request.method} ${path}`] ??
        (request.method === "GET" ? routes[path] : undefined);
      if (reply === undefined) {
        return Promise.resolve(
          jsonResponse(
            { status: 404, title: "Not found", detail: `No stub for ${request.method} ${path}` },
            404,
            "application/problem+json",
          ),
        );
      }
      if (reply === "pending") return new Promise<Response>(() => undefined);
      if (reply instanceof ProblemReply) {
        return Promise.resolve(
          jsonResponse(reply.body, reply.body.status, "application/problem+json"),
        );
      }
      const body = typeof reply === "function" ? reply(request) : reply;
      return Promise.resolve(jsonResponse(body, request.method === "POST" ? 201 : 200));
    },
  );
  return requests;
}

/* ---------- Fake EventSource ---------- */

type Listener = (event: MessageEvent<string>) => void;

/** A test double of EventSource; `streams` drives the instances a render opened. */
export class FakeEventSource {
  static readonly CONNECTING = 0;
  static readonly OPEN = 1;
  static readonly CLOSED = 2;
  static instances: FakeEventSource[] = [];

  readonly url: string;
  readyState = FakeEventSource.CONNECTING;
  onopen: ((event: Event) => void) | null = null;
  onerror: ((event: Event) => void) | null = null;
  private readonly listeners = new Map<string, Set<Listener>>();

  constructor(url: string | URL) {
    this.url = String(url);
    FakeEventSource.instances.push(this);
  }

  addEventListener(type: string, listener: Listener): void {
    const set = this.listeners.get(type) ?? new Set<Listener>();
    set.add(listener);
    this.listeners.set(type, set);
  }

  removeEventListener(type: string, listener: Listener): void {
    this.listeners.get(type)?.delete(listener);
  }

  close(): void {
    this.readyState = FakeEventSource.CLOSED;
  }

  /** Opens the connection. */
  open(): void {
    this.readyState = FakeEventSource.OPEN;
    this.onopen?.(new Event("open"));
  }

  /** Sends a named message with a JSON body. */
  emit(type: string, data: unknown, id = ""): void {
    const event = new MessageEvent<string>(type, { data: JSON.stringify(data), lastEventId: id });
    this.listeners.get(type)?.forEach((listener) => {
      listener(event);
    });
  }

  /** Fails the connection; `closed` makes it final (no browser retry). */
  fail(closed = false): void {
    this.readyState = closed ? FakeEventSource.CLOSED : FakeEventSource.CONNECTING;
    this.onerror?.(new Event("error"));
  }
}

/** Installs FakeEventSource for this test; returns a finder of the streams opened by URL prefix. */
export function stubEventSource(): (urlPrefix: string) => FakeEventSource {
  FakeEventSource.instances = [];
  vi.stubGlobal("EventSource", FakeEventSource);
  onTestFinished(() => {
    vi.unstubAllGlobals();
  });
  return (urlPrefix) => {
    const found = [...FakeEventSource.instances]
      .reverse()
      .find((source) => new URL(source.url, window.location.origin).pathname.startsWith(urlPrefix));
    if (!found) throw new Error(`No EventSource opened for ${urlPrefix}`);
    return found;
  };
}

/* ---------- Rendering ---------- */

export interface RenderWithApiOptions {
  routes?: ApiRoutes;
  /** The URL the router starts at (default "/"). */
  path?: string;
  /** The route pattern `ui` is mounted at (default "*"), for screens reading params. */
  route?: string;
}

export interface RenderWithApiResult extends RenderResult {
  requests: Request[];
  queryClient: QueryClient;
  router: ReturnType<typeof createMemoryRouter>;
  stream: (urlPrefix: string) => FakeEventSource;
}

export function testQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: Infinity }, mutations: { retry: false } },
  });
}

/** Providers every screen needs: queries and preferences. */
export function TestProviders({
  client,
  children,
}: {
  client: QueryClient;
  children: ReactNode;
}): ReactElement {
  return createElement(
    QueryClientProvider,
    { client },
    createElement(PreferencesProvider, null, children),
  );
}

/** Renders `ui` in a memory router with the API stubbed by `routes` (fetch and EventSource). */
export function renderWithApi(
  ui: ReactElement,
  { routes = {}, path = "/", route = "*" }: RenderWithApiOptions = {},
): RenderWithApiResult {
  const requests = stubApi(routes);
  const stream = stubEventSource();
  const queryClient = testQueryClient();
  const router = createMemoryRouter([{ path: route, element: ui }], { initialEntries: [path] });
  const result = render(
    createElement(TestProviders, {
      client: queryClient,
      children: createElement(RouterProvider, { router }),
    }),
  );
  return { ...result, requests, queryClient, router, stream };
}
