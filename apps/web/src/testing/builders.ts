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
export type LiveTile = Schemas["LiveTile"];
export type TimelineEventBody = Schemas["TimelineEvent"];
export type WorkflowRun = Schemas["WorkflowRun"];
export type Approval = Schemas["Approval"];
export type Learning = Schemas["Learning"];
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
export type KnowledgeResult = Schemas["KnowledgeResult"];
export type KnowledgeSearch = Schemas["KnowledgeSearch"];
export type NoteBacklink = Schemas["NoteBacklink"];
export type NoteBacklinks = Schemas["NoteBacklinks"];
export type FeatureRecord = Schemas["FeatureRecord"];
export type GoldenStep = Schemas["GoldenStep"];
export type GoldenPath = Schemas["GoldenPath"];
export type EvalRecord = Schemas["EvalRecord"];
export type TicketRow = Schemas["TicketRow"];
export type TicketFlow = Schemas["TicketFlow"];
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
export type CatalogItem = Schemas["CatalogItem"];
export type SkillCatalog = Schemas["SkillCatalog"];
export type SkillDetail = Schemas["SkillDetail"];
export type BundledFileText = Schemas["BundledFileText"];
export type WorkflowSummary = Schemas["WorkflowSummary"];
export type WorkflowCatalogView = Schemas["WorkflowCatalogView"];
export type WorkflowDetail = Schemas["WorkflowDetail"];
export type WorkflowProblem = Schemas["WorkflowProblemView"];
export type ItemVersion = Schemas["ItemVersionView"];
export type ItemVersionPage = Schemas["ItemVersionPage"];
export type ItemVersionContent = Schemas["ItemVersionContent"];
export type UsageRow = Schemas["UsageRow"];
export type UsageReport = Schemas["UsageReport"];

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

/** A `GET /sessions` route answering each `status=` query with only the sessions of that status. */
export function aSessionsByStatus(
  sessions: Session[],
  extra: { next_cursor?: string | null } = {},
) {
  return (request: Request) => {
    const status = new URL(request.url).searchParams.get("status");
    const items = sessions.filter((s) => status === null || s.status === status);
    return aPage(items, items.length > 0 ? extra : {});
  };
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

/** A live session tile (`GET /live-sessions`), with the same defaults as `aSession`. */
export function aLiveTile(overrides: Partial<LiveTile> = {}): LiveTile {
  return {
    actors: [anActor()],
    agent: "claude",
    agent_session_id: null,
    cost_usd: "1.2500",
    derived: true,
    errors: 0,
    files_touched: 3,
    group: "live",
    guard_denials: 0,
    id: anId(1, "5091b986"),
    is_subagent: false,
    issue: "AGH-48",
    label: aSessionLabel(),
    last_action: null,
    last_activity_at: at(600),
    last_tool: null,
    problems: { by_you: 0, handled: 0, needs_you: 0, open: 0 },
    project: "agent-hub",
    repo: "agent-hub",
    sources_missing: ["otel", "github", "linear"],
    started_at: T0,
    sparkline_60s: [],
    status: "live",
    tokens_total: 6400,
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
    kind: "workflow",
    last_activity_at: at(900),
    mode: "live",
    pr_url: null,
    project: "agent-hub",
    repo: "agent-hub",
    session_ids: [anId(1, "5091b986")],
    sources_missing: ["github", "linear"],
    stage: "IMPLEMENTING",
    started_at: T0,
    status: "running",
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

/** A failed run of the engine workflow `feature-flow` (see `aWorkflowDetail`): `plan` passed,
 * `build` failed twice (transient, then timeout), `docs` was skipped by its condition and
 * `review` because `build` failed. */
export function anEngineRun(overrides: Partial<WorkflowRun> = {}): WorkflowRun {
  const step = (
    key: string,
    attempt: number,
    status: WorkflowRun["steps"][number]["status"],
    extra: Partial<WorkflowRun["steps"][number]> = {},
  ): WorkflowRun["steps"][number] => ({
    attempt,
    ended_at: at(attempt * 60),
    key,
    max_attempts: 2,
    reason: null,
    session_ids: [],
    started_at: at(attempt * 60 - 50),
    status,
    ...extra,
  });
  return aRun({
    content_hash: "sha256:5f0c2e1d",
    ended_at: at(400),
    failure: {
      failing_event_id: null,
      failure_kind: "timeout",
      reason: "build",
      stage: "FAILED",
    },
    id: "feature-flow-7",
    issue: null,
    revision: 3,
    session_ids: [anId(7, "5091b986")],
    stage: "FAILED",
    status: "failed",
    steps: [
      step("plan", 1, "ok", { session_ids: [anId(7, "5091b986")], started_at: T0 }),
      step("build", 1, "failed", { failure_kind: "transient", reason: "transient" }),
      step("build", 2, "failed", { failure_kind: "timeout", reason: "timeout" }),
      step("docs", 1, "skipped", { skip_cause: "condition" }),
      step("review", 1, "skipped", {
        ended_at: at(300),
        skip_cause: "upstream_failed",
        started_at: at(300),
      }),
    ],
    workflow: "feature-flow",
    ...overrides,
  });
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

/** One knowledge search result: the decision on worktrees of project `demo` by default. */
export function aKnowledgeResult(overrides: Partial<KnowledgeResult> = {}): KnowledgeResult {
  return {
    path: "brain/decisions/0001-worktrees.md",
    kind: "decision",
    title: "Worktrees from origin",
    status: "accepted",
    provenance: null,
    snippet: "every task runs in its own worktrees created from origin",
    ...overrides,
  };
}

/** A knowledge search of project `demo` for "worktrees", with no result by default. */
export function aKnowledgeSearch(overrides: Partial<KnowledgeSearch> = {}): KnowledgeSearch {
  return {
    project: "demo",
    query: "worktrees",
    results: [],
    sync: { listed: 0, read: 0, indexed: 0, dropped: 0 },
    skipped: [],
    warnings: [],
    ...overrides,
  };
}

/** One source linking to a note: the playbook on cleanup by default. */
export function aBacklink(overrides: Partial<NoteBacklink> = {}): NoteBacklink {
  return {
    path: "brain/playbooks/cleanup.md",
    kind: "playbook",
    title: "Cleanup after merge",
    ...overrides,
  };
}

/** The backlinks of `index.md` in project `agent-hub`, none by default. */
export function aNoteBacklinks(overrides: Partial<NoteBacklinks> = {}): NoteBacklinks {
  const items = overrides.items ?? [];
  return { project: "agent-hub", path: "index.md", items, total: items.length, ...overrides };
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
    phase: "build",
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

/** One golden-path step: Build, current, with its progress. */
export function aGoldenStep(overrides: Partial<GoldenStep> = {}): GoldenStep {
  return {
    name: "build",
    state: "current",
    meta: "1 of 3 merged · 1 in progress",
    reason: null,
    progress: { done: 1, total: 3 },
    ...overrides,
  };
}

/** The golden path of feature `control-plane`: in Build, 1 of 3 tickets merged. */
export function aGoldenPath(overrides: Partial<GoldenPath> = {}): GoldenPath {
  const gate = "Build is not done";
  return {
    phase: "build",
    steps: [
      aGoldenStep({ name: "spec", state: "done", meta: null, progress: null }),
      aGoldenStep({
        name: "ux_design",
        state: "skipped",
        meta: "No screen change recorded",
        progress: null,
      }),
      aGoldenStep({ name: "research", state: "done", meta: null, progress: null }),
      aGoldenStep({ name: "plan", state: "done", meta: "v1", progress: null }),
      aGoldenStep({
        name: "tickets",
        state: "done",
        meta: "3 of 3 created",
        progress: { done: 3, total: 3 },
      }),
      aGoldenStep(),
      aGoldenStep({
        name: "acceptance",
        state: "partial",
        meta: "Ticket evals cover 3 of 66 ACs",
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
    parent: null,
    children: [],
    ...overrides,
  };
}

/** A ticket's own steps: implemented (a review round exists), at Review, 4 of 7. */
export function aTicketFlow(overrides: Partial<TicketFlow> = {}): TicketFlow {
  return {
    steps: [
      { name: "context", state: "unrecorded", meta: null },
      { name: "preflight", state: "unrecorded", meta: null },
      { name: "implement", state: "done", meta: null },
      { name: "review", state: "pending", meta: null },
      { name: "eval", state: "pending", meta: null },
      { name: "pr", state: "pending", meta: null },
      { name: "merged", state: "pending", meta: null },
    ],
    current: "review",
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
    epics: [],
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

export function anAcRow(overrides: Partial<Schemas["AcRow"]> = {}): Schemas["AcRow"] {
  return {
    command: "npm test",
    description: "The sidebar lists the Phase 2 items",
    evidence: "src/shell/Sidebar.test.tsx",
    id: "AC-200.42",
    manual: false,
    passes: true,
    repo: "agent-hub",
    signed_off: false,
    ...overrides,
  };
}

export function aFeatureDetail(
  overrides: Partial<Schemas["FeatureDetail"]> = {},
): Schemas["FeatureDetail"] {
  return {
    ...aFeature(),
    ac_rows: [anAcRow()],
    records: [
      aFeatureRecord({ name: "spec" }),
      aFeatureRecord({ name: "research" }),
      aFeatureRecord({ name: "plan" }),
      aFeatureRecord({ name: "eval", present: false }),
      aFeatureRecord({ name: "issues", present: false }),
    ],
    evals: [anEvalRecord()],
    plan: null,
    acceptance_eval: null,
    change_requests: [],
    ...overrides,
  };
}

/** Plan change request 2 of `control-plane`, asked by AGH-202 and open, its run waiting at its gate. */
export function aChangeRequest(
  overrides: Partial<Schemas["ChangeRequestView"]> = {},
): Schemas["ChangeRequestView"] {
  return {
    n: 2,
    ticket: "AGH-202",
    status: "open",
    plan_from: 2,
    plan_to: 3,
    affected: ["AGH-203"],
    opened_at: "2026-10-21T09:30:00Z",
    run_id: "implement-202",
    approval_id: "implement-202:approve-change:1",
    decidable_here: false,
    body_cut: false,
    decision: null,
    path: "features/control-plane/change-requests/2.md",
    problem: null,
    body: "## Evidence\n\nAGH-201 shipped `policyRef` instead of `policyId`.\n\n## Proposal\n\nRead `policyRef`.\n",
    ...overrides,
  };
}

/** One preflight run of a ticket: no drift, plan v2. */
export function aPreflightRun(
  overrides: Partial<Schemas["PreflightRun"]> = {},
): Schemas["PreflightRun"] {
  return {
    ran_at: "2026-10-21T09:30:00Z",
    plan_version: 2,
    commit: "4e1a9c2",
    blockers_read: [],
    input: "none",
    input_text: null,
    drift: "none",
    local_notes: [],
    change_request: null,
    run_id: "implement-202",
    ...overrides,
  };
}

/** AGH-202's records from the per-ticket route (A7): no brief, no preflight, no request. */
export function aTicketRecords(
  overrides: Partial<Schemas["TicketRecords"]> = {},
): Schemas["TicketRecords"] {
  return {
    derived: true,
    sources_missing: [],
    project: "agent-hub",
    slug: "control-plane",
    ticket: "AGH-202",
    preflight: null,
    change_requests: [],
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
    href: `/sessions/${anId(7, "0192bbbb")}`,
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
    changed_files: [],
    review_targets: [],
    claude_session_id: anId(1, "5091b986"),
    cloud_id: null,
    cost_usd: "0.0012",
    created_at: T0,
    end_reason: null,
    ended_at: null,
    id: anId(1, "0192a5e5"),
    kind: "local",
    last_prompt: null,
    last_reply: null,
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
  task: {
    description: "Review the change",
    status: "running",
    task_id: "task-1",
    task_type: "local_agent",
    tool_use_id: "toolu_02",
  },
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

/**
 * A body shaped like the hub's `/feature` (AC-164.18, P5): five steps by the shared rule (column-0
 * `^\d{1,9}[.)]\s` outside fences). The same text as core's `a_feature_shaped_body`.
 */
export function aFeatureShapedBody(): string {
  return [
    "# Feature",
    "",
    "Turn an idea into a delivered feature.",
    "",
    "## Steps",
    "",
    "1. **Spec**: the `requirements-analyst` agent writes `spec.md`.",
    "   1. A nested item is not a step.",
    "2. **Gate: user approves the spec**. Stop until they do.",
    "3. **Plan**: run `/create-plan` on the approved spec.",
    "4. **Implement** in a worktree; run `make check` before the PR.",
    "   ```bash",
    "   1. not a step inside a fence",
    "   ```",
    "5. **Doctor**: run `./hub doctor` and fix what it finds.",
    "",
    "```text",
    "6. not a step either",
    "```",
    "",
    "## Notes",
    "",
    "- Ask the user when the scope is unclear.",
    "",
  ].join("\n");
}

/** Project `demo`'s skill `refactor`, never used (as `a_usage_row` in core). */
export function aUsageRow(overrides: Partial<UsageRow> = {}): UsageRow {
  return {
    project: "demo",
    kind: "skill",
    name: "refactor",
    runs_7d: 0,
    runs_30d: 0,
    runs_90d: 0,
    last_used_at: null,
    ...overrides,
  };
}

/** Project `demo`'s 30-day report: `refactor` never used, then `feature` run twice. */
export function aUsageReport(overrides: Partial<UsageReport> = {}): UsageReport {
  return {
    days: 30,
    items: [
      aUsageRow(),
      aUsageRow({ name: "feature", runs_7d: 1, runs_30d: 2, runs_90d: 2, last_used_at: at(-3600) }),
    ],
    truncated: false,
    ...overrides,
  };
}

/** The card of the managed skill `feature` of project `demo`: used 3 times in 30 days. */
export function aCatalogItem(overrides: Partial<CatalogItem> = {}): CatalogItem {
  const name = overrides.name ?? "feature";
  const source = overrides.source ?? "hub-workflow";
  return {
    active: true,
    description: "Takes an idea or a tracker issue from spec to delivery.",
    diagnostics_count: 1,
    id: `skill/${source}/${name}`,
    invocation: `/${name} <idea or tracker issue id>`,
    kind: "skill",
    linked_from: [`.claude/skills/${name}`],
    mode: "both",
    name,
    origin: "managed",
    source,
    source_path: `plugin/${source}/skills/${name}/SKILL.md`,
    state: null,
    usage: { count: 3, last_used_at: at(-3600), model_count: 1, user_count: 2 },
    ...overrides,
  };
}

function anAgentItem(): CatalogItem {
  return aCatalogItem({
    description: "Checks a delivery against its spec.",
    diagnostics_count: 0,
    id: "agent/hub-workflow/evaluator",
    invocation: null,
    kind: "agent",
    linked_from: [".claude/agents/evaluator.md"],
    mode: null,
    name: "evaluator",
    source_path: "plugin/hub-workflow/agents/evaluator.md",
    usage: { count: 0, last_used_at: null, model_count: 0, user_count: 0 },
  });
}

function aHookItem(): CatalogItem {
  return aCatalogItem({
    description: "python3 plugin/hub-workflow/hooks/guard.py",
    diagnostics_count: 0,
    id: "hook/settings/settings-pretooluse-1",
    invocation: null,
    kind: "hook",
    linked_from: [],
    mode: null,
    name: "settings-pretooluse-1",
    source: "settings",
    source_path: ".claude/settings.json",
    state: "synced",
    usage: null,
  });
}

/** The catalog of project `demo`: `feature`, the user-only project skill `plan`, the agent
 * `evaluator`, one settings hook, and the pinned third-party plugin `superpowers`. */
export function aSkillCatalog(overrides: Partial<SkillCatalog> = {}): SkillCatalog {
  return {
    external_plugins: [
      {
        content: "not in this hub",
        enabled: true,
        marketplace: "agent-hub",
        name: "superpowers",
        pin: "5f0c2e1",
      },
    ],
    items: [
      aCatalogItem(),
      aCatalogItem({
        description: "Writes an implementation plan.",
        diagnostics_count: 0,
        invocation: "/plan",
        linked_from: [],
        mode: "user-only",
        name: "plan",
        origin: "project-owned",
        source: "demo",
        usage: { count: 0, last_used_at: null, model_count: 0, user_count: 0 },
      }),
      anAgentItem(),
      aHookItem(),
    ],
    notice: null,
    project: "demo",
    truncated: false,
    usage_days: 30,
    ...overrides,
  };
}

const FEATURE_FRONTMATTER =
  "---\nname: feature\ndescription: Takes an idea or a tracker issue from spec to delivery.\n" +
  'argument-hint: "<idea or tracker issue id>"\nreviewers: two\n---\n';

/** The detail of `skill/hub-workflow/feature`: the feature-shaped body, five derived steps, one
 * unknown key, two bundled files. */
export function aSkillDetail(overrides: Partial<SkillDetail> = {}): SkillDetail {
  const body = aFeatureShapedBody();
  return {
    ...aCatalogItem(),
    allowed_tools: [],
    argument_hint: "<idea or tracker issue id>",
    body,
    context_cost: { always_loaded_tokens: 14, approximate: true, on_invoke_tokens: 150 },
    description_full: "Takes an idea or a tracker issue from spec to delivery.",
    diagnostics: [
      {
        code: "unknown_key",
        message: "reviewers: not understood by Claude Code",
        severity: "info",
      },
    ],
    files: [
      {
        id: "0123456789abcdef",
        link: false,
        path: "references/checklist.md",
        role: "references",
        size: 64,
        too_large: false,
      },
      {
        id: "fedcba9876543210",
        link: false,
        path: "scripts/check.sh",
        role: "scripts",
        size: 32,
        too_large: false,
      },
    ],
    frontmatter: [
      { key: "name", known: true, value: "feature" },
      {
        key: "description",
        known: true,
        value: "Takes an idea or a tracker issue from spec to delivery.",
      },
      { key: "argument-hint", known: true, value: "<idea or tracker issue id>" },
      { key: "reviewers", known: false, value: "two" },
    ],
    hook: null,
    lock: { ownership: "managed", sha256: "a".repeat(64) },
    model: null,
    raw: FEATURE_FRONTMATTER + body,
    structure: {
      agents: ["requirements-analyst"],
      commands: ["make check", "./hub doctor"],
      dynamic_context: 0,
      gates: ["Gate: user approves the spec"],
      skills: ["create-plan"],
      steps: [
        {
          agents: ["requirements-analyst"],
          commands: [],
          index: 1,
          scripts: [],
          skills: [],
          tags: ["agent"],
          summary: "the requirements-analyst agent writes spec.md.",
          title: "Spec",
        },
        {
          agents: [],
          commands: [],
          index: 2,
          scripts: [],
          skills: [],
          tags: ["gate", "human"],
          summary: "Stop until they do.",
          title: "Gate: user approves the spec",
        },
        {
          agents: [],
          commands: [],
          index: 3,
          scripts: [],
          skills: ["create-plan"],
          tags: [],
          summary: "run /create-plan on the approved spec.",
          title: "Plan",
        },
        {
          agents: [],
          commands: ["make check"],
          index: 4,
          scripts: [],
          skills: [],
          tags: ["command"],
          summary: "in a worktree; run make check before the PR.",
          title: "Implement",
        },
        {
          agents: [],
          commands: ["./hub doctor"],
          index: 5,
          scripts: [],
          skills: [],
          tags: ["command"],
          summary: "run ./hub doctor and fix what it finds.",
          title: "Doctor",
        },
      ],
      truncated: false,
    },
    toc: [
      { level: 1, text: "Feature" },
      { level: 2, text: "Steps" },
      { level: 2, text: "Notes" },
    ],
    tools: [],
    used_by: [],
    uses: [
      {
        id: "agent/hub-workflow/requirements-analyst",
        kind: "agent",
        name: "requirements-analyst",
        source: "hub-workflow",
      },
      {
        id: "skill/hub-workflow/create-plan",
        kind: "skill",
        name: "create-plan",
        source: "hub-workflow",
      },
    ],
    when_to_use: null,
    ...overrides,
  };
}

/** The detail of `agent/hub-workflow/evaluator`, used by `feature`. */
export function anAgentDetail(overrides: Partial<SkillDetail> = {}): SkillDetail {
  const body = "You are the evaluator. Read the spec, then the diff.\n";
  return {
    ...aSkillDetail(),
    ...anAgentItem(),
    allowed_tools: [],
    argument_hint: null,
    body,
    context_cost: { always_loaded_tokens: 9, approximate: true, on_invoke_tokens: 13 },
    description_full: "Checks a delivery against its spec.",
    diagnostics: [],
    files: [],
    frontmatter: [
      { key: "name", known: true, value: "evaluator" },
      { key: "tools", known: true, value: "Read, Grep" },
      { key: "model", known: true, value: "sonnet" },
    ],
    model: "sonnet",
    raw: "---\nname: evaluator\ntools: Read, Grep\nmodel: sonnet\n---\n" + body,
    structure: {
      agents: [],
      commands: [],
      dynamic_context: 0,
      gates: [],
      skills: [],
      steps: [],
      truncated: false,
    },
    toc: [],
    tools: ["Read", "Grep"],
    used_by: [
      { id: "skill/hub-workflow/feature", kind: "skill", name: "feature", source: "hub-workflow" },
    ],
    uses: [],
    ...overrides,
  };
}

/** The detail of `hook/settings/settings-pretooluse-1`: a `Bash` guard, synced and active. */
export function aHookDetail(overrides: Partial<SkillDetail> = {}): SkillDetail {
  return {
    ...aSkillDetail(),
    ...aHookItem(),
    argument_hint: null,
    body: null,
    context_cost: null,
    description_full: null,
    diagnostics: [],
    files: [],
    frontmatter: [],
    hook: {
      active: true,
      command: "python3 plugin/hub-workflow/hooks/guard.py",
      event: "PreToolUse",
      matcher: "Bash",
      state: "synced",
      timeout: null,
      type: "command",
    },
    lock: null,
    raw: null,
    structure: null,
    toc: [],
    used_by: [],
    uses: [],
    ...overrides,
  };
}

/** The text of `feature`'s `references/checklist.md`. */
export function aBundledFileText(overrides: Partial<BundledFileText> = {}): BundledFileText {
  return {
    binary: false,
    id: "0123456789abcdef",
    path: "references/checklist.md",
    role: "references",
    size: 64,
    text: "# Checklist\n\n- The spec is approved.\n- `make check` passes.\n",
    ...overrides,
  };
}

/** `feature-flow`, a hub workflow of project `agent-hub`: 4 nodes in 3 layers. */
export function aWorkflowSummary(overrides: Partial<WorkflowSummary> = {}): WorkflowSummary {
  return {
    description: "Plans, builds and documents a feature, then asks for a review.",
    inputs: [{ name: "feature", type: "string", required: true, description: "What to build." }],
    layer_count: 3,
    name: "feature-flow",
    node_count: 4,
    project: "agent-hub",
    revision: 3,
    source: "hub",
    step_types: { agent: 1, shell: 1, script: 1, approval: 1 },
    steps: [
      { id: "plan", type: "agent", description: "Writes the plan.", body: [] },
      { id: "build", type: "shell", body: [] },
      { id: "docs", type: "script", body: [] },
      { id: "review", type: "approval", body: [] },
    ],
    ...overrides,
  };
}

/** A file of the hub that does not load. */
export function aWorkflowProblem(overrides: Partial<WorkflowProblem> = {}): WorkflowProblem {
  return {
    file: "workflows/team/broken.yaml",
    key: "nodes[1].depends_on",
    line: 12,
    message: "depends on unknown node 'plan'",
    project: "agent-hub",
    ...overrides,
  };
}

/** The hub's `feature-flow`, the built-in `issue-to-pr` and one file that does not load. */
export function aWorkflowCatalog(
  overrides: Partial<WorkflowCatalogView> = {},
): WorkflowCatalogView {
  return {
    items: [
      aWorkflowSummary(),
      aWorkflowSummary({
        description: "Takes a tracker issue to a pull request.",
        layer_count: 6,
        name: "issue-to-pr",
        node_count: 6,
        revision: 1,
        source: "builtin",
      }),
    ],
    problems: [aWorkflowProblem()],
    ...overrides,
  };
}

/** `feature-flow`: `plan` (agent), then `build` (shell) and `docs` (script), then `review`
 * (approval) after both. */
export function aWorkflowDetail(overrides: Partial<WorkflowDetail> = {}): WorkflowDetail {
  return {
    ...aWorkflowSummary(),
    layers: [
      [{ id: "plan", type: "agent", depends_on: [], description: "Writes the plan." }],
      [
        { id: "build", type: "shell", depends_on: ["plan"], description: null },
        { id: "docs", type: "script", depends_on: ["plan"], description: null },
      ],
      [{ id: "review", type: "approval", depends_on: ["build", "docs"], description: null }],
    ],
    document: {
      name: "feature-flow",
      description: "Plans, builds and documents a feature, then asks for a review.",
      nodes: [
        { id: "plan", type: "agent", description: "Writes the plan.", prompt: "Plan $issue." },
        { id: "build", type: "shell", depends_on: ["plan"], command: ["make", "check"] },
        { id: "docs", type: "script", depends_on: ["plan"], runtime: "sh", script: "docs.sh" },
        { id: "review", type: "approval", depends_on: ["build", "docs"], message: "Ship it?" },
      ],
    },
    ...overrides,
  };
}

/** A version as the history lists it: by default the app's Publish, by the hub's identity. */
export function anItemVersion(overrides: Partial<ItemVersion> = {}): ItemVersion {
  return {
    id: "0199f0a1-0000-7000-8000-000000000001",
    origin: "publish",
    first: false,
    author: { name: "Example Owner", email: "owner@example.com" },
    recorded_at: "2026-10-18T09:00:00Z",
    content_hash: `sha256:${"a1b2c3d4".repeat(8)}`,
    size: 120,
    restored_from: null,
    draft_id: null,
    ...overrides,
  };
}

/** A page of a skill folder's versions, newest first, whose disk is stored (`state` ok). */
export function anItemVersionPage(overrides: Partial<ItemVersionPage> = {}): ItemVersionPage {
  return {
    items: [anItemVersion()],
    managed: false,
    next_cursor: null,
    shared_by: 1,
    state: "ok",
    total_estimate: overrides.items?.length ?? 1,
    unit_kind: "skill",
    unit_path: "plugin/hub-workflow/skills/feature",
    ...overrides,
  };
}

/** One version's content: a skill folder's files in path order. */
export function anItemVersionContent(
  overrides: Partial<ItemVersionContent> = {},
): ItemVersionContent {
  return {
    id: "0199f0a1-0000-7000-8000-000000000001",
    unit_kind: "skill",
    files: [{ path: "SKILL.md", executable: false, size: 24, text: "---\nname: feature\n---\n" }],
    ...overrides,
  };
}

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

/** A route's answer: a JSON body, a problem, "pending" (never answers) or a function of the request (returning any of these). */
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
      // A function may answer per request, including with a problem or "pending".
      const body: unknown = typeof reply === "function" ? reply(request) : reply;
      if (body === "pending") return new Promise<Response>(() => undefined);
      if (body instanceof ProblemReply) {
        return Promise.resolve(
          jsonResponse(body.body, body.body.status, "application/problem+json"),
        );
      }
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

/* ---------- Scenarios (AGH-350 T13) ---------- */

export type ScenarioSummary = Schemas["ScenarioSummary"];
export type ScenarioCatalog = Schemas["ScenarioCatalogView"];
export type ScenarioDetail = Schemas["ScenarioDetail"];
export type ScenarioAction = Schemas["ScenarioActionView"];
export type ScenarioRunRef = Schemas["ScenarioRunRef"];
export type ScenarioPlan = Schemas["ScenarioPlanView"];
export type ScenarioPlanRow = Schemas["ScenarioPlanRow"];
export type ScenarioRunDetail = Schemas["ScenarioRunDetail"];
export type ScenarioOption = Schemas["OptionEntry"];
export type InvestigationSession = Schemas["InvestigationSession"];
export type FindingIssue = Schemas["FindingIssue"];

/** The synthetic scenario run every scenario builder names. */
export const SCENARIO_RUN = "3f2a91c0";

export function aScenarioRunRef(overrides: Partial<ScenarioRunRef> = {}): ScenarioRunRef {
  return {
    run_id: SCENARIO_RUN,
    status: "running",
    started_at: at(0),
    ended_at: null,
    environment: "personal",
    mode: "interactive",
    ...overrides,
  };
}

export function aScenarioSummary(overrides: Partial<ScenarioSummary> = {}): ScenarioSummary {
  return {
    project: "demo",
    name: "order-lifecycle",
    pack: "orders",
    description: "One order from fetch to an active cover",
    revision: 1,
    node_count: 9,
    inputs: [],
    last_run: null,
    ...overrides,
  };
}

export function aScenarioCatalog(overrides: Partial<ScenarioCatalog> = {}): ScenarioCatalog {
  return { items: [aScenarioSummary()], problems: [], ...overrides };
}

export function aScenarioDetail(overrides: Partial<ScenarioDetail> = {}): ScenarioDetail {
  return {
    ...aScenarioSummary(),
    node_count: 3,
    inputs: [
      { name: "external_ref", type: "string", required: true, description: "The order's ref." },
    ],
    steps: [
      {
        id: "fetch-order",
        type: "action",
        action: "send-queue-message",
        depends_on: [],
        description: null,
      },
      {
        id: "order-on-hold",
        type: "expect",
        action: "get-order-by-ref",
        depends_on: ["fetch-order"],
        description: null,
      },
      {
        id: "render-pdf",
        type: "action",
        action: "render-invoice-pdf",
        depends_on: ["order-on-hold"],
        description: null,
      },
    ],
    runs: [],
    environments: [
      { name: "personal", access: "write", production: false },
      { name: "qa", access: "read", production: false },
      { name: "live", access: "read", production: true },
    ],
    path: "scenarios/orders/order-lifecycle.yaml",
    document_text: "version: 1\nkind: scenario\nname: order-lifecycle\n",
    actions: [
      aScenarioAction({ ref: "send-queue-message", name: "send-queue-message", effect: "write" }),
      aScenarioAction({
        ref: "get-order-by-ref",
        name: "get-order-by-ref",
        description: "Read one order by its ref",
      }),
      aScenarioAction({
        ref: "render-invoice-pdf",
        name: "render-invoice-pdf",
        effect: "write",
        description: "Render the order's invoice PDF",
      }),
    ],
    ...overrides,
  };
}

export function aScenarioAction(overrides: Partial<ScenarioAction> = {}): ScenarioAction {
  const name = overrides.name ?? "get-order-by-ref";
  return {
    ref: name,
    name,
    pack: "orders",
    path: `actions/orders/${name}.yaml`,
    description: "Send one message to the orders queue",
    effect: "read",
    runtime: "python",
    script: `actions/orders/scripts/${name.replace(/-/g, "_")}.py`,
    timeout: "1m",
    inputs: [
      { name: "external_ref", type: "string", required: true, description: "The order's ref." },
    ],
    output_format: { type: "object", properties: { status: { type: "string" } } },
    draft: false,
    accept_command: null,
    document_text: `version: 1\nname: ${name}\n`,
    script_text: "print('{}')\n",
    script_truncated: false,
    problem: null,
    ...overrides,
  };
}

export function aScenarioPlanRow(overrides: Partial<ScenarioPlanRow> = {}): ScenarioPlanRow {
  return {
    step: "fetch-order",
    type: "action",
    action: "orders/send-queue-message",
    effect: "write",
    args: { queue: "FETCH_ORDERS", external_ref: "T-1" },
    endpoints: {
      queue: { service: "demo-api/queue", url: "https://queue.example.com/orders", resource: null },
    },
    every: null,
    timeout: null,
    content_hash: `sha256:${"a".repeat(64)}`,
    draft: false,
    decision: "allow",
    reason_kind: "table",
    reason: null,
    plan: "Sends FETCH_ORDERS for T-1",
    needs_acceptance: false,
    accept_command: null,
    ...overrides,
  };
}

export function aScenarioPlan(overrides: Partial<ScenarioPlan> = {}): ScenarioPlan {
  return {
    project: "demo",
    scenario: "order-lifecycle",
    environment: "personal",
    access: "write",
    production: false,
    denied: false,
    problems: [],
    rows: [
      aScenarioPlanRow(),
      aScenarioPlanRow({
        step: "order-on-hold",
        type: "expect",
        action: "orders/get-order-by-ref",
        effect: "read",
        args: { external_ref: "T-1" },
        endpoints: {
          db: { service: "demo-api/orders-db", url: null, resource: "demo-orders" },
        },
        every: "10s",
        timeout: "5m",
        plan: "Reads order T-1",
      }),
    ],
    ...overrides,
  };
}

/** A plan whose draft action is denied: the row shows the commit line (AM-5). */
export function aDraftRow(overrides: Partial<ScenarioPlanRow> = {}): ScenarioPlanRow {
  return aScenarioPlanRow({
    step: "render-pdf",
    action: "orders/render-invoice-pdf",
    args: { order: "<$CTX.order_id from order-on-hold>" },
    endpoints: { files: { service: "demo-api/files", url: null, resource: "demo-invoices" } },
    draft: true,
    decision: "deny",
    reason_kind: "draft",
    reason: "draft action: commit it to run",
    plan: "runs with values known at run time",
    needs_acceptance: true,
    accept_command:
      "git add -- actions/orders/render-invoice-pdf.yaml actions/orders/scripts/render-invoice-pdf.sh && git commit -m 'Accept action orders/render-invoice-pdf'",
    ...overrides,
  });
}

export function aScenarioOption(overrides: Partial<ScenarioOption> = {}): ScenarioOption {
  return {
    option_id: "o1",
    summary: "Set the order's carrier, then reprocess",
    steps: [{ action: "patch-order", with: { ref: "T-1" } }],
    plan: [
      {
        index: 1,
        action: "orders/patch-order",
        effect: "write",
        decision: "ask",
        draft: false,
        endpoint: { db: { service: "demo-api/orders-db", url: null, resource: "demo-orders" } },
      },
    ],
    needs_acceptance: false,
    accept_commands: [],
    pickable: true,
    refusal: null,
    ...overrides,
  };
}

/** A scenario run paused at its first investigation, with a proposal of three options. */
export function aScenarioRunDetail(overrides: Partial<ScenarioRunDetail> = {}): ScenarioRunDetail {
  const gate = "order-processed__investigation";
  return {
    run_id: SCENARIO_RUN,
    project: "demo",
    scenario: "order-lifecycle",
    pack: "orders",
    environment: "personal",
    mode: "interactive",
    status: null,
    open_investigation: 1,
    paused_step: "order-processed",
    timeline: [
      { event: "start", node: null, attempt: null, status: null, at: at(0) },
      { event: "step_start", node: "fetch-order", attempt: 1, status: null, at: at(5) },
      { event: "step_end", node: "fetch-order", attempt: 1, status: "ok", at: at(10) },
      { event: "step_start", node: "order-on-hold", attempt: 1, status: null, at: at(11) },
      { event: "step_end", node: "order-on-hold", attempt: 1, status: "ok", at: at(40) },
      { event: "gate", node: "resolve-cover__ask", attempt: 1, status: null, at: at(41) },
      { event: "decision", node: "resolve-cover__ask", attempt: 1, status: null, at: at(60) },
      { event: "step_start", node: "order-processed", attempt: 1, status: null, at: at(61) },
      { event: "step_end", node: "order-processed", attempt: 1, status: "failed", at: at(660) },
      { event: "investigation", node: "order-processed", attempt: 1, status: null, at: at(661) },
      { event: "gate", node: gate, attempt: 1, status: null, at: at(661) },
      {
        event: "agent_action",
        node: gate,
        attempt: 1,
        status: "ok",
        at: at(780),
        action: "orders/get-order",
        effect: "read",
      },
      { event: "proposal", node: gate, attempt: 1, status: null, at: at(960) },
    ],
    polls: [
      { node: "order-on-hold", attempt: 1, poll: 1, held: false, at: at(20) },
      { node: "order-on-hold", attempt: 1, poll: 2, held: false, at: at(30) },
      { node: "order-on-hold", attempt: 1, poll: 3, held: true, at: at(40) },
      { node: "order-processed", attempt: 1, poll: 1, held: false, at: at(100) },
      { node: "order-processed", attempt: 1, poll: 2, held: false, at: at(660) },
    ],
    captures: [{ node: "order-on-hold", attempt: 1, name: "order_id", value: "81234" }],
    decisions: [
      {
        node: "resolve-cover__ask",
        attempt: 1,
        choice: "approve",
        text: null,
        approver: "Dana Demo",
        where: "web",
        at: at(60),
      },
    ],
    findings: [
      {
        finding_id: "f1",
        step: "order-processed",
        title: "Collection orders lack tracking",
        text: "The order came in as COLLECTION and has no carrier.",
        evidence: "status OPEN after 40 polls",
      },
    ],
    investigations: [
      {
        number: 1,
        step: "order-processed",
        gate,
        failure_kind: "timeout",
        choice: null,
        text: null,
        approver: null,
        closed: false,
        agent_session_id: null,
      },
    ],
    proposal: {
      proposal: 2,
      investigation: 1,
      options: [
        aScenarioOption(),
        aScenarioOption({
          option_id: "o2",
          summary: "Regenerate the shipments",
          steps: [{ action: "regenerate-shipments", with: {} }],
          plan: [
            {
              index: 1,
              action: "orders/regenerate-shipments",
              effect: "destroy",
              decision: "ask",
              draft: false,
              endpoint: {},
            },
          ],
        }),
        aScenarioOption({
          option_id: "o3",
          summary: "Render the invoice PDF",
          steps: [{ action: "render-invoice-pdf", with: {} }],
          plan: [
            {
              index: 1,
              action: "orders/render-invoice-pdf",
              effect: "write",
              decision: "deny",
              reason_kind: "draft",
              draft: true,
              endpoint: {},
            },
          ],
          needs_acceptance: true,
          accept_commands: [
            "git add -- actions/orders/render-invoice-pdf.yaml && git commit -m 'Accept action orders/render-invoice-pdf'",
          ],
          pickable: false,
          refusal:
            "option o3 cannot be picked: step 1 (orders/render-invoice-pdf): draft action: commit it to run",
        }),
      ],
    },
    workarounds: [],
    actions: [
      {
        node: "fetch-order",
        attempt: 1,
        poll: 0,
        action: "orders/send-queue-message",
        effect: "write",
        origin: "author",
        decision: "allow",
        reason_kind: "table",
        content_hash: `sha256:${"a".repeat(64)}`,
        approver: null,
        status: "ok",
        failure_kind: null,
        at: at(10),
      },
    ],
    ...overrides,
  };
}

export function anInvestigationSession(
  overrides: Partial<InvestigationSession> = {},
): InvestigationSession {
  return {
    run_id: SCENARIO_RUN,
    project: "demo",
    investigation: 1,
    step: "order-processed",
    agent_session_id: anId(9, "0192f00d"),
    started: true,
    ...overrides,
  };
}

export function aFindingIssue(overrides: Partial<FindingIssue> = {}): FindingIssue {
  return {
    run_id: SCENARIO_RUN,
    finding_id: "f1",
    team: "DEMO",
    title: "Collection orders lack tracking",
    description: "Found by scenario run 3f2a91c0 in personal.",
    created: null,
    ...overrides,
  };
}
