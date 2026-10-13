import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { useApi } from "../lib/api";
import type { RecordKind } from "./builders";
import {
  aBrainNote,
  aCapabilities,
  aCloudSession,
  aDeltaFrame,
  aLogRecord,
  anAgentSession,
  aPermissionRequest,
  aWorkdir,
  aBrainTree,
  aCollectorStatus,
  aFeature,
  aFeatureDetail,
  aFeatureRecord,
  aFeatureTickets,
  aGoldenPath,
  aGoldenStep,
  aFinding,
  aHub,
  aLearning,
  aLearningActionResult,
  aLearningDetail,
  aLiveTile,
  anActor,
  aNeedsYouItem,
  anActivityItem,
  anApproval,
  anEvalRecord,
  anId,
  aPage,
  aProblem,
  aProjectDetail,
  aProjectNow,
  aProjectSummary,
  aRepo,
  aRun,
  aSearchHit,
  aSession,
  aSessionCost,
  aSessionFile,
  aSessionLabel,
  aSessionProblem,
  aSessionProblems,
  aSessionSummary,
  aSettings,
  aStreamCounts,
  aTicketPlan,
  aTicketRow,
  aTimelineEvent,
  at,
  manyEvents,
  renderWithApi,
  stubApi,
} from "./builders";

describe("builders", () => {
  it("build every response schema with overrides", () => {
    const bodies = [
      aSession({ status: "ended" }),
      aTimelineEvent({ seq: 3 }),
      aRun({ stage: "FAILED" }),
      anApproval({ status: "approved" }),
      aLearning({ status: "accepted" }),
      aLiveTile({ group: "waiting" }),
      aProjectSummary({ name: "loki-trader" }),
      aProjectDetail(),
      aProjectNow(),
      aRepo(),
      aFeature(),
      aFeatureDetail(),
      aFinding({ severity: "warning" }),
      aHub({ valid: false }),
      aCollectorStatus(),
      aSettings(),
      aNeedsYouItem(),
      anActivityItem(),
      aSearchHit(),
      aSessionSummary(),
      aSessionCost(),
      aSessionFile(),
      aStreamCounts(),
    ];

    expect(bodies).toHaveLength(23);
    expect(aSession({ status: "ended" }).status).toBe("ended");
    expect(aTimelineEvent({ seq: 3 }).event_id).toBe(anId(3, "0192aaaa"));
    expect(aPage([1, 2])).toEqual({ items: [1, 2], next_cursor: null, total_estimate: 2 });
  });

  it("builds the clarity bodies and fields", () => {
    const tile = aLiveTile({ problems: { by_you: 0, handled: 2, needs_you: 1, open: 0 } });
    const problems = aSessionProblems();

    expect(aSession().label).toEqual(aSessionLabel());
    expect(aSession().actors).toEqual([anActor()]);
    expect(aSessionLabel({ issue: null }).issue).toBeNull();
    expect(anActor({ kind: "subagent", type: "Explore" }).type).toBe("Explore");
    expect(tile.problems.needs_you).toBe(1);
    expect(tile.label?.workflow).toBe("/feature");
    expect(problems.summary[0]?.event_id).toBe(problems.items[0]?.event_id);
    expect(aSessionProblem({ resolution: "recovered" }).resolution).toBe("recovered");
    expect(aLearning().state).toBe("proposed");
    expect(aLearning().note_path).toBe("brain/_inbox/web-gates.md");
    expect(aLearningDetail().note?.path).toBe("_inbox/web-gates.md");
    expect(aLearningActionResult().state).toBe("accepted_pr_open");
    expect(aBrainTree().entries.map((entry) => entry.path)).toContain("index.md");
    expect(aBrainNote({ path: "now.md" }).path).toBe("now.md");
    expect(aFeatureRecord({ name: "plan", present: false }).present).toBe(false);
    expect(aFeatureDetail().records.map((record) => record.name)).toEqual([
      "spec",
      "research",
      "plan",
      "eval",
      "issues",
    ]);
  });

  it("builds the tickets, golden path and eval schemas consistently", () => {
    const tickets = aFeatureTickets();
    const refs = tickets.tickets.map((row) => row.ref);

    expect(tickets.source).toBe("linear");
    expect(tickets.planning.order.every((ref) => refs.includes(ref))).toBe(true);
    expect(tickets.planning.layers.flat().every((ref) => refs.includes(ref))).toBe(true);
    expect(tickets.golden_path.phase).toBe(aFeature().phase);
    expect(aGoldenPath().steps.map((step) => step.name)).toEqual([
      "spec",
      "research",
      "plan",
      "tickets",
      "implement",
      "review",
      "evaluate",
      "shipped",
    ]);
    expect(aGoldenStep({ state: "blocked" }).state).toBe("blocked");
    expect(aTicketRow({ readiness: "waiting" }).readiness).toBe("waiting");
    expect(aTicketPlan().can_start).toEqual(["AGH-202"]);
    expect(anEvalRecord({ acs: "all" }).acs).toBe("all");
    expect(aFeature().golden_path).toEqual(aGoldenPath());
    expect(aFeature().tickets_source).toBe("plan");
    expect(aFeatureDetail().evals).toEqual([anEvalRecord()]);
    expect(aFeatureTickets({ source: "plan", notice: "From the plan" }).notice).toBe(
      "From the plan",
    );
  });

  it("makes n ordered synthetic events of one session", () => {
    const events = manyEvents(5000);

    expect(events).toHaveLength(5000);
    expect(events[4999]?.seq).toBe(5000);
    expect(new Set(events.map((e) => e.event_id)).size).toBe(5000);
    expect(events[5]?.payload).toMatchObject({ turn: 2 });
  });

  it("writes UTC timestamps relative to T0", () => {
    expect(at(90)).toBe("2026-10-11T14:01:30.000Z");
  });
});

describe("stubApi", () => {
  it("answers bodies, problems, functions, methods and unknown routes", async () => {
    stubApi({
      "/a": { ok: true },
      "/b": aProblem({ status: 409, title: "Conflict" }),
      "/c": (request: Request) => ({ method: request.method }),
      "POST /d": { created: true },
    });

    const a = await fetch("http://localhost/a");
    const b = await fetch("http://localhost/b");
    const c = await fetch("http://localhost/c");
    const d = await fetch("http://localhost/d", { method: "POST" });
    const e = await fetch("http://localhost/e");

    expect(await a.json()).toEqual({ ok: true });
    expect(b.status).toBe(409);
    expect(b.headers.get("content-type")).toBe("application/problem+json");
    expect(await c.json()).toEqual({ method: "GET" });
    expect(d.status).toBe(201);
    expect(await e.json()).toMatchObject({ detail: "No stub for GET /e" });
  });
});

function HubCount() {
  const hubs = useApi("/api/v1/hubs");
  if (hubs.isPending) return <p>loading</p>;
  return <p>{hubs.data?.items.length ?? hubs.error?.title}</p>;
}

describe("renderWithApi", () => {
  it("renders against the stubbed API and records requests", async () => {
    const { requests } = renderWithApi(<HubCount />, {
      routes: { "/api/v1/hubs": aPage([aHub()]) },
    });

    expect(await screen.findByText("1")).toBeInTheDocument();
    expect(requests).toHaveLength(1);
  });

  it("keeps a pending route loading", () => {
    renderWithApi(<HubCount />, { routes: { "/api/v1/hubs": "pending" } });

    expect(screen.getByText("loading")).toBeInTheDocument();
  });

  it("finds the streams a render opened", () => {
    const { stream } = renderWithApi(<p>x</p>);
    new EventSource("/api/v1/live-sessions/stream");

    expect(stream("/api/v1/live-sessions/stream").url).toBe("/api/v1/live-sessions/stream");
    expect(() => stream("/api/v1/nothing")).toThrow("No EventSource opened for /api/v1/nothing");
  });
});

describe("agent-session builders", () => {
  it("build a record of every kind with its body", () => {
    const kinds: RecordKind[] = [
      "init",
      "text",
      "thinking",
      "tool.call",
      "tool.result",
      "todos",
      "permission.request",
      "result",
      "error",
      "exited",
      "user.message",
      "permission.decision",
      "interrupt",
      "settings",
      "close",
      "log.truncated",
      "cloud.start",
      "cloud.followup",
    ];

    const records = kinds.map((kind, index) => aLogRecord(kind, { seq: index + 1 }));

    expect(records.map((record) => record.kind)).toEqual(kinds);
    expect(records.map((record) => record.seq)).toEqual(kinds.map((_, index) => index + 1));
    expect(aLogRecord("user.message").by).toBe("web");
    expect(aLogRecord("text").by).toBe("driver");
    expect(aLogRecord("tool.call").body.name).toBe("Edit");
    expect(aLogRecord("text", { body: { block: 1, text: "Done." } }).body.text).toBe("Done.");
  });

  it("build the agent-session bodies with overrides", () => {
    const waiting = anAgentSession({
      status: "waiting_permission",
      open_permission: aPermissionRequest(),
    });

    expect(anAgentSession().status).toBe("idle");
    expect(waiting.open_permission?.suggestions.map((s) => s.destination)).toEqual([
      "localSettings",
      "session",
    ]);
    expect(aPermissionRequest({ request_kind: "plan_approval" }).request_kind).toBe(
      "plan_approval",
    );
    expect(aWorkdir({ kind: "worktree" }).workdir_id).toMatch(/^[0-9a-f]{16}$/);
    expect(aCapabilities().models).toEqual(["default", "opus", "sonnet", "haiku"]);
    expect(aCapabilities({ available: false, reason: "claude not found" }).reason).toBe(
      "claude not found",
    );
    expect(aCloudSession().url).toMatch(/^https:\/\/claude\.ai\/code\//);
    expect(aCloudSession().teleport_command).toBe(`claude --teleport ${aCloudSession().cloud_id}`);
    expect(aDeltaFrame({ index: 2 })).toEqual({ after_seq: 3, block: 0, index: 2, text: "Hel" });
    expect(aSession().agent_session_id).toBeNull();
  });
});
